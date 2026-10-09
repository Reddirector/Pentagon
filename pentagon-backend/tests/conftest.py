"""Test-wide setup.

The suite used to run against the same ``pentagon.db`` the app uses, so every
test row, and every row deleted by a test, landed in the real database. This
points the app at a throwaway file *before* anything imports it, because the
engine is built from settings at import time.
"""

import os
import secrets
import tempfile
from pathlib import Path

_TEST_DIRECTORY = Path(tempfile.mkdtemp(prefix="pentagon-tests-"))

# The suite runs against a throwaway SQLite file, never the app's own database.
# Pointing PENTAGON_TEST_DATABASE_URL at a Postgres database runs the same
# suite against that instead, which is how the Postgres path is checked without
# a second copy of every test. The schema is namespaced per run and dropped
# afterwards, so a run that opted in can never touch the tables a deployment
# already has in the app's usual schema.
_TEST_DATABASE_URL = os.environ.get("PENTAGON_TEST_DATABASE_URL") or (
    f"sqlite:///{_TEST_DIRECTORY / 'test.db'}"
)
_TEST_SCHEMA: str | None = None
if _TEST_DATABASE_URL.startswith("postgres"):
    _TEST_SCHEMA = f"pentagon_test_{secrets.token_hex(4)}"
    os.environ["DATABASE_SCHEMA"] = _TEST_SCHEMA
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL

# The request-budget limiter is process-wide and sized for NVIDIA's free tier
# (~40/min); with a real bucket, unrelated tests would queue behind each other
# and occasionally time out. Tests that care about the limiter construct their
# own instance with a small bucket and a fake clock.
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
# Index jobs are claimed and driven directly in tests, so the background
# worker must not race them from the app's lifespan poll loop.
os.environ["JOB_WORKER_ENABLED"] = "false"

# Import order matters: config and the engine read the variable above at import
# time, so nothing from the app may be imported before this line.
from app.db.session import initialize_database  # noqa: E402

initialize_database()

if _TEST_SCHEMA is not None:
    # The app creates the chat checkpoint tables at startup (app/main.py); the
    # suite drives ``initialize_database`` directly instead of running the
    # lifespan, so it does the same here. Doing it now -- before any test has a
    # transaction open -- is what keeps the checkpointer's
    # CREATE INDEX CONCURRENTLY from waiting on a test's own open session.
    import asyncio  # noqa: E402

    from app.services.checkpointer import prepare_checkpointer  # noqa: E402

    asyncio.run(prepare_checkpointer())


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001
    """Drop the throwaway Postgres schema this run created, if there was one."""
    if _TEST_SCHEMA is None:
        return
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    from app.db.session import engine as app_engine  # noqa: PLC0415

    app_engine.dispose()
    engine = create_engine(_TEST_DATABASE_URL)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(f'DROP SCHEMA IF EXISTS "{_TEST_SCHEMA}" CASCADE')
            )
    finally:
        engine.dispose()
