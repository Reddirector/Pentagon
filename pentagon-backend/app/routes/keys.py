from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApiKey, User
from app.db.session import get_db
from app.schemas import (
    ApiKeyRequest,
    KeyStoredResponse,
    KeyValidationFailure,
    KeyValidationSuccess,
    StoreApiKeyRequest,
)
from app.security.crypto import EncryptionConfigurationError, encrypt_api_key
from app.services.nvidia_client import clear_models_cache, validate_api_key


router = APIRouter(prefix="/api/keys", tags=["keys"])


@router.post(
    "/validate",
    response_model=KeyValidationSuccess | KeyValidationFailure,
)
async def validate_key(payload: ApiKeyRequest) -> dict:
    result = await validate_api_key(payload.api_key.get_secret_value())
    return result.as_response()


@router.post("", response_model=KeyStoredResponse)
async def store_key(
    payload: StoreApiKeyRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    raw_key = payload.api_key.get_secret_value()
    validation = await validate_api_key(raw_key)
    if not validation.valid:
        status_code = {
            "invalid_key": 400,
            "rate_limited": 429,
            "network_error": 502,
            "unknown_error": 502,
        }.get(validation.category or "unknown_error", 502)
        raise HTTPException(status_code=status_code, detail=validation.reason)

    try:
        encrypted_key = encrypt_api_key(raw_key)
    except EncryptionConfigurationError:
        raise HTTPException(
            status_code=503,
            detail="Key storage is not configured. Set KEY_ENCRYPTION_SECRET on the server.",
        ) from None

    user = db.get(User, payload.user_id)
    if user is None:
        db.add(User(id=payload.user_id))
        db.flush()

    stored_key = db.scalar(select(ApiKey).where(ApiKey.user_id == payload.user_id))
    if stored_key is None:
        stored_key = ApiKey(
            user_id=payload.user_id,
            encrypted_key=encrypted_key,
            masked_key=_mask_key(raw_key),
        )
        db.add(stored_key)
    else:
        stored_key.encrypted_key = encrypted_key
        stored_key.masked_key = _mask_key(raw_key)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not store the API key.") from None

    clear_models_cache(payload.user_id)
    return {"stored": True, "masked_key": _mask_key(raw_key)}


def _mask_key(api_key: str) -> str:
    return f"nvapi-...{api_key[-4:]}"
