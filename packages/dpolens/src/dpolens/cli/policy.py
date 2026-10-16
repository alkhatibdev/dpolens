"""An organisation's policies: read a file, upload it as a draft, review, publish, archive.

The commands act as the dashboard does, as the person at the shell, and every step is written
to the governance log with the operating system user and host.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer

from dpolens.engine.logs.governance import cli_actor
from dpolens.engine.originals import Directory
from dpolens.engine.policies import store
from dpolens.engine.policies.fixing import boundaries
from dpolens.engine.policies.parse import parse_policy
from dpolens.engine.policies.tree import Clause, Edit, ParsedPolicy
from dpolens.engine.session import session_scope
from dpolens.settings import load_settings

app = typer.Typer(
    name="policy",
    help="Upload, review and publish the organisation's own policies.",
    no_args_is_help=True,
)

LAYERS = {
    "native_structure": "file",
    "typography": "type",
    "numbering": "number",
    "reviewer": "you",
}
"""What decided a clause: the file's own structure, its type, a number in its text, or a
reviewer who fixed it."""

FLAGS = {
    "coverage_gap": "text",
    "numbering_gap": "numbering",
    "low_confidence_boundary": "boundary",
    "unmatched_key": "match",
}
WIDTH = 100

PolicyFile = Annotated[
    Path,
    typer.Argument(help="A Word (.docx) or Markdown (.md) file", exists=True, dir_okay=False),
]
Slug = Annotated[str, typer.Argument(help="The policy's slug, such as data-protection")]
EffectiveDate = Annotated[
    datetime | None,
    typer.Option(formats=["%Y-%m-%d"], help="When it takes effect, YYYY-MM-DD; today if left out"),
]
Label = Annotated[
    str | None,
    typer.Option("--label", help="The version label citations show; 1, 2 and so on if left out"),
]


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


def _day(value: datetime | None) -> date | None:
    return value.date() if value else None


@app.command()
def upload(
    path: PolicyFile,
    slug: Annotated[
        str | None, typer.Option(help="The slug every key begins with; from the file's name")
    ] = None,
    title: Annotated[str | None, typer.Option(help="The title; from the file if left out")] = None,
    effective_date: EffectiveDate = None,
    label: Label = None,
) -> None:
    """Upload a new policy. It becomes a draft, which nothing searches until it is published."""
    settings = load_settings()
    with session_scope(settings) as session:
        draft = store.upload_policy(
            session,
            Directory(settings.originals_dir),
            path.read_bytes(),
            path.name,
            actor=cli_actor(),
            slug=slug,
            title=title,
            effective_date=_day(effective_date),
            version_label=label,
        )
    show_draft(draft)


@app.command()
def revise(
    slug: Slug,
    path: PolicyFile,
    effective_date: EffectiveDate = None,
    label: Label = None,
    replace: Annotated[
        bool, typer.Option(help="Discard the policy's open draft and use this file instead")
    ] = False,
) -> None:
    """Upload a new version of a policy, as a draft matched to the version before it."""
    settings = load_settings()
    with session_scope(settings) as session:
        draft = store.upload_version(
            session,
            Directory(settings.originals_dir),
            slug,
            path.read_bytes(),
            path.name,
            actor=cli_actor(),
            effective_date=_day(effective_date),
            version_label=label,
            replace=replace,
        )
    show_draft(draft)


@app.command()
def draft(slug: Slug) -> None:
    """Show a policy's draft: its clauses, what changed, and what a reviewer must check."""
    with session_scope(load_settings()) as session:
        found = store.read_draft(session, slug)
    show_draft(found)


@app.command()
def accept(
    slug: Slug,
    positions: Annotated[
        list[int] | None, typer.Argument(help="The flags to accept, by their number")
    ] = None,
    every: Annotated[bool, typer.Option("--all", help="Accept every open flag")] = False,
) -> None:
    """Accept flags in a policy's draft, once someone has checked what each one says."""
    if not positions and not every:
        raise typer.BadParameter("Name the flags to accept by their number, or pass --all.")
    with session_scope(load_settings()) as session:
        found = store.accept_flags(session, slug, None if every else positions, actor=cli_actor())
    left = [flag.position for flag in found.flags if _open(flag)]
    if left:
        typer.echo(f"Still open: {', '.join(str(position) for position in left)}.")
    else:
        typer.echo(f"Every flag is settled. Publish with: dpolens policy publish {slug}")


