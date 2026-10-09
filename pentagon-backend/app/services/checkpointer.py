"""Where conversation checkpoints live, in one place.

Every chat route needs a checkpointer, and they all need the *same* one:
``/chat`` writes the interrupt that a paused approval sits in,
``/pending-approvals`` reads it back to build the approval card, approve and
deny resume it, and deleting a conversation purges it. Those routes each built
it inline, by stripping ``sqlite:///`` off ``DATABASE_URL`` -- which quietly
produced a nonsense file path the moment the app database was anything but
SQLite.

Checkpoints now follow the app database. SQLite keeps the local file it always
used (so an existing install still resumes the approvals it already has), and
Postgres keeps them in the app's schema next to the app's own tables, so a
paused approval survives a restart on either backend.
"""

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from sqlalchemy.engine import make_url

from app.config import settings
from app.db.session import app_schema

logger = logging.getLogger(__name__)

# A threading lock rather than an asyncio one on purpose: this guard is checked
# from every event loop in the process. ``asyncio.Lock`` binds itself to the
# first loop that awaits it and then raises if it is used from another, and
# there is more than one -- the purge path runs its own loop inside
# ``asyncio.run``. Nothing blocks inside the lock (the migration round trip
# happens after it is released), so the event loop is never held up.
_setup_lock = threading.Lock()
_setup_done = False


def is_sqlite_backend() -> bool:
    """Whether the configured database is SQLite.

    Read from settings per call rather than captured at import, so a test that
    points the app at another database gets the checkpointer that matches.
    """
    return make_url(settings.database_url).get_backend_name() == "sqlite"


def sqlite_checkpoint_path() -> str:
    """The SQLite file holding checkpoints.

    Exactly what the routes derived before Postgres was an option -- the
    ``DATABASE_URL`` with its ``sqlite:///`` prefix removed -- so an existing
    install finds its pending approvals where it left them.
    """
    return settings.database_url.replace("sqlite:///", "")


def postgres_checkpoint_dsn() -> str:
    """A libpq DSN for the checkpoint tables, pinned to the app's schema.

    ``langgraph-checkpoint-postgres`` reaches Postgres through psycopg rather
    than SQLAlchemy, so it never sees the engine's ``search_path``. Without the
    option below it would create its four ``checkpoint*`` tables in ``public``:
    beside the Supabase spec's tables, and inside the one schema the project's
    REST API exposes.

    The connection is also given a ``lock_timeout``. The library's first-run
    ``setup()`` builds its indexes with ``CREATE INDEX CONCURRENTLY``, which
    waits for every transaction that was already open -- and a chat turn holds
    its own session open for as long as the response is streaming. Unbounded,
    that wait can outlast the turn that is waiting on it. Ten seconds is orders
    of magnitude more than any checkpoint write needs, so hitting it means
    something is genuinely stuck, and the app says so instead of going quiet.
    """
    options = ["-c lock_timeout=10000"]
    schema = app_schema()
    if schema is not None:
        options.append(f"-csearch_path={schema}")
    # Encoded by hand rather than through SQLAlchemy's query helper: ``options``
    # is space-separated, and a form-encoded space is not a space to libpq.
    base = (
        make_url(settings.database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}options={quote(' '.join(options), safe='')}"


@asynccontextmanager
async def open_checkpointer() -> AsyncIterator[Any]:
    """Yield a checkpointer for the configured database, closed on exit.

    The routes that open and close one inside a single handler use this as an
    ``async with``. ``/chat`` cannot: its checkpointer has to outlive the
    request handler and be closed by the stream's ``finally`` once the client
    has finished reading, so it enters and exits this context manager by hand.
    Both are the same object, which matters -- a paused approval is only
    resumable by the backend that wrote it.
    """
    if is_sqlite_backend():
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(sqlite_checkpoint_path()) as saver:
            yield saver
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(postgres_checkpoint_dsn()) as saver:
        await _ensure_checkpoint_tables(saver)
        yield saver


async def prepare_checkpointer() -> None:
    """Create the checkpointer's tables before any turn can depend on them.

    Called once at startup (``app/main.py``). The DDL deliberately does not
    wait for the first chat turn: its ``CREATE INDEX CONCURRENTLY`` blocks on
    every transaction that was already open, and the transaction it would be
    waiting on is the streaming turn that asked for it. At startup this process
    has nothing else in flight.
    """
    if is_sqlite_backend():
        return
    async with open_checkpointer():
        pass


async def _ensure_checkpoint_tables(saver: Any) -> None:
    """Create the checkpointer's own tables once per process.

    ``setup()`` applies the library's migrations and records which ones ran, so
    it is idempotent -- but it is also a round trip that this path would pay on
    every chat turn. The first caller does it; everyone after that skips it.
    A failure clears the flag again, so a later turn retries instead of
    chatting against tables that were never created.
    """
    global _setup_done
    with _setup_lock:
        if _setup_done:
            return
        _setup_done = True
    try:
        await saver.setup()
    except BaseException:
        with _setup_lock:
            _setup_done = False
        raise
    logger.debug("checkpoint tables ready in schema %s", app_schema())
