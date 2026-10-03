"""The credential this server presents, read from a file the instance writes.

This server cannot reach the database, so it cannot mint anything for itself.
The instance mints one credential for it and writes it to a file both can see,
and this server waits for that file rather than for the API to report itself
healthy, because the file is what it needs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import anyio

logger = logging.getLogger(__name__)


class MissingCredential(Exception):
    """There is no credential to present."""


class Credential:
    """One credential, read from disk and read again when it may have changed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._held: str | None = None

    def read(self) -> str:
        """The credential, read from the file the first time it is needed."""
        if self._held is None:
            self._held = self._from_disk()
        return self._held

    def reread(self) -> str:
        """Read the file again, for when the instance may have replaced it.

        An operator who revokes this server's credential and provisions another
        one should not have to restart this container as well.
        """
        self._held = self._from_disk()
        return self._held

    async def wait(self, *, timeout: float, interval: float = 0.5) -> str:
        """Wait for the file to hold a credential, and return it."""
        with anyio.move_on_after(timeout):
            while True:
                try:
                    return self.reread()
                except MissingCredential:
                    await anyio.sleep(interval)
        raise MissingCredential(
            f"no credential at {self.path} after {timeout:g} seconds. The instance writes it "
            "as it starts: `dpolens token ensure-surface` creates one, and this server has to "
            "be able to read the file it writes."
        )

    def _from_disk(self) -> str:
        try:
            content = self.path.read_text(encoding="utf-8")
        except OSError as unreadable:
            raise MissingCredential(f"cannot read {self.path}: {unreadable}") from unreadable
        if not content.strip():
            raise MissingCredential(f"{self.path} is empty")
        return content.strip()
