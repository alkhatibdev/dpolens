"""Search questions beside each clause of a law: written by one model, checked by another.

They help search order the clauses it has already found, and are never shown, quoted or cited
(search-questions/README.md). Each article's questions are written by a `claude -p` call cut
off from this project, so the writer sees its prompt and the article and nothing else. A
second call, with another model, keeps only the questions the clause answers. Each article is
saved as it finishes, a rerun carries on where it stopped, and a plan's usage limit is waited
out.

    uv run python scripts/write_search_questions.py --pack uae-pdpl

The clauses are read from the instance's database, so load the pack first. It needs Claude
Code, signed in.
"""

from __future__ import annotations

import argparse
import functools
import json
import random
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

REPO = Path(__file__).parents[1]
sys.path.insert(0, str(REPO / "packages" / "dpolens" / "src"))

from dpolens.engine.search.questions import fingerprint  # noqa: E402
from dpolens.engine.session import session_scope  # noqa: E402
from dpolens.settings import load_settings  # noqa: E402

QUESTIONS = REPO / "search-questions"
WRITE_PROMPT = QUESTIONS / "write-prompt.md"
CHECK_PROMPT = QUESTIONS / "check-prompt.md"
PER_LANGUAGE = 3
ARABIC = re.compile(r"[؀-ۿ]")
LIMIT_WAIT = 15 * 60
TRIES = 5

WRITTEN = {
    "type": "object",
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    **{
                        lang: {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": PER_LANGUAGE,
                            "maxItems": PER_LANGUAGE,
                        }
                        for lang in ("en", "ar")
                    },
                },
                "required": ["key", "en", "ar"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clauses"],
    "additionalProperties": False,
}

