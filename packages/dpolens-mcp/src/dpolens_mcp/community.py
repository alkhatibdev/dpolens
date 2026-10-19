"""Answering everyone without a token, as a community version does.

Every call is made as the Community account the instance names in a file, so the
questions log records nobody. Three limits, kept in memory and never written down,
stop one caller spending everyone's allowance: one for each address, a larger one
shared by each range that carries many people's calls, such as an assistant
platform's servers, and one for everybody together.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from dpolens_mcp.api import Caller
from dpolens_mcp.settings import Settings

POLL_SECONDS = 0.5
FORGET_AFTER = 10_000
"""How many addresses to remember before forgetting the ones that are full again."""


class NoCommunityAccount(Exception):
    """The instance has not named the Community account this server answers as."""


@dataclass(frozen=True)
class Community:
    """The account and token every call on a community version is made as."""

    user_id: str
    token_id: str

    @classmethod
    def read(cls, path: Path) -> Community:
        named = json.loads(path.read_text(encoding="utf-8"))
        return cls(user_id=str(named["user"]), token_id=str(named["token"]))

    def caller(self) -> Caller:
        return Caller(user_id=self.user_id, pat_id=self.token_id, request_id=str(uuid.uuid4()))


async def wait_for(path: Path, *, timeout: float) -> Community:
    """The Community account, once the instance has written its file."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return Community.read(path)
        except (FileNotFoundError, ValueError, KeyError) as missing:
            if time.monotonic() >= deadline:
                raise NoCommunityAccount(
                    f"no Community account named in {path}. The API writes it as it starts, "
                    "when DPOLENS_COMMUNITY is true"
                ) from missing
        await asyncio.sleep(POLL_SECONDS)


@dataclass
class _Bucket:
    left: float
    at: float


class Allowance:
    """Calls a minute for each key, refilled continuously, in this process's memory."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def take(self, key: str, now: float | None = None) -> int | None:
        """Spend one call, or say how many seconds until there is one."""
        now = time.monotonic() if now is None else now
        rate = self.per_minute / 60
        with self._lock:
            if len(self._buckets) > FORGET_AFTER:
                self._forget_full(now, rate)
            bucket = self._buckets.setdefault(key, _Bucket(left=float(self.per_minute), at=now))
            bucket.left = min(self.per_minute, bucket.left + (now - bucket.at) * rate)
            bucket.at = now
            if bucket.left >= 1:
                bucket.left -= 1
                return None
            return max(1, math.ceil((1 - bucket.left) / rate))

    def _forget_full(self, now: float, rate: float) -> None:
        for key, bucket in list(self._buckets.items()):
            if bucket.left + (now - bucket.at) * rate >= self.per_minute:
                del self._buckets[key]


class Limiting:
    """The three limits, in front of the MCP endpoint. Nothing else is counted."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.path = settings.path
        self.header = settings.client_address_header
        self.ranges = list(settings.shared_ranges)
        self.addresses = Allowance(settings.per_address_per_minute)
        self.shared = Allowance(settings.per_range_per_minute)
        self.everybody = Allowance(settings.overall_per_minute)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].rstrip("/") != self.path.rstrip("/"):
            await self.app(scope, receive, send)
            return
        address = self._address(scope)
        wait = self._spend(address)
        if wait is not None:
            refused = JSONResponse(
                {"error": f"too many questions from here. Ask again in {wait} seconds"},
                status_code=429,
                headers={"Retry-After": str(wait)},
            )
            await refused(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _address(self, scope: Scope) -> str:
        if self.header:
            given = Headers(scope=scope).get(self.header)
            if given:
                return given.split(",")[0].strip()
        client = scope.get("client")
        return str(client[0]) if client else "unknown"

    def _spend(self, address: str) -> int | None:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            parsed = None
        shared = next(
            (str(net) for net in self.ranges if parsed is not None and parsed in net), None
        )
        own = self.shared.take(shared) if shared else self.addresses.take(address)
        if own is not None:
            return own
        return self.everybody.take("everybody")
