"""Measure what reaching DPOLens over HTTP costs, against calling it directly.

Every surface talks to the API rather than importing the engine, which buys a
network hop. This measures that hop on loopback, so the cost is a number rather
than an assumption.

Needs a migrated database and a cached model, the same as running the server:

    DPOLENS_DATABASE_URL=postgresql://... uv run python scripts/measure_hop.py

It starts a server of its own on a spare port, warms it up, and reports the
distribution. `/live` is the endpoint on purpose: it touches nothing, so what is
left is the hop and the framework around it.
"""

from __future__ import annotations

import socket
import statistics
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager

import httpx

REQUESTS = 300
WARMUP = 30


def spare_port() -> int:
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def server(port: int) -> Iterator[None]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "dpolens.api.app:create_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ]
    )
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                httpx.get(f"http://127.0.0.1:{port}/live", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            raise RuntimeError("the server did not start. Is the database migrated?")
        yield
    finally:
        process.terminate()
        process.wait(timeout=20)


def timings(client: httpx.Client, url: str, count: int) -> list[float]:
    measured = []
    for _ in range(count):
        started = time.perf_counter()
        client.get(url)
        measured.append((time.perf_counter() - started) * 1000)
    return measured


def main() -> int:
    port = spare_port()
    with server(port), httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
        timings(client, "/live", WARMUP)
        over_http = timings(client, "/live", REQUESTS)

    ordered = sorted(over_http)
    print(f"{REQUESTS} requests to /live over loopback, in milliseconds:")
    print(f"  median {statistics.median(ordered):.2f}")
    print(f"  mean   {statistics.fmean(ordered):.2f}")
    print(f"  p95    {ordered[int(0.95 * len(ordered))]:.2f}")
    print(f"  worst  {ordered[-1]:.2f}")
    print()
    print(
        "For comparison, one search costs about 110 ms of CPU, almost all of it "
        "embedding the question."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
