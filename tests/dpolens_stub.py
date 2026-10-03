"""A DPOLens instance that answers from canned bodies, for the tests of a surface.

The MCP server under test is the real one: the real door, the real token check,
the real tools. What is replaced is the instance behind it, so these tests need
no database and no socket and still exercise the path a question takes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx2

SURFACE = "dpol_surfacecredentialaaaaaaaaaaaaaaaaaaaa"
DEVELOPER = "dpol_developertokenbbbbbbbbbbbbbbbbbbbbbb"
USER_ID = "11111111-1111-1111-1111-111111111111"
PAT_ID = "22222222-2222-2222-2222-222222222222"

HOST = "http://localhost:8765"
"""Loopback, which is the only Host this server answers until one is named."""

ARTICLE: dict[str, Any] = {
    "key": "testlaw:art-5",
    "clause_type": "article",
    "label": "Article 5",
    "heading": "Storage limitation",
    "text": "Personal data shall be kept no longer than is necessary.",
    "lang": "en",
    "is_authoritative": True,
    "is_normative": True,
    "depth": 1,
    "document_title": "Test Data Protection Law",
    "document_slug": "testlaw",
    "version_label": "2020/1",
    "effective_date": "2020-01-01",
    "pack_slug": "testlaw",
    "jurisdiction": "TEST",
    "trust_tier": "community",
    "source_url": "https://example.invalid/testlaw/art-5",
}

PARAGRAPH: dict[str, Any] = {
    **ARTICLE,
    "key": "testlaw:art-5:para-1",
    "clause_type": "paragraph",
    "label": "1.",
    "heading": None,
    "text": "Data kept for a deleted account shall be erased within thirty days.",
    "depth": 2,
}

CHAPTER: dict[str, Any] = {
    **ARTICLE,
    "key": "testlaw:chap-2",
    "clause_type": "chapter",
    "label": "Chapter II",
    "heading": "Principles",
    "text": "Principles",
    "depth": 0,
}

DOCUMENT: dict[str, Any] = {
    "slug": "testlaw",
    "title": "Test Data Protection Law",
    "kind": "law",
    "version_label": "2020/1",
    "effective_date": "2020-01-01",
    "clauses": 12,
    "languages": ["en"],
    "pack_slug": "testlaw",
    "jurisdiction": "TEST",
    "trust_tier": "community",
    "source_url": "https://example.invalid/testlaw",
}


def problem(status: int, kind: str, title: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": f"/problems/{kind}",
        "title": title,
        "status": status,
        "detail": detail,
        **extra,
    }


@dataclass
class Refusal:
    """What the instance should answer instead of the usual body."""

    status: int
    body: dict[str, Any] | list[Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Stub:
    """One DPOLens instance, answering from canned bodies and remembering the asking."""

    seen: list[httpx2.Request] = field(default_factory=list)
    active: bool = True
    permissions: tuple[str, ...] = ("documents.read",)
    expires_at: str | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    accepts: str | None = None
    refusals: dict[str, Refusal] = field(default_factory=dict)
    unreachable: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.results:
            self.results = [
                {
                    "clause": PARAGRAPH,
                    "score": 0.93,
                    "breadcrumb": [CHAPTER, ARTICLE],
                    "cross_references": [{"key": "testlaw:art-6", "text": "Article 6"}],
                    "expanded": [],
                    "ranks": None,
                }
            ]
        if not self.documents:
            self.documents = [DOCUMENT]

    def refuse(self, path: str, refusal: Refusal) -> None:
        """Answer one path with a refusal rather than a result."""
        self.refusals[path] = refusal

    def ordered(self) -> list[str]:
        """The paths asked for, in the order they were asked."""
        return [request.url.path for request in self.seen]

    def calls(self, path: str) -> list[httpx2.Request]:
        return [request for request in self.seen if request.url.path == path]

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._answer)

    def _answer(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append(request)
        path = request.url.path
        if path in self.unreachable:
            raise httpx2.ConnectError("refused", request=request)

        presented = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if self.accepts is not None and presented != self.accepts:
            return self._problem(
                Refusal(401, problem(401, "unauthenticated", "Unauthenticated", "not valid here"))
            )

        if path in self.refusals:
            return self._problem(self.refusals[path])

        if path == "/v1/tokens/introspect":
            return httpx2.Response(200, json=self._introspection())
        if path == "/v1/search":
            return httpx2.Response(200, json={"results": self.results})
        if path.endswith("/subtree"):
            return httpx2.Response(200, json=[ARTICLE, PARAGRAPH])
        if path.startswith("/v1/clauses/"):
            return httpx2.Response(
                200,
                json={
                    "clause": ARTICLE,
                    "breadcrumb": [CHAPTER],
                    "children": [PARAGRAPH],
                    "cross_references": [{"key": "testlaw:art-6", "text": "Article 6"}],
                },
            )
        if path == "/v1/documents":
            return httpx2.Response(
                200,
                json={
                    "documents": self.documents,
                    "total": len(self.documents),
                    "limit": 50,
                    "offset": 0,
                },
            )
        if path.startswith("/v1/documents/"):
            return httpx2.Response(
                200,
                json={
                    "document": DOCUMENT,
                    "outline": [
                        {
                            "key": "testlaw:art-5",
                            "clause_type": "article",
                            "label": "Article 5",
                            "heading": "Storage limitation",
                            "is_normative": True,
                            "children": 3,
                        }
                    ],
                },
            )
        return self._problem(
            Refusal(404, problem(404, "not-found", "Not found", f"no route {path}"))
        )

    def _introspection(self) -> dict[str, Any]:
        if not self.active:
            return {"active": False}
        return {
            "active": True,
            "user_id": USER_ID,
            "email": "developer@example.com",
            "pat_id": PAT_ID,
            "permissions": list(self.permissions),
            "expires_at": self.expires_at,
        }

    def _problem(self, refusal: Refusal) -> httpx2.Response:
        headers = {"content-type": "application/problem+json", **refusal.headers}
        content = json.dumps(refusal.body or {}).encode()
        return httpx2.Response(refusal.status, content=content, headers=headers)


def said(result: Any) -> str:
    """What the model reads back from a call."""
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))


def structured(result: Any) -> dict[str, Any]:
    """What a client application reads back from a call."""
    answer: dict[str, Any] = result.structured_content or {}
    return answer


@contextmanager
def recorded(name: str) -> Iterator[list[logging.LogRecord]]:
    """What one logger emits, without depending on how logging is set up elsewhere.

    `caplog` reads through the root logger, and anything that has run
    `logging.config.fileConfig` in the same process (Alembic does, while
    migrating a test database) leaves every logger that already existed
    disabled. A handler on the logger itself is unaffected by that.
    """
    logger = logging.getLogger(name)
    kept: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            kept.append(record)

    handler = Keep()
    was_disabled, logger.disabled = logger.disabled, False
    level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield kept
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
        logger.disabled = was_disabled


def messages(records: list[logging.LogRecord]) -> str:
    return "\n".join(record.getMessage() for record in records)
