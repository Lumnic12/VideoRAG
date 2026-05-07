"""
Application configuration via pydantic-settings.
Reads from ../.env (project root) or environment variables.
Always resolves storage paths to absolute based on this file's location.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the backend/ directory (where this config file lives)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DATA_DIR = _BACKEND_DIR / "data"


class Settings(BaseSettings):
    """All config for Semantic Video Synthesizer."""

    # External API keys
    deepgram_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = ""
    ollama_model: str = "gemma3:1b"           # chat/text model
    ollama_vision_model: str = "moondream"    # vision model for keyframe analysis
    hf_api_token: str = ""

    # Infrastructure
    redis_url: str = "redis://localhost:6379/0"

    # Storage paths — always use absolute paths resolved from backend/
    faiss_index_path: str = str(_DATA_DIR / "faiss_index")
    upload_dir: str = str(_DATA_DIR / "uploads")
    keyframe_dir: str = str(_DATA_DIR / "keyframes")

    # Limits
    max_upload_size_mb: int = 500
    ssim_threshold: float = 0.95

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
