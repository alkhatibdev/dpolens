"""The clause command says when a text applies the way a citation says it."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from dpolens.cli.clause import in_force
from dpolens.engine.documents.read import ClauseView

CLAUSE = ClauseView(
    key="dpdp:sec-8:para-6",
    clause_type="paragraph",
    label="(6)",
    heading=None,
    text="In the event of a personal data breach, the Data Fiduciary shall give the Board notice.",
    lang="en",
    is_authoritative=True,
    is_normative=True,
    depth=1,
    document_title="The Digital Personal Data Protection Act, 2023",
    document_slug="dpdp",
    version_label="2026.1",
    effective_date=date(2025, 11, 13),
    in_force_from=date(2025, 11, 13),
)
TODAY = date(2026, 11, 6)


@pytest.mark.parametrize(
    ("clause", "said"),
    [
        (CLAUSE, "in force since 2025-11-13"),
        (
            replace(CLAUSE, in_force_until=date(2027, 5, 13)),
            "in force since 2025-11-13, until 2027-05-13",
        ),
        (
            replace(CLAUSE, in_force=False, in_force_from=date(2027, 5, 13)),
            "in force from 2027-05-13",
        ),
        (replace(CLAUSE, in_force=False, in_force_from=None), "not in force yet: no date set"),
        (
            replace(CLAUSE, in_force=False, in_force_until=date(2026, 6, 1)),
            "no longer in force since 2026-06-01",
        ),
    ],
)
def test_it_says_when_the_text_applies(clause: ClauseView, said: str) -> None:
    assert in_force(clause, TODAY) == said
