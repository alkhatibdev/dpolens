"""The only way this server reaches DPOLens.

Everything goes over the HTTP API: nothing here opens a database connection or
imports the engine, which is what lets a surface be written in any language.

A call carries this server's own credential and names the person it is acting
for in two headers. The caller's own token is never sent on, which the Model
Context Protocol requires of a server and which also keeps a leaked surface
credential from standing in for anybody's token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx2

from dpolens_mcp.credential import Credential

ON_BEHALF_OF_USER = "DPOLens-On-Behalf-Of-User"
ON_BEHALF_OF_TOKEN = "DPOLens-On-Behalf-Of-Token"
"""The API's names for an assertion about who a surface is acting for."""

REQUEST_ID = "X-Request-Id"
"""Carried so one question is one id across both calls it takes to answer it."""

PROBLEM_JSON = "application/problem+json"


@dataclass(frozen=True)
class Caller:
    """Who this server is acting for on one call, and under which id."""

    user_id: str
    pat_id: str
    request_id: str


@dataclass(frozen=True)
class Introspection:
    """What the API says about a token a caller presented."""

    user_id: str
    pat_id: str
    permissions: tuple[str, ...]
    expires_at: str | None


@dataclass(frozen=True)
class Refused(Exception):
    """The API refused the call, and said why in a way a caller can be told."""

    status: int
    type: str
    title: str
    detail: str
    retry_after: int | None = None

    def __str__(self) -> str:
        return self.detail or self.title


class Unreachable(Exception):
    """The API could not be reached at all, so nothing can be said about the answer."""


class Api:
    """A client of one DPOLens instance, holding one credential and one connection pool."""

    def __init__(
        self,
        *,
        base_url: str,
        credential: Credential,
        timeout: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.credential = credential
        self._client = httpx2.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def introspect(self, presented: str, *, request_id: str) -> Introspection | None:
        """Ask whose token this is, or get nothing back for one that cannot be used."""
        answer = await self.call(
            "POST",
            "/v1/tokens/introspect",
            request_id=request_id,
            body={"token": presented},
        )
        if not answer.get("active"):
            return None
        return Introspection(
            user_id=str(answer["user_id"]),
            pat_id=str(answer["pat_id"]),
            permissions=tuple(answer.get("permissions") or ()),
            expires_at=answer.get("expires_at"),
        )

    async def search(
        self,
        *,
        caller: Caller,
        query: str,
        limit: int,
        lang: str,
        as_of: date | None,
        include_explanatory: bool,
    ) -> dict[str, Any]:
        found: dict[str, Any] = await self.call(
            "POST",
            "/v1/search",
            caller=caller,
            request_id=caller.request_id,
            body={
                "query": query,
                "limit": limit,
                "lang": lang,
                "as_of": as_of.isoformat() if as_of else None,
                "include_explanatory": include_explanatory,
            },
        )
        return found

    async def clause(
        self, *, caller: Caller, key: str, lang: str, as_of: date | None
    ) -> dict[str, Any]:
        clause: dict[str, Any] = await self.call(
            "GET",
            f"/v1/clauses/{key}",
            caller=caller,
            request_id=caller.request_id,
            query=_present(lang=lang, as_of=as_of),
        )
        return clause

    async def subtree(
        self, *, caller: Caller, key: str, lang: str, as_of: date | None
    ) -> list[dict[str, Any]]:
        answer = await self.call(
            "GET",
            f"/v1/clauses/{key}/subtree",
            caller=caller,
            request_id=caller.request_id,
            query=_present(lang=lang, as_of=as_of),
        )
        return list(answer)

    async def documents(
        self, *, caller: Caller, limit: int, offset: int, as_of: date | None
    ) -> dict[str, Any]:
        listing: dict[str, Any] = await self.call(
            "GET",
            "/v1/documents",
            caller=caller,
            request_id=caller.request_id,
            query=_present(limit=limit, offset=offset, as_of=as_of),
        )
        return listing

    async def document(self, *, caller: Caller, slug: str, as_of: date | None) -> dict[str, Any]:
        document: dict[str, Any] = await self.call(
            "GET",
            f"/v1/documents/{slug}",
            caller=caller,
            request_id=caller.request_id,
            query=_present(as_of=as_of),
        )
        return document

    async def call(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        caller: Caller | None = None,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        """One call, retried once if this server's own credential was replaced."""
        presented = self.credential.read()
        response = await self._send(
            method, path, presented, request_id=request_id, caller=caller, body=body, query=query
        )

        if response.status_code == 401:
            # The instance may have provisioned a new credential while this
            # server was running. Read the file again, and try once more only if
            # it actually changed: presenting the same credential twice would
            # buy a second refusal and nothing else.
            replaced = self.credential.reread()
            if replaced != presented:
                response = await self._send(
                    method,
                    path,
                    replaced,
                    request_id=request_id,
                    caller=caller,
                    body=body,
                    query=query,
                )

        if response.status_code >= 400:
            raise _refusal(response)
        return response.json()

    async def _send(
        self,
        method: str,
        path: str,
        presented: str,
        *,
        request_id: str,
        caller: Caller | None,
        body: dict[str, Any] | None,
        query: dict[str, str] | None,
    ) -> httpx2.Response:
        headers = {"Authorization": f"Bearer {presented}", REQUEST_ID: request_id}
        if caller is not None:
            headers[ON_BEHALF_OF_USER] = caller.user_id
            headers[ON_BEHALF_OF_TOKEN] = caller.pat_id
        try:
            return await self._client.request(
                method, path, headers=headers, json=body, params=query
            )
        except httpx2.RequestError as failed:
            raise Unreachable(
                f"the DPOLens API at {self.base_url} could not be reached"
            ) from failed


def _present(**values: object) -> dict[str, str]:
    """Only the parameters that were given, so a default stays the API's to decide."""
    given = {}
    for name, value in values.items():
        if value is None:
            continue
        given[name] = value.isoformat() if isinstance(value, date) else str(value)
    return given


def _refusal(response: httpx2.Response) -> Refused:
    """Turn a problem document into something a caller can be told about."""
    problem: dict[str, Any] = {}
    if response.headers.get("content-type", "").startswith(PROBLEM_JSON):
        try:
            problem = response.json()
        except ValueError:
            problem = {}

    after = response.headers.get("Retry-After", "")
    return Refused(
        status=response.status_code,
        type=str(problem.get("type", "")),
        title=str(problem.get("title", f"HTTP {response.status_code}")),
        detail=str(problem.get("detail", "")),
        retry_after=int(after) if after.isdigit() else None,
    )
