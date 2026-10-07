"""Two lanes, one bucket: chat never queues behind an indexing job.

The budget here is NVIDIA's free tier (~40 requests/minute), and RAG indexing
would spend all of it. These tests pin the two promises the design makes:

* a background job can spend at most its fraction of the bucket, so chat's
  share is untouched by construction, and
* when a token does free up, a waiting chat turn gets it before a waiting
  index job, whoever arrived first.

Time is injected (``FakeClock``), so "a minute later" costs no wall-clock
waiting; only the bounded-timeout tests sleep, and those sleep for
milliseconds.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models import ApiKey, User
from app.db.session import SessionLocal
from app.main import app
from app.rag2.jobs import default_queue, register_handler, run_once
from app.services import rate_limiter as rl
from app.services.rate_limiter import (
    LANE_BACKGROUND,
    LANE_INTERACTIVE,
    RateLimiter,
    RateLimitTimeout,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _limiter(capacity: float = 10, refill_per_minute: float = 60, fraction: float = 0.5) -> RateLimiter:
    return RateLimiter(
        capacity=capacity,
        refill_per_minute=refill_per_minute,
        background_fraction=fraction,
        wait_seconds=5.0,
        clock=FakeClock(),
    )


def test_interactive_takes_a_token_without_waiting() -> None:
    limiter = _limiter(capacity=5)

    async def scenario() -> float:
        await limiter.acquire(LANE_INTERACTIVE)
        await limiter.acquire(LANE_INTERACTIVE)
        return limiter.tokens

    assert asyncio.run(scenario()) == 3


def test_background_spends_only_its_fraction_of_the_bucket() -> None:
    """Indexing must not be able to empty the bucket chat drinks from."""
    limiter = _limiter(capacity=10, fraction=0.5)

    async def scenario() -> tuple[int, bool]:
        granted = 0
        for _ in range(5):  # the credit line holds capacity * 0.5 = 5
            await limiter.acquire(LANE_BACKGROUND, timeout=0.05)
            granted += 1
        timed_out = False
        try:
            await limiter.acquire(LANE_BACKGROUND, timeout=0.05)
        except RateLimitTimeout:
            timed_out = True
        # Chat's half of the bucket is still there, untouched.
        await limiter.acquire(LANE_INTERACTIVE, timeout=0.05)
        return granted, timed_out

    granted, timed_out = asyncio.run(scenario())
    assert granted == 5, "background spent more than its fraction of the bucket"
    assert timed_out, "the sixth background call should have waited"
    assert limiter.tokens == 4  # 10 - 5 background - 1 chat


def test_chat_outqueues_a_line_of_index_jobs() -> None:
    """Priority: the arriving chat turn wins the next token, not FIFO."""
    clock = FakeClock()
    limiter = RateLimiter(
        capacity=10,
        refill_per_minute=60,  # 1 token/second
        background_fraction=0.5,
        wait_seconds=5.0,
        clock=clock,
    )
    order: list[str] = []

    async def scenario() -> None:
        for _ in range(10):  # drain the bucket
            await limiter.acquire(LANE_INTERACTIVE)

        bg1 = asyncio.create_task(limiter.acquire(LANE_BACKGROUND))
        bg2 = asyncio.create_task(limiter.acquire(LANE_BACKGROUND))
        await asyncio.sleep(0)
        chat = asyncio.create_task(limiter.acquire(LANE_INTERACTIVE))
        chat.add_done_callback(lambda _t: order.append("chat"))
        bg1.add_done_callback(lambda _t: order.append("bg1"))
        bg2.add_done_callback(lambda _t: order.append("bg2"))
        await asyncio.sleep(0)
        assert limiter.waiting == {"interactive": 1, "background": 2}

        # Two seconds pass: two tokens for chat's lane, one credit for bg.
        clock.advance(2)
        limiter.wake()

        await asyncio.wait_for(chat, timeout=1)
        await asyncio.wait_for(bg1, timeout=1)
        await asyncio.sleep(0)  # let the completion callbacks record the order
        assert order[:2] == ["chat", "bg1"], (
            f"priority failed: completion order was {order}"
        )
        assert not bg2.done(), "background must keep waiting while chat has demand"

        clock.advance(4)
        limiter.wake()
        await asyncio.wait_for(bg2, timeout=1)
        await asyncio.sleep(0)
        assert order == ["chat", "bg1", "bg2"]

    asyncio.run(scenario())


def test_timeout_frees_the_queue_and_says_so() -> None:
    limiter = _limiter(capacity=1, refill_per_minute=0)  # one token, never refilled

    async def scenario() -> None:
        await limiter.acquire(LANE_INTERACTIVE)
        try:
            await limiter.acquire(LANE_INTERACTIVE, timeout=0.05)
        except RateLimitTimeout as exc:
            assert "interactive" in str(exc)
        else:
            raise AssertionError("a spent bucket must refuse, not hang")
        assert limiter.waiting == {"interactive": 0, "background": 0}

    asyncio.run(scenario())


def test_unknown_lane_is_a_programming_error() -> None:
    limiter = _limiter()

    async def scenario() -> None:
        try:
            await limiter.acquire("sideways")
        except ValueError:
            return
        raise AssertionError("unknown lanes must be rejected")

    asyncio.run(scenario())


# --- wiring ----------------------------------------------------------------
def _provision(monkeypatch) -> str:
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.config import settings
    from app.security.crypto import encrypt_api_key

    monkeypatch.setattr(
        settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode())
    )
    user_id = f"lane-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-test-key"),
                masked_key="nvapi-...key",
            )
        )
        db.commit()
    return user_id


def _reset_jobs() -> None:
    """Cancel stray jobs left by other tests: run_once claims the oldest."""
    from sqlalchemy import update

    from app.db.models import IndexJob

    with SessionLocal() as db:
        db.execute(
            update(IndexJob)
            .where(IndexJob.status.in_(("queued", "running")))
            .values(status="cancelled")
        )
        db.commit()


def _install_refusal(monkeypatch) -> list[str]:
    """Make every lane request fail, and record what was asked for."""
    seen: list[str] = []

    def refuse(self, lane=LANE_INTERACTIVE, timeout=None):  # noqa: ANN001
        seen.append(lane)

        async def inner() -> None:
            raise RateLimitTimeout("budget spent")

        return inner()

    monkeypatch.setattr(rl.rate_limiter, "acquire", refuse)
    return seen


def test_chat_route_pays_for_admission(monkeypatch) -> None:
    """The chat route must consult the limiter on the interactive lane."""
    user_id = _provision(monkeypatch)
    seen = _install_refusal(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "conversation_id": str(uuid4()),
                "model": "test/model",
                "message": "hello",
            },
        )
    assert response.status_code == 429, response.text
    assert seen == [LANE_INTERACTIVE]


def test_agent_route_pays_for_admission(monkeypatch) -> None:
    user_id = _provision(monkeypatch)
    seen = _install_refusal(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": user_id,
                "conversation_id": str(uuid4()),
                "model": "test/model",
                "message": "hello",
            },
        )
    assert response.status_code == 429, response.text
    assert seen == [LANE_INTERACTIVE]


def test_index_jobs_wait_for_the_background_lane(monkeypatch) -> None:
    """A job claimed under a busy budget is re-queued, never left running."""
    _reset_jobs()
    user_id = _provision(monkeypatch)
    with SessionLocal() as db:
        from app.db.models import Conversation
        from app.rag2 import collections as service

        conversation = Conversation(user_id=user_id, title="t")
        db.add(conversation)
        db.commit()
        collection = service.create_collection(db, user_id=user_id, name="Budget")

    kind = f"lane-test-{uuid4()}"
    ran: list[str] = []
    register_handler(kind, lambda ctx: ran.append(ctx.job.id))
    job = default_queue.enqueue(
        user_id=user_id, collection_id=collection.id, kind=kind
    )

    def refuse(self, lane=LANE_INTERACTIVE, timeout=None):  # noqa: ANN001
        async def inner() -> None:
            raise RateLimitTimeout("budget spent")

        return inner()

    monkeypatch.setattr(rl.rate_limiter, "acquire", refuse)
    claimed = asyncio.run(run_once())
    assert claimed is False, "the job must not run while the budget is refused"
    assert ran == [], "a job must not execute without its background permit"
    assert default_queue.status(job.id) == "queued", (
        "the job must go back to queued, not freeze in running"
    )
