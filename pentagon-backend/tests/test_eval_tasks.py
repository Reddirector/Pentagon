"""T13: the eval task suite itself, run for real against the mock.

Every YAML task is a pytest case: if a task's assertions stop holding, the
main gate goes red -- the suite cannot rot silently beside it. ``--live``
spends real requests and is exercised only for its refusal contract here.
"""

import pytest

from app.evals.run_evals import load_tasks, run_task

TASKS = load_tasks()


def test_the_suite_carries_at_least_forty_tasks():
    assert len(TASKS) >= 40


def test_task_ids_are_unique_and_named():
    ids = [str(task.get("id") or "") for task in TASKS]
    assert all(ids), "every task needs an id"
    assert len(ids) == len(set(ids)), "task ids must be unique"


def test_every_task_declares_prompt_and_assertions():
    for task in TASKS:
        assert str(task.get("prompt") or "").strip(), task.get("id")
        assert isinstance(task.get("expect"), dict), task.get("id")


def test_live_tasks_carry_live_expectations():
    live = [task for task in TASKS if task.get("live")]
    assert live, "at least one task must be marked live: true for --live"
    for task in live:
        assert "live_expect" in task, task.get("id")


def test_a_non_live_task_refuses_the_live_flag():
    task = next(task for task in TASKS if not task.get("live"))
    result = run_task(task, live=True)
    assert not result["passed"]
    assert "live" in result["reason"]


@pytest.mark.parametrize("task", TASKS, ids=[str(t.get("id")) for t in TASKS])
def test_mock_task_passes(task):
    result = run_task(task, live=False)
    assert result["passed"], f"{result['id']}: {result['reason']}"
