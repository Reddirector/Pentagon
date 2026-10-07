"""The agent turn surface: run_turn's events, streamed as SSE.

``/api/chat`` (the graph) remains the default answer path; this route runs the
same request shape through the T1--T12 agent loop instead -- tool calls with
approval cards, plan updates, ask-user pauses, artifacts, budgets, and the
grounding verdict -- and forwards every ``AgentEvent`` under its own event
name, so a client that knows nothing extra still understands ``token`` and
``done`` while an agent-aware client can render the whole turn.

Waiting is part of the contract. Approval and ask-user pause the turn for as
long as the user needs, so the stream emits a keep-alive comment once a
second while nothing is moving: the client's stall timer must read patience
as patience, not as death. Stop is a disconnect: the client aborts the fetch,
this generator closes, the turn task is cancelled with it, and the session is
dropped -- a decision that arrives afterwards finds nothing and says so.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.bootstrap import build_registry
from app.agent.capabilities import ProbeResult
from app.agent.loop import TurnRequest, run_turn
from app.agent.schemas import ApprovalGate, AskUserGate, Budget
from app.db.models import Conversation, Message, ModelCapabilities, User, utc_now
from app.db.session import SessionLocal, get_db
from app.security.keys import resolve_api_key_or_http
from app.services.conversation_context import build_model_history
from app.services.image_inputs import parse_chat_submission
from app.services.nvidia_client import make_chat_model
from app.services.permissions import normalize_level

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

_SSE_KEEPALIVE = ": ping\n\n"
# How long the stream waits on an empty queue before sending a ping. Approval
# waits run up to five minutes; a ping every second keeps every client-side
# stall detector (ours is 75s) comfortably re-armed the whole time.
_WAIT_POLL_SECONDS = 1.0
# Approval (300s) plus real work must fit inside the turn's time budget, so a
# user thinking about a card is never what exhausts it.
_AGENT_MAX_SECONDS = 600.0
# A crashed client that never disconnected must not pin sessions forever.
_MAX_LIVE_SESSIONS = 32


def _sse(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


@dataclass
class _TurnSession:
    """Everything one live turn can be waited on for."""

    turn_id: str
    user_id: str
    approval: ApprovalGate = field(default_factory=ApprovalGate)
    ask: AskUserGate = field(default_factory=AskUserGate)
    started: float = field(default_factory=time.monotonic)


_SESSIONS: dict[str, _TurnSession] = {}

_REGISTRY: Any = None


def _agent_registry() -> Any:
    """Built lazily so MCP tools registered during startup are included."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry()
    return _REGISTRY


def _register(session: _TurnSession) -> _TurnSession:
    if len(_SESSIONS) >= _MAX_LIVE_SESSIONS:
        oldest = min(_SESSIONS.values(), key=lambda entry: entry.started)
        _SESSIONS.pop(oldest.turn_id, None)
    _SESSIONS[session.turn_id] = session
    return session


def _session_for(turn_id: str, user_id: str) -> _TurnSession:
    session = _SESSIONS.get(turn_id)
    # A turn belonging to someone else must be indistinguishable from one
    # that never existed -- the same rule the conversation routes follow.
    if session is None or session.user_id != user_id:
        raise HTTPException(
            status_code=404, detail="That turn is not waiting for a reply."
        )
    return session


class DecisionRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=64)
    # An empty list is a decline, not a mistake: the gate reads "nothing is
    # approved" and the loop denies every call on the card.
    call_ids: list[str] = Field(default_factory=list, max_length=32)


class AnswerRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=2000)


@router.post("/decisions", status_code=202)
async def decide(payload: DecisionRequest) -> dict[str, Any]:
    """Approve (or decline) the tool calls on a live turn's approval card."""
    session = _session_for(payload.turn_id, payload.user_id)
    if not session.approval.provide([str(call_id) for call_id in payload.call_ids]):
        raise HTTPException(
            status_code=409, detail="That approval was already answered."
        )
    return {"turn_id": payload.turn_id, "status": "recorded"}


@router.post("/answers", status_code=202)
async def answer(payload: AnswerRequest) -> dict[str, Any]:
    """Answer a question the turn asked through ask_user."""
    session = _session_for(payload.turn_id, payload.user_id)
    if not session.ask.provide({"text": payload.answer}):
        raise HTTPException(
            status_code=409,
            detail="That question is not open right now; it may have timed out.",
        )
    return {"turn_id": payload.turn_id, "status": "recorded"}


@router.get("/badges")
def capability_badges() -> dict[str, Any]:
    """Cached capability probe results, per model id.

    No network and no spend: the loop probes a model the first time a real
    turn uses it, and this only reads the rows that probing left behind. A
    model that was never probed simply has no entry -- the UI says so rather
    than guessing a badge.
    """
    with SessionLocal() as db:
        rows = list(db.scalars(select(ModelCapabilities)).all())
    return {
        row.model_id: {
            "badge": ProbeResult(
                native_tools=bool(row.native_tools),
                parallel_tools=bool(row.parallel_tools),
            ).badge,
            "native_tools": bool(row.native_tools),
            "parallel_tools": bool(row.parallel_tools),
        }
        for row in rows
    }


