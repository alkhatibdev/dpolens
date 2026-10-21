"""Instance settings, read from the environment at startup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from dpolens.engine.logs.redaction import check_pattern

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

    intra_op_num_threads: int = Field(
        default=2,
        ge=1,
        description=(
            "Threads one embedding call may use. Left to ONNX Runtime it takes every core, "
            "and several requests each taking every core is slower than one at a time"
        ),
    )

    query_log_retention_days: int | None = Field(
        default=None,
        ge=1,
        description=(
            "How many days a question is kept before the instance deletes it, counted from "
            "the day it was asked. Left unset, questions are kept. Changing it needs a "
            "restart, which is the right amount of friction for a promise with legal weight"
        ),
    )

    session_idle_minutes: int = Field(
        default=30,
        ge=1,
        description="How long a dashboard session may go unused before it ends",
    )

    session_lifetime_hours: int = Field(
        default=8,
        ge=1,
        le=168,
        description="How long a dashboard session lasts at most, however much it is used",
    )

    community: bool = Field(
        default=False,
        description=(
            "Run as a community version: no sample policy, and the Community account the "
            "MCP server answers everyone as, made when the API starts"
        ),
    )

    public_dashboard_url: str = Field(
        default="http://localhost:8080",
        max_length=500,
        description=(
            "The dashboard's URL as people open it, which `dpolens init` names when it "
            "is done. The default is the quickstart's"
        ),
    )

    public_mcp_url: str = Field(
        default="http://localhost:8765/mcp",
        max_length=500,
        description=(
            "The MCP server's URL as people's AI assistants reach it, which the "
            "dashboard shows next to a new token. The default is the quickstart's"
        ),
    )

    originals_dir: Path = Field(
        default=Path("/var/lib/dpolens/originals"),
        description=(
            "Where uploaded policies' original files are kept, a folder the API and the "
            "worker can both write to. The image's default is its originals volume"
        ),
    )

    packs_repository: str = Field(
        default="alkhatibdev/dpolens",
        pattern=r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$",
        description=(
            "The GitHub repository, as owner/name, whose releases `dpolens pack update` reads. "
            "A fork that publishes its own packs is named here"
        ),
    )

    redaction_patterns: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Extra patterns to redact from a stored question, as {name: regex}. Patterns "
            "can only be added: nothing here can remove a built-in or switch redaction off"
        ),
    )

    @field_validator("redaction_patterns")
    @classmethod
    def _usable_patterns(cls, value: dict[str, str]) -> dict[str, str]:
        """Refuse a bad pattern at startup rather than on the first question."""
        for name, pattern in value.items():
            check_pattern(name, pattern)
        return value

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
        if value.scheme == "postgresql":
            # Name the driver. SQLAlchemy reads a bare postgresql:// URL as a
            # request for psycopg2, which DPOLens does not install, and the
            # failure arrives as a missing module rather than as anything an
            # operator could act on.
            return PostgresDsn(str(value).replace("postgresql://", "postgresql+psycopg://", 1))
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
