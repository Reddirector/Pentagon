from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator):
    """A ``DateTime`` that survives SQLite.

    SQLite has no native datetime type: every value is stored as text, and a
    ``DateTime(timezone=True)`` column comes back out as a *naive* datetime with
    the UTC offset silently discarded. Pydantic then serialises it with no
    suffix at all -- ``"2026-10-04T06:16:28.144951"`` -- and ``new Date()`` in
    the browser reads an offset-less timestamp as **local** time. Every
    timestamp was therefore off by the client's UTC offset, and the sidebar
    filed a thread started at 02:30 IST under "Yesterday".

    Re-attaching UTC on load is what the column always meant: every writer in
    this package goes through :func:`utc_now`, so a stored naive value is UTC by
    construction. With the offset restored the API emits ``...Z`` and the two
    sides agree on the instant.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001, ANN201
        # Normalise on the way in too, so a value assigned from a non-UTC-aware
        # source (a test, another service) is stored as UTC rather than as a
        # wall-clock reading of a different zone.
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):  # noqa: ANN001, ANN201
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    # Per-user opt-in for the shell tool. Defaults to False, so a new user has
    # no command access until they turn it on and the server allows it. Stored
    # here rather than in localStorage so the backend -- which is what decides
    # whether to hand the model a tool -- can see it.
    command_tool_enabled: Mapped[bool] = mapped_column(default=False)

    api_key: Mapped["ApiKey | None"] = relationship(back_populates="user", uselist=False)
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    encrypted_key: Mapped[str] = mapped_column(Text)
    masked_key: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    user: Mapped[User] = relationship(back_populates="api_key")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    active_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary_at_switch: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="(Message.created_at, Message.id)",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    model_used: Mapped[str] = mapped_column(String(255))
    image_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    collection_name: Mapped[str] = mapped_column(String(128), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    chunk_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
