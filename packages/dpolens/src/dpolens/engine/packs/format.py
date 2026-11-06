"""Reading pack files.

A clause exists because a heading declares it, never because the prose looked
like one. Every failure here names the file and says what was expected, since
the reader is usually a contributor building a pack for their own jurisdiction.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import yaml

FORMAT = 2
"""The pack format this engine reads. A pack says which it is written in, so a pack written
for another engine is refused by name rather than read wrongly."""

SEGMENT_TYPES = {
    "art": "article",
    "para": "paragraph",
    "sub": "subparagraph",
    "pt": "point",
    "sec": "section",
    "rule": "rule",
    "reg": "regulation",
    "sch": "schedule",
    "cl": "clause",
    "suppl": "supplementary provisions",
    "ch": "chapter",
    "rec": "recital",
    "annex": "annex",
}

REGIONS = ("Africa", "Americas", "Asia Pacific", "Europe", "Middle East")
"""Where a law is listed. A fixed list, so an interface can name each in its own language."""

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
ANY_HEADING = re.compile(r"^#{1,6}[ \t]")
HEADING = re.compile(r"^(#{2,6})[ \t]+(.*?)[ \t]*\{#([a-z0-9][a-z0-9-]*)\}[ \t]*$")
KEY = re.compile(r"^[a-z0-9][a-z0-9-]*(?::[a-z0-9][a-z0-9-]*)+$")
LANG = r"[a-z]{2,3}(?:-[a-z0-9]+)?"
TRANSLATION_FILE = re.compile(rf"^(?P<stem>[^.@]+)\.(?P<lang>{LANG})\.md$")
"""`art-5.en.md` holds the English translation of `art-5.md`, under the same keys."""
COMING_FILE = re.compile(
    rf"^(?P<stem>[^.@]+)@(?P<date>\d{{4}}-\d{{2}}-\d{{2}})(?:\.(?P<lang>{LANG}))?\.md$"
)
"""`art-17@2027-01-17.md` holds Article 17 as an amendment words it from 17 January 2027, and
`art-17@2027-01-17.en.md` its translation. The text in force until then stays in `art-17.md`."""

TRANSLATION_STATUSES = {
    "official": "official_translation",
    "unofficial": "unofficial_translation",
}


class PackFormatError(Exception):
    """A pack file could not be read as written."""


@dataclass(frozen=True)
class CrossReference:
    key: str
    text: str


@dataclass(frozen=True)
class Clause:
    key: str
    clause_type: str
    label: str | None
    heading: str | None
    body_text: str
    lang: str
    normative: bool
    cross_references: tuple[CrossReference, ...] = ()
    children: tuple[Clause, ...] = ()

    def walk(self) -> list[Clause]:
        """This clause and everything beneath it, depth first."""
        found = [self]
        for child in self.children:
            found.extend(child.walk())
        return found


@dataclass(frozen=True)
class Commencement:
    """When some provisions start or stop applying, as whatever set those dates says.

    A key covers everything beneath it, and the most specific key wins, so a law can start
    on one date while one of its sub-sections starts on another.
    """

    keys: tuple[str, ...]
    source: str
    """What set the dates: the law's own article, a separate notice, a rule of the text."""
    starts: date | None = None
    pending: bool = False
    """The provisions do not apply yet, and nothing has set the day they will."""
    ends: date | None = None


@dataclass(frozen=True)
class Dates:
    """When one text applies. No start means from the pack's effective date."""

    starts: date | None = None
    pending: bool = False
    ends: date | None = None
    source: str | None = None
    """What set these dates, when anything other than the pack's effective date did."""


