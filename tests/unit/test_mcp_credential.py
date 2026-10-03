"""Reading the credential this server presents, and reading it again.

It is one file holding one secret, which is why the cases worth writing down are
the unhappy ones: no file yet, an empty file, a file that changed under us.
"""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from dpolens_mcp.credential import Credential, MissingCredential
from dpolens_stub import SURFACE

pytestmark = pytest.mark.anyio


class TestReadingIt:
    def test_the_credential_is_what_the_file_holds(self, surface_file: Path) -> None:
        assert Credential(surface_file).read() == SURFACE

    def test_a_trailing_newline_is_not_part_of_the_credential(self, tmp_path: Path) -> None:
        """A file written by an operator or by an editor usually ends in one."""
        path = tmp_path / "token"
        path.write_text(f"  {SURFACE}  \n\n", encoding="utf-8")

        assert Credential(path).read() == SURFACE

    def test_it_is_read_once_and_kept(self, surface_file: Path) -> None:
        """Every call presents it, so every call should not read a file."""
        credential = Credential(surface_file)
        assert credential.read() == SURFACE

        surface_file.write_text("dpol_somethingelse", encoding="utf-8")

        assert credential.read() == SURFACE

    def test_reading_again_picks_up_what_changed(self, surface_file: Path) -> None:
        credential = Credential(surface_file)
        credential.read()
        surface_file.write_text("dpol_replaced", encoding="utf-8")

        assert credential.reread() == "dpol_replaced"
        assert credential.read() == "dpol_replaced"


class TestWhenThereIsNoneToRead:
    def test_a_file_that_is_not_there_says_where_it_was_looked_for(self, tmp_path: Path) -> None:
        missing = tmp_path / "nowhere" / "token"

        with pytest.raises(MissingCredential, match=str(missing)):
            Credential(missing).read()

    def test_the_message_says_what_creates_one(self, tmp_path: Path) -> None:
        """Read by whoever is running a container that will not start."""
        credential = Credential(tmp_path / "token")

        with pytest.raises(MissingCredential, match="ensure-surface"):
            anyio.run(lambda: credential.wait(timeout=0.1, interval=0.05))

    @pytest.mark.parametrize("content", ["", "\n", "   \t\n"], ids=["empty", "newline", "spaces"])
    def test_a_file_with_nothing_in_it_is_not_a_credential(
        self, tmp_path: Path, content: str
    ) -> None:
        """Written but not yet filled is the state a first start passes through."""
        path = tmp_path / "token"
        path.write_text(content, encoding="utf-8")

        with pytest.raises(MissingCredential, match="is empty"):
            Credential(path).read()

    def test_a_directory_where_the_file_should_be_is_reported_not_crashed(
        self, tmp_path: Path
    ) -> None:
        """A volume mounted at the file's path instead of its parent does this."""
        path = tmp_path / "token"
        path.mkdir()

        with pytest.raises(MissingCredential, match="cannot read"):
            Credential(path).read()


class TestWaitingForIt:
    async def test_it_returns_as_soon_as_the_file_has_something(self, tmp_path: Path) -> None:
        path = tmp_path / "token"

        async def write_it() -> None:
            await anyio.sleep(0.05)
            path.write_text("", encoding="utf-8")
            await anyio.sleep(0.05)
            path.write_text(SURFACE, encoding="utf-8")

        async with anyio.create_task_group() as work:
            work.start_soon(write_it)
            held = await credential_wait(path)

        assert held == SURFACE

    async def test_a_credential_already_there_is_not_waited_for(self, surface_file: Path) -> None:
        started = anyio.current_time()

        held = await Credential(surface_file).wait(timeout=5, interval=1)

        assert held == SURFACE
        assert anyio.current_time() - started < 0.5


async def credential_wait(path: Path) -> str:
    return await Credential(path).wait(timeout=2, interval=0.02)
