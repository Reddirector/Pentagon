"""Tool implementations, one module per tool, registered into the agent registry.

Each module exposes ``TOOL_SPEC`` and ``handler``; the registry wiring lives in
``app.agent.bootstrap`` so a tool's import has no side effects (T1 wires the
first two: get_current_time and calculator).
"""
