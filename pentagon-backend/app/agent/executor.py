"""Tool execution: parallelism, timeouts, retries, caching, guards.

Independent calls the model asked for in one turn run concurrently (bounded by
a semaphore); tools marked ``parallel_safe=False`` run alone, in the order the
model asked. Read tools that are idempotent get exactly one retry on a
transient failure -- writes and destructive tools never retry, because a
repeated side effect is worse than a reported failure. Identical cacheable
calls within the TTL reuse the stored result and are marked ``cached``. Every
failure comes back as a result envelope rather than an exception, so the
transcript stays well-formed no matter what happened.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Any

from app.agent.registry import ToolRegistry, UnknownToolError
from app.agent.schemas import Budget, BudgetExceeded, ToolContext, ToolResult

_CONCURRENCY = 4
_RETRY_BACKOFF_SECONDS = (0.05, 0.2)
_CACHE_LIMIT = 256

# (expires_at, result) keyed by hash(tool + canonical args + user_id)
_CACHE: dict[str, tuple[float, ToolResult]] = {}


def canonical_key(tool: str, args: dict[str, Any]) -> str:
    """A stable identity for "the same call": name plus order-independent args."""
    return tool + ":" + json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)


def _cache_key(tool: str, args: dict[str, Any], user_id: str) -> str:
    digest = hashlib.sha256((canonical_key(tool, args) + "|" + user_id).encode()).hexdigest()
    return digest


def clear_cache() -> None:
    """Empty the cross-turn tool cache (used by tests and by key changes)."""
    _CACHE.clear()


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


@dataclass(frozen=True)
class ExecutedCall:
    """One tool call and everything that happened to it."""

    tool: str
    args: dict[str, Any]
    tool_call_id: str
    result: ToolResult
    # ok | error | denied | timeout | reused | cached | cancelled
    status: str
    elapsed_ms: float


class Executor:
    """Runs validated tool calls under the turn's budget and duplicate guard."""

    def __init__(self, registry: ToolRegistry, budget: Budget) -> None:
        self.registry = registry
        self.budget = budget
        self._seen: dict[str, ToolResult] = {}
        self._semaphore = asyncio.Semaphore(_CONCURRENCY)

    # -- one call -----------------------------------------------------------

    def _budget_denied(self, call_id: str, exc: BudgetExceeded, started: float) -> ExecutedCall:
        result = ToolResult.failure(
            "DENIED",
            f"This call was not run: the turn's tool budget ran out ({exc.what}).",
            hint="Answer the user with what has already been gathered.",
        )
        return ExecutedCall("", {}, call_id, result, "denied", _ms(started))

    def _cancelled(self, call_id: str, started: float) -> ExecutedCall:
        result = ToolResult.failure(
            "DENIED",
            "This call was not run because the turn was stopped.",
            hint="Do not retry; the user chose to stop.",
        )
        return ExecutedCall("", {}, call_id, result, "cancelled", _ms(started))

    async def run_one(self, call: dict[str, Any], ctx: ToolContext) -> ExecutedCall:
        """Execute a single call; never raises tool errors."""
        started = time.perf_counter()
        name = str(call.get("name") or "")
        raw_args = call.get("args")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        call_id = str(call.get("id") or "")

        if raw_args is not None and not isinstance(raw_args, dict):
            result = ToolResult.failure(
                "INVALID_ARGS",
                f"Arguments for {name!r} were not a JSON object.",
                hint="Re-send the call with a JSON object of arguments.",
            )
            return ExecutedCall(name, args, call_id, result, "error", _ms(started))

        if ctx.cancel is not None and ctx.cancel.is_set():
            return self._cancelled(call_id, started)

        key = canonical_key(name, args)
        if key in self._seen:
            earlier = self._seen[key]
            result = ToolResult.success(
                {
                    "note": "already called this turn; reuse this result instead of calling again",
                    "result": earlier.data,
                },
                source_ids=earlier.meta.source_ids,
            )
            return ExecutedCall(name, args, call_id, result, "reused", _ms(started))

        try:
            registered = self.registry.get(name)
        except UnknownToolError as exc:
            result = ToolResult.failure(
                "NOT_FOUND", str(exc), hint="Pick one of the valid tool names and try again."
            )
            return ExecutedCall(name, args, call_id, result, "error", _ms(started))

        spec = registered.spec
        cache_key = _cache_key(name, args, ctx.user_id) if spec.cacheable else None
        if cache_key is not None:
            hit = _CACHE.get(cache_key)
            if hit is not None and hit[0] > time.monotonic():
                cached = hit[1]
                result = ToolResult.success(
                    cached.data,
                    source_ids=cached.meta.source_ids,
                    elapsed_ms=cached.meta.elapsed_ms,
                )
                return ExecutedCall(name, args, call_id, result, "cached", _ms(started))

        try:
            self.budget.spend_tool_call()
        except BudgetExceeded as exc:
            return self._budget_denied(call_id, exc, started)

        may_retry = spec.tier == "read" and spec.idempotent
        attempts = 2 if may_retry else 1
        for attempt in range(attempts):
            if attempt and ctx.cancel is not None and ctx.cancel.is_set():
                return self._cancelled(call_id, started)
            if attempt:
                await asyncio.sleep(random.uniform(*_RETRY_BACKOFF_SECONDS))
            outcome = await self._attempt(name, args, call_id, registered.handler, ctx, started)
            transient = outcome.status in ("timeout", "error") and outcome.result.error is not None and (
                outcome.result.error.code in ("TIMEOUT", "UPSTREAM")
            )
            if outcome.status == "ok" or not transient or attempt == attempts - 1:
                break
        executed = outcome

        if executed.status == "ok":
            self._seen[key] = executed.result
            if cache_key is not None:
                if len(_CACHE) >= _CACHE_LIMIT:
                    oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
                    _CACHE.pop(oldest, None)
                _CACHE[cache_key] = (time.monotonic() + spec.cache_ttl_s, executed.result)
        return executed

    async def _attempt(
        self, name: str, args: dict[str, Any], call_id: str, handler, ctx: ToolContext, started: float
    ) -> ExecutedCall:
        try:
            registered = self.registry.get(name)
            async with self._semaphore:
                result = await asyncio.wait_for(handler(args, ctx), timeout=registered.spec.timeout_s)
        except asyncio.TimeoutError:
            result = ToolResult.failure(
                "TIMEOUT",
                f"{name} did not finish within {registered.spec.timeout_s}s.",
                hint="Try a narrower version of the call, or answer without it.",
            )
            return ExecutedCall(name, args, call_id, result, "timeout", _ms(started))
        except asyncio.CancelledError:
            if ctx.cancel is not None and ctx.cancel.is_set():
                return self._cancelled(call_id, started)
            raise
        except Exception as exc:  # a broken tool must not break the turn
            result = ToolResult.failure(
                "UPSTREAM",
                f"{name} failed: {type(exc).__name__}: {exc}",
                hint="Read the error, change the approach, or answer without this tool.",
            )
            return ExecutedCall(name, args, call_id, result, "error", _ms(started))
        status = "ok" if result.ok else "error"
        return ExecutedCall(name, args, call_id, result, status, _ms(started))

    # -- a batch ------------------------------------------------------------

    async def run_many(self, calls: list[dict[str, Any]], ctx: ToolContext) -> list[ExecutedCall]:
        """Run a batch, concurrent where safe, results in the model's order.

        Calls whose tool is ``parallel_safe`` run concurrently under the
        semaphore; the others run one at a time, in the given order, because
        their results may depend on ordering (or they simply must not
        interleave). The returned list always matches the input order, so each
        result can be paired with its ``tool_call_id``.
        """
        if not calls:
            return []
        results: list[ExecutedCall | None] = [None] * len(calls)

        async def run_at(index: int) -> None:
            results[index] = await self.run_one(calls[index], ctx)

        parallel_indexes = [i for i, call in enumerate(calls) if self._is_parallel_safe(call)]
        sequential_indexes = [i for i in range(len(calls)) if i not in set(parallel_indexes)]

        gathered = [asyncio.ensure_future(run_at(i)) for i in parallel_indexes]
        for i in sequential_indexes:
            await run_at(i)
        if gathered:
            await asyncio.gather(*gathered)
        return [result for result in results if result is not None]

    def _is_parallel_safe(self, call: dict[str, Any]) -> bool:
        name = str(call.get("name") or "")
        try:
            return self.registry.get(name).spec.parallel_safe
        except UnknownToolError:
            return False