@router.post("/chat")
async def agent_chat(request: Request, db: Session = Depends(get_db)) -> StreamingResponse:
    """Run one text turn through the agent loop and stream every event.

    Same request shape as ``/api/chat`` (multipart or JSON), text only for
    now: attachments, vision and voice stay with the graph route until the
    loop grows tools for them, and pretending otherwise would silently drop
    an upload the user could see in their thread.
    """
    payload, image, video = await parse_chat_submission(request)
    if image is not None or video is not None:
        raise HTTPException(
            status_code=422,
            detail="Agent turns are text-only for now; switch to Standard chat for media.",
        )
    message_content = payload.message.strip()
    if not message_content:
        raise HTTPException(status_code=422, detail="message is required.")

    api_key = resolve_api_key_or_http(db, payload.user_id)

    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == payload.conversation_id,
            Conversation.user_id == payload.user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found for this user.")
    if conversation.active_model is not None and conversation.active_model != payload.model:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This conversation uses {conversation.active_model}. Switch it with "
                "PATCH /api/conversations/{conversation_id} before chatting with another model."
            ),
        )
    if conversation.active_model is None:
        conversation.active_model = payload.model
    prior_messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )
    )

    if payload.regenerate:
        # Retry: the question is already the thread's last row. Keep it as the
        # turn's message, not as history as well, and store no second copy.
        if (
            prior_messages
            and prior_messages[-1].role == "user"
            and prior_messages[-1].content == message_content
        ):
            prior_messages = prior_messages[:-1]
    else:
        db.add(
            Message(
                id=str(uuid.uuid4()),
                conversation_id=conversation.id,
                role="user",
                content=message_content,
                model_used=payload.model,
            )
        )
        if conversation.title == "New conversation":
            conversation.title = " ".join(message_content.split())[:120] or "New conversation"
        conversation.updated_at = utc_now()
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="Could not save this message.") from None

    history = build_model_history(
        prior_messages,
        summary_at_switch=conversation.summary_at_switch,
        active_model=conversation.active_model,
    )
    user = db.get(User, payload.user_id)
    permission_level = normalize_level(
        user.permission_level if user is not None else None
    )

    session = _register(
        _TurnSession(turn_id=f"t-{uuid.uuid4().hex}", user_id=payload.user_id)
    )
    model = make_chat_model(api_key, payload.model)
    turn = TurnRequest(
        user_id=payload.user_id,
        conversation_id=conversation.id,
        turn_id=session.turn_id,
        permission_level=permission_level,
        user_message=message_content,
        history=history,
        # T12 routing: the first turn with this model id probes it once and
        # caches the result; a seeded row (tests) is read without probing.
        model_id=payload.model,
    )
    return StreamingResponse(
        _stream_agent(turn=turn, model=model, session=session, model_id=payload.model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_agent(
    *,
    turn: TurnRequest,
    model: Any,
    session: _TurnSession,
    model_id: str,
) -> AsyncIterator[str]:
    """Forward one turn's events as SSE, pinging while a gate holds it open."""
    queue: asyncio.Queue[Any] = asyncio.Queue()
    finished = object()

    async def _pump() -> None:
        try:
            async for event in run_turn(
                _agent_registry(),
                model,
                turn,
                budget=Budget(max_seconds=_AGENT_MAX_SECONDS),
                approval_gate=session.approval,
                pause_gate=session.ask,
            ):
                await queue.put(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("agent turn crashed turn=%s", turn.turn_id)
            await queue.put(RuntimeError("the agent turn failed"))
        finally:
            await queue.put(finished)

    task = asyncio.create_task(_pump())
    answer = ""
    persisted = False

    def _persist() -> None:
        # Runs in the generator's finally, possibly while the turn is being
        # cancelled: synchronous work only, no awaits, so a Stop still leaves
        # the partial answer behind exactly like the graph route does.
        nonlocal persisted
        if persisted or not answer.strip():
            return
        persisted = True
        with SessionLocal() as session_db:
            session_db.add(
                Message(
                    id=str(uuid.uuid4()),
                    conversation_id=turn.conversation_id,
                    role="assistant",
                    content=answer,
                    model_used=model_id,
                )
            )
            try:
                session_db.commit()
            except Exception:
                session_db.rollback()
                logger.exception(
                    "could not persist the agent reply turn=%s", turn.turn_id
                )

    try:
        yield _sse(
            "conversation",
            {"conversation_id": turn.conversation_id, "turn_id": turn.turn_id},
        )
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_WAIT_POLL_SECONDS)
            except asyncio.TimeoutError:
                # Nothing is moving because a gate is open or the model is
                # thinking: a ping keeps the client's stall timer honest.
                yield _SSE_KEEPALIVE
                continue
            if item is finished:
                break
            if isinstance(item, BaseException):
                yield _sse(
                    "error",
                    {"message": "The agent turn could not finish. Please try again."},
                )
                break
            event = item
            if event.name == "token":
                answer += str(event.payload.get("content", ""))
            elif event.name == "status" and isinstance(event.payload.get("answer"), str):
                # T12's repair replaces the answer of record after the old
                # text already streamed; the saved reply follows this, not that.
                answer = str(event.payload["answer"])
            yield _sse(event.name, event.payload)
    finally:
        # Normal end: the task is already finished and cancel is a no-op.
        # Stop or a dropped connection: cancel closes run_turn (and any gate
        # it awaits), the session disappears, and a late decision gets a 404.
        task.cancel()
        _SESSIONS.pop(session.turn_id, None)
        _persist()
