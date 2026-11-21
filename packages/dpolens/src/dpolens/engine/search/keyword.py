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
    config: str
    """The text search configuration the index was built with, which splits and stems."""


INDEXES = {
    "en": KeywordIndex("node_texts_bm25_en", "search_text", ":query", "english"),
    # Spellings folded and articles off, the same steps the text went through, then
    # Postgres's Arabic stemmer, which both forms of a word now reach alike.
    "ar": KeywordIndex(
        "node_texts_bm25_ar_folded_snowball", "search_text_ar", "arabic_light(:query)", "arabic"
    ),
}

ALTERNATIVES = {
    # The folding alone, with nothing stemmed.
    "light": {
        "ar": KeywordIndex("node_texts_bm25_ar", "search_text_ar", "arabic_light(:query)", "simple")
    },
    # Postgres's Arabic stemmer, on the text as written.
    "snowball": {
        "ar": KeywordIndex("node_texts_bm25_ar_snowball", "search_text", ":query", "arabic")
    },
    # The default, by name, so that a comparison can name all three.
    "folded-snowball": {"ar": INDEXES["ar"]},
}
"""The indexes an eval run can name for a language, to measure one against another."""

WITH_QUESTIONS = {
    "en": KeywordIndex("keyword_texts_bm25_en", "words", ":query", "english"),
    "ar": KeywordIndex("keyword_texts_bm25_ar", "words_ar", "arabic_light(:query)", "arabic"),
}
"""A law's clauses with their search questions' words after their own, in the same text search
configurations as the law's own indexes. Only laws have questions, so policies are not in it."""

SEARCHABLE_LANGUAGES = tuple(INDEXES)
"""The languages a question can be asked in, since each needs its own index."""


class UnsupportedLanguage(Exception):
    """No BM25 index exists for that language yet."""


IN_FORCE = """
    SELECT DISTINCT ON (document_id) id
    FROM document_versions
    WHERE status = 'published' AND effective_date <= :as_of
    ORDER BY document_id, effective_date DESC, version_number DESC
"""
"""Each document's version in force on :as_of, by the rule reading a clause follows: the latest
published version whose effective date has passed, and of two that took effect on one day, the
later. A version it replaced is still published and still reads, and nothing searches it: its
words could match a question and send it to a number that now names another rule."""


