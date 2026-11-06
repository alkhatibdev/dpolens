"""A clause as the API returns it, with the days it applies and an amendment's words."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from dpolens.api.schemas import ClauseInContext
from dpolens.engine.documents.read import ClauseDetail, ClauseView, Coming

CLAUSE = ClauseView(
    key="testlaw:art-6:para-1",
    clause_type="paragraph",
    label="1.",
    heading=None,
    text="Processing shall be lawful only if and to the extent that consent has been given.",
    lang="en",
    is_authoritative=True,
    is_normative=True,
    depth=1,
    document_title="Test Data Protection Law",
    document_slug="testlaw",
    version_label="2026.1",
    effective_date=date(2026, 1, 1),
    in_force_from=date(2026, 1, 1),
    in_force_until=date(2027, 1, 17),
    coming=Coming(
        heading=None,
        text="Processing shall be lawful only where a ground set out in the Schedule applies.",
        in_force_from=date(2027, 1, 17),
        dates_set_by="Amending Act 2026, section 4",
    ),
    pack_slug="testlaw",
    law_short_name="TESTLAW",
    jurisdiction="Example Republic",
)


def test_a_clause_carries_its_days_and_the_words_coming() -> None:
    detail = ClauseDetail(clause=CLAUSE, breadcrumb=(), children=(), cross_references=())

    body = ClauseInContext.of(detail, in_selected_laws=True).model_dump(mode="json")["clause"]

    assert (body["in_force"], body["in_force_from"], body["in_force_until"]) == (
        True,
        "2026-01-01",
        "2027-01-17",
    )
    assert body["coming"] == {
        "heading": None,
        "text": "Processing shall be lawful only where a ground set out in the Schedule applies.",
        "in_force_from": "2027-01-17",
        "dates_set_by": "Amending Act 2026, section 4",
    }
    assert body["law_short_name"] == "TESTLAW"


def test_a_provision_with_no_day_set_has_none() -> None:
    pending = replace(CLAUSE, in_force=False, in_force_from=None, in_force_until=None, coming=None)
    detail = ClauseDetail(clause=pending, breadcrumb=(), children=(), cross_references=())

    body = ClauseInContext.of(detail, in_selected_laws=True).model_dump(mode="json")["clause"]

    assert (body["in_force"], body["in_force_from"], body["coming"]) == (False, None, None)
