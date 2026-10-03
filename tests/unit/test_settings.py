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


def test_the_driver_is_named_even_when_the_url_leaves_it_out() -> None:
    """A bare postgresql:// URL is read by SQLAlchemy as a request for psycopg2.

    DPOLens installs psycopg 3, so a URL written the way every Postgres document
    writes it would fail with a missing module instead of connecting. The driver
    is filled in here rather than in each of the three places that connect.
    """
    settings = build(database_url=VALID_URL, migration_database_url=VALID_URL)

    assert str(settings.database_url).startswith("postgresql+psycopg://")
    assert str(settings.migration_database_url).startswith("postgresql+psycopg://")


def test_a_named_driver_is_left_as_it_is() -> None:
    settings = build(database_url="postgresql+psycopg://user:pass@localhost:5432/dpolens")

    assert str(settings.database_url) == "postgresql+psycopg://user:pass@localhost:5432/dpolens"


def test_naming_the_driver_does_not_change_the_role_the_url_names() -> None:
    """Migrations grant to this name, so it has to survive the rewrite."""
    settings = build(database_url=VALID_URL)

    assert settings.app_role == "user"


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
