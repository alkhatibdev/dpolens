"""The rate limiter, including the part that stops it growing without limit."""

from __future__ import annotations

import threading

from dpolens.api.limits import RateLimiter


def test_spends_the_quota_then_says_when_to_return() -> None:
    limiter = RateLimiter(per_minute=3)

    assert [limiter.consume("one") for _ in range(3)] == [None, None, None]

    retry_after = limiter.consume("one")
    assert retry_after is not None
    assert 1 <= retry_after <= 60


def test_each_key_has_its_own_quota() -> None:
    """One runaway client must not throttle everybody else."""
    limiter = RateLimiter(per_minute=1)

    assert limiter.consume("one") is None
    assert limiter.consume("one") is not None
    assert limiter.consume("two") is None


def test_it_refills_over_time() -> None:
    """Checked by moving the clock rather than by sleeping through a minute."""
    limiter = RateLimiter(per_minute=60)
    assert limiter.consume("one") is None
    bucket = limiter._buckets["one"]
    bucket.left = 0

    bucket.at -= 2  # two seconds ago, and the bucket refills one per second
    assert limiter.consume("one") is None


def test_it_never_refills_past_the_quota() -> None:
    limiter = RateLimiter(per_minute=5)
    limiter.consume("one")
    limiter._buckets["one"].at -= 3600

    assert [limiter.consume("one") for _ in range(5)] == [None] * 5
    assert limiter.consume("one") is not None


def test_it_forgets_the_least_recent_key_rather_than_growing() -> None:
    """A dictionary keyed by anything a caller controls is one a caller can grow."""
    limiter = RateLimiter(per_minute=10, capacity=4)

    for number in range(10):
        limiter.consume(f"token-{number}")

    assert limiter.remembered() == 4


def test_the_key_still_in_use_is_the_one_kept() -> None:
    limiter = RateLimiter(per_minute=10, capacity=2)
    limiter.consume("busy")
    limiter.consume("idle")
    limiter.consume("busy")

    limiter.consume("new")

    assert "busy" in limiter._buckets
    assert "idle" not in limiter._buckets


def test_it_counts_correctly_when_several_threads_share_a_key() -> None:
    """Handlers run in a thread pool, so the counter needs its lock."""
    limiter = RateLimiter(per_minute=100)
    refused: list[int | None] = []

    def spend() -> None:
        for _ in range(10):
            refused.append(limiter.consume("shared"))

    threads = [threading.Thread(target=spend) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(refused) == 100
    assert refused.count(None) == 100
    assert limiter.consume("shared") is not None
