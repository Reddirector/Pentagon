"""Run the eval task suite against the mock LLM (default) or ``--live``.

Usage, from ``pentagon-backend``:

    ../pentagon/bin/python -m app.evals.run_evals
    ../pentagon/bin/python -m app.evals.run_evals --filter time

Tasks live in ``app/evals/tasks/*.yaml``. A task passes when every assertion
in it holds against the agent's behavior on its scripted fixtures. The mock
suite is deterministic -- CI fails on any red. ``--live`` spends real NVIDIA
requests and is only ever run by a human.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

TASKS_DIR = Path(__file__).parent / "tasks"


def load_tasks(directory: Path = TASKS_DIR) -> list[dict[str, Any]]:
    """Every task in ``*.yaml``; a file may hold one task or a list of them."""
    tasks: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            tasks.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            tasks.append(data)
    return tasks


def run_task(task: dict[str, Any], *, live: bool) -> dict[str, Any]:
    """Execute one task and return ``{id, passed, reason}``.

    The wiring to the agent loop lands with the loop itself (T1) and grows
    with the tool set; until then, a present task is reported as failed so an
    empty runner can never look like a passing suite.
    """
    return {
        "id": str(task.get("id", "<unnamed>")),
        "passed": False,
        "reason": "eval runner is not wired to the agent loop yet (lands in T1/T13)",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Pentagon eval suite")
    parser.add_argument("--filter", default="", help="only run tasks whose id contains this")
    parser.add_argument(
        "--live",
        action="store_true",
        help="run against the real model (spends NVIDIA quota; human-run only)",
    )
    args = parser.parse_args(argv)

    tasks = [task for task in load_tasks() if args.filter in str(task.get("id", ""))]
    if not tasks:
        print("no eval tasks found (the suite lands in T13)")
        return 0

    results = [run_task(task, live=args.live) for task in tasks]
    failures = [r for r in results if not r["passed"]]
    for result in results:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark}  {result['id']}")
        if not result["passed"] and result.get("reason"):
            print(f"      {result['reason']}")
    print(f"\n{len(results) - len(failures)}/{len(results)} passed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
