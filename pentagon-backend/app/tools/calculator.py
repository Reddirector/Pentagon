"""calculator: exact arithmetic through an allowlisted AST walk -- never eval.

The model's arithmetic is a hallucination risk; this tool evaluates a plain
numeric expression by walking the syntax tree, permitting only numeric
literals, the arithmetic operators, parentheses, six safe functions and two
constants. Variables, attributes, imports, lambdas and calls to anything not
on the list are rejected before a single byte is executed.
"""

from __future__ import annotations

import ast
import math
from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec

_ALLOWED_FUNCTIONS = {
    "sqrt": math.sqrt,
    "log": math.log,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "pow": pow,
}
_ALLOWED_CONSTANTS = {"pi": math.pi, "e": math.e}
_MAX_EXPONENT = 10_000


class CalculatorError(ValueError):
    """The expression used something outside the allowlist."""


def evaluate(expression: str) -> int | float:
    """Evaluate a plain arithmetic expression; raises CalculatorError otherwise."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"{expression!r} is not a valid expression ({exc.msg}).") from None
    return _walk(tree.body)


def _walk(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        left, right = _walk(node.left), _walk(node.right)
        op = type(node.op)
        if op is ast.Add:
            return left + right
        if op is ast.Sub:
            return left - right
        if op is ast.Mult:
            return left * right
        if op in (ast.Div, ast.FloorDiv, ast.Mod):
            if right == 0:
                raise CalculatorError("division by zero")
            if op is ast.Div:
                return left / right
            if op is ast.FloorDiv:
                return left // right
            return left % right
        if op is ast.Pow:
            if abs(right) > _MAX_EXPONENT:
                raise CalculatorError(f"exponent {right} is too large")
            return left**right
        raise CalculatorError(f"operator {op.__name__} is not allowed")
    if isinstance(node, ast.UnaryOp):
        value = _walk(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return +value
        raise CalculatorError("this unary operator is not allowed")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS:
            allowed = ", ".join(sorted(_ALLOWED_FUNCTIONS))
            raise CalculatorError(f"only these functions are allowed: {allowed}")
        if node.keywords:
            raise CalculatorError("keyword arguments are not allowed")
        values = [_walk(arg) for arg in node.args]
        if node.func.id == "pow" and len(values) >= 2 and abs(values[1]) > _MAX_EXPONENT:
            raise CalculatorError(f"exponent {values[1]} is too large")
        return _ALLOWED_FUNCTIONS[node.func.id](*values)
    if isinstance(node, ast.Name) and node.id in _ALLOWED_CONSTANTS:
        return _ALLOWED_CONSTANTS[node.id]
    raise CalculatorError(
        "only arithmetic on numbers is allowed -- no variables, attributes, imports or code"
    )


TOOL_SPEC = ToolSpec(
    name="calculator",
    description=(
        "Evaluate an arithmetic expression exactly: + - * / // % ** , parentheses, and"
        " the functions sqrt, log, abs, round, min, max, pow, with pi and e. Use for"
        " any non-trivial arithmetic -- percentages, unit conversions once you have the"
        " numbers, sums over data you collected -- instead of computing in your head."
        " Do not use it for date or time questions (use get_current_time), and do not"
        " pass code, variables or imports: only plain numeric expressions. Returns the"
        " numeric result. Example: {\"expression\": \"(1 + 0.07) ** 30 * 1500\"}."
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "A plain arithmetic expression, e.g. '12 * (3 + 4)'.",
            }
        },
        "required": ["expression"],
    },
    tier="read",

    risk_category="read_only_info",    timeout_s=5,
    cacheable=True,
    cache_ttl_s=300,
    idempotent=True,
    parallel_safe=True,
    tags=("math", "arithmetic", "calculate", "number"),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    expression = args.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "expression must be a non-empty string.",
            hint="Pass plain arithmetic, e.g. {\"expression\": \"12 * (3 + 4)\"}.",
        )
    try:
        value = evaluate(expression)
    except (CalculatorError, OverflowError, ValueError, ZeroDivisionError) as exc:
        return ToolResult.failure(
            "INVALID_ARGS",
            str(exc) if str(exc) else "The expression could not be evaluated.",
            hint=(
                "Write a plain numeric expression using + - * / // % ** and the"
                " functions sqrt, log, abs, round, min, max, pow."
            ),
        )
    return ToolResult.success({"expression": expression, "value": value})
