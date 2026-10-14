"""A per-token rate limit, and a sign-in throttle, held in the worker.

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

import threading
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

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
