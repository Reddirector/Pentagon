"""Two lanes sharing one request budget, chat first.

NVIDIA's free tier is roughly 40 requests/minute for everything, and RAG
indexing (embedding batches, graph extraction, community summaries) would
happily spend all of it. So there is one bucket -- ``rate_limit_per_minute``
tokens, refilled at the same rate -- and two ways to spend from it:

``interactive``
    Chat turns. Waits are served **before** any waiting background job, so a
    person never queues behind an index run.
``background``
    Index jobs. Needs a token from the shared bucket *and* a token from its
    own credit line, which refills at ``graph_index_rate_fraction`` of the
    bucket's rate. Over any window indexing therefore spends at most that
    fraction, leaving the rest for chat by construction -- even before
    priority is considered.

There is deliberately no background timer: a permit is refilled when someone
asks for one (or when the scheduled wake for a waiter fires), so an idle app
does nothing at all. Waits are bounded -- a caller that cannot get a permit
inside ``rate_limit_wait_seconds`` raises :class:`RateLimitTimeout`, which the
routes turn into a 429 rather than a hang.

Accounting is admission-based: one permit per chat turn and one per index-job
step. The agent loop's per-call budgets (RAG §10.6) are a separate, stricter
control that sits closer to the model calls themselves.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from app.config import settings

LANE_INTERACTIVE = "interactive"
LANE_BACKGROUND = "background"


class RateLimitTimeout(Exception):
    """No permit became available within the wait budget."""


@dataclass
class _Waiter:
    lane: str
    future: asyncio.Future[None]


class RateLimiter:
    """A priority token bucket.

    ``clock`` is injectable so tests can move time without sleeping; every
    method that touches state is synchronous and non-blocking, so a single
    event-loop thread needs no lock.
    """

    def __init__(
        self,
        *,
        capacity: float,
        refill_per_minute: float,
        background_fraction: float = 0.5,
        wait_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_per_minute < 0:
            raise ValueError("refill rate cannot be negative")
        if not 0 < background_fraction <= 1:
            raise ValueError("background_fraction must be in (0, 1]")
        self.capacity = float(capacity)
        self.background_fraction = float(background_fraction)
        self.background_capacity = self.capacity * self.background_fraction
        self.wait_seconds = float(wait_seconds)
        self._refill_per_second = refill_per_minute / 60.0
        self._background_refill_per_second = self._refill_per_second * self.background_fraction
        self._clock = clock
        self._last_refill = clock()
        self._tokens = self.capacity
        self._background_tokens = self.background_capacity
        self._waiters: deque[_Waiter] = deque()

    # -- introspection (tests, traces) -------------------------------------
    @property
    def tokens(self) -> float:
        self._refill()
        return self._tokens

    @property
    def background_tokens(self) -> float:
        self._refill()
        return self._background_tokens

    @property
    def waiting(self) -> dict[str, int]:
        interactive = sum(1 for w in self._waiters if w.lane == LANE_INTERACTIVE)
        return {
            LANE_INTERACTIVE: interactive,
            LANE_BACKGROUND: len(self._waiters) - interactive,
        }

    # -- internals ----------------------------------------------------------
    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._last_refill = now
        if elapsed:
            self._tokens = min(self.capacity, self._tokens + elapsed * self._refill_per_second)
            self._background_tokens = min(
                self.background_capacity,
                self._background_tokens + elapsed * self._background_refill_per_second,
            )

    def _try_take(self, lane: str) -> bool:
        if lane == LANE_INTERACTIVE:
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False
        # Background needs both pots: a shared token (it counts against the
        # real budget) and a credit token (its fraction of that budget).
        if self._background_tokens >= 1 and self._tokens >= 1:
            self._background_tokens -= 1
            self._tokens -= 1
            return True
        return False

    def _drain(self) -> None:
        # Interactive first, always: priority is about who gets the next token
        # that frees up, not who arrived first.
        while True:
            granted = False
            for lane in (LANE_INTERACTIVE, LANE_BACKGROUND):
                for waiter in list(self._waiters):
                    if waiter.lane != lane:
                        continue
                    if waiter.future.done():
                        self._waiters.remove(waiter)
                        continue
                    if self._try_take(lane):
                        self._waiters.remove(waiter)
                        waiter.future.set_result(None)
                        granted = True
                        break
                if granted:
                    break
            if not granted:
                return

    def wake(self) -> None:
        """Refill from the clock and hand permits to whoever is waiting.

        The internal timer calls this; tests with an injected clock call it
        directly after advancing time.
        """
        self._refill()
        self._drain()

    def _seconds_until_next_grant(self, lane: str) -> float | None:
        """Real seconds until this lane could take a token, or None if never."""
        if self._refill_per_second <= 0:
            return None
        needed = max(0.0, 1.0 - self._tokens)
        delay = needed / self._refill_per_second
        if lane == LANE_BACKGROUND:
            if self._background_refill_per_second <= 0:
                return None
            background_needed = max(0.0, 1.0 - self._background_tokens)
            delay = max(delay, background_needed / self._background_refill_per_second)
        # Wake a hair early rather than a hair late; a spurious wake is free.
        return delay + 0.001

    def _schedule_wake(self) -> None:
        if not self._waiters:
            return
        loop = asyncio.get_running_loop()
        # The earliest any queued waiter can be served drives the timer.
        delays = [
            delay
            for delay in (
                self._seconds_until_next_grant(lane)
                for lane in (LANE_INTERACTIVE, LANE_BACKGROUND)
            )
            if delay is not None
        ]
        if not delays:
            return  # nothing refills; only a timeout will free these waiters
        loop.call_later(min(delays), self._wake_scheduled)

    def _wake_scheduled(self) -> None:
        if not self._waiters:
            return
        self.wake()
        # Tokens may still be short (refill is gradual); re-arm.
        self._schedule_wake()

    # -- public API ---------------------------------------------------------
    async def acquire(self, lane: str = LANE_INTERACTIVE, timeout: float | None = None) -> None:
        """Wait for one permit on ``lane``.

        Interactive callers never queue behind a waiting background job: if a
        token is free they take it immediately, and when tokens free up the
        interactive waiters are served first.
        """
        if lane not in (LANE_INTERACTIVE, LANE_BACKGROUND):
            raise ValueError(f"unknown lane: {lane!r}")
        wait = self.wait_seconds if timeout is None else timeout

        self._refill()
        if lane == LANE_INTERACTIVE or not self._waiters:
            if self._try_take(lane):
                return

        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(_Waiter(lane=lane, future=future))
        self._schedule_wake()
        try:
            await asyncio.wait_for(future, timeout=wait)
        except TimeoutError:
            # wait_for cancelled the future; drop the dead waiter so the
            # queue cannot fill with callers that already gave up.
            self._waiters = deque(w for w in self._waiters if w.future is not future)
            self._schedule_wake()
            raise RateLimitTimeout(
                f"No {lane} permit became available within {wait:.0f}s."
            ) from None


def build_limiter() -> RateLimiter:
    """The process-wide limiter, from settings."""
    return RateLimiter(
        capacity=settings.rate_limit_per_minute,
        refill_per_minute=settings.rate_limit_per_minute,
        background_fraction=settings.graph_index_rate_fraction,
        wait_seconds=settings.rate_limit_wait_seconds,
    )


rate_limiter = build_limiter()
