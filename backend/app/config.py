"""Central application settings, validated at startup."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings. Provider connections are opt-in by default."""

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
    tiktok_live_enabled: bool = False
    tiktok_live_username: str | None = Field(default=None, min_length=1, max_length=128)
    tiktok_live_diagnostics_enabled: bool = False

    @field_validator("tiktok_live_username")
    @classmethod
    def normalize_tiktok_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lstrip("@").strip()
        return cleaned or None

    @model_validator(mode="after")
    def require_username_when_tiktok_is_enabled(self) -> Settings:
        if self.tiktok_live_enabled and not self.tiktok_live_username:
            raise ValueError("TIKTOK_LIVE_USERNAME is required when TIKTOK_LIVE_ENABLED=true")
        if self.tiktok_live_diagnostics_enabled and self.app_env == "production":
            raise ValueError("TIKTOK_LIVE_DIAGNOSTICS_ENABLED is allowed only in development/test")
        return self
