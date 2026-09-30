"""Instance settings, read from the environment at startup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SECRET_SETTINGS = ("database_url", "migration_database_url")
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

    migration_database_url: PostgresDsn | None = Field(
        default=None,
        description=(
            "Connection URL for the role that owns the tables, used by migrations only. "
            "Unset means migrations run as the application role, which cannot grant away "
            "its own write access to the governance log"
        ),
    )

    rate_limit_per_minute: int = Field(
        default=60,
        ge=1,
        description=(
            "Requests a token may make each minute, counted inside each worker, so an "
            "instance running several workers allows that many times this number"
        ),
    )

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _require_postgres(cls, value: PostgresDsn | None) -> PostgresDsn | None:
        if value is None:
            return None
        if value.scheme not in ("postgresql", "postgresql+psycopg"):
            raise ValueError(
                "database URLs must be PostgreSQL URLs: several of the guarantees "
                "DPOLens makes are enforced by Postgres itself."
            )
        return value

    @property
    def app_role(self) -> str | None:
        """The role the application connects as, read from its own URL.

        Migrations grant to this name. Taking it from the URL rather than from a
        setting of its own means there is no second place to spell it, and so no
        way for the two to disagree.
        """
        return urlsplit(str(self.database_url)).username


def load_settings() -> Settings:
    """Build settings from the environment. Entry points call this; tests do not."""
    return Settings.model_validate(_read_secret_files({}))
