"""Checks that only mean anything on Postgres.

Skipped unless ``PENTAGON_TEST_DATABASE_URL`` names a Postgres database (see
``tests/conftest.py``), which is also how the rest of the suite is run against
Postgres. Two things are worth pinning down here:

* the app's tables -- and the langgraph checkpoint tables -- land in the app's
  own schema, never in ``public``, where the Supabase spec's incompatible
  tables live and where the project's REST API can see them;
* a checkpoint written through one connection is still there for the next one,
  and purging a thread removes it. That round trip is what a paused approval
  depends on, and it is the part that used to be a SQLite file path.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, TypedDict
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect

from app.db.models import Base, PerToolOverride, User
from app.db.session import SessionLocal, app_schema, backend_name, initialize_database
from app.services.checkpointer import open_checkpointer, postgres_checkpoint_dsn

pytestmark = pytest.mark.skipif(
    not os.environ.get("PENTAGON_TEST_DATABASE_URL"),
    reason="set PENTAGON_TEST_DATABASE_URL to a Postgres DSN to run these",
)

_CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations")


def _tables_in(schema: str) -> set[str]:
    """Every table in one schema, read through a connection with no search_path."""
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        return set(inspect(engine).get_table_names(schema=schema))
    finally:
        engine.dispose()


class _State(TypedDict):
    count: int


def _bump(state: _State) -> _State:
    return {"count": state["count"] + 1}


def _graph(saver: Any) -> Any:
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(_State)
    builder.add_node("bump", _bump)
    builder.add_edge(START, "bump")
    builder.add_edge("bump", END)
    return builder.compile(checkpointer=saver)


def test_the_app_keeps_its_tables_out_of_public() -> None:
    """The app's schema is its own, and it is not the one PostgREST exposes."""
    schema = app_schema()
    assert schema is not None, "a Postgres backend must have an app schema"
    assert schema != "public", "the app must not borrow the schema the REST API exposes"

    in_app_schema = _tables_in(schema)
    for table in Base.metadata.tables:
        assert table in in_app_schema, f"{table} was not created in {schema}"

    in_public = _tables_in("public")
    assert in_public.isdisjoint(_CHECKPOINT_TABLES), (
        "checkpoint tables leaked into public: " + ", ".join(sorted(in_public))
    )


def test_the_checkpoint_dsn_pins_the_app_schema() -> None:
    """The saver is a psycopg client, so its schema travels in the DSN."""
    dsn = postgres_checkpoint_dsn()
    assert backend_name() == "postgresql"
    assert dsn.startswith("postgresql://"), dsn
    assert "+psycopg" not in dsn, "langgraph wants a libpq DSN, not a SQLAlchemy dialect"
    assert app_schema() in dsn, "the app schema is missing from the checkpoint DSN"


def test_session_approval_memory_is_reset_on_postgres() -> None:
    """The reset uses a boolean literal Postgres accepts.

    ``initialize_database`` clears ``approved_this_session`` on every process
    start inside a ``try``/``except`` that exists so a brand-new database can
    still boot. On Postgres the old integer literal was not just wrong, it was
    wrong *quietly*: the statement raised, the except swallowed it, and every
    ``ask_first_time`` approval from a previous run stayed in force.
    """
    user_id = f"pg-reset-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        # Flushed first: the two rows are related by a foreign key but not by an
        # ORM relationship, so nothing else tells SQLAlchemy which to write first.
        db.flush()
        db.add(
            PerToolOverride(
                user_id=user_id,
                tool_name="run_command",
                category="local_shell",
                approved_this_session=True,
            )
        )
        db.commit()

    initialize_database()

    with SessionLocal() as db:
        row = db.get(PerToolOverride, (user_id, "run_command", "local_shell"))
        assert row is not None
        assert row.approved_this_session is False


def test_checkpoints_persist_across_connections_and_purge() -> None:
    thread_id = f"pg-thread-{uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    async def _write() -> dict[str, int]:
        async with open_checkpointer() as saver:
            return await _graph(saver).ainvoke({"count": 1}, config=config)

    assert asyncio.run(_write()) == {"count": 2}

    async def _read_through_a_second_connection() -> int:
        # Its own connection and its own saver, which is what a later request
        # -- or a restarted process -- gets.
        async with open_checkpointer() as saver:
            snap = await _graph(saver).aget_state(config)
            return snap.values["count"]

    assert asyncio.run(_read_through_a_second_connection()) == 2

    async def _purge_then_read() -> bool:
        async with open_checkpointer() as saver:
            await saver.adelete_thread(thread_id)
        async with open_checkpointer() as saver:
            snap = await _graph(saver).aget_state(config)
            return bool(snap.values)

    assert asyncio.run(_purge_then_read()) is False
