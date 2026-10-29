"""How many threads building the index takes: what the container may use, not the machine."""

from __future__ import annotations

import os
from pathlib import Path

from dpolens.engine.embedding.encode import usable_cpus


def limit(tmp_path: Path, written: str) -> Path:
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text(written, encoding="utf-8")
    return cpu_max


def test_a_limit_is_rounded_up(tmp_path: Path) -> None:
    assert usable_cpus(limit(tmp_path, "250000 100000\n")) == 3


def test_a_limit_under_one_processor_is_one(tmp_path: Path) -> None:
    assert usable_cpus(limit(tmp_path, "50000 100000\n")) == 1


def test_with_no_limit_it_is_every_processor_it_may_run_on(tmp_path: Path) -> None:
    assert usable_cpus(limit(tmp_path, "max 100000\n")) == os.process_cpu_count()


def test_outside_a_container_it_is_every_processor_it_may_run_on(tmp_path: Path) -> None:
    assert usable_cpus(tmp_path / "missing") == os.process_cpu_count()
