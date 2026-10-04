from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ApiKeyRequest(BaseModel):
    api_key: SecretStr = Field(json_schema_extra={"writeOnly": True})

    @field_validator("api_key")
    @classmethod
    def check_nvidia_key_format(cls, value: SecretStr) -> SecretStr:
        raw_key = value.get_secret_value().strip()
        if not raw_key.startswith("nvapi-") or len(raw_key) < 10:
            raise ValueError("API key must be an NVIDIA key starting with nvapi-.")
        return SecretStr(raw_key)


class StoreApiKeyRequest(ApiKeyRequest):
    user_id: str = Field(min_length=1, max_length=128)

    @field_validator("user_id")
    @classmethod
    def trim_user_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("user_id cannot be empty.")
        return cleaned


class KeyValidationSuccess(BaseModel):
    valid: Literal[True]
    model_count: int
    sample_models: list[str]


class KeyValidationFailure(BaseModel):
    valid: Literal[False]
    reason: str


class KeyStoredResponse(BaseModel):
    stored: Literal[True]
    masked_key: str


class ModelsResponse(BaseModel):
    models: list[dict[str, Any]]
    default_model: str | None = None


class SwitchConversationModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)

    @field_validator("model")
    @classmethod
    def trim_model(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("model cannot be empty.")
        return cleaned


class SwitchConversationModelResponse(BaseModel):
    conversation_id: str
    active_model: str
    summary_generated: bool
    summary_word_count: int


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=36)
    model: str = Field(min_length=1, max_length=255)
    message: str = Field(default="", max_length=100_000)
    use_web_search: bool | None = None
    respond_with_audio: bool = False
    voice: str | None = Field(default=None, max_length=100)
    transcription_duration_ms: float | None = Field(default=None, ge=0)
    transcription_provider: str | None = Field(default=None, max_length=100)

    @field_validator("user_id")
    @classmethod
    def trim_user_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("user_id cannot be empty.")
        return cleaned

    @field_validator("conversation_id")
    @classmethod
    def trim_conversation_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("conversation_id cannot be empty.")
        return cleaned


class SynthesizeSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    voice: str | None = Field(default=None, max_length=100)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: Literal["user", "assistant"]
    content: str
    model_used: str
    # ``image_path`` is deliberately absent. It holds the absolute server path
    # the upload was written to (``image_uploads/<conversation id>/<id>.png``),
    # which ``from_attributes=True`` copied straight into every conversation
    # response. Nothing in the client ever read it -- the image travels to the
    # model inline as a data URI and is rendered from the transcript, not from
    # disk -- so the only effect was telling any caller the server's directory
    # layout. The column stays for the deletion sweep in routes.chat, which
    # needs to know a message had an upload.
    created_at: datetime


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    updated_at: datetime
    active_model: str | None = None


class CreateConversationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=120)


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    chunks_stored: int
    created_at: datetime


class ConversationResponse(ConversationSummary):
    summary_at_switch: str | None = None
    messages: list[MessageResponse]
