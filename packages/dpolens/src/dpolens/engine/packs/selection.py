"""Which laws apply to this organisation, and so what a search covers.

Search covers the selected laws and the organisation's own policies, and nothing
else: a caller can narrow a search to some of the selected laws, never reach
another. Until an administrator chooses, nothing is searched. A selection can be
changed but never emptied, so once somebody has chosen, some law always applies.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from dpolens.engine.logs.governance import LAWS_SELECTED, Actor, record
from dpolens.engine.logs.models import GovernanceEntry
from dpolens.engine.packs.models import Pack, SelectedLaw

NEW_FOR = timedelta(days=30)
"""How long a law that arrived after the laws were chosen is marked as new."""


def _joined(slugs: Sequence[str]) -> str:
    return slugs[0] if len(slugs) == 1 else f"{', '.join(slugs[:-1])} and {slugs[-1]}"


class UnknownLaw(Exception):
    """A slug that names no loaded law."""

    def __init__(self, unknown: Sequence[str], choices: Sequence[str]) -> None:
        self.unknown = tuple(unknown)
        self.choices = tuple(choices)
        super().__init__(
            f"no law here is called {', '.join(self.unknown)}. "
            f"The laws to choose from are: {', '.join(self.choices) or 'none'}"
        )


class NotSelected(Exception):
    """A loaded law the organisation has not selected, which nothing reaches."""

    def __init__(self, slugs: Sequence[str]) -> None:
        self.slugs = tuple(slugs)
        if len(self.slugs) == 1:
            said = f"{self.slugs[0]} is loaded here but is not one of this organisation's laws"
            add = "it"
        else:
            said = f"{_joined(self.slugs)} are loaded here but are not this organisation's laws"
            add = "them"
        super().__init__(f"{said}. An administrator can add {add} in Selected laws.")


class NothingSelected(Exception):
    """Nobody has chosen which laws apply, so there is nothing to search yet."""

    def __init__(self) -> None:
        super().__init__(
            "nobody has chosen which laws apply to this organisation yet, so nothing is "
            "searched. An administrator chooses them at the first sign-in to the dashboard, "
            "or with: dpolens init"
        )


class EmptySelection(Exception):
    """A selection names at least one law."""


@dataclass(frozen=True)
class Scope:
    """The laws one search covers, against the laws loaded here."""

    laws: tuple[str, ...]
    loaded: tuple[str, ...]

    @property
    def narrowed(self) -> bool:
        """Whether a loaded law is left out, so search has to filter at all."""
        return set(self.laws) != set(self.loaded)


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


def in_selection(session: Session, pack_slug: str | None) -> bool:
    """Whether a document is the organisation's: its own policies always are."""
    return pack_slug is None or pack_slug in (selected_laws(session) or ())


def require_selected(session: Session, pack_slug: str | None) -> None:
    """Refuse a law the organisation has not selected, as anything but the dashboard is."""
    if pack_slug is None:
        return
    selected = selected_laws(session)
    if selected is None:
        raise NothingSelected()
    if pack_slug not in selected:
        raise NotSelected([pack_slug])


def scope_for(session: Session, laws: Sequence[str] | None = None) -> Scope:
    """What a search covers: the selected laws, or the ones of them it names.

    An instance with no law loaded has nothing to choose, so it searches its
    policies alone rather than refusing for ever.
    """
    loaded = tuple(pack.slug for pack in loaded_laws(session))
    selected = selected_laws(session)
    if selected is None:
        if loaded:
            raise NothingSelected()
        selected = []
    asked = tuple(dict.fromkeys(laws)) if laws else tuple(selected)
    unknown = [slug for slug in asked if slug not in loaded]
    if unknown:
        raise UnknownLaw(unknown, selected)
    outside = [slug for slug in asked if slug not in selected]
    if outside:
        raise NotSelected(outside)
    return Scope(laws=asked, loaded=loaded)


def law_alone(session: Session, slug: str) -> Scope:
    """One loaded law by itself, whatever is selected, which is what an eval run searches."""
    loaded = tuple(pack.slug for pack in loaded_laws(session))
    if slug not in loaded:
        raise UnknownLaw([slug], loaded)
    return Scope(laws=(slug,), loaded=loaded)


def newly_arrived(session: Session, *, now: datetime | None = None) -> frozenset[str]:
    """The laws loaded after the laws were first chosen, within the last 30 days.

    Every law in the image is loaded at first start, before anybody can choose, so
    a law that arrives later came with an upgrade or a `pack load`, and whoever
    chose has not seen it.
    """
    first = session.scalar(
        select(func.min(GovernanceEntry.occurred_at)).where(GovernanceEntry.action == LAWS_SELECTED)
    )
    if first is None:
        return frozenset()
    since = max(first, (now or datetime.now(UTC)) - NEW_FOR)
    return frozenset(session.scalars(select(Pack.slug).where(Pack.loaded_at > since)))


def select_laws(session: Session, slugs: Sequence[str], *, actor: Actor) -> list[str]:
    """Make these exactly the selected laws, and write the change to the governance log."""
    wanted = sorted(set(slugs))
    if not wanted:
        raise EmptySelection("name at least one law")

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
