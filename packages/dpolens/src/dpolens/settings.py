"""Instance settings, read from the environment at startup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRET_SETTINGS = ("database_url",)
"""Settings that also accept a `<NAME>_FILE` variant, for mounted secrets."""


def _read_secret_files(values: dict[str, Any]) -> dict[str, Any]:
    for name in SECRET_SETTINGS:
        path = os.environ.get(f"DPOLENS_{name.upper()}_FILE")
        if path and name not in values:
            values[name] = Path(path).read_text(encoding="utf-8").strip()
    return values


class Settings(BaseSettings):
    """Everything the instance needs to start.

    Unknown variables are rejected, so a typo stops the instance instead of
    being silently ignored on a machine nobody can inspect.
    """

    model_config = SettingsConfigDict(env_prefix="DPOLENS_", extra="forbid")

    database_url: PostgresDsn = Field(
        description="PostgreSQL connection URL, for example postgresql://user:pass@host:5432/dpolens",
    )

    @field_validator("database_url")
    @classmethod
    def _require_postgres(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme not in ("postgresql", "postgresql+psycopg"):
            raise ValueError(
                "database_url must be a PostgreSQL URL: several of the guarantees "
                "DPOLens makes are enforced by Postgres itself."
            )
        return value


def load_settings() -> Settings:
    """Build settings from the environment. Entry points call this; tests do not."""
    return Settings.model_validate(_read_secret_files({}))
