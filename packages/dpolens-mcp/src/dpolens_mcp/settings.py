"""What this server needs to start, read from the environment.

Unknown variables are rejected, so a typo stops the server instead of being
ignored on a machine nobody can inspect.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DPOLENS_MCP_", extra="forbid")

    api_url: AnyHttpUrl = Field(
        description="Where the DPOLens HTTP API is, such as http://api:8000",
    )

    surface_token_file: Path = Field(
        default=Path("/run/dpolens/surface-token"),
        description=(
            "The file holding this server's own credential, written by the instance. "
            "The credential is never passed in an environment variable, because a "
            "variable is visible to every process in the container and to anything "
            "that inspects it"
        ),
    )

    host: str = Field(
        default="127.0.0.1",
        description=(
            "Which address to listen on. A container has to set this to 0.0.0.0 to be "
            "reachable, which is a decision worth making on purpose"
        ),
    )

    port: int = Field(default=8765, ge=1, le=65535, description="Which port to listen on")

    allowed_hosts: list[str] = Field(
        default_factory=list,
        description=(
            "Host header values this server answers, such as "
            '["dpolens.example.com:8765"]. Empty means loopback only, which is right '
            "when each developer reaches the server on their own machine. A name has "
            "to be listed here before a browser can be tricked into using it, which "
            "is what keeps a page on the internet from reaching a server on a "
            "private network"
        ),
    )

    request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="How long to wait for the API before giving up on one call",
    )

    credential_wait_seconds: float = Field(
        default=120.0,
        ge=0,
        description=(
            "How long to wait at startup for the credential file to appear. The API "
            "writes it as it starts, and on a first run that includes the time the "
            "instance takes to migrate and load its packs"
        ),
    )

    log_level: str = Field(default="INFO", description="Python logging level for the process")

    @property
    def hosts(self) -> list[str]:
        """Which Host headers to answer, loopback when nothing else is named."""
        return self.allowed_hosts or ["127.0.0.1:*", "localhost:*", "[::1]:*"]

    @property
    def api(self) -> str:
        """The API's base URL, without the trailing slash a URL type adds."""
        return str(self.api_url).rstrip("/")