@dataclass(frozen=True)
class PackDocument:
    slug: str
    title: dict[str, str]
    """The document's official title in each language the pack names it in."""
    normative: bool
    expected_clauses: int
    source_url: str | None = None
    source_sha256: str | None = None
    """Where this document's text came from, so a rebuild can prove it used the same file."""
    commencement: tuple[Commencement, ...] = ()

    def dates_of(self, key: str) -> Dates:
        """When the text under `key` applies, from the most specific entry naming it."""
        covering = [
            (entry, named)
            for entry in self.commencement
            for named in entry.keys
            if key == named or key.startswith(f"{named}:")
        ]
        starting = max(
            ((entry, named) for entry, named in covering if entry.starts or entry.pending),
            key=lambda pair: pair[1].count(":"),
            default=None,
        )
        ending = max(
            ((entry, named) for entry, named in covering if entry.ends),
            key=lambda pair: pair[1].count(":"),
            default=None,
        )
        sources = [pair[0].source for pair in (starting, ending) if pair is not None]
        return Dates(
            starts=starting[0].starts if starting else None,
            pending=starting[0].pending if starting else False,
            ends=ending[0].ends if ending else None,
            source="; ".join(dict.fromkeys(sources)) or None,
        )


@dataclass(frozen=True)
class PackTranslation:
    """A translation the pack carries beside the text that prevails."""

    lang: str
    status: str
    """official, when the state published it, or unofficial."""
    license: str
    source_url: str | None = None

    @property
    def translation_status(self) -> str:
        return TRANSLATION_STATUSES[self.status]


@dataclass(frozen=True)
class PackMetadata:
    slug: str
    name: dict[str, str]
    """The law's official name in each language: its number and the short title it gives
    itself, where it gives one, else its title as printed."""
    short_name: dict[str, str]
    """What people call the law and search for, such as GDPR or UAE PDPL."""
    jurisdiction: dict[str, str]
    region: str
    version: str
    effective_date: date
    trust_tier: str
    source_url: str
    license: str
    authoritative_language: str
    documents: tuple[PackDocument, ...]
    translations: tuple[PackTranslation, ...] = field(default=())

    @property
    def languages(self) -> tuple[str, ...]:
        """The languages the pack has text in, the one that prevails first."""
        return (self.authoritative_language, *(t.lang for t in self.translations))


REQUIRED_PACK_FIELDS = (
    "format",
    "slug",
    "name",
    "short_name",
    "jurisdiction",
    "region",
    "version",
    "effective_date",
    "trust_tier",
    "source_url",
    "license",
    "authoritative_language",
    "documents",
)
NAMED_FIELDS = ("name", "short_name", "jurisdiction")
"""The fields written once per language, as a map from language to text."""
TRUST_TIERS = ("verified", "community")


def clause_type_for(segment: str) -> str:
    prefix = segment.split("-", 1)[0]
    clause_type = SEGMENT_TYPES.get(prefix)
    if clause_type is None:
        raise PackFormatError(
            f"unknown key segment '{segment}': expected one of "
            f"{', '.join(sorted(SEGMENT_TYPES))} followed by a number or letter"
        )
    return clause_type


