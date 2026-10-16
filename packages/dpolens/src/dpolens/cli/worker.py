"""Running the worker: the jobs that should not run inside a request."""

from __future__ import annotations

from dpolens.engine.jobs import run_worker
from dpolens.settings import load_settings
from dpolens.telemetry import configure


def run() -> None:
    """Run background jobs: embedding published policies, and the daily purge."""
    configure()
    run_worker(load_settings())
