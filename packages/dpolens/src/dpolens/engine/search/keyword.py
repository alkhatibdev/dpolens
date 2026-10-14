"""Keyword retrieval, ranked by BM25.

Legal text rewards keyword search: article numbers, defined terms and phrases
like "right to erasure" are what people type, and BM25 ranks them properly
because it accounts for how rare a term is, how often it repeats, and how long
the clause is. Postgres `ts_rank` does none of those three.

A BM25 index fixes its text search configuration when it is created, so there is
one index per language and a query names the one it wants. Arabic has three, which
treat word forms differently, so that the evals can measure which finds more.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class KeywordIndex:
    """A BM25 index, the column it ranks, and how a question reaches it."""

    name: str
    column: str
    terms: str
    """SQL that turns the question, bound as :query, into the index's words."""


INDEXES = {
    "en": KeywordIndex("node_texts_bm25_en", "search_text", ":query"),
    # Spellings folded and articles off, the same steps the text went through, then
    # Postgres's Arabic stemmer, which both forms of a word now reach alike.
    "ar": KeywordIndex(
        "node_texts_bm25_ar_folded_snowball", "search_text_ar", "arabic_light(:query)"
    ),
}

ALTERNATIVES = {
    # The folding alone, with nothing stemmed.
    "light": {"ar": KeywordIndex("node_texts_bm25_ar", "search_text_ar", "arabic_light(:query)")},
    # Postgres's Arabic stemmer, on the text as written.
    "snowball": {"ar": KeywordIndex("node_texts_bm25_ar_snowball", "search_text", ":query")},
    # The default, by name, so that a comparison can name all three.
    "folded-snowball": {"ar": INDEXES["ar"]},
}
"""The indexes an eval run can name for a language, to measure one against another."""

SEARCHABLE_LANGUAGES = tuple(INDEXES)
"""The languages a question can be asked in, since each needs its own index."""


class UnsupportedLanguage(Exception):
    """No BM25 index exists for that language yet."""


def scoped(packs: Sequence[str] | None) -> tuple[str, str]:
    """The join and the condition that keep a search to some laws, or nothing at all.

    An organisation's own policy belongs to no pack and is in every scope. Both
    parts are fixed text: the laws arrive as the :packs parameter.
    """
    if packs is None:
        return "", ""
    return (
        "JOIN documents d ON d.id = v.document_id LEFT JOIN packs p ON p.id = d.pack_id",
        "AND (d.kind = 'org_policy' OR p.slug = ANY(:packs))",
    )


@dataclass(frozen=True)
class Candidate:
    """One clause a retriever proposes, with the score that retriever gave it."""

    key: str
    lang: str
    score: float
    rank: int


def keyword_search(
    session: Session,
    query: str,
    lang: str = "en",
    limit: int = 100,
    normative_only: bool = False,
    indexes: Mapping[str, KeywordIndex] | None = None,
    packs: Sequence[str] | None = None,
) -> list[Candidate]:
    """The clauses whose text matches the query, best first.

    `indexes` replaces a language's index with another, which is how an eval run
    compares them. `packs` keeps the search to those laws and the organisation's
    own policies.
    """
    index = {**INDEXES, **(indexes or {})}.get(lang)
    if index is None:
        raise UnsupportedLanguage(
            f"no BM25 index for {lang!r}: a language needs its own index, "
            f"since the text search configuration is fixed when the index is built"
        )

    # The column and the terms come from the table above, never from a caller.
    rank = f"t.{index.column} <@> to_bm25query({index.terms}, :index)"
    scope_join, scope_condition = scoped(packs)

    # The operator returns negative scores and sorts ascending, so the best
    # match is the most negative. Flipping the sign here keeps every retriever
    # in this package on the same convention: higher is better.
    rows = session.execute(
        text(
            f"""
            SELECT n.canonical_key AS key,
                   t.lang AS lang,
                   -({rank}) AS score
            FROM node_texts t
            JOIN document_nodes n ON n.id = t.node_id
            JOIN document_versions v ON v.id = n.document_version_id
            {scope_join}
            WHERE t.lang = :lang
              AND v.status = 'published'
              AND v.effective_date <= :as_of
              AND (NOT :normative_only OR n.is_normative)
              {scope_condition}
              -- A clause that shares no term with the query scores zero, and
              -- the operator returns it anyway. An empty result is the honest
              -- answer to a question the corpus does not address.
              AND ({rank}) < 0
            ORDER BY {rank}
            LIMIT :limit
            """
        ),
        {
            "query": query,
            "index": index.name,
            "lang": lang,
            "as_of": date.today(),
            "limit": limit,
            "normative_only": normative_only,
            **({"packs": list(packs)} if packs is not None else {}),
        },
    ).all()

    return [
        Candidate(key=row.key, lang=row.lang, score=float(row.score), rank=position)
        for position, row in enumerate(rows, start=1)
    ]
