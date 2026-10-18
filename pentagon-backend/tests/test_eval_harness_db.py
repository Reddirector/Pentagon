"""Regression: the eval harness must migrate its own database.

``python -m app.evals.run_evals`` is a bare script, not a pytest process, so
``tests/conftest.py`` never runs for it. The first version of this bug left
the harness holding an engine pointed at an empty SQLite file, and any task
whose script reached the approval/trace path failed with
``OperationalError: no such table: users``. ``main()`` now calls the same
``initialize_database()`` the app lifespan does, and these tests pin that.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.config import settings

# Imported for the docstring's benefit and the type checker; the fixture
# module-swaps it, so nothing here may hold a reference across the swap.
from app.db import session as session_module


@pytest.fixture
def fresh_database(tmp_path):
    """Point DATABASE_URL at an empty file and install a matching engine.

    Mirrors the pattern test_bugfixes.py uses: the session module owns module
    state, so the fixture swaps it, hands it to the test, and restores both
    settings and engine afterwards. The restore is a manual try/finally with
    the originals captured exactly once -- a second ``monkeypatch.setattr`` on
    the same attribute re-records the rebound object as the 'original' and
    the leak then poisons every later test that shares the real database
    (this exact bug delayed the fix by one debugging cycle).
    """
    db_file = tmp_path / "harness.db"
    # Prove the file starts empty: no ``users`` table.
    connection = sqlite3.connect(db_file)
    connection.commit()
    connection.close()

    url = f"sqlite:///{db_file}"

    original_url = settings.database_url
    original_engine = session_module.engine
    original_sessionlocal = session_module.SessionLocal

    session_module.engine = session_module.create_engine(url)
    session_module.SessionLocal = session_module.sessionmaker(
        bind=session_module.engine, autoflush=False, expire_on_commit=False
    )
    settings.database_url = url
    try:
        yield url
    finally:
        session_module.engine = original_engine
        session_module.SessionLocal = original_sessionlocal
        settings.database_url = original_url


def test_main_migrates_a_fresh_database_then_runs_a_write_task(
    fresh_database, capsys
) -> None:
    """``main`` -- the bare-script entry point -- must not die on 'no such table'."""
    from sqlalchemy import inspect

    from app.evals.run_evals import main

    # Before main() runs, the database is genuinely empty.
    columns = [t for t in inspect(session_module.engine).get_table_names()]
    assert "users" not in columns, "fixture leaked a migrated database"

    # side-effect-artifact-written drives create_artifact end to end: trace
    # rows, capability seeds and the approval-free write tier. It is the exact
    # task class that used to raise OperationalError.
    exit_code = main(["--filter", "side-effect-artifact-written"])
    output = capsys.readouterr().out
    assert "FAIL" not in output, output
    assert exit_code == 0

    tables = set(inspect(session_module.engine).get_table_names())
    assert "users" in tables, "main() did not run the migrations"
    assert "tool_traces" in tables


def test_harness_task_writes_the_users_row_into_the_fresh_database(fresh_database) -> None:
    """The pass is not vacuous: the harness seeded its rows in the right file.

    Traces are deliberately cleaned up after every task (``_clear_eval_state``),
    so the durable marker of a migrated, functioning harness is the eval user
    and conversation rows ``_ensure_eval_rows`` writes before the first task.
    """
    from sqlalchemy import select

    from app.db.models import Conversation, User
    from app.evals.run_evals import _ensure_eval_rows, main

    assert main(["--filter", "side-effect-artifact-written"]) == 0
    # _ensure_eval_rows is idempotent; running it again directly proves that.
    _ensure_eval_rows()
    with session_module.SessionLocal() as db:
        assert db.get(User, "eval-user") is not None
        assert db.get(Conversation, "eval-conv") is not None
        users = db.scalars(select(User)).all()
    assert users, "the harness wrote no users row -- is it pointing at the right engine?"