def read_pack_metadata(pack_dir: Path) -> PackMetadata:
    path = pack_dir / "pack.yaml"
    if not path.is_file():
        raise PackFormatError(f"{pack_dir} has no pack.yaml")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise PackFormatError(f"{path} holds a list or a value, where it holds fields by name")
    if "format" not in raw:
        raise PackFormatError(
            f"{path} says no pack format, and this engine reads format {FORMAT}. A pack "
            "without one was written for DPOLens 0.2.0 or earlier"
        )
    if raw["format"] != FORMAT:
        raise PackFormatError(
            f"{path} says pack format {raw['format']}, and this engine reads format {FORMAT}. "
            "Use the DPOLens release it was written for"
        )
    missing = [name for name in REQUIRED_PACK_FIELDS if name not in raw]
    if missing:
        raise PackFormatError(f"{path} is missing required fields: {', '.join(missing)}")
    # A licence or a source left empty is as missing as one left out, and both are what the
    # licensing gate exists to check.
    empty = [
        name
        for name in REQUIRED_PACK_FIELDS
        if name not in ("documents", *NAMED_FIELDS) and not str(raw[name] or "").strip()
    ]
    if empty:
        raise PackFormatError(f"{path} leaves required fields empty: {', '.join(empty)}")

    if raw["trust_tier"] not in TRUST_TIERS:
        raise PackFormatError(
            f"{path}: trust_tier must be one of {', '.join(TRUST_TIERS)}, not {raw['trust_tier']!r}"
        )
    if raw["region"] not in REGIONS:
        raise PackFormatError(
            f"{path}: region must be one of {', '.join(REGIONS)}, not {raw['region']!r}"
        )

    effective_date = raw["effective_date"]
    if not isinstance(effective_date, date):
        raise PackFormatError(f"{path}: effective_date must be a date, for example 2018-05-25")

    translations = _read_translation_entries(path, raw)
    # Every interface is in English, so a law is named in English as well as in each
    # language it has a text in.
    languages = tuple(
        dict.fromkeys((str(raw["authoritative_language"]), *(t.lang for t in translations), "en"))
    )
    names = {name: _named(path, name, raw[name], languages) for name in NAMED_FIELDS}
    if len({frozenset(named) for named in names.values()}) > 1:
        raise PackFormatError(
            f"{path}: name, short_name and jurisdiction name the law in different languages. "
            "Each names it in the same ones, so a screen in any of them has all three"
        )

    documents = tuple(
        _read_document_entry(path, entry, languages) for entry in raw["documents"] or ()
    )
    if not documents:
        raise PackFormatError(f"{path}: a pack needs at least one document")

    return PackMetadata(
        slug=str(raw["slug"]),
        name=names["name"],
        short_name=names["short_name"],
        jurisdiction=names["jurisdiction"],
        region=str(raw["region"]),
        version=str(raw["version"]),
        effective_date=effective_date,
        trust_tier=str(raw["trust_tier"]),
        source_url=str(raw["source_url"]),
        license=str(raw["license"]),
        authoritative_language=str(raw["authoritative_language"]),
        documents=documents,
        translations=translations,
    )


def _named(
    path: Path, name: str, value: Any, languages: tuple[str, ...], what: str | None = None
) -> dict[str, str]:
    """A field written once per language, checked to name every language it has to."""
    what = what or name
    if not isinstance(value, dict):
        raise PackFormatError(
            f"{path}: {what} is written once per language, for example\n"
            f"{name}:" + "".join(f"\n  {lang}: ..." for lang in languages)
        )
    named = {
        str(lang): str(text).strip()
        for lang, text in value.items()
        if text is not None and str(text).strip()
    }
    missing = [lang for lang in languages if not named.get(lang)]
    if missing:
        raise PackFormatError(
            f"{path}: {what} has nothing for {', '.join(missing)}. A pack names its law in "
            "each language it has a text in, and in English, since every interface is English"
        )
    return named


def _read_translation_entries(path: Path, raw: dict[str, Any]) -> tuple[PackTranslation, ...]:
    translations = []
    for entry in raw.get("translations") or ():
        if not isinstance(entry, dict) or not all(
            str(entry.get(name) or "").strip() for name in ("lang", "status", "license")
        ):
            raise PackFormatError(
                f"{path}: each translation needs a 'lang', a 'status' and a 'license'"
            )
        if entry["status"] not in TRANSLATION_STATUSES:
            raise PackFormatError(
                f"{path}: translation status must be one of "
                f"{', '.join(TRANSLATION_STATUSES)}, not {entry['status']!r}"
            )
        if entry["lang"] == raw["authoritative_language"]:
            raise PackFormatError(
                f"{path}: '{entry['lang']}' is the authoritative language, not a translation"
            )
        translations.append(
            PackTranslation(
                lang=str(entry["lang"]),
                status=str(entry["status"]),
                license=str(entry["license"]),
                source_url=str(entry["source_url"]) if entry.get("source_url") else None,
            )
        )
    return tuple(translations)


def _read_document_entry(
    path: Path, entry: dict[str, Any], languages: tuple[str, ...]
) -> PackDocument:
    for name in ("slug", "title", "expected_clauses"):
        if name not in entry:
            raise PackFormatError(f"{path}: document entry is missing '{name}'")
    slug = str(entry["slug"])
    return PackDocument(
        slug=slug,
        title=_named(path, "title", entry["title"], languages, what=f"the title of {slug}"),
        normative=bool(entry.get("normative", True)),
        expected_clauses=int(entry["expected_clauses"]),
        source_url=str(entry["source_url"]) if entry.get("source_url") else None,
        source_sha256=str(entry["source_sha256"]) if entry.get("source_sha256") else None,
        commencement=tuple(
            _read_commencement(path, slug, item) for item in entry.get("commencement") or ()
        ),
    )


