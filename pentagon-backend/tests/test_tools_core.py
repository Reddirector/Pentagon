"""Core tools in isolation: calculator must never execute code, time must validate zones."""

import asyncio

import pytest

from app.agent.schemas import ToolContext
from app.tools import calculator, get_current_time
from app.tools.calculator import CalculatorError, evaluate


def _ctx() -> ToolContext:
    return ToolContext(user_id="t", conversation_id="c", turn_id="t0", permission_level=2)


# --- calculator: the allowlist is the security boundary ----------------------

def test_calculator_evaluates_plain_arithmetic():
    assert evaluate("1 + 2 * 3") == 7
    assert evaluate("(1 + 0.07) ** 30 * 1500") == pytest.approx((1 + 0.07) ** 30 * 1500)
    assert evaluate("10 / 4") == 2.5
    assert evaluate("2 ** 10") == 1024
    assert evaluate("sqrt(144) + max(3, 9)") == 21
    assert evaluate("round(pi, 2)") == 3.14


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",          # the classic
        "__builtins__",
        "().__class__.__bases__[0].__subclasses__",  # attribute traversal
        "(lambda: 1)()",
        "x = 5",                                   # statements, not expressions
        "open('/etc/passwd')",
        "eval('1')",
        "os.getcwd",
    ],
)
def test_calculator_refuses_code_and_traversal(expression):
    with pytest.raises(CalculatorError):
        evaluate(expression)


def test_calculator_refuses_variables_and_names():
    with pytest.raises(CalculatorError):
        evaluate("secret_key + 1")


def test_calculator_guards_the_big_exponent_bomb():
    with pytest.raises(CalculatorError):
        evaluate("9 ** 9999999")


def test_calculator_division_by_zero_is_an_error_not_a_crash():
    with pytest.raises(CalculatorError):
        evaluate("1 / 0")


async def _run_calculator(expression: str):
    return await calculator.run({"expression": expression}, _ctx())


def test_calculator_tool_envelope_on_success_and_failure():
    ok = asyncio.run(_run_calculator("6 * 7"))
    assert ok.ok is True
    assert ok.data["value"] == 42

    bad = asyncio.run(_run_calculator("__import__('os')"))
    assert bad.ok is False
    assert bad.error is not None and bad.error.code == "INVALID_ARGS"


def test_calculator_tool_rejects_a_missing_expression():
    result = asyncio.run(calculator.run({}, _ctx()))
    assert result.ok is False
    assert result.error is not None and result.error.code == "INVALID_ARGS"


# --- get_current_time --------------------------------------------------------

def test_time_tool_answers_in_utc_by_default():
    result = asyncio.run(get_current_time.run({}, _ctx()))
    assert result.ok is True
    assert result.data["timezone"] == "UTC"
    assert result.data["weekday"] in (
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    )


def test_time_tool_accepts_a_valid_zone():
    result = asyncio.run(get_current_time.run({"timezone": "Asia/Kolkata"}, _ctx()))
    assert result.ok is True
    assert result.data["timezone"] == "Asia/Kolkata"
    assert result.data["utc_offset"] == "+0530"


def test_time_tool_suggests_close_matches_for_a_bad_zone():
    result = asyncio.run(get_current_time.run({"timezone": "Asia/Kolkatta"}, _ctx()))
    assert result.ok is False
    assert result.error is not None and result.error.code == "INVALID_ARGS"
    assert "Asia/Kolkata" in (result.error.hint or "")


def test_time_tool_rejects_an_empty_timezone_value():
    result = asyncio.run(get_current_time.run({"timezone": "   "}, _ctx()))
    assert result.ok is False
    assert result.error is not None and result.error.code == "INVALID_ARGS"
