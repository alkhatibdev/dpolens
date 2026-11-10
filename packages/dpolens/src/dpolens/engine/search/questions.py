"""Search questions: what people might ask, kept beside the clause they were written for.

They are written per clause by a model and checked by another, and they are never shown,
quoted or cited: a law's own words are the only answer. A question only helps search order
the clauses it has already found, among the places those clauses hold, and an organisation can
turn them off. search-questions/README.md says how they are made.
"""

from __future__ import annotations

import hashlib
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
from dpolens.engine.search.fuse import Fused, Fusion, fuse
from dpolens.engine.search.keyword import Candidate

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
            """
            SELECT n.canonical_key AS key, t.lang, t.body_text
            FROM node_texts t
            JOIN document_nodes n ON n.id = t.node_id
            JOIN document_versions v ON v.id = n.document_version_id AND v.status = 'published'
            WHERE n.canonical_key = ANY(:keys) AND NOT t.pending
              AND (t.applies_from IS NULL OR t.applies_from <= :today)
              AND (t.applies_until IS NULL OR t.applies_until > :today)
            """
        ),
        {"keys": list(keys), "today": today or date.today()},
    ):
        if (row.body_text or "").strip():
            texts.setdefault(row.key, {})[row.lang] = row.body_text
    return {key: fingerprint(words) for key, words in texts.items()}


def mark_current(session: Session, today: date | None = None) -> dict[str, int]:
    """Which questions sit beside the words they were written for, by law.

    Run when questions are loaded and when the index is built, so a law loaded or updated
    since is compared with the words it holds now.
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


def question_scores(
    session: Session, embedder: Embedder, vector: np.ndarray, keys: Sequence[str]
) -> dict[str, float]:
    """How close the query is to each clause's nearest question, for the clauses given."""
    if not keys:
        return {}
    dimensions = embedder.model.dimensions
    return {
        row.key: float(row.score)
        for row in session.execute(
            text(
                f"""
                SELECT q.canonical_key AS key,
                       max(1 - (e.embedding::vector({dimensions}) <=> :vector)) AS score
                FROM search_question_embeddings e
                JOIN search_questions q ON q.id = e.question_id
                JOIN embedding_models m ON m.id = e.embedding_model_id AND m.name = :model
                WHERE q.current AND q.canonical_key = ANY(:keys)
                GROUP BY q.canonical_key
                """
            ),
            {"vector": str(vector.tolist()), "model": embedder.model.name, "keys": list(keys)},
        )
    }


def with_questions(
    lists: Mapping[str, Sequence[Candidate]],
    fused: Sequence[Fused],
    scores: Mapping[str, float],
    fusion: Fusion,
) -> list[Fused]:
    """The fused list reordered by the questions, among the clauses that have them.

    In meaning search, a clause scores as the closer of its own words and its nearest
    question, and the lists are fused again. Only the clauses with questions move, and only
    into the places those clauses already held, each place keeping its score: a question
    measures closer to a question than a clause's words do, so a clause without questions,
    such as a policy's, would otherwise sink below every clause with them.
    """
    keyword, meaning = list(lists["keyword"]), list(lists["meaning"])
    found = {candidate.key for candidate in keyword} | {candidate.key for candidate in meaning}
    closest = {candidate.key: candidate.score for candidate in meaning}
    langs = {candidate.key: candidate.lang for candidate in meaning}
    for candidate in keyword:
        langs.setdefault(candidate.key, candidate.lang)
    for key in found & scores.keys():
        closest[key] = max(closest.get(key, -1.0), scores[key])
    ordered = sorted(closest.items(), key=lambda pair: (-pair[1], pair[0]))
    lifted = [
        Candidate(key=key, lang=langs[key], score=score, rank=rank)
        for rank, (key, score) in enumerate(ordered, start=1)
    ]
    moved = iter(
        item for item in fuse({"keyword": keyword, "meaning": lifted}, fusion) if item.key in scores
    )
    reordered = []
    for place in fused:
        if place.key in scores:
            item = next(moved)
            reordered.append(
                Fused(key=item.key, lang=item.lang, score=place.score, ranks=item.ranks)
            )
        else:
            reordered.append(place)
    return reordered


@dataclass(frozen=True)
class QuestionFile:
    """A law's questions as loaded: how many, how many still current, and who wrote them."""

    pack: str
    questions: int
    current: int
    written_by: str
    checked_by: str
    written_on: date


def loaded_files(session: Session) -> list[QuestionFile]:
    return [
        QuestionFile(
            pack=row.slug,
            questions=int(row.questions),
            current=int(row.current),
            written_by=row.written_by,
            checked_by=row.checked_by,
            written_on=row.written_on,
        )
        for row in session.execute(
            text(
                """
                SELECT p.slug, f.written_by, f.checked_by, f.written_on,
                       count(q.id) AS questions, count(q.id) FILTER (WHERE q.current) AS current
                FROM search_question_files f
                JOIN packs p ON p.id = f.pack_id
                LEFT JOIN search_questions q ON q.pack_id = f.pack_id
                GROUP BY p.slug, f.written_by, f.checked_by, f.written_on
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
