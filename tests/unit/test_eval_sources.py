"""Where an eval label comes from, as the source check reads it.

A label is cited when the guidance names the article. The quote is what a reader checks, so a
question that quotes its source is cited only when the quote itself names the article: a page
can name an article anywhere, about anything.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import check_eval_sources  # noqa: E402
from check_eval_sources import check, names_article  # noqa: E402

PAGE = (
    "Their obligations (Art. 7) under the PDPL Law include: Appointing a processor by ensuring "
    "lawful and secure data processing. Records are kept under Article 7(4). Article 9 sets out "
    "what a breach report holds."
)


@pytest.fixture(autouse=True)
def one_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every source reads as the same page, so nothing is fetched."""
    monkeypatch.setattr(check_eval_sources, "page_text", lambda url: PAGE)


def checked(tmp_path: Path, **question: Any) -> tuple[int, int, list[str]]:
    asked = {"id": "q", "source": "https://example.org/guide", **question}
    path = tmp_path / "tuning.yaml"
    path.write_text(yaml.safe_dump({"questions": [asked]}), encoding="utf-8")
    return check(path)


def test_a_quote_that_names_the_article_is_cited(tmp_path: Path) -> None:
    found = checked(
        tmp_path,
        expected_keys=["uae-pdpl:art-7:para-5"],
        quote="Their obligations (Art. 7) under the PDPL Law include: ... Appointing a processor",
    )

    assert found == (1, 0, [])


def test_the_page_naming_the_article_elsewhere_does_not_cite_a_quote(tmp_path: Path) -> None:
    found = checked(
        tmp_path, expected_keys=["uae-pdpl:art-7:para-5"], quote="Appointing a processor"
    )

    assert found == (
        0,
        0,
        [
            "q: the quote does not name article 7 and there is no note explaining why this "
            "clause is the answer"
        ],
    )


def test_a_note_justifies_a_quote_that_does_not_name_the_article(tmp_path: Path) -> None:
    found = checked(
        tmp_path,
        expected_keys=["uae-pdpl:art-7:para-5"],
        quote="Appointing a processor",
        note="The guide lists the duties in the order of Article 7's paragraphs.",
    )

    assert found == (0, 1, [])


def test_without_a_quote_the_page_names_the_article(tmp_path: Path) -> None:
    assert checked(tmp_path, expected_keys=["uae-pdpl:art-9:para-3"]) == (1, 0, [])


def test_a_quote_the_page_does_not_hold_is_rejected(tmp_path: Path) -> None:
    found = checked(
        tmp_path, expected_keys=["uae-pdpl:art-9:para-3"], quote="Article 9 ... never written"
    )

    assert found == (0, 0, ["q: the source does not contain the quote"])


@pytest.mark.parametrize(
    ("text", "article", "named"),
    [
        ("Their obligations (Art. 7) under the law", "7", True),
        ("the identity of the data subject (Art.12(6) GDPR)", "12", True),
        ("delineating responsibilities [ Article 8(10) ]", "8", True),
        ("delineating responsibilities [ Article 8(10) ]", "10", False),
        ("By virtue of Article 10 of the PDPL", "1", False),
        # "Articles" names neither, which is why a label resting on it needs a note.
        ("to oversee compliance (Articles 10 and 11)", "11", False),
    ],
)
def test_an_article_is_named_the_way_guides_write_it(text: str, article: str, named: bool) -> None:
    assert names_article(text, article) is named
