"""Search questions: what people might ask, kept beside the clause they were written for.

They are written per clause by a model and checked by another, and they are never shown,
quoted or cited: a law's own words are the only answer. A question helps search find its clause:
it is a list of its own beside the clause's words, and its words are read by keyword search
after them. An organisation can turn them off. search-questions/README.md says how they are made.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session

from dpolens.engine.embedding.encode import Embedder
from dpolens.engine.logs.governance import (
    SEARCH_QUESTIONS_LOADED,
    SEARCH_QUESTIONS_SWITCHED,
    Actor,
    record,
)
from dpolens.engine.search.fuse import standardised_scores
from dpolens.engine.search.keyword import IN_FORCE, Candidate

BATCH = 64
"""How many questions are embedded at once: each is a sentence, so memory is not the limit."""

FIELDS = ("pack", "written_by", "checked_by", "written_on", "write_prompt", "check_prompt")


class QuestionsError(Exception):
    """A file of search questions that cannot be loaded as it is."""


@dataclass(frozen=True)
class Loaded:
    pack: str
    questions: int
    current: int
    """How many sit beside words that are still the ones they were written for."""
    unchanged: bool
    """The same file was loaded already, so nothing was replaced."""


def fingerprint(texts: Mapping[str, str]) -> str:
    """Which words of a clause its questions were written for, in every language it has.

    A question written before any of them changed is not used, until it is written again.
    """
    joined = "\n".join(f"{lang}\n{' '.join(body.split())}" for lang, body in sorted(texts.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def load_questions(session: Session, path: Path, *, actor: Actor) -> Loaded:
    """Replace a law's search questions with the ones its file holds."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.safe_load(raw.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as problem:
        said = str(problem).splitlines()[0]
        raise QuestionsError(f"{path} cannot be read as a file of questions: {said}") from problem
    if not isinstance(data, dict):
        raise QuestionsError(f"{path} cannot be read as a file of questions: it is not a mapping")
    missing = [name for name in (*FIELDS, "clauses") if not data.get(name)]
    if missing:
        raise QuestionsError(f"{path} has no {', '.join(missing)}")
    seen: set[str] = set()
    for entry in data["clauses"]:
        if not isinstance(entry, dict) or not entry.get("key") or not entry.get("text"):
            raise QuestionsError(f"{path} has a clause without its key or its text")
        if entry["key"] in seen:
            raise QuestionsError(f"{path} names {entry['key']} twice")
        seen.add(entry["key"])
    slug = str(data["pack"])
    pack_id = session.execute(
        text("SELECT id FROM packs WHERE slug = :slug"), {"slug": slug}
    ).scalar()
    if pack_id is None:
        raise QuestionsError(f"{path}: {slug} is not loaded here, so its questions have no clauses")
    foreign = sorted(e["key"] for e in data["clauses"] if not e["key"].startswith(f"{slug}:"))
    if foreign:
        raise QuestionsError(f"{path} holds questions for another law's clauses: {foreign[0]}")

    loaded = session.execute(
        text("SELECT digest FROM search_question_files WHERE pack_id = :pack"), {"pack": pack_id}
    ).scalar()
    if loaded == digest:
        marked = mark_current(session)
        return Loaded(slug, _count(session, pack_id), marked.get(slug, 0), unchanged=True)

    session.execute(
        text("DELETE FROM search_question_files WHERE pack_id = :pack"), {"pack": pack_id}
    )
    session.execute(
        text(
            """
            INSERT INTO search_question_files
                (pack_id, written_by, checked_by, written_on, write_prompt, check_prompt, digest)
            VALUES (:pack, :written_by, :checked_by, :written_on, :write_prompt, :check_prompt,
                    :digest)
            """
        ),
        {
            "pack": pack_id,
            "written_by": _named(data["written_by"]),
            "checked_by": _named(data["checked_by"]),
            "written_on": date.fromisoformat(str(data["written_on"])),
            "write_prompt": str(data["write_prompt"]),
            "check_prompt": str(data["check_prompt"]),
            "digest": digest,
        },
    )
    session.execute(
        text(
            """
            INSERT INTO search_question_clauses (pack_id, canonical_key, fingerprint)
            VALUES (:pack, :key, :fingerprint)
            """
        ),
        [
            {"pack": pack_id, "key": entry["key"], "fingerprint": entry["text"]}
            for entry in data["clauses"]
        ],
    )
    rows = [
        {
            "id": uuid.uuid4(),
            "pack": pack_id,
            "key": entry["key"],
            "fingerprint": entry["text"],
            "lang": lang,
            "question": question,
        }
        for entry in data["clauses"]
        for lang in ("en", "ar")
        for question in entry.get(lang) or []
    ]
    if rows:
        session.execute(
            text(
                """
                INSERT INTO search_questions
                    (id, pack_id, canonical_key, fingerprint, lang, question)
                VALUES (:id, :pack, :key, :fingerprint, :lang, :question)
                """
            ),
            rows,
        )
    current = mark_current(session).get(slug, 0)
    record(
        session,
        actor=actor,
        action=SEARCH_QUESTIONS_LOADED,
        target_type="pack",
        target_id=slug,
        details={
            "pack": slug,
            "questions": len(rows),
            "current": current,
            "written_by": _named(data["written_by"]),
            "checked_by": _named(data["checked_by"]),
            "written_on": str(data["written_on"]),
            "digest": digest,
        },
    )
    return Loaded(slug, len(rows), current, unchanged=False)


