from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.services.permissions import DEFAULT_PERMISSION_LEVEL


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
    # Which rung of the approval ladder this user is on: 1 Restricted,
    # 2 Balanced, 3 Trusted. Defaults to Balanced, which is exactly how the
    # gates behaved before levels existed, so an existing row that gains this
    # column keeps its current posture rather than silently loosening.
    permission_level: Mapped[int] = mapped_column(default=DEFAULT_PERMISSION_LEVEL)

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
    # Web citations for an assistant turn, as JSON. They were only ever emitted
    # on the live stream, so reloading a conversation lost every source it had
    # shown -- the answer stayed and its evidence disappeared.
    sources_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ToolTrace(Base):
    """One tool invocation inside an agent turn.

    Written by ``app.agent.traces.TraceRecorder`` after each call; arguments
    are redacted before they get here (secret-shaped keys masked, long values
    cut). SQLite has no row-level security, so ownership is enforced the same
    way every other table's is: queries scope by ``user_id``.
    """

    __tablename__ = "tool_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[str] = mapped_column(String(36), index=True)
    step: Mapped[int] = mapped_column(default=0)
    tool: Mapped[str] = mapped_column(String(128))
    args_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # ok | error | denied | cached | timeout
    status: Mapped[str] = mapped_column(String(16))
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class ModelCapabilities(Base):
    """What one model can do with tools, as measured -- never assumed.

    Written once per model by ``app.agent.capabilities`` after a three-request
    probe, then read on every selection instead of probing again. Open rows
    mean 'never probed'; a badge (Strong / Basic / Prompted-only) is derived
    from the flags, not stored.
    """

    __tablename__ = "model_capabilities"

    model_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    native_tools: Mapped[bool | None] = mapped_column(nullable=True)
    parallel_tools: Mapped[bool | None] = mapped_column(nullable=True)
    vision: Mapped[bool | None] = mapped_column(nullable=True)
    json_mode: Mapped[bool | None] = mapped_column(nullable=True)
    max_context: Mapped[int | None] = mapped_column(nullable=True)
    probed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


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


