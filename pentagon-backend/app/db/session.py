from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base


is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if is_sqlite else {},
    pool_pre_ping=True,
    echo=False,
)

if is_sqlite:

    @event.listens_for(Engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    message_columns = {column["name"] for column in inspect(engine).get_columns("messages")}
    if "image_path" not in message_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE messages ADD COLUMN image_path VARCHAR(1024)"))
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
                    "BOOLEAN NOT NULL DEFAULT 0"
                )
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
