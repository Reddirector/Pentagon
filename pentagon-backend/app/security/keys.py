from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ApiKey
from app.security.crypto import decrypt_api_key

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
