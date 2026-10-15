"""Central application settings, validated at startup."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings. Infrastructure knobs are added with their owning slice."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    websocket_send_timeout_seconds: float = Field(default=2.0, gt=0, le=30.0)
    database_url: str = "sqlite:///./data/interactive_live_engine.db"
    event_record_retention_days: int = Field(default=7, ge=1, le=365)
