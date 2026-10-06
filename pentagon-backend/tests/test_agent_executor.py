"""The executor: concurrency that is real, guards that actually guard."""

import asyncio
import time

import pytest

from app.agent.executor import Executor, clear_cache
from app.agent.registry import ToolRegistry
from app.agent.schemas import Budget, ToolContext, ToolResult, ToolSpec


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _ctx(**overrides) -> ToolContext:
    fields = {"user_id": "u1", "conversation_id": "c1", "turn_id": "t1", "permission_level": 2}
    fields.update(overrides)
    return ToolContext(**fields)


def _spec(name: str, **overrides) -> ToolSpec:
    fields = {
        "name": name,
        "description": f"The {name} tool.",
        "parameters": {"type": "object", "properties": {}},
    }
    fields.update(overrides)
    return ToolSpec(**fields)


def test_parallel_calls_run_concurrently():
    registry = ToolRegistry()
    started: list[float] = []
    finished: list[float] = []

    async def sleeper(args, ctx):
        started.append(time.monotonic())
        await asyncio.sleep(0.15)
        finished.append(time.monotonic())
        return ToolResult.success("ok")

    for i in range(4):
        registry.register(_spec(f"tool_{i}", timeout_s=5), sleeper)

    executor = Executor(registry, Budget())
    calls = [
        {"name": f"tool_{i}", "args": {}, "id": f"c{i}"} for i in range(4)
    ]
    results = asyncio.run(executor.run_many(calls, _ctx()))

    assert len(results) == 4
    assert all(r.status == "ok" for r in results)
    assert max(finished) - min(started) < 0.45, "4 x 150ms calls must overlap, not queue"


def test_results_keep_the_model_s_order():
    registry = ToolRegistry()

    async def fast(args, ctx):
        await asyncio.sleep(0.01)
        return ToolResult.success("fast")

    async def slow(args, ctx):
        await asyncio.sleep(0.05)
        return ToolResult.success("slow")

    registry.register(_spec("a_fast", timeout_s=5), fast)
    registry.register(_spec("b_slow", timeout_s=5), slow)

    executor = Executor(registry, Budget())
    results = asyncio.run(
        executor.run_many(
            [
                {"name": "b_slow", "args": {}, "id": "first"},
                {"name": "a_fast", "args": {}, "id": "second"},
            ],
            _ctx(),
        )
    )
    assert [r.tool_call_id for r in results] == ["first", "second"]
    assert results[0].result.data == "slow"


def test_non_parallel_tool_runs_alone():
    registry = ToolRegistry()
    overlaps: list[tuple[float, float]] = []

    async def exclusive(args, ctx):
        start = time.monotonic()
        await asyncio.sleep(0.08)
        overlaps.append((start, time.monotonic()))
        return ToolResult.success("ok")

    registry.register(_spec("mutex_tool", parallel_safe=False, timeout_s=5), exclusive)

    async def quick(args, ctx):
        await asyncio.sleep(0.01)
        return ToolResult.success("ok")

    registry.register(_spec("side_tool", timeout_s=5), quick)

    executor = Executor(registry, Budget())
    results = asyncio.run(
        executor.run_many(
            [
                {"name": "mutex_tool", "args": {}, "id": "m1"},
                {"name": "side_tool", "args": {}, "id": "s1"},
                {"name": "mutex_tool", "args": {"x": 1}, "id": "m2"},
            ],
            _ctx(),
        )
    )
    assert len(results) == 3
    first, second = overlaps
    assert second[0] >= first[1], "the two exclusive runs must not overlap"


def test_cacheable_calls_are_served_from_cache():
    registry = ToolRegistry()
    counter = {"n": 0}

    async def counted(args, ctx):
        counter["n"] += 1
        return ToolResult.success(counter["n"])

    registry.register(_spec("count_me", cacheable=True, cache_ttl_s=60, timeout_s=5), counted)

    # Two separate turns (fresh executors), same user: the second turn hits
    # the cross-turn cache. Within one turn the duplicate guard answers
    # "reused" first, which is its own tested behavior.
    first = asyncio.run(
        Executor(registry, Budget()).run_one({"name": "count_me", "args": {}, "id": "c1"}, _ctx())
    )
    again = asyncio.run(
        Executor(registry, Budget()).run_one({"name": "count_me", "args": {}, "id": "c2"}, _ctx())
    )

    assert first.status == "ok"
    assert again.status == "cached"
    assert counter["n"] == 1
    assert again.result.data == 1


