from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrowserWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BROWSER_WORKER_",
        env_file=".env",
        extra="ignore",
    )

    headless: bool = True
    executable_path: str | None = None
    max_concurrency: int = Field(default=2, ge=1, le=3)
    navigation_timeout_ms: int = Field(default=30_000, ge=5_000, le=120_000)
    artifact_dir: Path = Path("../data/browser-artifacts")
    maps_live_smoke_enabled: bool = Field(
        default=False,
        validation_alias="MAPS_LIVE_SMOKE_ENABLED",
    )
