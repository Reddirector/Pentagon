from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import SynthesizeSpeechRequest
from app.security.keys import resolve_api_key
from app.services.speech import stream_speech, transcribe_audio


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice", tags=["voice"])
_MAX_AUDIO_BYTES = 25 * 1024 * 1024
_AUDIO_EXTENSIONS = {".webm", ".wav", ".mp3"}


def _stored_api_key(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    try:
        return resolve_api_key(db, user_id)
    except Exception:
        return None


@router.post("/transcribe")
async def transcribe(
    user_id: str = Form(..., min_length=1, max_length=128),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    filename = file.filename or "audio"
    if Path(filename).suffix.lower() not in _AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Audio format must be webm, wav, or mp3.")
    content = await file.read(_MAX_AUDIO_BYTES + 1)
    await file.close()
    if len(content) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file must be 25 MB or smaller.")
    if not content:
        raise HTTPException(status_code=400, detail="Audio file is empty.")

    api_key = _stored_api_key(db, user_id)
    started = time.perf_counter()
    try:
        text, provider = await transcribe_audio(content, filename, api_key)
    except Exception:
        logger.exception("Speech transcription failed")
        raise HTTPException(
            status_code=422,
            detail="Could not transcribe this audio. Check that it contains valid speech audio.",
        ) from None

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    status = "empty" if not text.strip() else "ran"
    logger.info(
        "speech transcription status=%s provider=%s duration_ms=%.2f",
        status,
        provider,
        duration_ms,
    )
    return {
        "text": text.strip(),
        "execution_trace": {
            "transcription": {
                "status": status,
                "ran": True,
                "duration_ms": duration_ms,
                "provider": provider,
            }
        },
    }


@router.post("/synthesize")
async def synthesize(
    payload: SynthesizeSpeechRequest,
    user_id: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty.")
    api_key = _stored_api_key(db, user_id)

    async def audio_stream():
        started = time.perf_counter()
        first_audio_ms: float | None = None
        provider: str | None = None
        total_bytes = 0
        try:
            async for chunk in stream_speech(text, payload.voice, api_key):
                if first_audio_ms is None:
                    first_audio_ms = round((time.perf_counter() - started) * 1000, 2)
                    provider = chunk.provider
                total_bytes += len(chunk.content)
                yield chunk.content
        except Exception:
            logger.exception("Direct speech synthesis stream failed")
            raise
        logger.info(
            "speech synthesis status=%s provider=%s duration_ms=%.2f time_to_first_audio_ms=%s",
            "ran" if total_bytes else "empty",
            provider or "unavailable",
            round((time.perf_counter() - started) * 1000, 2),
            first_audio_ms,
        )

    return StreamingResponse(
        audio_stream(),
        media_type="audio/pcm",
        headers={
            "X-Audio-Format": "pcm_s16le",
            "X-Audio-Sample-Rate": "22050",
            "X-Audio-Channels": "1",
            "Content-Disposition": 'inline; filename="pentagon-response.pcm"',
        },
    )
