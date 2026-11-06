"""Starting a pack: the files a contributor fills in, written once.

A new pack begins as `pack.yaml`, a folder for its first document and the eval sets a pack
needs before it is accepted. Every value only the contributor can know is left commented out
in `pack.yaml`, so the pack does not load until each is filled in, and the loader names what
is still missing. A pack half started cannot be loaded, released or merged by accident.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dpolens.engine.packs.format import REGIONS, PackFormatError

PACK_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
"""The first part of every key in the pack, so it takes what a key's parts take."""

LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]+)?$")

PACK_YAML = """\
# A DPOLens pack. packs/README.md says what each field means, and packs/BUILDING.md
# how to fill in the ones left commented out: the pack does not load until they are.
format: 2
slug: {slug}
# The law as its official text names it, as people call it, and where it applies, in each
# language the pack has a text in and in English.
name:
  {lang}: {name_value}{english_name}
short_name:
  {lang}: {short_name_value}{english_short_name}
jurisdiction:
  {lang}: {jurisdiction_value}{english_jurisdiction}
region: {region}
version: "{year}.1"
# effective_date: the day the law's text started to apply, such as 2018-05-25
trust_tier: community
# source_url: the official text, where the state publishes it
# license: >-
#   Why the text may be republished: the provision that excludes laws from
#   copyright, or the licence the state gives it, and which language prevails.
authoritative_language: {lang}
translations: []

documents:
  - slug: {slug}
    title:
      {lang}: {name_value}{english_title}
    normative: true
    # expected_clauses: how many clause files packs/{slug}/{slug}/ holds
"""

IN_ENGLISH_TOO = {
    "name": "\n  # en: the law's official name in English",
    "short_name": "\n  # en: what people call the law in English, such as LGPD",
    "jurisdiction": "\n  # en: where the law applies, in English",
    "title": "\n      # en: the document's official title in English",
}
"""What a law whose text is not English still needs: every interface is in English."""

EVAL_SETS = {
    "tuning": """\
# Tuning questions, asked in {lang}, the language the law's text prevails in: the set
# used while improving search, which holds at least 20 before any score is published.
# evals/README.md says how to write one. The clause a question expects comes from
# guidance that names it, never from what search returns.
questions: []
""",
    "held_out": """\
# Held-out questions, asked in {lang}, the language the law's text prevails in: the set
# behind the published score, and nothing else, which holds at least 30 before any score
# is published. evals/README.md says how to write one. The clause a question expects
# comes from guidance that names it, never from what search returns.
questions: []
""",
}
"""Each set a pack needs before it is accepted, as a contributor first sees it."""

IN_ENGLISH = """\
# The {kind} questions again, asked in English as people ask in it, under the same ids,
# labels and sources. evals/README.md says how to write one.
questions: []
"""


@dataclass(frozen=True)
class NewPack:
    slug: str
    name: str
    """The law's official name, in the language whose text prevails."""
    short_name: str
    jurisdiction: str
    lang: str
    """The language whose text prevails in law."""
    region: str


def start_pack(
    pack: NewPack, packs_dir: Path, evals_dir: Path, today: date | None = None
) -> list[Path]:
    """Write a new pack's files, and say which, leaving any pack that exists as it is."""
    if not PACK_SLUG.match(pack.slug):
        raise PackFormatError(
            f"'{pack.slug}' cannot start a key: a pack's slug is lower-case letters, digits and "
            "hyphens, named after its law, such as lgpd or sg-pdpa"
        )
    if not LANGUAGE.match(pack.lang):
        raise PackFormatError(f"'{pack.lang}' is not a language code, such as pt or ar")
    if pack.region not in REGIONS:
        raise PackFormatError(f"'{pack.region}' is not a region: one of {', '.join(REGIONS)}")

    pack_dir = packs_dir / pack.slug
    sets_dir = evals_dir / pack.slug
    for existing in (pack_dir, sets_dir):
        if existing.exists():
            raise PackFormatError(f"{existing} already exists, and a pack is started once")

    year = (today or date.today()).year
    document = pack_dir / pack.slug
    document.mkdir(parents=True)
    metadata = pack_dir / "pack.yaml"
    english = {} if pack.lang == "en" else IN_ENGLISH_TOO
    metadata.write_text(
        PACK_YAML.format(
            slug=pack.slug,
            name_value=_scalar(pack.name),
            short_name_value=_scalar(pack.short_name),
            jurisdiction_value=_scalar(pack.jurisdiction),
            region=pack.region,
            year=year,
            lang=pack.lang,
            **{f"english_{name}": english.get(name, "") for name in IN_ENGLISH_TOO},
        ),
        encoding="utf-8",
    )

    sets_dir.mkdir(parents=True)
    written = [metadata, document]
    for kind, template in EVAL_SETS.items():
        path = sets_dir / f"{kind}.yaml"
        path.write_text(template.format(lang=pack.lang), encoding="utf-8")
        written.append(path)
        if pack.lang != "en":
            path = sets_dir / f"{kind}.en.yaml"
            path.write_text(IN_ENGLISH.format(kind=kind.replace("_", "-")), encoding="utf-8")
            written.append(path)
    return written


def _scalar(value: str) -> str:
    """A value YAML reads back as written, colons and quotes included: JSON's string is
    one of YAML's."""
    return json.dumps(value, ensure_ascii=False)
