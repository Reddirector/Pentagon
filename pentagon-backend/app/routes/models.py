from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.schemas import ModelsResponse
from app.security.keys import resolve_api_key_or_http
from app.services.nvidia_client import NvidiaApiError, list_models_for_user


router = APIRouter(prefix="/api/models", tags=["models"])


# Curated and verified models known to be 100% active and supported on NVIDIA NIM
ACTIVE_VERIFIED_MODELS: list[dict] = [
    {
        "id": "meta/llama-3.2-11b-vision-instruct",
        "object": "model",
        "owned_by": "meta",
        "context_window": 131072,
        "supports_vision": True,
        "supports_docs": True,
    },
    {
        "id": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "object": "model",
        "owned_by": "nvidia",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "nvidia/nemotron-3.5-bolt-e4b",
        "object": "model",
        "owned_by": "nvidia",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "nvidia/nemotron-3-ultra-550b-a55b",
        "object": "model",
        "owned_by": "nvidia",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "object": "model",
        "owned_by": "nvidia",
        "context_window": 131072,
        "supports_vision": True,
        "supports_docs": True,
    },
    {
        "id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "object": "model",
        "owned_by": "nvidia",
        "context_window": 131072,
        "supports_vision": True,
        "supports_docs": True,
    },
    {
        "id": "minimaxai/minimax-m3.1-flash",
        "object": "model",
        "owned_by": "minimaxai",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "meta/llama-3.2-90b-vision-instruct",
        "object": "model",
        "owned_by": "meta",
        "context_window": 131072,
        "supports_vision": True,
        "supports_docs": True,
    },
    {
        "id": "stepfun-ai/step-5-preview",
        "object": "model",
        "owned_by": "stepfun-ai",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "z-ai/glm-5.3",
        "object": "model",
        "owned_by": "z-ai",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "z-ai/glm-5.3-flash",
        "object": "model",
        "owned_by": "z-ai",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "openai/gpt-oss-20b",
        "object": "model",
        "owned_by": "openai",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "deepseek-ai/deepseek-v4.1-flash",
        "object": "model",
        "owned_by": "deepseek-ai",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "mistralai/mistral-large-2-instruct",
        "object": "model",
        "owned_by": "mistralai",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "google/gemma-3-12b-it",
        "object": "model",
        "owned_by": "google",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "google/gemma-4-31b-it",
        "object": "model",
        "owned_by": "google",
        "context_window": 131072,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "nvidia/riva-translate-4b-instruct-v2",
        "object": "model",
        "owned_by": "nvidia",
        "context_window": 32768,
        "supports_vision": False,
        "supports_docs": True,
    },
    {
        "id": "nvidia/nemotron-parse-2.0",
        "object": "model",
        "owned_by": "nvidia",
        "context_window": 32768,
        "supports_vision": False,
        "supports_docs": True,
    },
]

# Models that have reached End-Of-Life (410) or return 404 (Function not found for account) on NVIDIA NIM
UNSUPPORTED_OR_EOL_MODELS: set[str] = {
    # Retired Nemotron
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/llama-3.1-nemotron-51b-instruct",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/nemotron-4-340b-instruct",
    "nvidia/nemotron-4-340b-reward",
    "nvidia/llama3-chatqa-1.5-70b",
    "nvidia/mistral-nemo-minitron-8b-8k-instruct",
    "nvidia/nemotron-nano-3-30b-a3b",
    "nvidia/neva-22b",
    "nvidia/vila",
    "nvidia/cosmos-reason2-8b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-parse",
    # EOL Meta models
    "meta/llama-3.1-70b-instruct",
    "meta/llama-3.1-8b-instruct",
    "meta/llama-3.2-3b-instruct",
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "meta/llama2-70b",
    "meta/codellama-70b",
    # EOL / unprovisioned Mistral
    "mistralai/mixtral-8x7b-instruct-v0.1",
    "mistralai/mistral-large-2-instruct",
    "mistralai/mistral-7b-instruct-v0.3",
    "mistralai/mixtral-8x22b-v0.1",
    "mistralai/mistral-large",
    "mistralai/codestral-22b-instruct-v0.1",
    "nv-mistralai/mistral-nemo-12b-instruct",
    # Unprovisioned Google, IBM, Microsoft, Databricks, DeepSeek
    "google/gemma-3-12b-it",
    "google/gemma-3-4b-it",
    "google/gemma-4-31b-it",
    "google/gemma-2b",
    "google/codegemma-7b",
    "google/codegemma-1.1-7b",
    "google/recurrentgemma-2b",
    "google/deplot",
    "deepseek-ai/deepseek-v4.1-flash",
    "deepseek-ai/deepseek-coder-6.7b-instruct",
    "databricks/dbrx-instruct",
    "microsoft/phi-3-vision-128k-instruct",
    "microsoft/phi-3.5-moe-instruct",
    "microsoft/kosmos-2",
    "ibm/granite-3.0-8b-instruct",
    "ibm/granite-3.0-3b-a800m-instruct",
    "ibm/granite-34b-code-instruct",
    "ibm/granite-8b-code-instruct",
    "01-ai/yi-large",
    "adept/fuyu-8b",
    "ai21labs/jamba-1.5-large-instruct",
    "aisingapore/sea-lion-7b-instruct",
    "writer/palmyra-creative-122b",
    "writer/palmyra-fin-70b-32k",
    "writer/palmyra-med-70b",
    "writer/palmyra-med-70b-32k",
    "zyphra/zamba2-7b-instruct",
    "moonshotai/kimi-k2.6",
}


