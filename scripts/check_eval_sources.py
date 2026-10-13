"""Check where each eval question's label comes from.

A question's label is the clause that counts as the right answer, and it must
not be the search author's opinion. There are two admissible kinds of evidence,
and this reports which one each question rests on:

  cited      the guidance page names the article, which a machine can confirm
  justified  the guidance answers the question without printing the number, and
             the note records why that clause is the answer

A question with neither is rejected. The split is published, so a reader can see
how much of the set rests on a regulator's words and how much on reasoning.

A question may also quote its source. The quote is the evidence a reader checks,
so a quote the page does not contain is rejected too.
"""

from __future__ import annotations

import html
import re
import sys
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).parents[1]
AGENT = "Mozilla/5.0 (compatible; DPOLens eval source check)"
TIMEOUT = 40


def article_of(key: str) -> str | None:
    found = re.search(r"art-(\d+)", key)
    return found.group(1) if found else None


def page_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read().decode("utf-8", errors="replace")
    return plain(html.unescape(re.sub(r"<[^>]+>", " ", body)))


def plain(text: str) -> str:
    """One space between words and straight quotes, however the page sets them."""
    for curly, straight in (("\u2018", "'"), ("\u2019", "'"), ("\u201c", '"'), ("\u201d", '"')):
        text = text.replace(curly, straight)
    return re.sub(r"\s+", " ", text).strip()


def names_article(text: str, article: str) -> bool:
    return bool(re.search(rf"Article\s*{article}\b", text))


def quoted(quote: str, text: str) -> bool:
    """Whether the page holds the quote. "..." marks words left out between parts."""
    parts = (part.strip() for part in plain(quote).split("..."))
    return all(part in text for part in parts if part)


def check(path: Path) -> tuple[int, int, list[str]]:
    questions = yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]
    cited = justified = 0
    problems = []

    for question in questions:
        article = article_of(question["expected_keys"][0])
        names = False
        if article or question.get("quote"):
            try:
                text = page_text(question["source"])
            except Exception as problem:
                problems.append(f"{question['id']}: source unreachable ({type(problem).__name__})")
                continue
            names = bool(article) and names_article(text, article)
            if question.get("quote") and not quoted(question["quote"], text):
                problems.append(f"{question['id']}: the source does not contain the quote")
                continue

        if names:
            cited += 1
            print(f"  cited      {question['id']:24} article {article}")
        elif question.get("note"):
            justified += 1
            print(f"  justified  {question['id']:24} article {article}")
        else:
            problems.append(
                f"{question['id']}: the source does not name article {article} and there is "
                "no note explaining why this clause is the answer"
            )

    return cited, justified, problems


def main() -> int:
    failures = []
    for path in sorted((REPO / "evals").glob("*/*.yaml")):
        if path.parent.name == "trigger":
            # The trigger test's tasks are not retrieval questions and carry no labels.
            continue
        print(f"\n{path.relative_to(REPO)}")
        cited, justified, problems = check(path)
        total = cited + justified
        if total:
            print(f"  {cited} cited, {justified} justified ({cited / total:.0%} cited)")
        for problem in problems:
            print(f"  REJECTED   {problem}")
        failures.extend(problems)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