def scoped(packs: Sequence[str] | None) -> tuple[str, str]:
    """The join and the condition that keep a search to some laws, or nothing at all.

    An organisation's own policy belongs to no pack, and :policies says whether it is searched
    beside them. Both parts are fixed text: the laws arrive as the :packs parameter.
    """
    if packs is None:
        return "", ""
    return (
        "JOIN documents d ON d.id = v.document_id LEFT JOIN packs p ON p.id = d.pack_id",
        "AND ((d.kind = 'org_policy' AND :policies) OR p.slug = ANY(:packs))",
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
    as_of: date | None = None,
    *,
    policies: bool = True,
    with_questions: bool = False,
) -> list[Candidate]:
    """The clauses whose text matches the query, best first, each once.

    `indexes` replaces a language's index with another, which is how an eval run
    compares them. `packs` keeps the search to those laws, and to the organisation's
    own policies unless `policies` is false. `as_of` is the day the text is read on,
    today unless given. `with_questions` reads a law's clauses with their search
    questions' words after their own, which only laws have: the policies are then
    not searched, and `indexes` does not apply.
    """
    chosen = WITH_QUESTIONS if with_questions else {**INDEXES, **(indexes or {})}
    index = chosen.get(lang)
    if index is None:
        raise UnsupportedLanguage(
            f"no BM25 index for {lang!r}: a language needs its own index, "
            f"since the text search configuration is fixed when the index is built"
        )

    # The column and the terms come from the tables above, never from a caller.
    table = "k" if with_questions else "t"
    rank = f"{table}.{index.column} <@> to_bm25query({index.terms}, :index)"
    scope_join, scope_condition = scoped(packs)
    # A row of questions alone has no text of its own, and so no days of its own: its clause's
    # version decides. A heading with no text of its own is a place in the law, read in browsing
    # and breadcrumbs, and never an answer, whatever its words match: such a row is never
    # written with the questions, and is passed over here.
    source = (
        "keyword_texts k JOIN document_nodes n ON n.id = k.node_id "
        "LEFT JOIN node_texts t ON t.id = k.node_text_id"
        if with_questions
        else "node_texts t JOIN document_nodes n ON n.id = t.node_id"
    )
    language = "k.lang" if with_questions else "t.lang"
    worded = "" if with_questions else "AND length(trim(t.body_text)) > 0"

    # The operator returns negative scores and sorts ascending, so the best
    # match is the most negative. Flipping the sign here keeps every retriever
    # in this package on the same convention: higher is better.
    rows = session.execute(
        text(
            f"""
            SELECT n.canonical_key AS key,
                   {language} AS lang,
                   -({rank}) AS score
            FROM {source}
            JOIN document_versions v ON v.id = n.document_version_id
            JOIN ({IN_FORCE}) in_force ON in_force.id = v.id
            {scope_join}
            WHERE {language} = :lang
              -- Words that stopped applying are not an answer. Words that start later
              -- are, marked as such, so a duty can be prepared for.
              AND (t.applies_until IS NULL OR t.applies_until > :as_of)
              AND (NOT :normative_only OR n.is_normative)
              {worded}
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
            "as_of": as_of or date.today(),
            "limit": limit,
            "normative_only": normative_only,
            **({"packs": list(packs), "policies": policies} if packs is not None else {}),
        },
    ).all()

    # The rows arrive in whichever order the plan gives. Postgres sorts them itself
    # until the table has statistics, then lets the BM25 index order them, and the
    # two orders can disagree, so the order is set here from each row's own score,
    # with the key settling a tie. A clause with texts that both match, such as one
    # whose words change on a later day, counts once, at its better text.
    ordered = sorted(rows, key=lambda row: (-row.score, row.key))
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for row in ordered:
        if row.key in seen:
            continue
        seen.add(row.key)
        candidates.append(
            Candidate(key=row.key, lang=row.lang, score=float(row.score), rank=len(candidates) + 1)
        )
    return candidates


QUOTED_SHARE = 0.9
"""A clause whose own words hold this share of a question's content words is quoted by it."""

QUOTED_WORDS = 5
"""Fewer content words than this, and a short question would quote any clause that holds them."""


def quoted(
    session: Session,
    query: str,
    lang: str,
    keys: Sequence[str],
    as_of: date | None = None,
) -> str | None:
    """The clause among `keys` that the question nearly quotes, if any.

    A question in everyday words wants keyword search at a modest weight, and one that repeats a
    clause's own words wants that clause. Content words are what the keyword index makes of the
    question: common words dropped, the rest stemmed. A clause's own words count, never its
    search questions'. Of several, the one holding the most comes first, then the earlier key.
    """
    index = INDEXES.get(lang)
    if index is None or not keys:
        return None
    rows = session.execute(
        text(
            f"""
            WITH asked AS (
                SELECT tsvector_to_array(to_tsvector('{index.config}', {index.terms})) AS terms
            )
            SELECT n.canonical_key AS key,
                   cardinality(asked.terms) AS asked,
                   (SELECT count(*) FROM unnest(asked.terms) term
                    WHERE term = ANY(tsvector_to_array(
                        to_tsvector('{index.config}', t.{index.column})))) AS held
            FROM asked, node_texts t
            JOIN document_nodes n ON n.id = t.node_id
            JOIN ({IN_FORCE}) in_force ON in_force.id = n.document_version_id
            WHERE n.canonical_key = ANY(:keys)
              AND t.lang = :lang
              AND length(trim(t.body_text)) > 0
              AND (t.applies_until IS NULL OR t.applies_until > :as_of)
            """
        ),
        {"query": query, "keys": list(keys), "lang": lang, "as_of": as_of or date.today()},
    ).all()
    held: dict[str, int] = {}
    for row in rows:
        held[row.key] = max(held.get(row.key, 0), int(row.held))
    asked = int(rows[0].asked) if rows else 0
    return quote_of(asked, held, keys)


def quote_of(asked: int, held: Mapping[str, int], keys: Sequence[str]) -> str | None:
    """Which clause a question of `asked` content words quotes, from how many each holds."""
    if asked < QUOTED_WORDS:
        return None
    order = {key: position for position, key in enumerate(keys)}
    quoting = [key for key, count in held.items() if count >= QUOTED_SHARE * asked]
    if not quoting:
        return None
    return min(quoting, key=lambda key: (-held[key], order.get(key, len(order))))
