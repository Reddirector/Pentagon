from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.schemas import ModelsResponse
from app.security.keys import resolve_api_key_or_http
from app.services.nvidia_client import NvidiaApiError, list_models_for_user


router = APIRouter(prefix="/api/models", tags=["models"])


def _supports_vision(model: dict) -> bool:
    model_id = str(model.get("id", "")).lower()
    indicators = ("vision", "visual", "vlm", "omni", "multimodal", "multi-modal", "llava", "pixtral", "internvl", "video")
    if any(indicator in model_id for indicator in indicators):
        return True

    metadata = " ".join(
        value if isinstance(value, str) else " ".join(map(str, value))
        for key in ("capabilities", "modalities", "input_modalities", "supported_modalities", "tags")
        if (value := model.get(key)) is not None
        and (isinstance(value, (str, list, tuple, set)))
    ).lower()
    return any(indicator in metadata for indicator in indicators)


@router.get("", response_model=ModelsResponse)
async def get_models(
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    api_key = resolve_api_key_or_http(db, user_id)

    try:
        models = await list_models_for_user(user_id, api_key)
    except NvidiaApiError as exc:
        status_code = 429 if exc.category == "rate_limited" else 502
        raise HTTPException(status_code=status_code, detail=exc.reason) from None

    return {
        "models": [
            {**model, "supports_vision": _supports_vision(model)}
            for model in models
        ],
        "default_model": settings.default_chat_model,
    }