@app.command(name="reject-match")
def reject_match(
    slug: Slug,
    key: Annotated[str, typer.Argument(help="The clause in the draft, such as 4.3")],
) -> None:
    """Say a clause of a new version is a different rule from the one it was matched to.

    It becomes new, and the earlier clause it was matched to becomes removed, so that a citation
    of the earlier clause says its rule was removed.
    """
    full = key if key.startswith(slug + ":") else f"{slug}:{key}"
    with session_scope(load_settings()) as session:
        before = {clause.key: clause for clause in _walk(store.read_draft(session, slug).clauses)}
        earlier = before[full].continues if full in before else None
        found = store.reject_match(session, slug, full, actor=cli_actor())
    gone = (earlier or "").removeprefix(slug + ":")
    typer.echo(f"{key} is new in the draft, and version {found.previous}'s {gone} is removed.")


@app.command(name="fix")
def fix(
    slug: Slug,
    key: Annotated[str, typer.Argument(help="The clause in the draft, such as 4.1")],
    how: Annotated[
        Edit,
        typer.Argument(
            help="split, merge, make-text, make-heading, move-under or move-out",
            show_default=False,
        ),
    ],
    before: Annotated[
        str | None,
        typer.Option(
            "--before",
            help='For split: the words the second part starts with, such as "4.2 The"',
        ),
    ] = None,
) -> None:
    """Fix how a clause of a draft was read, without changing a word.

    Split it where a second rule begins (--before), merge it with the clause before it, make a
    heading text or text a heading, or move it under the clause before it or out a level. Keys
    follow from where each clause ends up, and a flag on the clause is settled by the fix.
    """
    full = key if key.startswith(slug + ":") else f"{slug}:{key}"
    with session_scope(load_settings()) as session:
        at: int | None = None
        if how == "split":
            if not before:
                raise typer.BadParameter("Say where to split it, with --before WORDS.")
            clauses = {
                clause.key: clause for clause in _walk(store.read_draft(session, slug).clauses)
            }
            text = clauses[full].text if full in clauses else ""
            at = next(
                (found for found in boundaries(text) if text[found:].startswith(before)), None
            )
            if at is None:
                raise typer.BadParameter(
                    f"No sentence or paragraph of {key} starts with {before!r}."
                )
        fixed = store.fix_clause(session, slug, how, full, actor=cli_actor(), at=at)
    now = fixed.clause.removeprefix(slug + ":")
    said = {
        "split": f"Split {key}.",
        "merge": f"Merged {key} into {now}.",
        "make-text": f"{key} is text now, as {now}.",
        "make-heading": f"{key} is a heading now, as {now}.",
        "move-under": f"Moved {key} under the clause before it. Its key is {now}.",
        "move-out": f"Moved {key} out a level. Its key is {now}.",
    }
    typer.echo(said[how])
    left = [flag.position for flag in fixed.draft.flags if _open(flag)]
    typer.echo(
        f"Still open: {', '.join(str(position) for position in left)}."
        if left
        else f"Every flag is settled. Publish with: dpolens policy publish {slug}"
    )


@app.command()
def edit(
    slug: Slug,
    title: Annotated[str | None, typer.Option(help="A new title")] = None,
    effective_date: EffectiveDate = None,
    label: Label = None,
) -> None:
    """Change a draft's title, effective date or version label before it is published."""
    with session_scope(load_settings()) as session:
        found = store.edit_draft(
            session,
            slug,
            actor=cli_actor(),
            title=title,
            effective_date=_day(effective_date),
            version_label=label,
        )
    version = found.version
    typer.echo(
        f"{version.title}, draft version {version.number}, takes effect "
        f"{version.effective_date.isoformat()}"
        + (f", labelled {version.label}." if version.label else ".")
    )


@app.command()
def publish(slug: Slug) -> None:
    """Publish a policy's draft. From its effective date, searches find it and cite it."""
    with session_scope(load_settings()) as session:
        version = store.publish(session, slug, actor=cli_actor())
    typer.echo(
        f"Published version {version.label} of {version.title}, in force from "
        f"{version.effective_date.isoformat()}. Searching by words finds it now, and by meaning "
        "once the worker has embedded it."
    )


@app.command()
def discard(slug: Slug) -> None:
    """Discard a policy's draft. It is kept as discarded, and nothing searches it."""
    with session_scope(load_settings()) as session:
        store.discard(session, slug, actor=cli_actor())
    typer.echo(f"Discarded the draft of {slug}.")


@app.command()
def archive(slug: Slug) -> None:
    """Take a policy out of search. Its clauses still read by key, so citations still work."""
    with session_scope(load_settings()) as session:
        store.archive(session, slug, actor=cli_actor())
    typer.echo(f"Archived {slug}. Publishing a new version of it brings it back.")


@app.command(name="list")
def list_() -> None:
    """List the organisation's policies, with the version in force and any open draft."""
    with session_scope(load_settings()) as session:
        found = store.list_policies(session)
    if not found:
        typer.echo("No policies yet. Upload one with: dpolens policy upload FILE")
        return
    for summary in found:
        state = (
            "archived"
            if summary.status == "archived"
            else f"version {summary.in_force}"
            if summary.in_force
            else "not in force"
        )
        draft = f", draft {summary.draft}" if summary.draft else ""
        typer.echo(f"{summary.slug:28} {state + draft:24} {summary.title}")