def current_fingerprints(
    session: Session, keys: Sequence[str], today: date | None = None
) -> dict[str, str]:
    """The fingerprint of each clause's words in force today, in every language it has them."""
    texts: dict[str, dict[str, str]] = {}
    for row in session.execute(
        text(
            f"""
            SELECT n.canonical_key AS key, t.lang, t.body_text
            FROM node_texts t
            JOIN document_nodes n ON n.id = t.node_id
            JOIN ({IN_FORCE}) in_force ON in_force.id = n.document_version_id
            WHERE n.canonical_key = ANY(:keys) AND NOT t.pending
              AND (t.applies_from IS NULL OR t.applies_from <= :as_of)
              AND (t.applies_until IS NULL OR t.applies_until > :as_of)
            """
        ),
        {"keys": list(keys), "as_of": today or date.today()},
    ):
        if (row.body_text or "").strip():
            texts.setdefault(row.key, {})[row.lang] = row.body_text
    return {key: fingerprint(words) for key, words in texts.items()}


def mark_current(session: Session, today: date | None = None) -> dict[str, int]:
    """Which questions sit beside the words they were written for, by law.

    Run when questions are loaded, when a law is loaded and when the index is built, so a law
    loaded or updated since is compared with the words it holds now. What keyword search reads
    with the questions is written again from the result.
    """
    keys = list(session.scalars(text("SELECT DISTINCT canonical_key FROM search_questions")))
    prints = current_fingerprints(session, keys, today)
    if keys:
        session.execute(
            text(
                "UPDATE search_questions SET current = (fingerprint = :print) "
                "WHERE canonical_key = :key"
            ),
            [{"key": key, "print": prints.get(key, "")} for key in keys],
        )
    write_keyword_texts(session, today)
    return {
        row.slug: int(row.current)
        for row in session.execute(
            text(
                """
                SELECT p.slug, count(*) FILTER (WHERE q.current) AS current
                FROM search_questions q JOIN packs p ON p.id = q.pack_id
                GROUP BY p.slug
                """
            )
        )
    }


def without_questions(session: Session, today: date | None = None) -> dict[str, list[str]]:
    """Each law with questions loaded, and its clauses that state a rule but have none written
    for their words in force, in the law's order.

    Such a clause is found only by its own words, among clauses also found by their questions.
    A law's file names every clause it was written for, even one whose check kept no question,
    so a clause missing from it, or named at other words, is one nobody has written for.
    """
    as_of = today or date.today()
    rows = session.execute(
        text(
            f"""
            SELECT p.slug, n.canonical_key AS key, written.fingerprint
            FROM search_question_files f
            JOIN packs p ON p.id = f.pack_id
            JOIN documents d ON d.pack_id = p.id AND d.kind = 'law'
            JOIN document_versions v ON v.document_id = d.id
            JOIN ({IN_FORCE}) in_force ON in_force.id = v.id
            JOIN document_nodes n ON n.document_version_id = v.id AND n.is_normative
            LEFT JOIN search_question_clauses written
              ON written.pack_id = p.id AND written.canonical_key = n.canonical_key
            """
        ),
        {"as_of": as_of},
    ).all()
    prints = current_fingerprints(session, [row.key for row in rows], as_of)
    missing: dict[str, list[str]] = {}
    for row in rows:
        words = prints.get(row.key)
        if words is not None and row.fingerprint != words:
            missing.setdefault(row.slug, []).append(row.key)
    return {slug: sorted(keys, key=_in_order) for slug, keys in missing.items()}


