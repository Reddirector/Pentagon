from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import BaseMessage
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Conversation, Message, User, utc_now
from app.db.session import SessionLocal, get_db
from app.config import settings
from app.schemas import (
    ConversationResponse,
    ConversationSummary,
    CreateConversationRequest,
    RenameConversationRequest,
    SwitchConversationModelRequest,
    SwitchConversationModelResponse,
)
from app.security.keys import NoKeyAvailableError, resolve_api_key
from app.services.chat_graph import (
    build_chat_graph,
    initial_chat_state,
    public_sources,
)
from app.services.conversation_context import build_model_history, summarize_for_model_switch
from app.services.image_inputs import parse_chat_submission
from app.services.nvidia_client import NvidiaApiError, list_models_for_user
from app.services.speech import stream_speech


router = APIRouter(prefix="/api", tags=["chat"])
_MAX_RATE_LIMIT_RETRIES = 3
logger = logging.getLogger(__name__)


@router.post("/chat")
async def chat(
    request: Request,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    payload, image, video = await parse_chat_submission(request)
    message_content = payload.message.strip()
    if not message_content and image is not None:
        message_content = "Describe what's in this image."
    elif not message_content and video is not None:
        message_content = "Describe what's happening in this video with timestamps."

    try:
        api_key = resolve_api_key(db, payload.user_id)
    except NoKeyAvailableError:
        raise HTTPException(status_code=404, detail="No API key is stored for this user.") from None

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

    message_id = str(uuid4())
    image_path: Path | None = None
    if image is not None:
        image_path = (
            Path(settings.image_upload_directory)
            / conversation.id
            / f"{message_id}.{image.extension}"
        )
        try:
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(image.content)
        except OSError:
            raise HTTPException(status_code=500, detail="Could not save the uploaded image.") from None

    user_message = Message(
        id=message_id,
        conversation_id=conversation.id,
        role="user",
        content=message_content,
        model_used=payload.model,
        image_path=str(image_path) if image_path is not None else None,
    )
    if conversation.title == "New conversation":
        conversation.title = " ".join(message_content.split())[:120] or "New conversation"
    conversation.updated_at = utc_now()
    db.add(user_message)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if image_path is not None:
            image_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not save this message.") from None

    graph_history: list[BaseMessage] = build_model_history(
        prior_messages,
        summary_at_switch=conversation.summary_at_switch,
        active_model=conversation.active_model,
    )
    graph = build_chat_graph(
        api_key,
        payload.model,
        user_id=payload.user_id,
        use_web_search=payload.use_web_search,
    )
    graph_input = initial_chat_state(
        user_id=payload.user_id,
        conversation_id=conversation.id,
        message=message_content,
        history=graph_history,
        use_web_search=payload.use_web_search,
        image_data_uri=image.data_uri if image is not None else None,
        video_data_uri=video.data_uri if video is not None else None,
        video_duration_seconds=video.duration_seconds if video is not None else None,
        video_frames_sent=video.frames_sent if video is not None else None,
        video_sampling_fps=video.fps if video is not None else None,
        transcription_duration_ms=payload.transcription_duration_ms,
        transcription_provider=payload.transcription_provider,
        context_summary_used=conversation.summary_at_switch is not None,
        context_summary_word_count=(
            len(conversation.summary_at_switch.split()) if conversation.summary_at_switch else 0
        ),
        context_raw_message_count=(min(len(prior_messages), 6) if conversation.summary_at_switch else 0),
        context_model=conversation.active_model,
    )

    return StreamingResponse(
        _stream_chat(
            graph,
            graph_input,
            conversation.id,
            payload.model,
            api_key=api_key,
            respond_with_audio=payload.respond_with_audio,
            voice=payload.voice,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
    )


@router.post("/conversations", response_model=ConversationSummary, status_code=201)
def create_conversation(
    payload: CreateConversationRequest,
    db: Session = Depends(get_db),
) -> Conversation:
    if db.get(User, payload.user_id) is None:
        if settings.nvidia_server_api_key is None:
            raise HTTPException(status_code=404, detail="User not found. Store an API key first.")
        # Server-key fallback mode: provision the local user so chat can start
        # before any personal key is stored.
        db.add(User(id=payload.user_id))
        db.flush()
    title = (payload.title or "New conversation").strip() or "New conversation"
    conversation = Conversation(user_id=payload.user_id, title=title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.patch(
    "/conversations/{conversation_id}/title",
    response_model=ConversationSummary,
)
def rename_conversation(
    conversation_id: str,
    payload: RenameConversationRequest,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        # 404 rather than 403: a thread belonging to somebody else must be
        # indistinguishable from one that does not exist.
        raise HTTPException(status_code=404, detail="Conversation not found.")

    # A title of only whitespace would render as an empty row in the sidebar.
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title cannot be empty.")

    conversation.title = title
    conversation.updated_at = utc_now()
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        # Scoped by owner, so another user's thread cannot be deleted by id.
        raise HTTPException(status_code=404, detail="Conversation not found.")

    # Messages cascade through the ORM relationship; documents cascade through
    # the foreign key, since SQLite runs with PRAGMA foreign_keys=ON.
    db.delete(conversation)
    db.commit()
    logger.info("conversation deleted conversation=%s", conversation_id)
    return Response(status_code=204)


@router.patch(
    "/conversations/{conversation_id}",
    response_model=SwitchConversationModelResponse,
)
async def switch_conversation_model(
    conversation_id: str,
    payload: SwitchConversationModelRequest,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    try:
        api_key = resolve_api_key(db, conversation.user_id)
    except NoKeyAvailableError:
        raise HTTPException(status_code=404, detail="No API key is stored for this user.") from None

    try:
        models = await list_models_for_user(conversation.user_id, api_key)
    except NvidiaApiError as exc:
        status_code = 429 if exc.category == "rate_limited" else 502
        raise HTTPException(status_code=status_code, detail=exc.reason) from None
    if not any(model.get("id") == payload.model for model in models):
        raise HTTPException(status_code=422, detail="The requested model is not available to this API key.")

    if conversation.active_model == payload.model:
        current_summary = conversation.summary_at_switch or ""
        return {
            "conversation_id": conversation.id,
            "active_model": payload.model,
            "summary_generated": False,
            "summary_word_count": len(current_summary.split()),
        }

    prior_messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at, Message.id)
        )
    )
    summary: str | None = None
    if prior_messages:
        try:
            summary = await summarize_for_model_switch(api_key, payload.model, prior_messages)
        except Exception as exc:
            logger.warning(
                "Conversation model switch summary failed conversation=%s model=%s error=%s",
                conversation_id,
                payload.model,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=502,
                detail="Could not summarize this conversation with the requested model; the active model was not changed.",
            ) from None

    conversation.active_model = payload.model
    conversation.summary_at_switch = summary
    conversation.updated_at = utc_now()
    db.commit()
    logger.info(
        "conversation model switched conversation=%s model=%s summary_generated=%s summary_word_count=%d retained_raw_messages=%d",
        conversation_id,
        payload.model,
        summary is not None,
        len(summary.split()) if summary else 0,
        min(len(prior_messages), 6),
    )
    return {
        "conversation_id": conversation.id,
        "active_model": payload.model,
        "summary_generated": summary is not None,
        "summary_word_count": len(summary.split()) if summary else 0,
    }


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conversation = db.scalar(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        # Scoped by owner so a conversation id cannot be used to read somebody
        # else's thread.
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return {
        "id": conversation.id,
        "title": conversation.title,
        "updated_at": conversation.updated_at,
        "active_model": conversation.active_model,
        "summary_at_switch": conversation.summary_at_switch,
        "messages": conversation.messages,
    }


async def _stream_chat(
    graph: Any,
    graph_input: dict[str, Any],
    conversation_id: str,
    model: str,
    *,
    api_key: str,
    respond_with_audio: bool = False,
    voice: str | None = None,
) -> AsyncIterator[str]:
    yield _sse("conversation", {"conversation_id": conversation_id})
    answer = ""
    final_state: dict[str, Any] = {}
    graph_started = time.perf_counter()
    llm_started: float | None = None
    first_token_ms: float | None = None

    for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
        emitted_token = False
        try:
            async for chunk in graph.astream(
                graph_input,
                stream_mode=["messages", "values"],
                version="v2",
            ):
                if chunk["type"] == "messages":
                    message_chunk, _metadata = chunk["data"]
                    token_text = _content_as_text(message_chunk.content)
                    if token_text:
                        if first_token_ms is None:
                            first_token_ms = round(
                                (time.perf_counter() - (llm_started or graph_started)) * 1000,
                                2,
                            )
                        emitted_token = True
                        answer += token_text
                        yield _sse("token", {"content": token_text})
                elif chunk["type"] == "values":
                    final_state = chunk["data"]
                    answer = final_state.get("answer", answer)
                    if (
                        llm_started is None
                        and "context_assembler" in final_state.get("execution_trace", {})
                    ):
                        llm_started = time.perf_counter()

            break
        except Exception as exc:
            status_code = _status_code(exc)
            if (
                status_code == 429
                and not emitted_token
                and attempt < _MAX_RATE_LIMIT_RETRIES
            ):
                await asyncio.sleep(min(2**attempt, 15))
                continue

            if status_code == 429:
                error_message = "NVIDIA is rate-limiting this request. Please try again shortly."
            elif status_code in (401, 403):
                error_message = "NVIDIA rejected the stored API key. Save a valid key and try again."
            else:
                error_message = "The NVIDIA chat request failed. Please try again."
            yield _sse(
                "metadata",
                {
                    "sources_used": public_sources(final_state),
                    "execution_trace": final_state.get("execution_trace", {}),
                },
            )
            yield _sse("error", {"message": error_message})
            return

    if answer and not emitted_token:
        # Some compatible endpoints return one complete message even when
        # streaming was requested; preserve the answer for SSE clients.
        first_token_ms = round(
            (time.perf_counter() - (llm_started or graph_started)) * 1000,
            2,
        )
        yield _sse("token", {"content": answer})

    if first_token_ms is not None:
        final_state.setdefault("execution_trace", {}).setdefault("generate_response", {})[
            "time_to_first_token_ms"
        ] = first_token_ms

    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is not None:
            db.add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                    model_used=model,
                )
            )
            conversation.updated_at = utc_now()
            db.commit()

    if respond_with_audio and answer:
        synthesis_started = time.perf_counter()
        first_audio_ms: float | None = None
        total_audio_bytes = 0
        audio_provider: str | None = None
        audio_format: dict[str, int | str] | None = None
        synthesis_error: str | None = None
        try:
            async for audio_chunk in stream_speech(answer, voice, api_key):
                if first_audio_ms is None:
                    first_audio_ms = round((time.perf_counter() - synthesis_started) * 1000, 2)
                    audio_provider = audio_chunk.provider
                    audio_format = {
                        "encoding": "pcm_s16le",
                        "sample_rate_hz": audio_chunk.sample_rate_hz,
                        "channels": audio_chunk.channels,
                        "sample_width": audio_chunk.sample_width,
                    }
                total_audio_bytes += len(audio_chunk.content)
                for offset in range(0, len(audio_chunk.content), 16 * 1024):
                    piece = audio_chunk.content[offset : offset + 16 * 1024]
                    yield _sse(
                        "audio_chunk",
                        {
                            "encoding": "base64",
                            "content": base64.b64encode(piece).decode("ascii"),
                            **(audio_format or {}),
                        },
                    )
        except Exception as exc:
            synthesis_error = type(exc).__name__
            logger.exception("Speech synthesis failed after text response was delivered")

        duration_ms = round((time.perf_counter() - synthesis_started) * 1000, 2)
        final_state.setdefault("execution_trace", {})["synthesis"] = {
            "status": "failed" if synthesis_error else "ran" if total_audio_bytes else "empty",
            "ran": True,
            "duration_ms": duration_ms,
            "time_to_first_audio_ms": first_audio_ms,
            "provider": audio_provider,
            "audio_bytes": total_audio_bytes,
            **({"error": synthesis_error} if synthesis_error else {}),
        }
        logger.info(
            "speech synthesis status=%s provider=%s duration_ms=%.2f time_to_first_audio_ms=%s",
            final_state["execution_trace"]["synthesis"]["status"],
            audio_provider or "unavailable",
            duration_ms,
            first_audio_ms,
        )
        yield _sse(
            "audio_end",
            {
                "complete": synthesis_error is None,
                "provider": audio_provider,
                "audio_bytes": total_audio_bytes,
                "time_to_first_audio_ms": first_audio_ms,
                **(audio_format or {}),
            },
        )
        if synthesis_error:
            yield _sse(
                "audio_error",
                {"message": "Speech synthesis failed; the text response is still available."},
            )

    yield _sse(
        "metadata",
        {
            "sources_used": public_sources(final_state),
            "execution_trace": final_state.get("execution_trace", {}),
        },
    )
    yield _sse("done", {"conversation_id": conversation_id})


def _sse(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


def _status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _content_as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item["text"]
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""