@app.command()
def sample() -> None:
    """Publish the made-up sample policy, unless it was published before."""
    settings = load_settings()
    with session_scope(settings) as session:
        published = store.load_sample(session, Directory(settings.originals_dir), actor=cli_actor())
    if published:
        typer.echo(f"Published the sample policy, {store.SAMPLE_SLUG}.")
    else:
        typer.echo("The sample policy was published before, so it is left as it is.")


CHANGES = {"added": "new", "modified": "reworded", "unchanged": "same"}
RESOLVED = {
    "match-rejected": "said to be a different rule",
    "split": "split",
    "merged": "merged",
    "made-text": "made text",
    "made-heading": "made a heading",
    "moved-under": "moved under the clause before",
    "moved-out": "moved out a level",
}


def _open(flag: store.FlagView) -> bool:
    return flag.accepted_at is None and flag.resolved_at is None


def show_draft(found: store.DraftView) -> None:
    version = found.version
    typer.secho(f"{version.title} ({version.slug})", bold=True)
    checks = found.checks
    coverage = checks.get("coverage", {})
    kind = "Word" if version.source_format == "docx" else "Markdown"
    count = len(_walk(found.clauses))
    typer.secho(
        f"Draft version {version.number}, from {version.source_name}, takes effect "
        f"{version.effective_date.isoformat()}. {kind} file, {count} clauses",
        fg=typer.colors.BRIGHT_BLACK,
        nl=False,
    )
    missed = coverage.get("missed", 0)
    typer.secho(
        f", and {missed:,} characters not read." if missed else ".", fg=typer.colors.BRIGHT_BLACK
    )
    if found.previous:
        changes = found.changes
        typer.secho(
            f"Against version {found.previous}: {changes['added']} new, "
            f"{changes['modified']} reworded, {changes['moved']} renumbered, "
            f"{changes['unchanged']} the same, {changes['removed']} removed.",
            fg=typer.colors.BRIGHT_BLACK,
        )
    typer.echo("")
    for clause in found.clauses:
        draft_line(clause, version.slug, 0, compared=found.previous is not None)
    for gone in found.removed:
        typer.secho(
            f"Removed: {(gone['key'] or '').removeprefix(version.slug + ':')}  "
            f"{(gone['heading'] or gone['text'] or '')[:60]}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    for notice in checks.get("notices", []):
        typer.secho(notice, fg=typer.colors.BRIGHT_BLACK)
    typer.echo("")
    open_flags = [flag for flag in found.flags if _open(flag)]
    for flag in found.flags:
        where = flag.key.removeprefix(version.slug + ":") if flag.key else "the file"
        done = ""
        if flag.accepted_at:
            done = typer.style(f" (accepted by {flag.accepted_by})", dim=True)
        elif flag.resolved_at:
            done = typer.style(
                f" ({RESOLVED.get(flag.resolution or '', 'fixed')} by {flag.resolved_by})", dim=True
            )
        typer.echo(f"  {flag.position:>3}  {FLAGS[flag.kind]:<10} {where}  {flag.detail}{done}")
    if open_flags:
        typer.secho(
            f"\n{len(open_flags)} to settle before publishing. Accept them with: "
            f"dpolens policy accept {version.slug} NUMBER... (or --all)",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho(
            f"Nothing to settle. Publish with: dpolens policy publish {version.slug}",
            fg=typer.colors.GREEN,
        )


def _walk(clauses: tuple[store.DraftClause, ...]) -> list[store.DraftClause]:
    found: list[store.DraftClause] = []
    for clause in clauses:
        found.append(clause)
        found.extend(_walk(clause.children))
    return found


def draft_line(clause: store.DraftClause, slug: str, depth: int, *, compared: bool) -> None:
    key = clause.key.removeprefix(slug + ":")
    words = clause.heading or clause.text.replace("\n", " ")
    if compared and clause.change == "moved":
        note = f"was {(clause.continues or '').removeprefix(slug + ':')}"
    elif compared:
        note = CHANGES.get(clause.change or "", "")
    else:
        note = LAYERS.get(clause.layer or "", "")
    lead = f"{'  ' * depth}{key}  "
    room = WIDTH - len(lead) - 14
    if len(words) > room:
        words = words[: max(room - 1, 10)].rstrip() + "…"
    typer.echo(f"{lead}{words:<{max(room, 0)}}  " + typer.style(note, dim=True))
    for child in clause.children:
        draft_line(child, slug, depth + 1, compared=compared)