def _in_order(key: str) -> list[Any]:
    """A clause's place in its law, by its key: Article 4 before Article 10."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", key)]


ASKED = """
    SELECT canonical_key, lang, string_agg(question, ' ' ORDER BY question) AS words
    FROM search_questions
    WHERE current
    GROUP BY canonical_key, lang
"""
"""Each clause's current questions in one language, as one run of words."""


def write_keyword_texts(session: Session, today: date | None = None) -> None:
    """Write what keyword search reads for a law when searches use the questions.

    Each worded text of a law, with its clause's current questions in that language after it
    when it is the text in force today, and for a clause with questions in a language it has no
    words in, a row of those questions alone. The table is emptied with TRUNCATE: a BM25 index
    keeps counting a deleted row in its statistics, so rows deleted and written again would not
    score as the same rows written once.
    """
    as_of = {"as_of": today or date.today()}
    session.execute(text("TRUNCATE keyword_texts"))
    session.execute(
        text(
            f"""
            INSERT INTO keyword_texts (node_id, node_text_id, lang, words)
            SELECT t.node_id, t.id, t.lang, t.search_text || coalesce(' ' || asked.words, '')
            FROM node_texts t
            JOIN document_nodes n ON n.id = t.node_id
            JOIN document_versions v ON v.id = n.document_version_id AND v.status = 'published'
            JOIN documents d ON d.id = v.document_id AND d.kind = 'law'
            LEFT JOIN ({IN_FORCE}) in_force ON in_force.id = v.id
            LEFT JOIN ({ASKED}) asked
              ON asked.canonical_key = n.canonical_key AND asked.lang = t.lang
             AND in_force.id IS NOT NULL AND NOT t.pending
             AND (t.applies_from IS NULL OR t.applies_from <= :as_of)
             AND (t.applies_until IS NULL OR t.applies_until > :as_of)
            WHERE length(trim(t.body_text)) > 0
            """
        ),
        as_of,
    )
    session.execute(
        text(
            f"""
            INSERT INTO keyword_texts (node_id, node_text_id, lang, words)
            SELECT n.id, NULL, asked.lang, asked.words
            FROM ({ASKED}) asked
            JOIN document_nodes n ON n.canonical_key = asked.canonical_key
            JOIN ({IN_FORCE}) in_force ON in_force.id = n.document_version_id
            WHERE NOT EXISTS (
                SELECT 1 FROM node_texts t
                WHERE t.node_id = n.id AND t.lang = asked.lang AND length(trim(t.body_text)) > 0
            )
            """
        ),
        as_of,
    )


def nearest_questions(
    session: Session,
    embedder: Embedder,
    vector: np.ndarray,
    pack: str,
    limit: int = 100,
    normative_only: bool = False,
) -> list[Candidate]:
    """One law's clauses whose current questions are closest to the query, each at its nearest.

    Every question of the law is compared, as every clause is in meaning search: a law's
    questions come to thousands, which takes milliseconds.
    """
    dimensions = embedder.model.dimensions
    rows = session.execute(
        text(
            f"""
            SELECT key, lang, score FROM (
                SELECT DISTINCT ON (q.canonical_key)
                       q.canonical_key AS key, q.lang,
                       1 - (e.embedding::vector({dimensions}) <=> :vector) AS score
                FROM search_question_embeddings e
                JOIN search_questions q ON q.id = e.question_id
                JOIN packs p ON p.id = q.pack_id
                JOIN embedding_models m ON m.id = e.embedding_model_id AND m.name = :model
                WHERE q.current AND p.slug = :pack
                  -- One set of keys, read once. Asked of each question, the planner can work
                  -- out every document's version in force again for each of thousands.
                  AND (NOT :normative_only OR q.canonical_key IN (
                      SELECT n.canonical_key FROM document_nodes n
                      JOIN ({IN_FORCE}) in_force ON in_force.id = n.document_version_id
                      WHERE n.is_normative
                  ))
                ORDER BY q.canonical_key, e.embedding::vector({dimensions}) <=> :vector, q.lang
            ) nearest
            ORDER BY score DESC, key
            LIMIT :limit
            """
        ),
        {
            "vector": str(vector.tolist()),
            "model": embedder.model.name,
            "pack": pack,
            "normative_only": normative_only,
            "limit": limit,
            "as_of": date.today(),
        },
    ).all()
    return [
        Candidate(key=row.key, lang=row.lang, score=float(row.score), rank=position)
        for position, row in enumerate(rows, start=1)
    ]


