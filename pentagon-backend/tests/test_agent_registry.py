"""The registry is the one gate a tool passes through, so it must reject bad specs."""

import pytest

from app.agent.registry import (
    DuplicateToolError,
    ToolRegistry,
    UnknownToolError,
)
from app.agent.schemas import ToolResult, ToolSpec

_PARAMS = {"type": "object", "properties": {}, "required": []}


async def _handler(args, ctx):  # pragma: no cover - never invoked in these tests
    return ToolResult.success("hi")


def _spec(name: str = "get_current_time", **overrides) -> ToolSpec:
    fields: dict = {
        "name": name,
        "description": "Get the current time for a timezone.",
        "parameters": _PARAMS,
    }
    fields.update(overrides)
    return ToolSpec(**fields)


def test_register_then_get_returns_spec_and_handler():
    registry = ToolRegistry()
    registry.register(_spec(), _handler)

    registered = registry.get("get_current_time")
    assert registered.spec.name == "get_current_time"
    assert registered.handler is _handler
    assert registry.names() == ["get_current_time"]


def test_duplicate_name_is_rejected():
    registry = ToolRegistry()
    registry.register(_spec(), _handler)
    with pytest.raises(DuplicateToolError):
        registry.register(_spec(), _handler)


def test_unknown_tool_error_lists_valid_names():
    registry = ToolRegistry()
    registry.register(_spec(name="calculator"), _handler)

    with pytest.raises(UnknownToolError) as excinfo:
        registry.get("get_time_now")
    assert "calculator" in str(excinfo.value)
    assert excinfo.value.valid == ["calculator"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "GetTime"},                      # not snake_case
        {"description": "   "},                   # empty description
        {"parameters": {"type": "string"}},       # schema is not an object
        {"tier": "mega"},                         # not a real tier
        {"timeout_s": 0},                         # nonsense timeout
    ],
)
def test_invalid_specs_are_rejected_at_registration(overrides):
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="spec is invalid"):
        registry.register(_spec(**overrides), _handler)


def test_openai_schemas_shape_and_subset():
    registry = ToolRegistry()
    registry.register(_spec(name="calculator"), _handler)
    registry.register(_spec(name="get_current_time"), _handler)

    schemas = registry.openai_schemas()
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "calculator"
    assert schemas[0]["function"]["description"]
    assert schemas[0]["function"]["parameters"] == _PARAMS

    subset = registry.openai_schemas(names=["get_current_time"])
    assert [entry["function"]["name"] for entry in subset] == ["get_current_time"]
