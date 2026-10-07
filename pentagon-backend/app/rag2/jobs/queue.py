"""Postgres-backed (SQLite here) index-job queue: status, budget, progress.

Jobs are the only way indexing work happens, which is what makes RAG §7.1's
promises enforceable rather than aspirational: an estimate is stored before
the job starts, a cap counts model calls against it, and pause/resume/cancel
are rows the worker checks between batches instead of flags a UI hopes the
backend honours.

Claiming is a conditional UPDATE (``queued`` -> ``running``), so two workers
cannot take the same job: the loser's rowcount is zero and it looks again.
A job interrupted by a crash is left ``running``; :meth:`JobQueue.requeue_interrupted`
puts those back in ``queued`` on startup, and handlers are written to be
idempotent per batch so re-running a partial batch is safe.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import IndexJob, utc_now
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
PAUSED = "paused"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

# Statuses a job can no longer move out of.
TERMINAL = frozenset({DONE, FAILED, CANCELLED})
# What the worker is allowed to claim.
CLAIMABLE = frozenset({QUEUED})

_MAX_ERROR_CHARS = 500


class JobQueue:
    """Queue operations, each opening its own session (workers are async)."""

    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    # -- lifecycle ----------------------------------------------------------
    def enqueue(
        self,
        *,
        user_id: str,
        collection_id: str,
        kind: str,
        llm_calls_estimated: int | None = None,
        llm_calls_cap: int | None = None,
    ) -> IndexJob:
        job = IndexJob(
            user_id=user_id,
            collection_id=collection_id,
            kind=kind,
            status=QUEUED,
            llm_calls_estimated=llm_calls_estimated,
            llm_calls_cap=llm_calls_cap,
        )
        with self._session() as db:
            db.add(job)
            db.commit()
            db.refresh(job)
        return job

    def get(self, job_id: str, user_id: str | None = None) -> IndexJob | None:
        """Fetch a job; pass ``user_id`` to make it a scoped (RLS-equivalent)
        read -- someone else's job id then simply does not exist."""
        with self._session() as db:
            statement = select(IndexJob).where(IndexJob.id == job_id)
            if user_id is not None:
                statement = statement.where(IndexJob.user_id == user_id)
            return db.scalar(statement)

    def list(
        self, user_id: str, collection_id: str | None = None
    ) -> list[IndexJob]:
        statement = (
            select(IndexJob)
            .where(IndexJob.user_id == user_id)
            .order_by(IndexJob.created_at, IndexJob.id)
        )
        if collection_id is not None:
            statement = statement.where(IndexJob.collection_id == collection_id)
        with self._session() as db:
            return list(db.scalars(statement))

    def claim_next(self) -> IndexJob | None:
        """Atomically take the oldest claimable job, or None."""
        with self._session() as db:
            for _ in range(5):  # a lost race just means someone else was faster
                candidate = db.scalar(
                    select(IndexJob)
                    .where(IndexJob.status.in_(CLAIMABLE))
                    .order_by(IndexJob.created_at, IndexJob.id)
                    .limit(1)
                )
                if candidate is None:
                    return None
                result = db.execute(
                    update(IndexJob)
                    .where(IndexJob.id == candidate.id, IndexJob.status.in_(CLAIMABLE))
                    .values(status=RUNNING, updated_at=utc_now())
                )
                db.commit()
                if result.rowcount == 1:
                    db.expire_all()
                    return db.get(IndexJob, candidate.id)
            return None

    # -- progress and budget ------------------------------------------------
    def report(
        self,
        job_id: str,
        *,
        progress: float | None = None,
        llm_calls_used: int | None = None,
        llm_calls_estimated: int | None = None,
    ) -> None:
        values: dict[str, Any] = {"updated_at": utc_now()}
        if progress is not None:
            values["progress"] = max(0.0, min(1.0, float(progress)))
        if llm_calls_used is not None:
            values["llm_calls_used"] = int(llm_calls_used)
        if llm_calls_estimated is not None:
            values["llm_calls_estimated"] = int(llm_calls_estimated)
        with self._session() as db:
            db.execute(update(IndexJob).where(IndexJob.id == job_id).values(**values))
            db.commit()

    def status(self, job_id: str) -> str | None:
        with self._session() as db:
            return db.scalar(select(IndexJob.status).where(IndexJob.id == job_id))

    # -- transitions --------------------------------------------------------
    def _transition(self, job_id: str, *, allowed: set[str], target: str) -> bool:
        with self._session() as db:
            result = db.execute(
                update(IndexJob)
                .where(IndexJob.id == job_id, IndexJob.status.in_(allowed))
                .values(status=target, updated_at=utc_now())
            )
            db.commit()
            return result.rowcount == 1

    def pause(self, job_id: str) -> bool:
        """``queued``/``running`` -> ``paused``.

        A running handler observes the pause between batches and returns,
        leaving the row paused; resume re-queues the remainder.
        """
        return self._transition(job_id, allowed={QUEUED, RUNNING}, target=PAUSED)

    def resume(self, job_id: str) -> bool:
        return self._transition(job_id, allowed={PAUSED}, target=QUEUED)

    def cancel(self, job_id: str) -> bool:
        return self._transition(job_id, allowed={QUEUED, RUNNING, PAUSED}, target=CANCELLED)

    def requeue(self, job_id: str) -> bool:
        """Put a claimed job back (e.g. the rate limiter said not now)."""
        return self._transition(job_id, allowed={RUNNING}, target=QUEUED)

    def complete(self, job_id: str) -> bool:
        return self._transition(job_id, allowed={RUNNING}, target=DONE)

    def fail(self, job_id: str, error: str) -> bool:
        with self._session() as db:
            result = db.execute(
                update(IndexJob)
                .where(IndexJob.id == job_id, IndexJob.status.in_({QUEUED, RUNNING, PAUSED}))
                .values(
                    status=FAILED,
                    error=error[:_MAX_ERROR_CHARS],
                    updated_at=utc_now(),
                )
            )
            db.commit()
            return result.rowcount == 1

    def requeue_interrupted(self, user_id: str | None = None) -> int:
        """Jobs left ``running`` by a crash go back to ``queued``.

        Called once at startup: a job half-done by a process that died is
        resumable work, not a row frozen in a state nothing will ever claim.
        """
        statement = update(IndexJob).where(IndexJob.status == RUNNING).values(
            status=QUEUED, updated_at=utc_now()
        )
        if user_id is not None:
            statement = statement.where(IndexJob.user_id == user_id)
        with self._session() as db:
            result = db.execute(statement)
            db.commit()
            if result.rowcount:
                logger.info("Re-queued %d interrupted index job(s)", result.rowcount)
            return int(result.rowcount or 0)


default_queue = JobQueue()
