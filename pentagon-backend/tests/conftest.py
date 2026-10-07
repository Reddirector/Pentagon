"""Test-wide setup.

The suite used to run against the same ``pentagon.db`` the app uses, so every
test row, and every row deleted by a test, landed in the real database. This
points the app at a throwaway file *before* anything imports it, because the
engine is built from settings at import time.
"""

import os
import tempfile
from pathlib import Path

_TEST_DIRECTORY = Path(tempfile.mkdtemp(prefix="pentagon-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIRECTORY / 'test.db'}"

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
