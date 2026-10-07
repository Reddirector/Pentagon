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
    # How much of an uploaded video is actually analysed. Longer clips are
    # sampled more sparsely rather than rejected.
    video_max_duration_seconds: float = 600.0
    speech_models_directory: str = "./speech_models"
    # Where create_artifact writes deliverables, one subfolder per turn.
    artifact_directory: str = "./artifacts"
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

    # --- RAG 2: collections, multilingual/hybrid/graph retrieval ------------
    # Default embedding model for new collections (EMBEDDING_MODEL, RAG §18).
    # Stored per collection as ``id@version``; changing it is a reindex, and
    # vectors from two different models are never mixed in one collection.
    # Defaults to the local model so indexing works with no key at all.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    # NVIDIA's free tier is roughly 40 requests/minute, shared across
    # everything. Chat is admitted from this bucket; background indexing may
    # spend at most ``graph_index_rate_fraction`` of it, so an index job can
    # never spend a person's answer. Chat waiters are served before indexing
    # waiters whenever a token frees up.
    rate_limit_per_minute: int = 40
    graph_index_rate_fraction: float = 0.5
    # How long a caller waits for a permit before the request is refused with
    # a 429 instead of hanging behind a queue.
    rate_limit_wait_seconds: float = 30.0
    # The background index-job worker. Tests turn this off (tests/conftest.py)
    # so jobs are claimed and driven deterministically instead of racing a
    # poll loop; the app runs with it on.
    job_worker_enabled: bool = True

    # --- MCP bridge -------------------------------------------------------
    # External MCP servers to bridge, as a JSON array. Only these commands
    # are ever spawned -- never one a model or a web page asks for. Example:
    # [{"name":"files","command":["npx","-y","@modelcontextprotocol/server-filesystem","/data"],"tier":"read"}]
    # "tier" is the approval tier for the server's tools when it publishes
    # no annotations of its own (default write, so unknown capabilities are
    # approval-gated at Balanced rather than auto-run).
    mcp_servers: str = "[]"

    # --- Shell tool -------------------------------------------------------
    # Master switch. The model is given no command tool at all unless this is
    # true, so a deployment that does not want shell access never exposes it,
    # regardless of what any client asks for. It is off by default because a
    # prompt-injected web page or uploaded PDF must not be able to reach a shell.
    command_tool_enabled: bool = False
    # A command the user has not answered is denied, never run. Silence is a
    # "no": a closed tab must not turn into an executed command.
    command_approval_timeout_seconds: float = 300.0
    command_timeout_seconds: float = 120.0
    # Ceiling on what a single command can hand back to the model, so one
    # runaway `cat` of a huge log cannot blow out the conversation context.
    command_max_output_bytes: int = 20_000
    # Where commands run. Empty means the backend's own working directory.
    command_working_directory: str = ""
    # How many commands the model may request in a single turn. Each one is a
    # round trip through the model, so this bounds a runaway loop.
    command_max_calls_per_turn: int = 8
    # Desktop control (opening and closing apps, screenshots, volume, power)
    # is a separate switch from the shell, because it is a different and much
    # larger blast radius: it can lock the screen or shut the machine down.
    # Off by default for the same reason the shell is.
    desktop_actions_enabled: bool = False
    # Desktop actions get a shorter answer window than shell commands: the
    # window you agreed to close five minutes ago may not be the one that is on
    # screen now, so a late yes is worth less than a prompt no.
    desktop_action_approval_timeout_seconds: float = 120.0
    # Where screenshots land. Empty means the system temp directory.
    screenshot_directory: str = ""
    # How long a window-manager script may take before we give up on it.
    # (no separate execution timeout: desktop actions either finish fast or
    # are waiting on the user for the approval window below.)
    # Location. Separate again, because "where is this person" is a different
    # kind of question from "run this command". Off by default, and only ever
    # consulted when the model decides an answer needs it.
    location_enabled: bool = False
    # Where the capability token lives. Empty means
    # $XDG_CONFIG_HOME/pentagon/capability-token.
    capability_token_path: str = ""
    # Ceiling on video we will accept or fetch. video.py keeps hard limits as
    # well; this is the tunable side of them.
    video_max_bytes: int = 120 * 1024 * 1024

    # Origins allowed to call this API from a browser or a native WebView. The
    # web and Electron builds are same-origin, so they need nothing here; the
    # iOS and Android shells load from their own bundled origin and therefore
    # dial this server cross-origin, which the browser engine blocks without an
    # explicit allowance. Add any extra origins (a hosted frontend, a Tailscale
    # or LAN address) as a comma-separated list.
    cors_origins: str = "capacitor://localhost,http://localhost,https://localhost"


def cors_origin_list() -> list[str]:
    return [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]


settings = Settings()
