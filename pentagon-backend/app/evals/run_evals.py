"""Run the eval task suite against the mock LLM (default) or ``--live``.

Usage, from ``pentagon-backend``:

    ../pentagon/bin/python -m app.evals.run_evals
    ../pentagon/bin/python -m app.evals.run_evals --filter time

Tasks live in ``app/evals/tasks/*.yaml``. A task passes when every assertion
in it holds against the agent's behavior on its scripted fixtures. The mock
suite is deterministic -- CI fails on any red. ``--live`` spends real NVIDIA
requests and is only ever run by a human.

The injection suite (``app/evals/injection_suite.yaml``, T7) always runs
alongside the tasks: it exercises the spotlight, the detector, the
exfiltration guard and the permission ladder against known attacks and known
benign text. Any failing injection case is a failed run, regardless of how
the tasks did.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from app.agent.injection import detect_injection, exfiltration_risk, spotlight
from app.services.permissions import requires_tool_approval

TASKS_DIR = Path(__file__).parent / "tasks"
INJECTION_SUITE = Path(__file__).parent / "injection_suite.yaml"


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


def load_injection_suite(path: Path = INJECTION_SUITE) -> list[dict[str, Any]]:
    """Every case in the injection suite; missing file means empty (not green)."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return [data] if isinstance(data, dict) else []


def run_injection_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one injection-suite case against the real defenses.

    Returns ``{id, passed, reason}``. Every kind asserts observable behavior
    of the shipped code -- no mocks, no network.
    """
    case_id = str(case.get("id", "<unnamed>"))
    kind = str(case.get("kind", ""))
    expect = str(case.get("expect", ""))

    if kind == "detect":
        flags = detect_injection(str(case.get("text", "")))
        if expect == "flagged":
            passed = bool(flags)
            reason = "" if passed else "the detector let a known attack through"
        elif expect == "clean":
            passed = not flags
            reason = "" if passed else f"false positive: matched {flags}"
        else:
            passed = False
            reason = f"unknown expect value {expect!r}"
        return {"id": case_id, "passed": passed, "reason": reason}

    if kind == "exfiltration":
        risk = exfiltration_risk(case.get("args"))
        if expect == "denied":
            passed = risk is not None
            reason = "" if passed else "credential-shaped arguments were allowed through"
        elif expect == "allowed":
            passed = risk is None
            reason = "" if passed else f"false positive: denied because they {risk}"
        else:
            passed = False
            reason = f"unknown expect value {expect!r}"
        return {"id": case_id, "passed": passed, "reason": reason}

    if kind == "spotlight":
        wrapped = spotlight(str(case.get("tool", "web_search")), str(case.get("text", "")))
        has_open = "<<<UNTRUSTED" in wrapped
        has_close = "<<<END UNTRUSTED>>>" in wrapped
        # The wrapper's own pair must survive; embedded forgeries must not
        # add or remove markers beyond that pair.
        open_count = wrapped.count("<<<UNTRUSTED")
        close_count = wrapped.count("<<<END UNTRUSTED>>>")
        passed = expect == "wrapped" and has_open and has_close and open_count == 1 and close_count == 1
        reason = "" if passed else (
            f"markers wrong: open={open_count} close={close_count}"
        )
        return {"id": case_id, "passed": passed, "reason": reason}

    if kind == "permission":
        tier = str(case.get("tier", "read"))
        level = int(case.get("level", 2))
        needs = requires_tool_approval(tier, level)
        if expect == "approval_required":
            passed = needs
            reason = "" if passed else f"{tier}@L{level} ran without approval despite injected text"
        elif expect == "auto":
            passed = not needs
            reason = "" if passed else f"{tier}@L{level} demanded approval it should not need"
        else:
            passed = False
            reason = f"unknown expect value {expect!r}"
        return {"id": case_id, "passed": passed, "reason": reason}

    return {"id": case_id, "passed": False, "reason": f"unknown kind {kind!r}"}


def run_injection_suite(path: Path = INJECTION_SUITE) -> list[dict[str, Any]]:
    return [run_injection_case(case) for case in load_injection_suite(path)]


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
    results = [run_task(task, live=args.live) for task in tasks]
    if not tasks:
        print("no eval tasks found (the suite lands in T13)")

    injection = run_injection_suite()

    for result in results:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark}  {result['id']}")
        if not result["passed"] and result.get("reason"):
            print(f"      {result['reason']}")
    for result in injection:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark}  {result['id']}")
        if not result["passed"] and result.get("reason"):
            print(f"      {result['reason']}")

    all_results = [*results, *injection]
    failures = [r for r in all_results if not r["passed"]]
    print(f"\n{len(all_results) - len(failures)}/{len(all_results)} passed")
    if not injection:
        print("warning: injection suite missing or empty - that is a failed gate")
        failures = [*failures, {"id": "<injection-suite>"}]
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
