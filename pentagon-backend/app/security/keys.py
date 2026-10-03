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


def resolve_api_key(db: Session, user_id: str) -> str:
    """Return the NVIDIA key for a request.

    Precedence: the user's stored key (decrypted) first, then the server-side
    fallback key from settings. Decrypt failures propagate so route handlers can
    map them to their existing HTTP responses. The server key is never returned
    to the client; it exists only so the app works before a user stores a key.
    """
    row = db.scalar(select(ApiKey).where(ApiKey.user_id == user_id))
    if row is not None:
        return decrypt_api_key(row.encrypted_key)

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


def resolve_api_key_or_http(db: Session, user_id: str) -> str:
    """Resolve a key for a request, mapping every failure to an HTTP error.

    ``resolve_api_key`` can also fail to decrypt a stored key, which happens in
    practice whenever ``KEY_ENCRYPTION_SECRET`` is rotated. Routes that only
    caught ``NoKeyAvailableError`` turned that into a bare 500, so every chat
    and model request failed with an opaque error and no way forward.
    """
    try:
        return resolve_api_key(db, user_id)
    except (NoKeyAvailableError, EncryptionConfigurationError, EncryptedKeyError) as exc:
        raise key_error_to_http(exc) from None