CHECKED = {
    "type": "object",
    "properties": {
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    **{
                        lang: {"type": "array", "items": {"type": "boolean"}}
                        for lang in ("en", "ar")
                    },
                },
                "required": ["key", "en", "ar"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clauses"],
    "additionalProperties": False,
}


class LimitReached(Exception):
    """The plan's usage limit refused a call."""


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_articles(pack: str) -> list[dict[str, Any]]:
    """Every article of the law with each clause's text in force today, normative text only."""
    with session_scope(load_settings()) as session:
        names = session.execute(
            text(
                """
                SELECT n.short_name, n.name FROM packs p
                JOIN pack_names n ON n.pack_id = p.id AND n.lang = 'en'
                WHERE p.slug = :pack
                """
            ),
            {"pack": pack},
        ).one()
        rows = session.execute(
            text(
                """
                SELECT n.id, n.parent_node_id AS parent, n.canonical_key AS key, n.label,
                       n.depth, n.order_index, t.lang, t.heading, t.body_text
                FROM document_nodes n
                JOIN document_versions v ON v.id = n.document_version_id
                     AND v.status = 'published'
                JOIN documents d ON d.id = v.document_id
                JOIN packs p ON p.id = d.pack_id AND p.slug = :pack
                LEFT JOIN node_texts t ON t.node_id = n.id AND NOT t.pending
                     AND (t.applies_from IS NULL OR t.applies_from <= current_date)
                     AND (t.applies_until IS NULL OR t.applies_until > current_date)
                WHERE n.is_normative
                ORDER BY n.depth, n.order_index
                """
            ),
            {"pack": pack},
        ).all()

    nodes: dict[str, dict[str, Any]] = {}
    for row in rows:
        node = nodes.setdefault(
            str(row.id),
            {
                "key": row.key,
                "label": row.label,
                "depth": row.depth,
                "order": row.order_index,
                "parent": str(row.parent) if row.parent else None,
                "texts": {},
            },
        )
        if row.lang:
            node["texts"][row.lang] = {"heading": row.heading, "body": row.body_text or ""}

    def placed(node: dict[str, Any]) -> list[int]:
        """Where a node sits among its ancestors' children, so an article reads in order."""
        out = []
        while node:
            out.append(int(node["order"]))
            node = nodes[node["parent"]] if node["parent"] else None  # type: ignore[assignment]
        return out[::-1]

    def top(node: dict[str, Any]) -> dict[str, Any]:
        while node["parent"]:
            node = nodes[node["parent"]]
        return node

    articles: dict[str, dict[str, Any]] = {}
    for node in sorted(nodes.values(), key=placed):
        head = top(node)
        article = articles.setdefault(
            head["key"],
            {
                "key": head["key"],
                "law": [names.short_name, names.name],
                "heading": {lang: t["heading"] for lang, t in head["texts"].items()},
                "clauses": [],
            },
        )
        bodies = {lang: t["body"] for lang, t in node["texts"].items() if t["body"].strip()}
        if bodies:
            article["clauses"].append(
                {"key": node["key"], "label": node["label"], "depth": node["depth"], "text": bodies}
            )
    return [article for article in articles.values() if article["clauses"]]


def article_text(
    article: dict[str, Any], asked: set[str], questions: dict[str, Any] | None = None
) -> str:
    """The article as the writer reads it, and with its questions as the checker does.

    Every clause is shown, so each is read in its place, but only the clauses asked about carry
    their key: an answer that leaves some out is completed by asking for those alone.
    """
    short, full = article["law"]
    headings = " / ".join(heading for heading in article["heading"].values() if heading)
    every = all(clause["key"] in asked for clause in article["clauses"])
    lines = [
        f"Law: {short} ({full})",
        f"Article: {headings}" if headings else "Article: (no heading)",
        "",
        "Clauses, each key followed by its text in each language the law has:"
        if every
        else "Clauses, each followed by its text in each language the law has. Answer for each "
        "clause shown with a key: the others are there to be read with them, not answered.",
        "",
    ]
    for clause in article["clauses"]:
        indent = "  " * int(clause["depth"])
        label = f" {clause['label']}" if clause["label"] else ""
        shown = clause["key"] in asked
        marker = f"[{clause['key']}]" if shown else "(read with them)"
        lines.append(f"{indent}{marker}{label}")
        for lang, body in clause["text"].items():
            lines.append(f"{indent}  {lang}: {body}")
        if questions is not None and shown:
            for lang in ("en", "ar"):
                for number, question in enumerate(questions[clause["key"]][lang], start=1):
                    lines.append(f"{indent}  question {lang} {number}: {question}")
        lines.append("")
    return "\n".join(lines)


def claude(
    prompt: str, schema: dict[str, Any], given: str, model: str, empty: Path
) -> dict[str, Any]:
    """One call cut off from this project: no tools, no MCP servers, no settings, no session."""
    command = [
        "claude",
        "-p",
        "--model",
        model,
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "local",
        "--no-session-persistence",
        "--system-prompt",
        prompt,
        "--json-schema",
        json.dumps(schema),
        "--output-format",
        "json",
    ]
    done = subprocess.run(
        command, input=given, capture_output=True, text=True, cwd=empty, timeout=900, check=False
    )
    try:
        answer = json.loads(done.stdout)
    except json.JSONDecodeError:
        answer = None
    if done.returncode != 0 or not isinstance(answer, dict) or answer.get("is_error"):
        said = answer.get("result") if isinstance(answer, dict) else None
        message = " ".join(
            str(part) for part in (said, done.stdout[-400:], done.stderr[-400:]) if part
        )
        if "limit" in message.lower():
            raise LimitReached(message[:300])
        raise RuntimeError(f"exit {done.returncode}: {message[:300]}")
    return answer


def answered_by(answer: dict[str, Any], asked: str) -> tuple[str, dict[str, Any]]:
    """The model that answered, named as the call asked for it, and every model's tokens.

    Claude Code runs a small model of its own beside the one asked for, and on a short answer
    it can write more than the model that answered.
    """
    usage = {
        name: {key: value for key, value in figures.items() if key.endswith("Tokens")}
        for name, figures in (answer.get("modelUsage") or {}).items()
    }
    named = [name for name in usage if asked in name]
    return (named[0] if len(named) == 1 else f"unknown, asked for {asked}"), usage


def usable_written(found: Any, asked: set[str]) -> tuple[dict[str, Any], list[str]]:
    """The clauses an answer wrote usable questions for, and what was wrong with the rest."""
    if not isinstance(found, dict) or not isinstance(found.get("clauses"), list):
        return {}, ["no clauses in the answer"]
    good, wrong = {}, []
    for entry in found["clauses"]:
        key, english, arabic = str(entry.get("key")), entry.get("en", []), entry.get("ar", [])
        if key not in asked:
            wrong.append(f"{key}: not asked for")
        elif len(english) != PER_LANGUAGE or len(arabic) != PER_LANGUAGE:
            wrong.append(f"{key}: not {PER_LANGUAGE} questions in each language")
        elif any(not question.strip() for question in english + arabic):
            wrong.append(f"{key}: an empty question")
        elif not all(ARABIC.search(question) for question in arabic):
            wrong.append(f"{key}: an Arabic question with no Arabic in it")
        else:
            good[key] = {"key": key, "en": english, "ar": arabic}
    return good, wrong


def usable_checked(
    found: Any, asked: set[str], questions: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """The clauses an answer judged every question of, by key, and what was wrong with the rest."""
    if not isinstance(found, dict) or not isinstance(found.get("clauses"), list):
        return {}, ["no clauses in the answer"]
    good, wrong = {}, []
    for entry in found["clauses"]:
        key = str(entry.get("key"))
        if key not in asked:
            wrong.append(f"{key}: not asked for")
        elif any(len(entry.get(lang, [])) != len(questions[key][lang]) for lang in ("en", "ar")):
            wrong.append(f"{key}: not one answer for each question")
        else:
            good[key] = {"key": key, "en": entry["en"], "ar": entry["ar"]}
    return good, wrong


def complete(
    step: str,
    article: dict[str, Any],
    prompt: str,
    schema: dict[str, Any],
    model: str,
    empty: Path,
    given: Callable[[set[str]], str],
    usable: Callable[[Any, set[str]], tuple[dict[str, Any], list[str]]],
) -> dict[str, Any] | None:
    """The step done for every clause of the article, or None when the tries run out.

    What an answer gets right is kept, and the next try asks only for the clauses still missing,
    so a long article an answer leaves short is finished a part at a time.
    """
    wanted = [clause["key"] for clause in article["clauses"]]
    entries: dict[str, Any] = {}
    models: set[str] = set()
    usage: dict[str, dict[str, int]] = {}
    for number in range(1, TRIES + 1):
        asked = {key for key in wanted if key not in entries}
        if not asked:
            break
        try:
            answer = claude(prompt, schema, given(asked), model, empty)
        except RuntimeError as failure:
            print(f"{stamp()} {article['key']} {step} try {number} failed: {failure}", flush=True)
            time.sleep(20)
            continue
        good, wrong = usable(answer.get("structured_output"), asked)
        entries.update(good)
        name, tokens = answered_by(answer, model)
        models.add(name)
        for each, figures in tokens.items():
            for kind, count in figures.items():
                usage.setdefault(each, {})[kind] = usage.get(each, {}).get(kind, 0) + count
        if len(good) < len(asked):
            print(
                f"{stamp()} {article['key']} {step} try {number}: {len(good)} of {len(asked)} "
                f"clauses done {wrong[:3]}",
                flush=True,
            )
    if len(entries) < len(wanted):
        return None
    return {
        "model": ", ".join(sorted(models)),
        "usage": usage,
        "clauses": [entries[key] for key in wanted],
    }


def save(path: Path, record: dict[str, Any]) -> None:
    partial = path.with_suffix(".part")
    partial.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    partial.rename(path)


def assemble(pack: str, articles: list[dict[str, Any]], work: Path) -> Path:
    """The law's file: each clause's fingerprint and the questions its check kept."""
    writers, checkers, entries = set(), set(), []
    for article in articles:
        name = article["key"].replace(":", "_") + ".json"
        written = json.loads((work / "written" / name).read_text(encoding="utf-8"))
        checked = json.loads((work / "checked" / name).read_text(encoding="utf-8"))
        writers.add(written["model"])
        checkers.add(checked["model"])
        verdicts = {entry["key"]: entry for entry in checked["clauses"]}
        questions = {entry["key"]: entry for entry in written["clauses"]}
        for clause in article["clauses"]:
            kept = {
                lang: [
                    question
                    for question, keep in zip(
                        questions[clause["key"]][lang], verdicts[clause["key"]][lang], strict=True
                    )
                    if keep
                ]
                for lang in ("en", "ar")
            }
            if kept["en"] or kept["ar"]:
                entries.append({"key": clause["key"], "text": fingerprint(clause["text"]), **kept})
    header = (
        f"# Search questions for {articles[0]['law'][0]}, beside the clauses they were written\n"
        "# for. They help search order clauses it has already found, and are never shown,\n"
        "# quoted or cited. A clause's `text` is the fingerprint of the words they were written\n"
        "# for: when those words change, its questions are not used until they are written\n"
        "# again. search-questions/README.md says how they are written and checked.\n"
    )
    body = {
        "pack": pack,
        "written_by": sorted(writers),
        "checked_by": sorted(checkers),
        "written_on": datetime.now(UTC).date().isoformat(),
        "write_prompt": sha256(WRITE_PROMPT.read_bytes()).hexdigest()[:16],
        "check_prompt": sha256(CHECK_PROMPT.read_bytes()).hexdigest()[:16],
        "clauses": entries,
    }
    out = QUESTIONS / f"{pack}.yaml"
    out.write_text(
        header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--pack", required=True)
    parser.add_argument("--writer", default="sonnet")
    parser.add_argument("--checker", default="opus")
    parser.add_argument("--work", type=Path, help="where each article is saved as it finishes")
    parser.add_argument("--only", type=int, default=0, help="stop after this many articles")
    parser.add_argument(
        "--sample", type=int, default=0, help="also print this many random kept questions"
    )
    args = parser.parse_args()

    work = args.work or QUESTIONS / ".work" / args.pack
    for folder in ("written", "checked", "empty"):
        (work / folder).mkdir(parents=True, exist_ok=True)
    clauses = work / "clauses.json"
    if not clauses.exists():
        clauses.write_text(
            json.dumps(read_articles(args.pack), ensure_ascii=False), encoding="utf-8"
        )
    articles = json.loads(clauses.read_text(encoding="utf-8"))
    write_prompt = WRITE_PROMPT.read_text(encoding="utf-8")
    check_prompt = CHECK_PROMPT.read_text(encoding="utf-8")

    new, left = 0, []
    for article in articles:
        if args.only and new >= args.only:
            break
        name = article["key"].replace(":", "_") + ".json"
        written_path, checked_path = work / "written" / name, work / "checked" / name
        if checked_path.exists():
            continue
        new += 1
        while True:
            try:
                if not written_path.exists():
                    written = complete(
                        "write",
                        article,
                        write_prompt,
                        WRITTEN,
                        args.writer,
                        work / "empty",
                        functools.partial(article_text, article),
                        usable_written,
                    )
                    if written is None:
                        print(
                            f"{stamp()} {article['key']} not written, left for a rerun", flush=True
                        )
                        left.append(article["key"])
                        break
                    save(written_path, written)
                written = json.loads(written_path.read_text(encoding="utf-8"))
                questions = {entry["key"]: entry for entry in written["clauses"]}
                checked = complete(
                    "check",
                    article,
                    check_prompt,
                    CHECKED,
                    args.checker,
                    work / "empty",
                    functools.partial(article_text, article, questions=questions),
                    functools.partial(usable_checked, questions=questions),
                )
                if checked is None:
                    print(f"{stamp()} {article['key']} not checked, left for a rerun", flush=True)
                    left.append(article["key"])
                    break
                save(checked_path, checked)
                saved = sum(1 for _ in (work / "checked").glob("*.json"))
                print(
                    f"{stamp()} {saved}/{len(articles)} {article['key']} written and checked",
                    flush=True,
                )
                break
            except LimitReached as limit:
                print(
                    f"{stamp()} usage limit at {article['key']}, waiting 15 minutes: {limit}",
                    flush=True,
                )
                time.sleep(LIMIT_WAIT)

    if left:
        print(f"{stamp()} left for a rerun: {', '.join(left)}", flush=True)
    if sum(1 for _ in (work / "checked").glob("*.json")) < len(articles):
        return 0 if args.only else 2
    out = assemble(args.pack, articles, work)
    print(f"{stamp()} wrote {out.relative_to(REPO)}", flush=True)
    if args.sample:
        kept = [
            (entry["key"], lang, question)
            for entry in yaml.safe_load(out.read_text(encoding="utf-8"))["clauses"]
            for lang in ("en", "ar")
            for question in entry[lang]
        ]
        for key, lang, question in random.Random(args.pack).sample(
            kept, min(args.sample, len(kept))
        ):
            print(f"{key}\t{lang}\t{question}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
