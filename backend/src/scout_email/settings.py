from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with fail-safe development defaults."""

    model_config = SettingsConfigDict(
        env_prefix="SCOUT_EMAIL_",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path("../data")
    database_url: str = "sqlite+aiosqlite:///../data/scout_email.db"
    browser_worker_url: str = "http://browser-worker:8010"
    send_mode: Literal["mock", "gmail"] = "mock"
    maps_live_smoke_enabled: bool = False
    max_browser_concurrency: int = Field(default=2, ge=1, le=3)
    http_crawl_concurrency: int = Field(default=8, ge=1, le=32)
    gemini_api_key: str | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"
    n8n_webhook_secret: str | None = None


settings = Settings()
