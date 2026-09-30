"""Two probes, answering two different questions.

`/live` says the process is running and touches nothing outside it, because a
liveness check that reaches the database restarts a healthy process whenever the
database blinks.

`/ready` says the database is reachable, which is the dependency this instance
can lose and recover. The embedding model and the governance log privileges are
startup conditions: a process that fails them never serves, so a probe reporting
them forever tells an orchestrator nothing it can act on.

Neither carries a version or any configuration, because an unauthenticated
endpoint is the one thing anybody can always reach.
"""

from __future__ import annotations

from fastapi import APIRouter

from dpolens.api import problems
from dpolens.api.dependencies import Opened
from dpolens.engine.session import ping

router = APIRouter(tags=["health"])


@router.get("/live", summary="Is the process running")
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/ready", summary="Can the process serve requests")
def ready(opened: Opened) -> dict[str, str]:
    try:
        ping(opened)
    # Any failure at all means not ready, including one nobody has thought of.
    except Exception as unreachable:
        raise problems.not_ready("the database is not reachable") from unreachable
    return {"status": "ready"}
