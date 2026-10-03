"""Keep the guidance every client carries in one place.

The same instruction has to reach an assistant three ways: sent on connect by
the MCP server, carried by the Claude Code plugin, and written in the Cursor
rules file, which is read without connecting to anything. The sentences live in
`dpolens_mcp.instructions`, and this writes the files that repeat them.

    uv run python scripts/client_text.py            # check, which is what the tests do
    uv run python scripts/client_text.py --write    # after changing the words

Editing one of the generated files by hand is fine as long as the change belongs
in all of them: make it in `instructions.py` and run this.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from dpolens_mcp.instructions import (
    CITE,
    EXAMPLES,
    LOGGED,
    NO_MEMORY,
    NOT_LEGAL_ADVICE,
    PERSONAL_DATA,
    POLICY_CHECK,
    POLICY_TOUR,
    TRIGGER,
)

REPO = Path(__file__).resolve().parents[1]
CLIENTS = REPO / "clients"
WIDTH = 95
"""Where the lines are broken, so a generated file reads like a written one."""


def wrapped(sentence: str) -> str:
    return textwrap.fill(sentence, width=WIDTH)


TRIGGER_TEXT = wrapped(TRIGGER)
PERSONAL_DATA_TEXT = wrapped(PERSONAL_DATA)
NO_MEMORY_TEXT = wrapped(NO_MEMORY)
CITE_TEXT = wrapped(CITE)
NOT_LEGAL_ADVICE_TEXT = wrapped(NOT_LEGAL_ADVICE)
LOGGED_TEXT = wrapped(LOGGED)

HOW_TO_SEARCH = f"""Questions that work well:

- {EXAMPLES[0]}
- {EXAMPLES[1]}
- {EXAMPLES[2]}

Search the organisation's own policies as well as the law. A policy can be stricter than the
law, and the stricter rule is the one the code has to meet. Say plainly when you found nothing
about part of a change: a gap in the policies is worth knowing and is not the same as
approval."""


def skill() -> str:
    """The Claude Code skill, which is how an assistant knows to reach for DPOLens."""
    return f"""---
name: dpolens
description: >-
  Search this organisation's privacy policies and the privacy law that applies to it, through
  DPOLens, and cite the clause. Use when writing or changing code that collects, stores, logs,
  shares or deletes personal data, when choosing a retention period, when adding a field or a
  column that holds personal data, when sending data to another service, and when asked what a
  policy or the law requires.
---

# DPOLens

{TRIGGER_TEXT}

{PERSONAL_DATA_TEXT}

{NO_MEMORY_TEXT}

{CITE_TEXT}

## How to search

Call `search_policies` with the question in ordinary words, the way somebody would ask it.
What comes back is the clause itself, with a citation line, the document, the version and the
date that version took effect. Quote it rather than paraphrasing it.

`get_clause` reads one clause by its key, with the clauses around it, which is what you want
when a result points at another clause or when you need a whole article. `list_documents` and
`get_document` say what this instance can cite at all.

{HOW_TO_SEARCH}

{NOT_LEGAL_ADVICE_TEXT}

{LOGGED_TEXT}
"""


def cursor_rule() -> str:
    """The Cursor rule, which is read whether or not the server is connected."""
    return f"""---
description: >-
  How to use DPOLens, which holds this organisation's privacy policies and the privacy law that
  applies to it, and when to search it.
alwaysApply: true
---

# DPOLens

{TRIGGER_TEXT}

{PERSONAL_DATA_TEXT}

{NO_MEMORY_TEXT}

{CITE_TEXT}

Use the `dpolens` MCP server's tools: `search_policies` for a question in ordinary words,
`get_clause` to read one clause by its key with the clauses around it, and `list_documents`
or `get_document` to see what this instance can cite.

{HOW_TO_SEARCH}

{NOT_LEGAL_ADVICE_TEXT}

{LOGGED_TEXT}
"""


def policy_check_command() -> str:
    return f"""---
description: Check the change you are working on against the policies and the law
argument-hint: "[a file or area to look at]"
---

{POLICY_CHECK}

$ARGUMENTS
"""


def policy_tour_command() -> str:
    return f"""---
description: Show what this DPOLens instance holds, with a few real searches
---

{POLICY_TOUR}
"""


def files() -> dict[Path, str]:
    return {
        CLIENTS / "claude-code" / "skills" / "dpolens" / "SKILL.md": skill(),
        CLIENTS / "claude-code" / "commands" / "policy-check.md": policy_check_command(),
        CLIENTS / "claude-code" / "commands" / "policy-tour.md": policy_tour_command(),
        CLIENTS / "cursor" / "dpolens.mdc": cursor_rule(),
    }


def stale() -> list[Path]:
    """The files that no longer say what the instructions say."""
    behind = []
    for path, content in files().items():
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            behind.append(path)
    return behind


def write() -> list[Path]:
    written = []
    for path, content in files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write the files")
    arguments = parser.parse_args()

    if arguments.write:
        for path in write():
            print(f"wrote {path.relative_to(REPO)}")
        return 0

    behind = stale()
    if behind:
        print(
            "these files no longer match the instructions the MCP server sends:\n"
            + "\n".join(f"  {path.relative_to(REPO)}" for path in behind)
            + "\nRun `uv run python scripts/client_text.py --write`.",
            file=sys.stderr,
        )
        return 1

    print("every client carries the same guidance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
