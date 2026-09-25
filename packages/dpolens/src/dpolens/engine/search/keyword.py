"""Keyword retrieval, ranked by BM25.

Legal text rewards keyword search: article numbers, defined terms and phrases
like "right to erasure" are what people type, and BM25 ranks them properly
because it accounts for how rare a term is, how often it repeats, and how long
the clause is. Postgres `ts_rank` does none of those three.

A BM25 index fixes its text search configuration when it is created, so there is
one index per language and a query names the one it wants.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

INDEXES = {"en": "node_texts_bm25_en"}


class UnsupportedLanguage(Exception):
    """No BM25 index exists for that language yet."""


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
) -> list[Candidate]:
    """The clauses whose text matches the query, best first."""
    index = INDEXES.get(lang)
    if index is None:
        raise UnsupportedLanguage(
            f"no BM25 index for {lang!r}: a language needs its own index, "
            f"since the text search configuration is fixed when the index is built"
        )

    # The operator returns negative scores and sorts ascending, so the best
    # match is the most negative. Flipping the sign here keeps every retriever
    # in this package on the same convention: higher is better.
    rows = session.execute(
        text(
            """
            SELECT n.canonical_key AS key,
                   t.lang AS lang,
                   -(t.search_text <@> to_bm25query(:query, :index)) AS score
            FROM node_texts t
            JOIN document_nodes n ON n.id = t.node_id
            JOIN document_versions v ON v.id = n.document_version_id
            WHERE t.lang = :lang
              AND v.status = 'published'
              AND v.effective_date <= :as_of
              AND (NOT :normative_only OR n.is_normative)
              -- A clause that shares no term with the query scores zero, and
              -- the operator returns it anyway. An empty result is the honest
              -- answer to a question the corpus does not address.
              AND (t.search_text <@> to_bm25query(:query, :index)) < 0
            ORDER BY t.search_text <@> to_bm25query(:query, :index)
            LIMIT :limit
            """
        ),
        {
            "query": query,
            "index": index,
            "lang": lang,
            "as_of": date.today(),
            "limit": limit,
            "normative_only": normative_only,
        },
    ).all()

    return [
        Candidate(key=row.key, lang=row.lang, score=float(row.score), rank=position)
        for position, row in enumerate(rows, start=1)
    ]