def with_questions(meaning: Sequence[Candidate], asked: Sequence[Candidate]) -> list[Candidate]:
    """The meaning list, each clause at the better of its own words and its nearest question.

    Each list is standardised first, so a clause counts for how far it stands above the rest of
    its own list, and a question's higher scale wins nothing by itself. A clause only a question
    found joins the list.
    """
    if not asked:
        return list(meaning)
    best: dict[str, tuple[float, str]] = {}
    for found in (meaning, asked):
        for candidate, score in zip(found, standardised_scores(found), strict=True):
            if candidate.key not in best or score > best[candidate.key][0]:
                best[candidate.key] = (score, candidate.lang)
    ordered = sorted(best.items(), key=lambda pair: (-pair[1][0], pair[0]))
    return [
        Candidate(key=key, lang=lang, score=score, rank=rank)
        for rank, (key, (score, lang)) in enumerate(ordered, start=1)
    ]


def embed_questions(session: Session, embedder: Embedder) -> int:
    """Embed each question the model has not, as the question it is.

    Run after the clauses are embedded, which is what registers the model.
    """
    model_id = session.execute(
        text("SELECT id FROM embedding_models WHERE name = :name"), {"name": embedder.model.name}
    ).scalar_one()
    rows = session.execute(
        text(
            """
            SELECT q.id, q.question FROM search_questions q
            WHERE NOT EXISTS (
                SELECT 1 FROM search_question_embeddings e
                WHERE e.question_id = q.id AND e.embedding_model_id = :model
            )
            ORDER BY q.id
            """
        ),
        {"model": model_id},
    ).all()
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        vectors = embedder.encode_queries([row.question for row in batch])
        session.execute(
            text(
                """
                INSERT INTO search_question_embeddings (question_id, embedding_model_id, embedding)
                VALUES (:question, :model, :embedding)
                """
            ),
            [
                {"question": row.id, "model": model_id, "embedding": str(vector.tolist())}
                for row, vector in zip(batch, vectors, strict=True)
            ],
        )
    return len(rows)


@dataclass(frozen=True)
class QuestionFile:
    """A law's questions as loaded: how many, how many still current, and who wrote them."""

    pack: str
    short_name: str
    """What people call the law, in English, which is the interface's language."""
    questions: int
    current: int
    written_by: str
    checked_by: str
    written_on: date


def loaded_files(session: Session) -> list[QuestionFile]:
    return [
        QuestionFile(
            pack=row.slug,
            short_name=row.short_name,
            questions=int(row.questions),
            current=int(row.current),
            written_by=row.written_by,
            checked_by=row.checked_by,
            written_on=row.written_on,
        )
        for row in session.execute(
            text(
                """
                SELECT p.slug, n.short_name, f.written_by, f.checked_by, f.written_on,
                       count(q.id) AS questions, count(q.id) FILTER (WHERE q.current) AS current
                FROM search_question_files f
                JOIN packs p ON p.id = f.pack_id
                JOIN pack_names n ON n.pack_id = p.id AND n.lang = 'en'
                LEFT JOIN search_questions q ON q.pack_id = f.pack_id
                GROUP BY p.slug, n.short_name, f.written_by, f.checked_by, f.written_on
                ORDER BY p.slug
                """
            )
        )
    ]


def questions_on(session: Session) -> bool:
    """Whether this organisation's searches use the questions: they do unless turned off."""
    on = session.execute(text("SELECT questions FROM search_settings")).scalar()
    return True if on is None else bool(on)


def switch_questions(session: Session, on: bool, *, actor: Actor) -> bool:
    """Turn the questions on or off for every search, and write the change to the log."""
    before = questions_on(session)
    session.execute(
        text(
            """
            INSERT INTO search_settings (singleton, questions) VALUES (true, :on)
            ON CONFLICT (singleton) DO UPDATE SET questions = EXCLUDED.questions
            """
        ),
        {"on": on},
    )
    if before != on:
        record(
            session,
            actor=actor,
            action=SEARCH_QUESTIONS_SWITCHED,
            target_type="search_settings",
            target_id="instance",
            details={"before": before, "after": on},
        )
    return on


def _count(session: Session, pack_id: Any) -> int:
    return int(
        session.execute(
            text("SELECT count(*) FROM search_questions WHERE pack_id = :pack"), {"pack": pack_id}
        ).scalar_one()
    )


def _named(value: Any) -> str:
    """A file names its models as a list, since a law's questions can come from more than one."""
    return ", ".join(value) if isinstance(value, list) else str(value)
