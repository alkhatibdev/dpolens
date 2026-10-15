"""Reading an organisation's policy file, before anything is stored."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from dpolens.engine.policies.parse import parse_policy
from dpolens.engine.policies.tree import Clause, ParsedPolicy

app = typer.Typer(name="policy", help="Read organisation policies.", no_args_is_help=True)

LAYERS = {"native_structure": "file", "typography": "type", "numbering": "number"}
"""What decided a clause: the file's own structure, its type, or a number in its text."""

FLAGS = {
    "coverage_gap": "text",
    "numbering_gap": "numbering",
    "low_confidence_boundary": "boundary",
}
WIDTH = 100


@app.command()
def parse(
    path: Annotated[
        Path, typer.Argument(help="A Word (.docx) or Markdown (.md) file", exists=True)
    ],
    slug: Annotated[
        str | None, typer.Option(help="The document's slug, which begins every key")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print everything as JSON")] = False,
) -> None:
    """Show how DPOLens reads a policy: its clauses and keys, and what a reviewer must check."""
    policy = parse_policy(path.read_bytes(), path.name, slug)
    if as_json:
        typer.echo(json.dumps(asdict(policy), ensure_ascii=False, indent=2))
        return
    show(policy)


def show(policy: ParsedPolicy) -> None:
    clauses = policy.walk()
    if policy.title:
        typer.secho(policy.title, bold=True)
    kind = "Word" if policy.format == "docx" else "Markdown"
    coverage = policy.coverage
    typer.secho(
        f"{kind} file, {len(clauses)} clauses. Of its {coverage.characters:,} characters, "
        f"{coverage.in_clauses:,} are in clauses and {coverage.set_aside:,} set aside"
        + (f", and {coverage.missed:,} were not read." if coverage.missed else "."),
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.echo("")
    for clause in policy.clauses:
        line(clause, policy.slug, 0)
    if policy.set_aside:
        typer.echo("")
        reasons: dict[str, int] = {}
        for block in policy.set_aside:
            written = sum(1 for text in block.text.split("\n") if text.strip())
            reasons[block.reason] = reasons.get(block.reason, 0) + written
        listed = ", ".join(
            f"{reason} ({count} paragraph{'s' if count > 1 else ''})"
            for reason, count in reasons.items()
        )
        typer.secho(f"Set aside, not searched: {listed}.", fg=typer.colors.BRIGHT_BLACK)
    for notice in policy.notices:
        typer.secho(notice, fg=typer.colors.BRIGHT_BLACK)
    typer.echo("")
    if not policy.flags:
        typer.secho("Nothing for a reviewer to settle.", fg=typer.colors.GREEN)
        return
    count = len(policy.flags)
    typer.secho(f"For a reviewer to settle ({count}):", fg=typer.colors.YELLOW)
    for flag in policy.flags:
        where = flag.key.removeprefix(policy.slug + ":") if flag.key else "the file"
        typer.echo(f"  {FLAGS[flag.kind]:<10} {where}  {flag.detail}")


def line(clause: Clause, slug: str, depth: int) -> None:
    key = clause.key.removeprefix(slug + ":")
    words = clause.heading or clause.text.replace("\n", " ")
    lead = f"{'  ' * depth}{key}  "
    room = WIDTH - len(lead) - 8
    if len(words) > room:
        words = words[: max(room - 1, 10)].rstrip() + "…"
    typer.echo(f"{lead}{words:<{max(room, 0)}}  " + typer.style(LAYERS[clause.layer], dim=True))
    for child in clause.children:
        line(child, slug, depth + 1)
