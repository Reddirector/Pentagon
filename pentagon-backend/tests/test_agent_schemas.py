"""The result envelope and the budget: the shapes the whole agent layer shares."""

import json

import pytest

from app.agent.schemas import Budget, BudgetExceeded, ToolResult, ToolSpec


def test_success_envelope_has_the_documented_shape():
    result = ToolResult.success("31 degrees", source_ids=["S1"], elapsed_ms=412)

    payload = json.loads(result.compact(max_chars=10_000))
    assert payload["ok"] is True
    assert payload["data"] == "31 degrees"
    assert payload["meta"]["source_ids"] == ["S1"]
    assert payload["meta"]["elapsed_ms"] == 412
    assert "error" not in payload


def test_failure_envelope_carries_code_message_hint():
    result = ToolResult.failure(
        "UPSTREAM", "The URL returned 403.", "Try a different source from the search results."
    )

    payload = json.loads(result.compact(max_chars=10_000))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "UPSTREAM"
    assert payload["error"]["message"] == "The URL returned 403."
    assert "hint" in payload["error"]
    assert "data" not in payload


def test_compact_truncates_and_flags():
    result = ToolResult.success("x" * 5_000)

    compact = result.compact(max_chars=500)
    assert len(compact) < 600
    payload = json.loads(compact)
    assert payload["meta"]["truncated"] is True
    assert len(payload["data"]) < 5_000


def test_compact_leaves_small_results_untouched():
    result = ToolResult.success({"answer": 4})
    compact = result.compact(max_chars=10_000)
    assert json.loads(compact) == json.loads(json.dumps(result.model_dump(exclude_none=True)))


def test_budget_counts_calls_then_raises():
    budget = Budget(max_llm_calls=2, max_tool_calls=1)
    budget.spend_llm_call()
    budget.spend_llm_call()
    with pytest.raises(BudgetExceeded) as excinfo:
        budget.spend_llm_call()
    assert "llm_calls" in str(excinfo.value)

    budget.spend_tool_call()
    with pytest.raises(BudgetExceeded):
        budget.spend_tool_call()


def test_budget_wall_clock():
    budget = Budget(max_seconds=120.0)
    assert budget.out_of_time() is False
    assert budget.time_left() > 100


def test_spec_accepts_a_well_formed_tool():
    spec = ToolSpec(
        name="web_search",
        description="Search the public web.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        tier="read",
    )
    assert spec.validation_errors() == []
