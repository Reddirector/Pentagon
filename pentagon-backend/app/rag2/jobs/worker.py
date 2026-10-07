"""The background worker: claim a job, run its handler, tell the truth.

Handlers are registered per ``kind`` (graph extraction registers ``graph_extract``
in R3, ingest registers ``ingest`` in R1, and so on). R0 ships the skeleton
only -- no handler does real work yet, which is deliberate: the queue, its
transitions and its crash-resume are testable on their own, and a handler that
spends model calls should arrive with its own budget tests.

Every job step waits for a **background** permit first (RAG §0 rule 3), so
indexing yields to chat by construction rather than by good manners.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.db.models import IndexJob
from app.rag2.jobs.queue import RUNNING, JobQueue, default_queue
from app.services.rate_limiter import LANE_BACKGROUND, RateLimitTimeout, rate_limiter

logger = logging.getLogger(__name__)


@dataclass
class JobContext:
    """What a handler is given: the job row, and honest ways to report."""

    job: IndexJob
    queue: JobQueue

    @property
    def kind(self) -> str:
        return self.job.kind

    @property
    def llm_calls_used(self) -> int:
        return self.job.llm_calls_used

    @property
    def llm_calls_cap(self) -> int | None:
        return self.job.llm_calls_cap

    def should_continue(self) -> bool:
        """Cooperative cancellation/pause check: read the row, not a cache.

        Between batches, this is how a Pause or Cancel click reaches work
        that is already running -- and how a capped job stops at its cap
        instead of overrunning it.
        """
        status = self.queue.status(self.job.id)
        if status is None:
            return False
        if status == RUNNING:
            return True
        logger.info("Index job %s stopped: status is now %s", self.job.id, status)
        return False

    def remaining_calls(self) -> int | None:
        if self.job.llm_calls_cap is None:
            return None
        return max(0, self.job.llm_calls_cap - self.job.llm_calls_used)

    def spend_call(self, n: int = 1) -> bool:
        """Count model calls against the cap. False means the cap is spent."""
        if self.job.llm_calls_cap is not None and self.job.llm_calls_used + n > self.job.llm_calls_cap:
            return False
        self.job.llm_calls_used += n
        self.queue.report(self.job.id, llm_calls_used=self.job.llm_calls_used)
        return True

    def report(self, progress: float | None = None, *, llm_calls_used: int | None = None) -> None:
        self.queue.report(self.job.id, progress=progress, llm_calls_used=llm_calls_used)
        if progress is not None:
            self.job.progress = progress


Handler = Callable[[JobContext], Awaitable[None] | None]
_handlers: dict[str, Handler] = {}


def register_handler(kind: str, handler: Handler) -> None:
    """Register the worker for one job kind (last registration wins)."""
    _handlers[kind] = handler


def handler_for(kind: str) -> Handler | None:
    return _handlers.get(kind)


async def run_once(queue: JobQueue | None = None) -> bool:
    """Claim and run one job. True when a job was claimed.

    Failures are recorded on the row (``failed`` + error), never raised at the
    caller: a broken job must not take the worker loop down with it.
    """
    queue = queue or default_queue
    job = queue.claim_next()
    if job is None:
        return False

    handler = handler_for(job.kind)
    if handler is None:
        queue.fail(job.id, f"No worker is registered for job kind {job.kind!r}.")
        return True

    # Background lane: indexing waits its turn behind chat (RAG §0 rule 3).
    # The job was already claimed, so a timeout re-queues it instead of
    # freezing it in `running` forever.
    try:
        await rate_limiter.acquire(LANE_BACKGROUND)
    except RateLimitTimeout:
        queue.requeue(job.id)
        logger.info("Index job %s re-queued: the request budget is busy", job.kind)
        return False

    context = JobContext(job=job, queue=queue)
    try:
        result = handler(context)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning("Index job %s failed (%s)", job.kind, type(exc).__name__)
        queue.fail(job.id, str(exc) or type(exc).__name__)
        return True

    # A handler that paused or cancelled itself must keep that status; only a
    # job still marked running is actually done.
    if queue.status(job.id) == RUNNING:
        queue.complete(job.id)
    return True


async def worker_loop(
    stop: asyncio.Event,
    *,
    queue: JobQueue | None = None,
    poll_seconds: float = 1.0,
) -> None:
    """Poll for work until ``stop`` is set. Started by the app's lifespan."""
    queue = queue or default_queue
    logger.info("Index job worker started")
    while not stop.is_set():
        try:
            worked = await run_once(queue)
        except Exception as exc:  # a DB hiccup must not kill the worker
            logger.warning("Index worker pass failed (%s)", type(exc).__name__)
            worked = False
        if worked:
            continue  # drain the queue before sleeping
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass
    logger.info("Index job worker stopped")


def start_worker(queue: JobQueue | None = None) -> tuple[asyncio.Event, "asyncio.Task[Any]"]:
    """Start the loop in the background; returns (stop_event, task)."""
    stop = asyncio.Event()
    task = asyncio.create_task(worker_loop(stop, queue=queue))
    return stop, task


__all__ = [
    "JobContext",
    "JobQueue",
    "handler_for",
    "register_handler",
    "run_once",
    "start_worker",
    "worker_loop",
]
