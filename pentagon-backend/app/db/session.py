import re
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base


def backend_name() -> str:
    """The backend in ``DATABASE_URL``: ``"sqlite"``, ``"postgresql"``, ..."""
    return make_url(settings.database_url).get_backend_name()


is_sqlite = backend_name() == "sqlite"
is_postgres = backend_name() == "postgresql"


def app_schema() -> str | None:
    """The Postgres schema this app owns, or ``None`` when the backend has none.

    A Supabase project usually already holds the tables ``supabase/schema.sql``
    and ``supabase/migrations/rag2.sql`` describe: ``public`` tables with uuid
    keys and foreign keys into ``auth.users``. This app does not authenticate
    through Supabase, so it cannot satisfy those keys -- and because ``public``
    is the schema PostgREST exposes, sharing it would also put the app's own
    rows (encrypted API keys among them) behind the project's publishable key.
    So the app keeps its tables in a schema of its own, and everything it
    creates -- including the langgraph checkpoint tables -- goes there.
    """
    if backend_name() != "postgresql":
        return None
    return settings.database_schema.strip() or None


def _connect_args() -> dict[str, object]:
    if is_sqlite:
        return {"check_same_thread": False}
    schema = app_schema()
    if schema is None:
        return {}
    # ``options`` is a libpq parameter rather than a SQLAlchemy one, so it is
    # attached to every connection the pool opens. It has to be set at
    # connection level, not per-statement: the app's sessions, the checkpointer
    # and the job worker each take their own connection out of the same pool,
    # and each one must land in the app's schema.
    return {"options": f"-csearch_path={schema}"}


_engine_options: dict[str, object] = {
    "connect_args": _connect_args(),
    "pool_pre_ping": True,
    "echo": False,
}
if is_postgres:
    # Supabase's shared pooler allows a limited number of session-mode
    # connections (15 on the free tier), and the API is not the only client:
    # the checkpointer and the background job worker open their own. A smaller
    # pool per client leaves room for all three instead of exhausting the
    # project's budget on the API alone.
    _engine_options["pool_size"] = 5
    _engine_options["max_overflow"] = 5

engine = create_engine(settings.database_url, **_engine_options)

if is_sqlite:

    @event.listens_for(Engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_app_schema(schema: str) -> None:
    """Create the app's schema before anything is created inside it.

    Postgres accepts a ``search_path`` entry that does not exist yet and
    silently ignores it, so ``create_all`` would otherwise land the app's
    tables in the next schema on the path -- ``public``, where the Supabase
    spec's incompatible tables of the same names live. The name is validated
    rather than pasted in: it comes from configuration and this is a DDL
    statement, which cannot be parameterised.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", schema):
        raise ValueError(f"Refusing to create an unexpected schema name: {schema!r}")
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))


def initialize_database() -> None:
    # Read the backend off the engine rather than off settings. A caller can
    # swap ``engine`` for a different database (the migration tests do), and a
    # statement written for the wrong backend fails in a way that is easy to
    # misread: CREATE SCHEMA on SQLite, or ``0`` in a Postgres BOOLEAN.
    dialect = engine.dialect.name
    # How a boolean false is written. SQLite stores booleans as 0/1 and has no
    # ``false`` keyword; Postgres rejects ``0`` for a BOOLEAN column outright.
    # That difference is not cosmetic: the reset of session-scoped approval
    # memory is wrapped in a try/except so a brand-new database can still boot,
    # so the wrong literal would fail silently -- leaving yesterday's approvals
    # in force after a restart.
    false_literal = "false" if dialect == "postgresql" else "0"
    schema = app_schema()
    if schema is not None and dialect == "postgresql":
        _ensure_app_schema(schema)
    Base.metadata.create_all(bind=engine)
    if dialect == "sqlite":
        # WAL lets the API's sessions, the langgraph checkpointer, and the
        # background job worker share one SQLite file: readers stop blocking a
        # writer's commit, which is what produced multi-second stalls (and
        # "database is locked") once chat turns began writing checkpoints
        # alongside the app's own tables. ``journal_mode`` is a property of the
        # file, so setting it once here covers every later connection.
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        except Exception:  # pragma: no cover - best effort, never fatal
            pass
    message_columns = {column["name"] for column in inspect(engine).get_columns("messages")}
    if "image_path" not in message_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE messages ADD COLUMN image_path VARCHAR(1024)"))
    if "sources_used" not in message_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE messages ADD COLUMN sources_used TEXT"))
    conversation_columns = {
        column["name"] for column in inspect(engine).get_columns("conversations")
    }
    with engine.begin() as connection:
        if "active_model" not in conversation_columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN active_model VARCHAR(255)"))
        if "summary_at_switch" not in conversation_columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN summary_at_switch TEXT"))
    # Additive migrations for existing databases. SQLite cannot add a column
    # with a non-constant default, so the flag is created NOT NULL DEFAULT 0:
    # existing users are off, which is the safe direction to fail.
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    if "command_tool_enabled" not in user_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE users ADD COLUMN command_tool_enabled "
                    f"BOOLEAN NOT NULL DEFAULT {false_literal}"
                )
            )
    # The approval level rides along with the same additive-migration rule.
    # DEFAULT 2 is Balanced, the behaviour that already shipped, so upgrading
    # neither tightens nor loosens anyone's existing setup. The column is
    # intentionally not constrained in SQL: normalize_level() clamps a bad
    # value on the way in, which keeps a hand-edited row from being able to
    # hand the model more access than any of the three rungs allow.
    if "permission_level" not in user_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE users ADD COLUMN permission_level "
                    "INTEGER NOT NULL DEFAULT 2"
                )
            )

    # --- permission/autonomy system ---
    # Session-scoped approval memory must start clean every process restart:
    # ``ask_first_time`` approvals from a previous run must not carry over.
    # (approved_this_session is NOT persisted across restarts by design.)
    url = engine.url
    db_part = getattr(url, "database", None) or getattr(url, "get_database", lambda: None)()
    is_memory = db_part == ":memory:"
    if is_memory:
        # In-memory DB: the create_all above already produced empty tables.
        pass
    else:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE per_tool_overrides SET approved_this_session = "
                        f"{false_literal}"
                    )
                )
        except Exception:
            # Table may not exist yet on very first run; create_all above
            # handles that, and the UPDATE is best-effort.
            pass