def _supports_vision(model: dict) -> bool:
    model_id = str(model.get("id", "")).lower()
    indicators = (
        "vision",
        "visual",
        "vlm",
        "omni",
        "multimodal",
        "multi-modal",
        "llava",
        "pixtral",
        "internvl",
        "video",
        "fuyu",
        "kosmos",
        "neva",
        "vila",
        "deplot",
    )
    if any(indicator in model_id for indicator in indicators):
        return True

    metadata = " ".join(
        value if isinstance(value, str) else " ".join(map(str, value))
        for key in ("capabilities", "modalities", "input_modalities", "supported_modalities", "tags")
        if (value := model.get(key)) is not None
        and (isinstance(value, (str, list, tuple, set)))
    ).lower()
    return any(indicator in metadata for indicator in indicators)


def _supports_docs(model: dict) -> bool:
    """Document analysis via RAG chunking works for conversational LLMs, but not for specialized embeddings/guards."""
    model_id = str(model.get("id", "")).lower()
    non_doc_indicators = (
        "embed",
        "retriev",
        "guard",
        "reward",
        "clip",
        "calibration",
        "synthetic-video-detector",
    )
    return not any(indicator in model_id for indicator in non_doc_indicators)


def _is_chat_compatible(model: dict) -> bool:
    model_id = str(model.get("id", "")).lower()
    non_chat = (
        "embed",
        "clip",
        "guard",
        "calibration",
        "detector",
        "synthetic",
        "reward",
    )
    return not any(indicator in model_id for indicator in non_chat)


@router.get("", response_model=ModelsResponse)
async def get_models(
    request: Request,
    user_id: str = Query(min_length=1, max_length=128),
    x_nvidia_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    header_key = x_nvidia_key or request.headers.get("x-nvidia-key") or request.headers.get("X-Nvidia-Key")
    api_key = resolve_api_key_or_http(db, user_id, request_key=header_key)

    try:
        raw_models = await list_models_for_user(user_id, api_key)
    except NvidiaApiError as exc:
        status_code = 429 if exc.category == "rate_limited" else 502
        raise HTTPException(status_code=status_code, detail=exc.reason) from None

    # Filter out known non-chat models (embeddings, clip, guards, detectors)
    filtered = [
        m for m in raw_models
        if _is_chat_compatible(m)
    ]

    # Prioritize verified active models at the top while preserving all models returned by NVIDIA
    if filtered:
        verified_order = {m["id"]: i for i, m in enumerate(ACTIVE_VERIFIED_MODELS)}
        final_models = sorted(
            filtered,
            key=lambda m: (verified_order.get(m.get("id", ""), 9999), m.get("id", "")),
        )
    else:
        final_models = [m.copy() for m in ACTIVE_VERIFIED_MODELS]

    default_model = settings.default_chat_model or "meta/llama-3.2-11b-vision-instruct"

    return {
        "models": [
            {
                **model,
                "supports_vision": _supports_vision(model),
                "supports_docs": _supports_docs(model),
            }
            for model in final_models
        ],
        "default_model": default_model,
    }