def test_cache_is_per_user():
    registry = ToolRegistry()

    async def who(args, ctx):
        return ToolResult.success(ctx.user_id)

    registry.register(_spec("who_am_i", cacheable=True, cache_ttl_s=60, timeout_s=5), who)

    mine = asyncio.run(
        Executor(registry, Budget()).run_one({"name": "who_am_i", "args": {}, "id": "c1"}, _ctx(user_id="u1"))
    )
    theirs = asyncio.run(
        Executor(registry, Budget()).run_one({"name": "who_am_i", "args": {}, "id": "c2"}, _ctx(user_id="u2"))
    )

    assert mine.result.data == "u1"
    assert theirs.result.data == "u2", "one user must never be served another's cached result"


def test_read_tools_retry_once_on_transient_failure():
    registry = ToolRegistry()
    attempts = {"n": 0}

    async def flaky(args, ctx):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("connection reset")
        return ToolResult.success("second try")

    registry.register(_spec("flaky_read", timeout_s=5), flaky)
    executor = Executor(registry, Budget())

    result = asyncio.run(executor.run_one({"name": "flaky_read", "args": {}, "id": "c1"}, _ctx()))
    assert result.status == "ok"
    assert result.result.data == "second try"
    assert attempts["n"] == 2


def test_write_tools_never_retry():
    registry = ToolRegistry()
    attempts = {"n": 0}

    async def flaky_write(args, ctx):
        attempts["n"] += 1
        raise RuntimeError("send failed")

    registry.register(_spec("flaky_write", tier="write", timeout_s=5), flaky_write)
    executor = Executor(registry, Budget())

    result = asyncio.run(executor.run_one({"name": "flaky_write", "args": {}, "id": "c1"}, _ctx()))
    assert result.status == "error"
    assert attempts["n"] == 1, "a failed send must not be re-sent automatically"


def test_stop_cancels_pending_calls():
    registry = ToolRegistry()

    async def never_ends(args, ctx):
        await asyncio.sleep(5)
        return ToolResult.success("nope")

    registry.register(_spec("endless", timeout_s=10), never_ends)

    cancel = asyncio.Event()

    async def scenario():
        executor = Executor(registry, Budget())
        task = asyncio.ensure_future(
            executor.run_one({"name": "endless", "args": {}, "id": "c1"}, _ctx(cancel=cancel))
        )
        await asyncio.sleep(0.05)
        cancel.set()
        return await asyncio.wait_for(task, timeout=3)

    result = asyncio.run(scenario())
    assert result.status == "cancelled"
    assert result.result.error.code == "DENIED"


def test_budget_denial_comes_back_as_an_envelope():
    registry = ToolRegistry()

    async def any_tool(args, ctx):
        return ToolResult.success("ok")

    registry.register(_spec("tool_a", timeout_s=5), any_tool)
    registry.register(_spec("tool_b", timeout_s=5), any_tool)

    executor = Executor(registry, Budget(max_tool_calls=1))
    first = asyncio.run(executor.run_one({"name": "tool_a", "args": {}, "id": "c1"}, _ctx()))
    second = asyncio.run(executor.run_one({"name": "tool_b", "args": {}, "id": "c2"}, _ctx()))

    assert first.status == "ok"
    assert second.status == "denied"
    assert second.result.error.code == "DENIED"
    assert "budget" in second.result.error.message


def test_duplicate_within_a_turn_is_reused_not_rerun():
    registry = ToolRegistry()
    counter = {"n": 0}

    async def counted(args, ctx):
        counter["n"] += 1
        return ToolResult.success(counter["n"])

    registry.register(_spec("once_only", timeout_s=5), counted)
    executor = Executor(registry, Budget())

    first = asyncio.run(executor.run_one({"name": "once_only", "args": {"q": "x"}, "id": "c1"}, _ctx()))
    second = asyncio.run(executor.run_one({"name": "once_only", "args": {"q": "x"}, "id": "c2"}, _ctx()))

    assert first.status == "ok" and second.status == "reused"
    assert counter["n"] == 1


def test_empty_batch_and_unknown_tool_shapes():
    registry = ToolRegistry()
    executor = Executor(registry, Budget())
    assert asyncio.run(executor.run_many([], _ctx())) == []

    unknown = asyncio.run(executor.run_one({"name": "ghost", "args": {}, "id": "c1"}, _ctx()))
    assert unknown.status == "error"
    assert unknown.result.error.code == "NOT_FOUND"
