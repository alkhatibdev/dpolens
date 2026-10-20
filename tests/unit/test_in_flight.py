"""How many requests run at once, which has to stay within what the database pool can
give two connections each."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dpolens.api.app import create_app
from dpolens.api.limits import CONNECTIONS_PER_REQUEST, InFlight
from dpolens.engine.session import POOL_OVERFLOW, POOL_SIZE
from dpolens.settings import Settings

LIMIT = 3


class Running:
    """How many requests are inside the route now, and the most there ever were."""

    def __init__(self) -> None:
        self.now = 0
        self.most = 0
        self._lock = threading.Lock()

    def enter(self) -> None:
        with self._lock:
            self.now += 1
            self.most = max(self.most, self.now)

    def leave(self) -> None:
        with self._lock:
            self.now -= 1


def client(running: Running, gate: threading.Event | None = None) -> TestClient:
    app = FastAPI()
    app.add_middleware(InFlight, limit=LIMIT)

    @app.get("/work")
    def work() -> dict[str, str]:
        running.enter()
        if gate is None:
            time.sleep(0.05)
        else:
            gate.wait(5)
        running.leave()
        return {}

    @app.get("/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    return TestClient(app)


def test_no_more_requests_run_at_once_than_the_limit() -> None:
    running = Running()

    with client(running) as limited, ThreadPoolExecutor(max_workers=12) as pool:
        answered = list(pool.map(lambda _: limited.get("/work").status_code, range(12)))

    assert answered == [200] * 12
    assert running.most == LIMIT


def test_a_health_check_never_waits_for_a_turn() -> None:
    running = Running()
    gate = threading.Event()

    with client(running, gate) as limited, ThreadPoolExecutor(max_workers=LIMIT) as pool:
        busy = [pool.submit(limited.get, "/work") for _ in range(LIMIT)]
        deadline = time.monotonic() + 5
        while running.now < LIMIT and time.monotonic() < deadline:
            time.sleep(0.01)

        assert running.now == LIMIT
        assert limited.get("/live").status_code == 200

        gate.set()
        assert [request.result().status_code for request in busy] == [200] * LIMIT


def test_the_api_runs_no_more_requests_than_its_pool_can_give_two_connections_each() -> None:
    app = create_app(Settings.model_validate({"database_url": "postgresql://unused@localhost/x"}))

    # Starlette types a middleware's class as a factory, and its arguments as anything.
    (limit,) = [
        entry.kwargs["limit"]
        for entry in app.user_middleware
        if cast(object, entry.cls) is InFlight
    ]

    assert isinstance(limit, int)
    assert limit >= 1
    assert limit * CONNECTIONS_PER_REQUEST <= POOL_SIZE + POOL_OVERFLOW