def _read_commencement(path: Path, slug: str, item: Any) -> Commencement:
    where = f"{path}: a commencement entry of {slug}"
    if not isinstance(item, dict):
        raise PackFormatError(f"{where} is a list of from or until, keys and source")
    starts, ends = item.get("from"), item.get("until")
    if starts is None and ends is None:
        raise PackFormatError(f"{where} needs a 'from' date, 'from: pending', or an 'until' date")
    pending = starts == "pending"
    for name, value in (("from", None if pending else starts), ("until", ends)):
        if value is not None and not isinstance(value, date):
            raise PackFormatError(
                f"{where}: '{name}' must be a date, for example 2027-05-13"
                + (", or pending" if name == "from" else "")
            )
    keys = item.get("keys")
    if not isinstance(keys, list) or not keys:
        raise PackFormatError(f"{where} lists no keys")
    if not str(item.get("source") or "").strip():
        raise PackFormatError(
            f"{where} needs a 'source': what set these dates, so they can be checked"
        )
    if isinstance(starts, date) and isinstance(ends, date) and ends <= starts:
        raise PackFormatError(f"{where} ends on {ends}, which is not after it starts")
    return Commencement(
        keys=tuple(str(key) for key in keys),
        source=str(item["source"]).strip(),
        starts=starts if isinstance(starts, date) else None,
        pending=pending,
        ends=ends,
    )


def read_clause_file(path: Path, document_normative: bool = True) -> Clause:
    """Read one clause file into a clause and its children."""
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    if match is None:
        raise PackFormatError(
            f"{path}: a clause file starts with YAML front matter between --- lines"
        )

    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)

    for name in ("key", "lang"):
        if name not in meta:
            raise PackFormatError(f"{path}: front matter is missing '{name}'")

    key = str(meta["key"])
    if not KEY.match(key):
        raise PackFormatError(
            f"{path}: '{key}' is not a canonical key. Expected a document slug and at "
            "least one segment, such as gdpr:art-17"
        )

    normative = bool(meta.get("normative", document_normative))
    root_text, children = _read_body(
        path, body, parent_key=key, lang=str(meta["lang"]), normative=normative
    )

    clause = Clause(
        key=key,
        clause_type=clause_type_for(key.split(":")[-1]),
        label=str(meta["label"]) if meta.get("label") else None,
        heading=str(meta["title"]) if meta.get("title") else None,
        body_text=root_text,
        lang=str(meta["lang"]),
        normative=normative,
        children=children,
    )
    _reject_repeated_keys(path, clause)
    return _attach_cross_references(
        path, clause, _read_cross_references(path, meta.get("cross_references") or [])
    )


def _reject_repeated_keys(path: Path, clause: Clause) -> None:
    seen: set[str] = set()
    for found in clause.walk():
        if found.key in seen:
            raise PackFormatError(
                f"{path}: '{found.key}' appears twice. A key identifies one clause, and "
                "citations to it must never become ambiguous"
            )
        seen.add(found.key)


