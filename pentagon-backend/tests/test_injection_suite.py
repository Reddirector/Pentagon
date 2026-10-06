"""The injection suite is a gate: every case, or the build fails."""

from __future__ import annotations

from app.evals.run_evals import (
    load_injection_suite,
    main,
    run_injection_case,
    run_injection_suite,
)


def test_suite_file_loads_with_all_four_kinds():
    cases = load_injection_suite()
    assert len(cases) >= 20, "the suite must cover attacks, benign text and policies"
    kinds = {case["kind"] for case in cases}
    assert kinds == {"detect", "exfiltration", "spotlight", "permission"}


def test_every_injection_case_passes():
    failures = [r for r in run_injection_suite() if not r["passed"]]
    assert failures == [], f"injection suite red: {failures}"


def test_suite_contains_both_flagged_and_clean_cases():
    cases = load_injection_suite()
    expects = {(case["kind"], case["expect"]) for case in cases}
    assert ("detect", "flagged") in expects
    assert ("detect", "clean") in expects, "no false-positive coverage"
    assert ("exfiltration", "denied") in expects
    assert ("exfiltration", "allowed") in expects


def test_runner_exits_zero_when_green():
    assert main([]) == 0


def test_runner_exits_nonzero_on_a_broken_case():
    result = run_injection_case(
        {"id": "broken", "kind": "detect", "expect": "flagged", "text": "all fine"}
    )
    assert result["passed"] is False
    assert result["reason"]


def test_unknown_kind_fails_closed():
    result = run_injection_case({"id": "weird", "kind": "nonsense"})
    assert result["passed"] is False
