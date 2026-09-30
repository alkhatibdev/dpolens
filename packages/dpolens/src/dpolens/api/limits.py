"""A per-token rate limit held in the worker.

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
from collections import OrderedDict
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
