"""Links are made from what the text states, and only where the target exists."""

from __future__ import annotations

from dpolens.engine.documents.references import Reference, extract, resolve


def test_finds_an_article_and_paragraph() -> None:
    found = extract("as referred to in Article 6(1)", "gdpr")

    assert found == [Reference(target_key="gdpr:art-6:para-1", raw_text="Article 6(1)")]


def test_finds_a_point_inside_a_paragraph() -> None:
    found = extract("pursuant to Article 9(2)(a)", "gdpr")

    assert found[0].target_key == "gdpr:art-9:para-2:pt-a"


def test_finds_the_point_first_wording() -> None:
    found = extract("point (a) of Article 6(1) applies", "gdpr")
    keys = {reference.target_key for reference in found}

    assert "gdpr:art-6:para-1:pt-a" in keys


def test_ignores_a_reference_to_another_law() -> None:
    """Linking this inside GDPR would point an authoritative-looking citation at
    the wrong clause, which is worse than no link at all."""
    found = extract("adopted on the basis of Article 25(6) of Directive 95/46/EC", "gdpr")

    assert found == []


def test_ignores_the_treaty_and_the_charter() -> None:
    assert extract("Article 16(1) of the Treaty", "gdpr") == []
    assert extract("enshrined in Article 8(1) of the Charter", "gdpr") == []


def test_keeps_a_reference_to_this_regulation() -> None:
    found = extract("decisions adopted pursuant to Article 45(3) of this Regulation", "gdpr")

    assert found[0].target_key == "gdpr:art-45:para-3"


def test_resolution_splits_real_targets_from_missing_ones() -> None:
    references = [
        Reference("gdpr:art-6:para-1", "Article 6(1)"),
        Reference("gdpr:art-99:para-9", "Article 99(9)"),
    ]

    resolution = resolve(references, {"gdpr:art-6:para-1"})

    assert [reference.target_key for reference in resolution.resolved] == ["gdpr:art-6:para-1"]
    assert [reference.target_key for reference in resolution.unresolved] == ["gdpr:art-99:para-9"]
