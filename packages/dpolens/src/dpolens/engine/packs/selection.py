"""Which laws apply to this organisation, and so what a search covers.

Search covers the selected laws and the organisation's own policies. A caller can
name other laws, and what comes back from those is marked as outside the selection.

Until an administrator chooses, every loaded law counts as selected, so a new
instance answers from everything it holds. A selection can be changed or cleared
but never emptied, which keeps "nobody has chosen" meaning one thing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dpolens.engine.logs.governance import (
    LAWS_SELECTED,
    LAWS_SELECTION_CLEARED,
    Actor,
    record,
)
from dpolens.engine.packs.models import Pack, SelectedLaw


class UnknownLaw(Exception):
    """A slug that names no loaded law."""

    def __init__(self, unknown: Sequence[str], loaded: Sequence[str]) -> None:
        self.unknown = tuple(unknown)
        self.loaded = tuple(loaded)
        super().__init__(
            f"no law loaded here is called {', '.join(self.unknown)}. "
            f"The loaded laws are: {', '.join(self.loaded) or 'none'}"
        )


class EmptySelection(Exception):
    """A selection names at least one law; clearing it is how to go back to all."""


@dataclass(frozen=True)
class Scope:
    """The laws one search covers, against the laws the organisation selected."""

    laws: tuple[str, ...]
    selected: tuple[str, ...]
    loaded: tuple[str, ...]

    @property
    def narrowed(self) -> bool:
        """Whether a loaded law is left out, so search has to filter at all."""
        return set(self.laws) != set(self.loaded)

    @property
    def outside_selection(self) -> bool:
        """Whether this search reaches a law the organisation did not select."""
        return not set(self.laws) <= set(self.selected)

    def is_selected(self, pack_slug: str | None) -> bool:
        """An organisation's own policy has no pack, and is always in scope."""
        return pack_slug is None or pack_slug in self.selected


def loaded_laws(session: Session) -> list[Pack]:
    return list(session.scalars(select(Pack).order_by(Pack.slug)))


def selected_laws(session: Session) -> list[str] | None:
    """The selected laws by slug, or None when nobody has chosen yet."""
    slugs = list(
        session.scalars(
            select(Pack.slug).join(SelectedLaw, SelectedLaw.pack_id == Pack.id).order_by(Pack.slug)
        )
    )
    return slugs or None


def scope_for(session: Session, laws: Sequence[str] | None = None) -> Scope:
    """What a search covers: the laws it names, or else the selected ones."""
    loaded = tuple(pack.slug for pack in loaded_laws(session))
    selected = tuple(selected_laws(session) or loaded)
    asked = tuple(dict.fromkeys(laws)) if laws else selected
    unknown = [slug for slug in asked if slug not in loaded]
    if unknown:
        raise UnknownLaw(unknown, loaded)
    return Scope(laws=asked, selected=selected, loaded=loaded)


def select_laws(session: Session, slugs: Sequence[str], *, actor: Actor) -> list[str]:
    """Make these exactly the selected laws, and write the change to the governance log."""
    wanted = sorted(set(slugs))
    if not wanted:
        raise EmptySelection("name at least one law, or clear the selection to search them all")

    packs = {pack.slug: pack for pack in loaded_laws(session)}
    unknown = [slug for slug in wanted if slug not in packs]
    if unknown:
        raise UnknownLaw(unknown, sorted(packs))

    before = selected_laws(session)
    session.execute(delete(SelectedLaw))
    session.add_all(SelectedLaw(pack_id=packs[slug].id) for slug in wanted)
    session.flush()
    record(
        session,
        actor=actor,
        action=LAWS_SELECTED,
        target_type="selected_laws",
        target_id="instance",
        details={"before": before, "after": wanted},
    )
    return wanted


def clear_selection(session: Session, *, actor: Actor) -> None:
    """Go back to every loaded law. Writes to the governance log only if a selection existed."""
    before = selected_laws(session)
    if before is None:
        return
    session.execute(delete(SelectedLaw))
    record(
        session,
        actor=actor,
        action=LAWS_SELECTION_CLEARED,
        target_type="selected_laws",
        target_id="instance",
        details={"before": before},
    )
