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

# Import order matters: config and the engine read the variable above at import
# time, so nothing from the app may be imported before this line.
from app.db.session import initialize_database  # noqa: E402

initialize_database()
