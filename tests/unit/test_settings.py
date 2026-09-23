"""Settings are validated when the process starts, not on first use.

Built through `model_validate`, the way the environment reaches them, so these
exercise validation rather than Python's own typing.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from dpolens.settings import Settings

VALID_URL = "postgresql://user:pass@localhost:5432/dpolens"


def build(**values: Any) -> Settings:
    return Settings.model_validate(values)


def test_accepts_a_postgres_url() -> None:
    settings = build(database_url=VALID_URL)

    assert settings.database_url.path == "/dpolens"


def test_refuses_a_missing_database_url() -> None:
    with pytest.raises(ValidationError):
        build()


def test_refuses_a_non_postgres_url() -> None:
    with pytest.raises(ValidationError):
        build(database_url="mysql://user:pass@localhost:3306/dpolens")


def test_refuses_an_unknown_setting() -> None:
    """A typo in an environment variable stops the instance rather than being ignored."""
    with pytest.raises(ValidationError):
        build(database_url=VALID_URL, databse_url=VALID_URL)
