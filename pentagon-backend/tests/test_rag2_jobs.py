"""Index jobs: every promise in RAG §7.1 that lives in the queue.

Estimate, cap, progress, pause, resume, cancel, crash-resume -- these are rows
and transitions, so they are testable without a model or a network. Handlers
here are fakes: the point is the machinery around them, not real indexing.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.db.models import Conversation, IndexJob, User
from app.db.session import SessionLocal
from app.rag2 import collections as service
from app.rag2.jobs import JobContext, default_queue, register_handler, run_once
from app.rag2.jobs.queue import (
    CANCELLED,
    DONE,
    FAILED,
    PAUSED,
    QUEUED,
    RUNNING,
    JobQueue,
)


@pytest.fixture
def user_id() -> str:
    uid = f"jobs-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=uid))
        db.add(Conversation(user_id=uid, title="thread"))
        db.commit()
    return uid


@pytest.fixture
def collection_id(user_id: str) -> str:
    with SessionLocal() as db:
        return service.create_collection(db, user_id=user_id, name="Jobs").id


@pytest.fixture(autouse=True)
def quiet_worker_pool() -> None:
    """run_once claims the oldest queued job, so strays must not exist."""
    with SessionLocal() as db:
        db.execute(
            update(IndexJob)
            .where(IndexJob.status.in_((QUEUED, RUNNING)))
            .values(status=CANCELLED)
        )
        db.commit()


def _enqueue(user_id: str, collection_id: str, kind: str, **kwargs) -> IndexJob:
    return default_queue.enqueue(
        user_id=user_id, collection_id=collection_id, kind=kind, **kwargs
    )


def test_claim_is_atomic_and_one_shot(user_id: str, collection_id: str) -> None:
    first = _enqueue(user_id, collection_id, "kind-a")
    second = _enqueue(user_id, collection_id, "kind-b")

    claimed_one = default_queue.claim_next()
    claimed_two = default_queue.claim_next()
    assert claimed_one is not None and claimed_two is not None
    assert {claimed_one.id, claimed_two.id} == {first.id, second.id}
    assert claimed_one.status == RUNNING
    # Nothing left to claim, and re-claiming never hands out a running job.
    assert default_queue.claim_next() is None


def test_transitions_are_one_way(user_id: str, collection_id: str) -> None:
    queue = default_queue
    job = _enqueue(user_id, collection_id, "transitions")

    # A queued job can be paused, resumed, cancelled -- and only in order.
    assert queue.complete(job.id) is False, "queued is not done"
    assert queue.pause(job.id) is True
    assert queue.status(job.id) == PAUSED
    assert queue.claim_next() is None, "a paused job is not claimable"
    assert queue.resume(job.id) is True
    assert queue.status(job.id) == QUEUED
    assert queue.cancel(job.id) is True
    assert queue.status(job.id) == CANCELLED
    assert queue.resume(job.id) is False, "cancelled is terminal"
    assert queue.pause(job.id) is False, "cancelled is terminal"


def test_fail_records_a_bounded_error(user_id: str, collection_id: str) -> None:
    job = _enqueue(user_id, collection_id, "doomed")
    default_queue.claim_next()
    assert default_queue.fail(job.id, "x" * 2000) is True
    row = default_queue.get(job.id)
    assert row is not None and row.status == FAILED
    assert row.error is not None and len(row.error) == 500


def test_jobs_are_scoped_to_their_owner(user_id: str, collection_id: str) -> None:
    job = _enqueue(user_id, collection_id, "private")
    assert default_queue.get(job.id, user_id=user_id) is not None
    assert default_queue.get(job.id, user_id=f"other-{uuid4()}") is None
    assert default_queue.get(job.id) is not None  # unscoped read for the worker


def test_crashed_running_jobs_are_requeued(user_id: str, collection_id: str) -> None:
    """A process that died mid-job leaves rows nothing would ever claim."""
    job = _enqueue(user_id, collection_id, "interrupted")
    with SessionLocal() as db:
        db.execute(
            update(IndexJob).where(IndexJob.id == job.id).values(status=RUNNING)
        )
        db.commit()
    assert default_queue.claim_next() is None, "running is not claimable"

    assert default_queue.requeue_interrupted() >= 1
    assert default_queue.status(job.id) == QUEUED
    assert default_queue.claim_next() is not None


def test_worker_runs_a_handler_and_records_progress(
    user_id: str, collection_id: str
) -> None:
    kind = f"handler-ok-{uuid4()}"
    seen: list[JobContext] = []

    def handler(ctx: JobContext) -> None:
        seen.append(ctx)
        ctx.report(0.5)
        ctx.report(1.0)

    register_handler(kind, handler)
    job = _enqueue(user_id, collection_id, kind)

    assert asyncio.run(run_once()) is True
    assert len(seen) == 1 and seen[0].job.id == job.id
    row = default_queue.get(job.id)
    assert row is not None and row.status == DONE and row.progress == 1.0


def test_handler_failure_fails_the_job_not_the_worker(
    user_id: str, collection_id: str
) -> None:
    kind = f"handler-boom-{uuid4()}"

    def handler(ctx: JobContext) -> None:
        raise RuntimeError("index exploded")

    register_handler(kind, handler)
    job = _enqueue(user_id, collection_id, kind)

    assert asyncio.run(run_once()) is True  # the failure is recorded, not raised
    row = default_queue.get(job.id)
    assert row is not None and row.status == FAILED
    assert "index exploded" in (row.error or "")


def test_unregistered_kind_fails_honestly(user_id: str, collection_id: str) -> None:
    job = _enqueue(user_id, collection_id, f"nobody-home-{uuid4()}")
    assert asyncio.run(run_once()) is True
    row = default_queue.get(job.id)
    assert row is not None and row.status == FAILED
    assert "No worker" in (row.error or "")


def test_cancel_inside_a_handler_is_honoured(user_id: str, collection_id: str) -> None:
    """Cancellation reaches work already running, between batches."""
    kind = f"handler-cancel-{uuid4()}"
    stopped: list[bool] = []

    def handler(ctx: JobContext) -> None:
        # The user clicks Cancel while the first batch is in flight.
        assert ctx.queue.cancel(ctx.job.id)
        stopped.append(ctx.should_continue())

    register_handler(kind, handler)
    job = _enqueue(user_id, collection_id, kind)

    asyncio.run(run_once())
    assert stopped == [False]
    assert default_queue.status(job.id) == CANCELLED, (
        "a cancelled job must not be completed by the worker finishing"
    )


def test_pause_inside_a_handler_keeps_the_job_paused(
    user_id: str, collection_id: str
) -> None:
    kind = f"handler-pause-{uuid4()}"

    def handler(ctx: JobContext) -> None:
        assert ctx.queue.pause(ctx.job.id)
        assert ctx.should_continue() is False

    register_handler(kind, handler)
    job = _enqueue(user_id, collection_id, kind)

    asyncio.run(run_once())
    assert default_queue.status(job.id) == PAUSED
    # Resume puts the remainder back in the queue, claimable again.
    assert default_queue.resume(job.id) is True
    assert default_queue.status(job.id) == QUEUED


def test_llm_call_cap_is_enforced_by_context(user_id: str, collection_id: str) -> None:
    kind = f"handler-cap-{uuid4()}"
    results: list[bool] = []

    def handler(ctx: JobContext) -> None:
        assert ctx.spend_call(2) is True  # 2 of 3 used
        assert ctx.spend_call(2) is False  # would exceed the cap
        assert ctx.remaining_calls() == 1
        results.append(True)

    register_handler(kind, handler)
    job = _enqueue(
        user_id, collection_id, kind, llm_calls_estimated=3, llm_calls_cap=3
    )

    asyncio.run(run_once())
    assert results == [True]
    row = default_queue.get(job.id)
    assert row is not None and row.llm_calls_used == 2
    assert row.llm_calls_cap == 3 and row.llm_calls_estimated == 3
    assert row.status == DONE


def test_empty_queue_returns_false() -> None:
    assert asyncio.run(run_once()) is False


def test_queue_rejects_foreign_reads_through_the_session(user_id: str, collection_id: str) -> None:
    """list() is the RLS-equivalent read used by any future job UI."""
    _enqueue(user_id, collection_id, "mine")
    mine = default_queue.list(user_id)
    assert [j.user_id for j in mine] == [user_id]
    assert default_queue.list(f"intruder-{uuid4()}") == []


def test_job_rows_cascade_with_their_collection(user_id: str, collection_id: str) -> None:
    """Deleting a collection removes its jobs (RAG §14.2, no residue)."""
    _enqueue(user_id, collection_id, "cascade-me")
    with SessionLocal() as db:
        assert service.delete_collection(db, user_id, collection_id) is True
    assert default_queue.list(user_id) == []


def test_worker_drains_back_to_back(user_id: str, collection_id: str) -> None:
    """run_once is called in a loop; each call takes exactly one job."""
    kind = f"drain-{uuid4()}"
    ran: list[str] = []
    register_handler(kind, lambda ctx: ran.append(ctx.job.id))
    first = _enqueue(user_id, collection_id, kind)
    second = _enqueue(user_id, collection_id, kind)

    async def drain() -> None:
        while await run_once():
            pass

    asyncio.run(drain())
    assert {first.id, second.id} == set(ran)
    assert default_queue.status(first.id) == DONE
    assert default_queue.status(second.id) == DONE


def test_job_queue_instance_is_independent() -> None:
    """A second queue over the same database behaves identically (no state is
    kept in Python between calls -- everything is a row)."""
    other = JobQueue()
    assert other.status("no-such-job") is None
