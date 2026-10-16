"""The limit on a request body, which has to hold before anything reads the body."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Body, FastAPI
from fastapi.testclient import TestClient

from dpolens.api.limits import BodyLimit

LIMIT = 10
OCTETS = {"Content-Type": "application/octet-stream"}


def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(BodyLimit, limit=LIMIT)

    @app.post("/files")
    def receive(
        content: Annotated[bytes, Body(media_type="application/octet-stream")],
    ) -> dict[str, int]:
        return {"size": len(content)}

    return TestClient(app)


def test_a_body_within_the_limit_reaches_the_route() -> None:
    response = client().post("/files", content=b"x" * LIMIT, headers=OCTETS)

    assert response.status_code == 200
    assert response.json() == {"size": LIMIT}


def test_a_declared_length_over_the_limit_is_refused_unread() -> None:
    response = client().post("/files", content=b"x" * (LIMIT + 1), headers=OCTETS)

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "/problems/too-large"


def test_a_body_without_a_length_is_cut_off_at_the_limit() -> None:
    def chunks() -> Iterator[bytes]:
        yield b"x" * LIMIT
        yield b"x"

    response = client().post("/files", content=chunks(), headers=OCTETS)

    assert response.status_code == 413
    assert response.json()["type"] == "/problems/too-large"
