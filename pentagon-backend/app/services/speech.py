from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
from faster_whisper import WhisperModel
from piper import PiperVoice

from app.config import settings


logger = logging.getLogger(__name__)
_VOICE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_LOCAL_TRANSCRIPTION_REASON = (
    "The current NVIDIA key lists no speech-recognition model; the catalog's Riva ASR models are downloadable deployments."
)
_LOCAL_TTS_REASON = (
    "The current key exposes no TTS model; the catalog's free Magpie zero-shot endpoint requires separate access approval."
)
# Active ASR path for the checked local-user key: faster-whisper:base, because
# the live model list contains no ASR model and NVIDIA marks ASR NIMs downloadable.
# Active TTS path for that key: local Piper, because Magpie ZeroShot requires
# separate access approval and no TTS NIM is present in the key's model list.


@dataclass(frozen=True)
class AudioChunk:
    content: bytes
    sample_rate_hz: int
    channels: int
    sample_width: int
    provider: str


@lru_cache(maxsize=1)
def _load_whisper_model() -> WhisperModel:
    model_name = settings.faster_whisper_model
    logger.info("Loading local faster-whisper model=%s on CPU int8", model_name)
    return WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        download_root=settings.speech_models_directory,
        cpu_threads=max(1, min(8, os.cpu_count() or 1)),
    )


def _transcribe_local(audio_path: Path) -> str:
    model = _load_whisper_model()
    segments, _info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
    )
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()


def _asr_wav_bytes(content: bytes, filename: str) -> bytes:
    if Path(filename).suffix.lower() == ".wav":
        return content
    converted = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            "pipe:0",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            "pipe:1",
        ],
        input=content,
        capture_output=True,
        check=True,
        timeout=120,
    )
    return converted.stdout


async def transcribe_audio(
    content: bytes,
    filename: str,
    api_key: str | None,
) -> tuple[str, str]:
    """Try an explicitly configured Riva NIM, then use local faster-whisper."""
    if settings.nvidia_riva_asr_url and api_key:
        try:
            nvidia_audio = await asyncio.to_thread(_asr_wav_bytes, content, filename)
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{settings.nvidia_riva_asr_url.rstrip('/')}/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"language": "en-US", "response_format": "json"},
                    files={
                        "file": (
                            Path(filename).stem + ".wav",
                            nvidia_audio,
                            "audio/wav",
                        )
                    },
                )
                response.raise_for_status()
                payload = response.json()
                transcript = payload.get("text") if isinstance(payload, dict) else None
                if not isinstance(transcript, str):
                    raise ValueError("NVIDIA Riva returned an invalid transcription response.")
                return transcript.strip(), "nvidia-riva"
        except Exception as exc:
            logger.warning(
                "NVIDIA Riva ASR failed (%s); falling back to local faster-whisper",
                type(exc).__name__,
            )
    else:
        logger.info("NVIDIA Riva ASR unavailable for this key; using local faster-whisper: %s", _LOCAL_TRANSCRIPTION_REASON)

    suffix = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(prefix="pentagon-audio-", suffix=suffix, delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(content)
    try:
        text = await asyncio.to_thread(_transcribe_local, temp_path)
        return text, f"faster-whisper:{settings.faster_whisper_model}"
    finally:
        temp_path.unlink(missing_ok=True)


@lru_cache(maxsize=4)
def _load_piper_voice(model_path: str) -> PiperVoice:
    logger.info("Loading local Piper voice=%s", Path(model_path).stem)
    return PiperVoice.load(model_path)


def _resolve_voice(voice: str | None) -> tuple[str, Path]:
    voice_name = (voice or settings.local_tts_voice).strip()
    if not _VOICE_NAME.fullmatch(voice_name):
        raise ValueError("voice must be a local Piper voice name.")
    model_path = Path(settings.speech_models_directory) / f"{voice_name}.onnx"
    if not model_path.is_file() and voice_name != settings.local_tts_voice:
        logger.warning(
            "Requested local voice=%s is not installed; using configured Piper voice=%s",
            voice_name,
            settings.local_tts_voice,
        )
        voice_name = settings.local_tts_voice
        model_path = Path(settings.speech_models_directory) / f"{voice_name}.onnx"
    if not model_path.is_file():
        model_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "piper.download_voices",
                    voice_name,
                    "--download-dir",
                    str(model_path.parent),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError):
            logger.exception("Could not download the configured local Piper voice")
            raise RuntimeError(
                "The local Piper voice is missing. Download it using the README setup command."
            ) from None
    if not model_path.is_file():
        raise RuntimeError("The configured local Piper voice did not download correctly.")
    return voice_name, model_path


def _next_piper_chunk(iterator):
    return next(iterator, None)


async def _local_audio_chunks(text: str, voice: str | None) -> AsyncIterator[AudioChunk]:
    voice_name, model_path = await asyncio.to_thread(_resolve_voice, voice)
    piper_voice = await asyncio.to_thread(_load_piper_voice, str(model_path))
    iterator = iter(piper_voice.synthesize(text))
    provider = f"piper:{voice_name}"
    while True:
        chunk = await asyncio.to_thread(_next_piper_chunk, iterator)
        if chunk is None:
            break
        yield AudioChunk(
            content=chunk.audio_int16_bytes,
            sample_rate_hz=chunk.sample_rate,
            channels=chunk.sample_channels,
            sample_width=chunk.sample_width,
            provider=provider,
        )


async def _nvidia_audio_chunks(
    text: str,
    voice: str | None,
    api_key: str,
) -> AsyncIterator[AudioChunk]:
    endpoint = settings.nvidia_riva_tts_url
    if not endpoint:
        return
    if len(text) > 2000:
        logger.warning("NVIDIA Riva TTS input is over 2,000 characters; falling back to local Piper")
        return
    data = {
        "text": text,
        "language": "en-US",
        "sample_rate_hz": "22050",
        "encoding": "LINEAR_PCM",
    }
    if voice:
        data["voice"] = voice
    started = False
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{endpoint.rstrip('/')}/v1/audio/synthesize_online",
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
            ) as response:
                response.raise_for_status()
                async for part in response.aiter_bytes(16 * 1024):
                    if part:
                        started = True
                        yield AudioChunk(
                            content=part,
                            sample_rate_hz=22050,
                            channels=1,
                            sample_width=2,
                            provider="nvidia-riva",
                        )
    except Exception as exc:
        if started:
            raise
        logger.warning(
            "NVIDIA Riva TTS failed (%s); falling back to local Piper",
            type(exc).__name__,
        )
        return


async def stream_speech(
    text: str,
    voice: str | None,
    api_key: str | None,
) -> AsyncIterator[AudioChunk]:
    """Use configured NVIDIA Riva TTS when available, otherwise local Piper."""
    if settings.nvidia_riva_tts_url and api_key:
        produced_remote_audio = False
        try:
            async for chunk in _nvidia_audio_chunks(text, voice, api_key):
                produced_remote_audio = True
                yield chunk
            if produced_remote_audio:
                return
        except Exception:
            logger.exception("NVIDIA Riva TTS stream ended unexpectedly")
            raise
    else:
        logger.info("NVIDIA Riva TTS unavailable for this key; using local Piper: %s", _LOCAL_TTS_REASON)
    async for chunk in _local_audio_chunks(text, voice):
        yield chunk


async def iter_local_speech(text: str, voice: str | None) -> AsyncIterator[AudioChunk]:
    """Synthesize locally for users who request audio without a stored NVIDIA key."""
    async for chunk in _local_audio_chunks(text, voice):
        yield chunk
