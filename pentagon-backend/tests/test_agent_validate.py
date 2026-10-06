"""The validation layer: fix what is safe, refuse what is not, and say why."""

from app.agent.schemas import ToolSpec
from app.agent.validate import (
    RepairTracker,
    coerce_and_fill,
    parse_arguments,
    validate_call,
)

_CALCULATOR = ToolSpec(
    name="calculator",
    description="Evaluate arithmetic.",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string"},
            "precision": {"type": "integer", "default": 6},
        },
        "required": ["expression"],
    },
)


def _lookup(name: str):
    return _CALCULATOR if name == "calculator" else None


def test_parse_arguments_accepts_dicts_strings_and_nothing():
    as_dict, err = parse_arguments("calculator", {"expression": "1+1"})
    assert err is None and as_dict == {"expression": "1+1"}

    fenced, err = parse_arguments(
        "calculator", '```json\n{"expression": "1+1",}\n```'
    )
    assert err is None and fenced == {"expression": "1+1"}

    empty, err = parse_arguments("calculator", None)
    assert err is None and empty == {}

    bad, err = parse_arguments("calculator", '{"expression": "1+1"')
    assert bad is None
    assert err is not None and err.error.code == "INVALID_ARGS"


def test_parse_arguments_refuses_lists_and_scalars_instead_of_wrapping():
    for raw in (["1+1"], "42"):
        args, err = parse_arguments("calculator", raw)
        assert args is None
        assert err is not None and err.error.code == "INVALID_ARGS"


def test_coerce_fills_defaults_and_safe_casts():
    args, errors = coerce_and_fill(
        _CALCULATOR, {"expression": "1+1", "precision": "3"}
    )
    assert errors == []
    assert args["precision"] == 3
    assert isinstance(args["precision"], int)


def test_schema_violations_become_readable_errors():
    args, errors = coerce_and_fill(_CALCULATOR, {})
    assert errors, "a missing required argument must be reported"
    assert any("expression" in e for e in errors)
    assert args["precision"] == 6, "the default still fills in"


def test_validate_call_passes_a_good_call_through():
    tracker = RepairTracker()
    checked = validate_call(
        {"name": "calculator", "args": {"expression": "2+2"}, "id": "c1"},
        _lookup,
        tracker,
    )
    assert checked.executable is True
    assert checked.args == {"expression": "2+2", "precision": 6}


def test_validate_call_refuses_unknown_tools():
    tracker = RepairTracker()
    checked = validate_call({"name": "nope", "args": {}, "id": "c1"}, _lookup, tracker)
    assert checked.executable is False
    assert checked.refusal is not None
    assert checked.refusal.error.code == "NOT_FOUND"


def test_validate_call_quotes_schema_in_the_corrective_message():
    tracker = RepairTracker()
    checked = validate_call(
        {"name": "calculator", "args": {"precision": "not-a-number"}, "id": "c1"},
        _lookup,
        tracker,
    )
    assert checked.executable is False
    assert checked.refusal.error.code == "INVALID_ARGS"
    assert "expression" in checked.refusal.error.message
    assert "schema" in checked.refusal.error.hint.lower()


def test_repair_exhaustion_blocks_the_tool_after_two_failures():
    tracker = RepairTracker()
    call = {"name": "calculator", "args": {}, "id": "c1"}
    first = validate_call(call, _lookup, tracker)
    assert first.executable is False
    second = validate_call(call, _lookup, tracker)
    assert second.executable is False
    third = validate_call(call, _lookup, tracker)
    assert third.executable is False
    # The third refusal is the exhaustion refusal, not another schema one.
    assert third.refusal.error.code == "DENIED"
    assert "twice" in third.refusal.error.message


def test_repair_tracker_is_per_tool():
    tracker = RepairTracker()
    validate_call({"name": "calculator", "args": {}, "id": "c1"}, _lookup, tracker)
    assert tracker.exhausted("calculator") is False
    assert tracker.exhausted("other") is False
