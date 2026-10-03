from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: str = "sqlite:///./pentagon.db"
    key_encryption_secret: SecretStr | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # Reasoning models on NVIDIA NIM can take 2-3 minutes before their first
    # output token; 30s killed every app request (verified live, Oct 2026).
    nvidia_timeout_seconds: float = 300.0
    tavily_api_key: SecretStr | None = None
    chroma_persist_directory: str = "./chroma_data"
    image_upload_directory: str = "./image_uploads"
    video_sampling_fps: float = 1.0
    video_max_duration_seconds: float = 60.0
    speech_models_directory: str = "./speech_models"
    faster_whisper_model: str = "base"
    local_tts_voice: str = "en_US-lessac-medium"
    nvidia_riva_asr_url: str | None = None
    nvidia_riva_tts_url: str | None = None
    local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_project_ref: str | None = None
    # Server-side fallback: used when the local user has no stored NVIDIA key.
    # Never exposed to the client; tests cover the fallback path with mocks.
    nvidia_server_api_key: SecretStr | None = None
    default_chat_model: str | None = None


settings = Settings()
