from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
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
    llm_provider: Literal["gemini", "ollama", "openrouter"] | None = None
    llm_model: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"
    writing_playbook_dir: Path = Path("../config/weberaise")
    n8n_send_webhook_url: str | None = None
    n8n_webhook_secret: str | None = None

    @field_validator("llm_provider", "llm_model", mode="before")
    @classmethod
    def blank_llm_values_are_unset(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def require_runtime_configuration_pairs(self) -> "Settings":
        provider = (self.llm_provider or "").strip()
        model = (self.llm_model or "").strip()
        if bool(provider) != bool(model):
            raise ValueError("llm provider and model must both be configured")
        if self.send_mode == "gmail" and (
            not self.n8n_send_webhook_url or not self.n8n_webhook_secret
        ):
            raise ValueError(
                "gmail send mode requires n8n send webhook URL and shared secret"
            )
        return self


settings = Settings()