def _read_cross_references(
    path: Path, entries: list[Any]
) -> dict[str | None, list[CrossReference]]:
    """Group the file's links by the clause that states each one.

    An entry without a `from` is stated by the file's own clause.
    """
    grouped: dict[str | None, list[CrossReference]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or "key" not in entry or "text" not in entry:
            raise PackFormatError(
                f"{path}: each cross reference needs a 'key' and the 'text' as written"
            )
        stated_by = str(entry["from"]) if entry.get("from") else None
        reference = CrossReference(key=str(entry["key"]), text=str(entry["text"]))
        grouped.setdefault(stated_by, []).append(reference)
    return grouped


def _attach_cross_references(
    path: Path, clause: Clause, grouped: dict[str | None, list[CrossReference]]
) -> Clause:
    """Give every link to the clause that states it."""
    keys = {found.key for found in clause.walk()}
    for stated_by in grouped:
        if stated_by is not None and stated_by not in keys:
            raise PackFormatError(
                f"{path}: a cross reference says it comes from '{stated_by}', which is "
                "not a clause in this file"
            )

    def rebuild(current: Clause, is_root: bool) -> Clause:
        found = grouped.get(None, []) if is_root else grouped.get(current.key, [])
        return replace(
            current,
            cross_references=tuple(found),
            children=tuple(rebuild(child, is_root=False) for child in current.children),
        )

    return rebuild(clause, is_root=True)


@dataclass
class _Section:
    level: int
    label: str
    segment: str
    lines: list[str]


def _read_body(
    path: Path, body: str, parent_key: str, lang: str, normative: bool
) -> tuple[str, tuple[Clause, ...]]:
    """Split a body into the clause's own text and its child clauses."""
    own_lines: list[str] = []
    sections: list[_Section] = []

    for number, line in enumerate(body.splitlines(), start=1):
        heading = HEADING.match(line)
        if heading is None:
            if ANY_HEADING.match(line):
                raise PackFormatError(
                    f"{path} line {number}: a heading opens a clause, so it needs a key "
                    "segment anchor, for example '## 1. {#para-1}'. Text that is not a "
                    "clause belongs in the body."
                )
            (sections[-1].lines if sections else own_lines).append(line)
            continue

        hashes, label, segment = heading.groups()
        sections.append(_Section(level=len(hashes), label=label, segment=segment, lines=[]))

    _reject_skipped_levels(path, sections)

    return "\n".join(own_lines).strip(), _build_tree(sections, parent_key, lang, normative)


def _reject_skipped_levels(path: Path, sections: list[_Section]) -> None:
    previous = 1
    for section in sections:
        if section.level > previous + 1:
            raise PackFormatError(
                f"{path}: heading '{section.label}' jumps from level {previous} to "
                f"{section.level}. Clause depth follows heading depth, so levels cannot be skipped"
            )
        previous = section.level


def _build_tree(
    sections: list[_Section], parent_key: str, lang: str, normative: bool
) -> tuple[Clause, ...]:
    roots: list[Clause] = []
    open_clauses: list[tuple[_Section, str, list[Clause]]] = []

    def close(down_to: int) -> None:
        while open_clauses and open_clauses[-1][0].level >= down_to:
            section, key, children = open_clauses.pop()
            clause = Clause(
                key=key,
                clause_type=clause_type_for(section.segment),
                label=section.label or None,
                heading=None,
                body_text="\n".join(section.lines).strip(),
                lang=lang,
                normative=normative,
                children=tuple(children),
            )
            siblings = open_clauses[-1][2] if open_clauses else roots
            siblings.append(clause)

    for section in sections:
        close(down_to=section.level)
        parent = open_clauses[-1][1] if open_clauses else parent_key
        open_clauses.append((section, f"{parent}:{section.segment}", []))

    close(down_to=0)
    return tuple(roots)


def law_order(path: Path) -> tuple[list[int | str], str]:
    """Sort key that puts art-2 before art-10 and art-5 before art-5-bis, the order the law
    itself uses, with a file's translations and coming texts after it."""
    stem = re.split(r"[.@]", path.name, maxsplit=1)[0]
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", stem)], path.name


def _in_force_file(path: Path) -> bool:
    """A clause file holding the text that prevails as the pack has it, not a translation of
    it and not a text an amendment brings later."""
    return TRANSLATION_FILE.match(path.name) is None and "@" not in path.name


def read_document(pack_dir: Path, document: PackDocument) -> list[Clause]:
    """Read every clause file in one document, in the law's own order."""
    directory = pack_dir / document.slug
    if not directory.is_dir():
        raise PackFormatError(
            f"{pack_dir}: pack.yaml lists document '{document.slug}' but {directory} is missing"
        )

    clauses = [
        read_clause_file(path, document_normative=document.normative)
        for path in sorted(directory.glob("*.md"), key=law_order)
        if _in_force_file(path)
    ]
    if len(clauses) != document.expected_clauses:
        raise PackFormatError(
            f"{directory}: pack.yaml expects {document.expected_clauses} clauses, "
            f"found {len(clauses)}. A clause lost between building the pack and "
            "committing it would otherwise be missing from every search."
        )

    for clause in clauses:
        expected_prefix = f"{document.slug}:"
        if not clause.key.startswith(expected_prefix):
            raise PackFormatError(
                f"{directory}: key '{clause.key}' does not start with '{expected_prefix}', "
                "so it would not resolve inside this document"
            )

    keys = {found.key for clause in clauses for found in clause.walk()}
    named = [key for entry in document.commencement for key in entry.keys]
    unknown = sorted(set(named) - keys)
    if unknown:
        raise PackFormatError(
            f"{pack_dir / 'pack.yaml'}: the commencement of {document.slug} names {unknown}, "
            "which the document does not have. A text an amendment brings later carries its "
            "own date in its file name"
        )
    for key in sorted(set(named)):
        entries = [entry for entry in document.commencement if key in entry.keys]
        starting = [entry for entry in entries if entry.starts or entry.pending]
        ending = [entry for entry in entries if entry.ends]
        if len(starting) > 1 or len(ending) > 1:
            raise PackFormatError(
                f"{pack_dir / 'pack.yaml'}: the commencement of {document.slug} dates "
                f"'{key}' twice, so which date applies would depend on the order"
            )
    return clauses


def read_translations(
    pack_dir: Path, document: PackDocument, pack: PackMetadata, clauses: list[Clause]
) -> dict[str, list[Clause]]:
    """Every translation of one document, clause for clause with the text that prevails.

    A translation covers the whole document under exactly the same keys, so a
    citation resolves to the same clause in every language. A partial or
    misaligned translation is refused rather than loaded, since it would answer
    some questions in one language and silently not in another.
    """
    directory = pack_dir / document.slug
    declared = {translation.lang for translation in pack.translations}
    files: dict[str, list[Path]] = {}
    for path in sorted(directory.glob("*.md"), key=law_order):
        match = TRANSLATION_FILE.match(path.name)
        if match is None:
            continue
        lang = match.group("lang")
        if lang not in declared:
            raise PackFormatError(
                f"{path}: '{lang}' is not a translation pack.yaml declares. List it under "
                "translations, with its status and licence"
            )
        files.setdefault(lang, []).append(path)

    for clause in clauses:
        if clause.lang != pack.authoritative_language:
            raise PackFormatError(
                f"{directory}: '{clause.key}' is written in '{clause.lang}', and a clause file "
                f"without a language suffix holds the authoritative text, "
                f"'{pack.authoritative_language}'"
            )

    found: dict[str, list[Clause]] = {}
    for lang in sorted(declared):
        read = [read_clause_file(path, document.normative) for path in files.get(lang, [])]
        counted = Counter(translated.key for translated in read)
        repeated = sorted(key for key, count in counted.items() if count > 1)
        if repeated:
            raise PackFormatError(
                f"{directory}: more than one '{lang}' file holds {repeated}. A clause has "
                "one text in each language"
            )
        by_key = {translated.key: translated for translated in read}
        for path, translated in zip(files.get(lang, []), read, strict=True):
            if translated.lang != lang:
                raise PackFormatError(
                    f"{path}: the file name says '{lang}' and the front matter says "
                    f"'{translated.lang}'"
                )
        aligned = []
        for clause in clauses:
            counterpart = by_key.pop(clause.key, None)
            if counterpart is None:
                raise PackFormatError(
                    f"{directory}: '{clause.key}' has no '{lang}' translation. A translation "
                    "covers every clause, or it is not loaded"
                )
            original_keys = [found_clause.key for found_clause in clause.walk()]
            translated_keys = [found_clause.key for found_clause in counterpart.walk()]
            if translated_keys != original_keys:
                missing = sorted(set(original_keys) - set(translated_keys))
                extra = sorted(set(translated_keys) - set(original_keys))
                raise PackFormatError(
                    f"{directory}: the '{lang}' translation of '{clause.key}' does not have the "
                    f"same clauses in the same order. Missing: {missing or 'none'}. "
                    f"Not in the original: {extra or 'none'}"
                )
            aligned.append(counterpart)
        if by_key:
            raise PackFormatError(
                f"{directory}: '{lang}' files hold keys the original does not: {sorted(by_key)}"
            )
        found[lang] = aligned
    return found


@dataclass(frozen=True)
class ComingText:
    """A clause as an amendment words it from a later date, with its translations.

    The text in force until then stays in its own file and ends that day. A coming text
    whose key the document does not have yet adds a clause from that day.
    """

    starts: date
    source: str
    """The amendment that brings it, so the date and the words can be checked."""
    clause: Clause
    translations: dict[str, Clause]


def read_coming(pack_dir: Path, document: PackDocument, pack: PackMetadata) -> list[ComingText]:
    """Every text an amendment brings later, in the law's order and then by date."""
    directory = pack_dir / document.slug
    declared = {translation.lang for translation in pack.translations}
    grouped: dict[tuple[str, date], dict[str | None, Path]] = {}
    for path in sorted(directory.glob("*@*.md"), key=law_order):
        match = COMING_FILE.match(path.name)
        if match is None:
            raise PackFormatError(
                f"{path}: a text an amendment brings later is named for the file it replaces "
                "and the day it starts, such as art-17@2027-01-17.md"
            )
        try:
            starts = date.fromisoformat(match.group("date"))
        except ValueError as error:
            raise PackFormatError(f"{path}: {match.group('date')} is not a date") from error
        lang = match.group("lang")
        if lang is not None and lang not in declared:
            raise PackFormatError(
                f"{path}: '{lang}' is not a translation pack.yaml declares. List it under "
                "translations, with its status and licence"
            )
        grouped.setdefault((match.group("stem"), starts), {})[lang] = path

    found: list[ComingText] = []
    for (stem, starts), files in grouped.items():
        original = files.get(None)
        if original is None:
            raise PackFormatError(
                f"{directory}: {stem}@{starts} has a translation and no text in "
                f"'{pack.authoritative_language}', the language that prevails"
            )
        if starts <= pack.effective_date:
            raise PackFormatError(
                f"{original}: starts on {starts}, which is not after the pack's effective_date "
                f"{pack.effective_date}. A text already in force belongs in {stem}.md"
            )
        source = str(_front_matter(original).get("source") or "").strip()
        if not source:
            raise PackFormatError(
                f"{original}: front matter needs a 'source', the amendment that brings this text"
            )
        clause = read_clause_file(original, document.normative)
        if clause.lang != pack.authoritative_language:
            raise PackFormatError(
                f"{original}: is written in '{clause.lang}', and a file without a language "
                f"suffix holds the text that prevails, '{pack.authoritative_language}'"
            )
        if not clause.key.startswith(f"{document.slug}:"):
            raise PackFormatError(
                f"{original}: key '{clause.key}' does not start with '{document.slug}:', so it "
                "would not resolve inside this document"
            )
        translations: dict[str, Clause] = {}
        for lang in sorted(declared):
            in_lang = files.get(lang)
            if in_lang is None:
                raise PackFormatError(
                    f"{directory}: {stem}@{starts} has no '{lang}' translation. A translation "
                    "covers every clause, or it is not loaded"
                )
            translated = read_clause_file(in_lang, document.normative)
            if translated.lang != lang:
                raise PackFormatError(
                    f"{in_lang}: the file name says '{lang}' and the front matter says "
                    f"'{translated.lang}'"
                )
            if [c.key for c in translated.walk()] != [c.key for c in clause.walk()]:
                raise PackFormatError(
                    f"{in_lang}: does not have the same clauses in the same order as "
                    f"{original.name}"
                )
            translations[lang] = translated
        found.append(ComingText(starts, source, clause, translations))

    repeated = Counter((coming.clause.key, coming.starts) for coming in found)
    for (key, starts), count in repeated.items():
        if count > 1:
            raise PackFormatError(f"{directory}: more than one file words '{key}' from {starts}")
    return found


def _front_matter(path: Path) -> dict[str, Any]:
    match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    return (yaml.safe_load(match.group(1)) or {}) if match else {}
