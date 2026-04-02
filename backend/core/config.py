"""
Application configuration via pydantic-settings.
Reads from ../.env (project root) or environment variables.
"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All config for Semantic Video Synthesizer."""

    # External API keys
    deepgram_api_key: str = ""
    deepgram_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    hf_api_token: str = ""

    # Infrastructure
    redis_url: str = "redis://localhost:6379/0"

    # Storage paths
    faiss_index_path: str = "./data/faiss_index"
    upload_dir: str = "./data/uploads"
    keyframe_dir: str = "./data/keyframes"

    # Limits
    max_upload_size_mb: int = 500
    ssim_threshold: float = 0.95

    class Config:
        env_file = "../.env"          # relative to backend/
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
