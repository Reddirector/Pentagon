from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ApiKey
from app.security.crypto import (
    EncryptedKeyError,
    EncryptionConfigurationError,
    decrypt_api_key,
)

logger = logging.getLogger(__name__)


class NoKeyAvailableError(RuntimeError):
    """No NVIDIA key is stored for the user and no server fallback is configured."""


def resolve_api_key(db: Session, user_id: str, request_key: str | None = None) -> str:
    """Return the NVIDIA key for a request.

    Precedence:
    1. Direct request key (from X-Nvidia-Key header or request body) if provided.
    2. The user's stored key (decrypted) in the database.
    3. Any active key stored in the ApiKey table (fallback for multi-tab/ephemeral user IDs in local Pentagon installs).
    4. The server-side fallback key from settings. Decrypt failures propagate so
       route handlers can map them to their existing HTTP responses.
    """
    if request_key and isinstance(request_key, str) and request_key.strip():
        cleaned_key = request_key.strip()
        if len(cleaned_key) > 8:
            return cleaned_key

    row = db.scalar(select(ApiKey).where(ApiKey.user_id == user_id))
    if row is not None:
        return decrypt_api_key(row.encrypted_key)

    # Local multi-session/ephemeral ID fallback: if any key exists in DB, use the latest one
    fallback_row = db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc())).first()
    if fallback_row is not None:
        try:
            return decrypt_api_key(fallback_row.encrypted_key)
        except Exception:
            logger.warning("Fallback ApiKey decryption failed, checking server settings.")

    server_key = settings.nvidia_server_api_key
    if server_key is not None:
        value = server_key.get_secret_value().strip()
        if value:
            return value

    raise NoKeyAvailableError(f"No NVIDIA key is stored for user {user_id}.")


def key_error_to_http(exc: Exception) -> HTTPException:
    """Map a key-resolution failure onto the response the client should see."""
    if isinstance(exc, NoKeyAvailableError):
        return HTTPException(status_code=404, detail="No API key is stored for this user.")
    if isinstance(exc, EncryptionConfigurationError):
        return HTTPException(status_code=503, detail="Key storage is not configured on the server.")
    return HTTPException(
        status_code=500,
        detail="The stored API key could not be decrypted. Save it again to continue.",
    )


def resolve_api_key_or_http(db: Session, user_id: str, request_key: str | None = None) -> str:
    """Resolve a key for a request, mapping every failure to an HTTP error.

    ``resolve_api_key`` can also fail to decrypt a stored key, which happens in
    practice whenever ``KEY_ENCRYPTION_SECRET`` is rotated. Routes that only
    caught ``NoKeyAvailableError`` turned that into a bare 500, so every chat
    and model request failed with an opaque error and no way forward.
    """
    try:
        return resolve_api_key(db, user_id, request_key=request_key)
    except (NoKeyAvailableError, EncryptionConfigurationError, EncryptedKeyError) as exc:
        raise key_error_to_http(exc) from None