class Memory(Base):
    """A durable fact the user chose to keep (T11 memory).

    One flat row per memory: ``recall`` scores the user's rows in Python
    (keyword overlap, recency as the tie-break) instead of reaching for
    embeddings, so retrieval is deterministic, testable, and the settings
    UI can list -- and delete -- exactly what is stored. Nothing else in
    the app reads this table: memories never enter a conversation unless
    the model calls ``recall``.
    """

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class Collection(Base):
    """A named, user-owned scope for retrieval (RAG 2).

    SQLite has no row-level security, so the RLS "own rows" policy that
    ``supabase/migrations/rag2.sql`` declares for Supabase is enforced here the
    same way the rest of the app enforces it: every query filters on
    ``user_id``. The two must stay in agreement -- the SQL file is the schema
    spec, this row is the local-first behaviour.

    ``embedding_model`` is ``id@version`` (see ``app.rag2.embeddings``). A
    different value means the collection's vectors live in a different space,
    so a change is a reindex, never a silent mix.
    """

    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(255))
    # Graph building is opt-in per collection and never runs automatically:
    # extraction is the one place indexing spends model calls.
    graph_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class CollectionFile(Base):
    """Which uploaded file belongs to which collection.

    ``file_id`` points at ``documents`` -- the local-first stand-in for the
    Supabase ``files`` table that ``rag2.sql`` references (DECISIONS #8/#9):
    one row per uploaded document, owned by the same user.
    """

    __tablename__ = "collection_files"
    __table_args__ = (PrimaryKeyConstraint("collection_id", "file_id"),)

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class ConversationCollection(Base):
    """Collections attached to a conversation -- the retrieval scope.

    The retriever may only ever search collections linked to the conversation
    in play; this join table is that link, and it is also where an implicit
    per-conversation collection is recorded.
    """

    __tablename__ = "conversation_collections"
    __table_args__ = (PrimaryKeyConstraint("conversation_id", "collection_id"),)

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class Chunk(Base):
    """One retrievable passage, source of truth for text and metadata.

    Vectors live in Chroma (tagged with the embedding model), the keyword index
    is built from these rows, and citations resolve back to them -- so this
    table, not the vector store, is what an answer is grounded in.
    """

    __tablename__ = "chunks"
    # The ordering index retrieval pages through: per file, in order.
    __table_args__ = (Index("ix_chunks_collection_file_ord", "collection_id", "file_id", "ord"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    ord: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    # BCP-47, or "hi-Latn" for romanized Hindi; script is the Unicode block
    # (Latn, Deva, Arab, ...). Both are detected per chunk (RAG §5.2).
    lang: Mapped[str | None] = mapped_column(String(32), nullable=True)
    script: Mapped[str | None] = mapped_column(String(16), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class IndexJob(Base):
    """A background indexing job with a visible budget and honest status.

    Every kind of indexing work (ingest, embed, graph extraction, communities,
    summaries, reindex) is queued as one of these so it can be estimated,
    capped, paused, resumed, cancelled and resumed after a crash -- and so an
    LLM-spending job always shows how many calls it has used against its cap.
    """

    __tablename__ = "index_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    # ``text`` in supabase/migrations/rag2.sql, and deliberately not narrowed
    # here: ``kind`` names a registered handler, and the registry is open to
    # more than the built-in ingest/embed/graph_* vocabulary. SQLite stores any
    # length in a VARCHAR, so a shorter limit would only ever be enforced on
    # Postgres -- rejecting a handler name there and nowhere else.
    kind: Mapped[str] = mapped_column(Text)
    # queued | running | paused | done | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls_estimated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class SkillSetting(Base):
    """A user's on/off switch for one skill.

    Absence of a row means enabled -- a fresh install works with everything
    on, and a skill that ships later needs no backfill. Off is a stored row,
    not a hint: the router excludes these before it applies the per-turn cap,
    so a disabled skill cannot load no matter how well it matches.
    """

    __tablename__ = "skill_settings"
    __table_args__ = (PrimaryKeyConstraint("user_id", "skill_id"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


from app.services.autonomy import (
    RiskCategory,
    AutonomyLevel,
    DECISION,
)


class AutonomySetting(Base):
    """A user's chosen autonomy level for one risk category.

    ``(user_id, category)`` is the primary key. A missing row means "use the
    documented defaults", so a brand-new user has ``read_only_info=auto_approve``
    and everything else ``always_ask`` without any row being inserted.
    """

    __tablename__ = "autonomy_settings"
    __table_args__ = (PrimaryKeyConstraint("user_id", "category"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[RiskCategory] = mapped_column(String(32))
    level: Mapped[AutonomyLevel] = mapped_column(String(24))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)


class PerToolOverride(Base):
    """Session-scoped approval memory for the ``ask_first_time`` level.

    ``approved_this_session`` is the only field that survives across a turn loop;
    it is reset to ``False`` at process start (in ``initialize_database``), never
    persisted across restarts. A missing row means "not approved this session".
    """

    __tablename__ = "per_tool_overrides"
    __table_args__ = (PrimaryKeyConstraint("user_id", "tool_name", "category"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[RiskCategory] = mapped_column(String(32))
    approved_this_session: Mapped[bool] = mapped_column(Boolean, default=False)


class ActionAuditLog(Base):
    """One row per tool-execution attempt. Append-only; never deleted automatically.

    ``arguments_summary`` is a short human-readable line (from
    ``autonomy.arguments_summary``), not the raw potentially-sensitive payload.
    """

    __tablename__ = "action_audit_log"
    __table_args__ = (
        Index("ix_action_audit_log_user_conversation", "user_id", "conversation_id"),
        Index("ix_action_audit_log_timestamp", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    tool_name: Mapped[str] = mapped_column(String(128))
    category: Mapped[RiskCategory] = mapped_column(String(32))
    autonomy_level_at_time: Mapped[AutonomyLevel] = mapped_column(String(24))
    decision: Mapped[DECISION] = mapped_column(String(24))
    arguments_summary: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
