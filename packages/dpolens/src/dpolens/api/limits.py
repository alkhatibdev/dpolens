"""A per-token rate limit, a sign-in throttle, a limit on the size of a request body, and
on how many requests run at once.

The purpose is stopping a runaway integration from eating the instance, not
enforcing a quota anybody has paid for, so an approximate limit inside each
worker is worth more than an exact one that puts a database write in front of
every request. An instance running four workers allows four times the configured
number, which the documentation says rather than hides.

The state is bounded, because a dictionary keyed by anything a caller controls is
a dictionary a caller can grow. Authentication happens first, so the keys here
are tokens that exist.
"""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dpolens.api import problems

CAPACITY = 4096
"""How many tokens the limiter remembers before forgetting the least recent."""


@dataclass
class _Bucket:
    left: float
    at: float


class RateLimiter:
    """A token bucket per key, refilling steadily over a minute."""

    def __init__(self, per_minute: int, capacity: int = CAPACITY) -> None:
        self.per_minute = per_minute
        self.capacity = capacity
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = threading.Lock()

    def consume(self, key: str) -> int | None:
        """Spend one request. Returns seconds to wait when there is nothing left."""
        rate = self.per_minute / 60
        now = monotonic()

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(left=float(self.per_minute), at=now)
                self._buckets[key] = bucket
                if len(self._buckets) > self.capacity:
                    self._buckets.popitem(last=False)
            else:
                self._buckets.move_to_end(key)
                bucket.left = min(self.per_minute, bucket.left + (now - bucket.at) * rate)
                bucket.at = now

            if bucket.left < 1:
                return max(1, int((1 - bucket.left) / rate))
            bucket.left -= 1
            return None

    def remembered(self) -> int:
        with self._lock:
            return len(self._buckets)


SIGN_IN_FAILURES = 5
SIGN_IN_WINDOW = 15 * 60
"""Five wrong passwords for one address in fifteen minutes, then a wait."""


class SignInThrottle:
    """Failed sign-ins per email address, so guessing one account's password is slow.

    Every address is counted, those that match no account included, so being made
    to wait says nothing about whether an account exists. The keys here are
    whatever a caller types, unlike the token limiter's, which is why the bound
    on how many are remembered matters.
    """

    def __init__(
        self,
        failures: int = SIGN_IN_FAILURES,
        window: float = SIGN_IN_WINDOW,
        capacity: int = CAPACITY,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.failures = failures
        self.window = window
        self.capacity = capacity
        self._clock = clock
        self._seen: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def wait(self, key: str) -> int | None:
        """Seconds until `key` may try again, or None when it may try now."""
        now = self._clock()
        with self._lock:
            attempts = self._recent(key, now)
            if len(attempts) < self.failures:
                return None
            return max(1, int(attempts[0] + self.window - now) + 1)

    def failed(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            attempts = self._recent(key, now)
            attempts.append(now)
            self._seen[key] = attempts
            self._seen.move_to_end(key)
            if len(self._seen) > self.capacity:
                self._seen.popitem(last=False)

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._seen.pop(key, None)

    def _recent(self, key: str, now: float) -> deque[float]:
        attempts = self._seen.get(key, deque())
        while attempts and attempts[0] <= now - self.window:
            attempts.popleft()
        return attempts


class _TooLarge(Exception):
    pass


class BodyLimit:
    """Refuses a request body larger than `limit` bytes, with `/problems/too-large`.

    A route reads its whole body before it runs, and before the caller is authenticated, so
    the limit sits in front of the application. A declared length over the limit is refused
    before a byte is read. A body sent without one is counted as it arrives and cut off at the
    limit, whatever the application then makes of the part it received.
    """

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        def refusal() -> Response:
            return problems.render(Request(scope), problems.too_large(self.limit))

        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > self.limit:
            await refusal()(scope, receive, send)
            return

        seen = 0
        over = False
        started = False

        async def counted() -> Message:
            nonlocal seen, over
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    over = True
                    raise _TooLarge
            return message

        async def answered(message: Message) -> None:
            nonlocal started
            if over:
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await refusal()(scope, receive, send)
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counted, answered)
        except _TooLarge:
            if not started:
                await refusal()(scope, receive, send)


CONNECTIONS_PER_REQUEST = 2
"""The most database connections one request holds at once: its own, and the one that
writes a record which has to outlive the request failing, such as its question in the
query log."""

HEALTH = frozenset({"/live", "/ready"})


class InFlight:
    """Runs at most `limit` requests at once, and keeps the rest waiting their turn.

    A request holds its connection while it waits for a second one, so once every
    connection is held by a request doing the same, none of them can go on until the
    pool's timeout fails them all. Running no more requests than the pool can give two
    connections each makes that impossible. A request waiting here holds neither a
    connection nor a thread. Health checks go straight through, so a busy instance
    still answers that it is alive and ready.
    """

    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.turns = asyncio.Semaphore(limit)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in HEALTH:
            await self.app(scope, receive, send)
            return
        async with self.turns:
            await self.app(scope, receive, send)
