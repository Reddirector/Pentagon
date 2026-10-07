#!/usr/bin/env python
"""Migrate legacy per-conversation document stores into RAG 2 collections.

Run from ``pentagon-backend``:

    python scripts/migrate_rag2.py --dry-run   # report the plan, change nothing
    python scripts/migrate_rag2.py             # apply; verifies before deleting

Nothing is deleted until the new table and vector store have been verified
against the legacy count, so an interrupted run is fixed by running it again.
Exit code is 0 only when every conversation migrated or was skipped cleanly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a plain script from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal, initialize_database  # noqa: E402
from app.rag2.migrate import migrate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be migrated without writing or deleting anything",
    )
    args = parser.parse_args(argv)

    initialize_database()
    with SessionLocal() as db:
        report = migrate(db, dry_run=args.dry_run)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
