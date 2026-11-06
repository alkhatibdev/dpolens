# The pack format

This is the reference for what a pack contains. To build one, start with
[BUILDING.md](BUILDING.md).

A pack is one law plus its official companion texts, structured so that a citation can
point at exactly one clause and be checked against the official source.

A pack is reviewed by reading a diff. That is why it is a directory of small Markdown
files rather than one large machine-readable file: a correction to one article should be a
few readable lines.

## Layout

```
packs/<pack-slug>/
    pack.yaml                     metadata, licensing and expected counts
    <document-slug>/
        <clause-file>.md          one file per article, or per recital
```

For example:

```
packs/gdpr/
    pack.yaml
    gdpr/
        art-17.md
    gdpr-recitals/
        rec-65.md
```

The pack slug names the law, not the place: `gdpr`, `uae-pdpl`, `difc-dpl`. Where the same
abbreviation is used in two countries, the slug carries the country: `sg-pdpa`, `th-pdpa`.

A document slug is the prefix of every canonical key in that document, so
`packs/gdpr/gdpr/art-17.md` holds `gdpr:art-17` and
`packs/gdpr/gdpr-recitals/rec-65.md` holds `gdpr-recitals:rec-65`.

## pack.yaml

```yaml
format: 2
slug: gdpr
name:
  en: Regulation (EU) 2016/679 (General Data Protection Regulation)
short_name:
  en: GDPR
jurisdiction:
  en: European Union
region: Europe
version: "2026.2"
effective_date: 2018-05-25
trust_tier: community          # or verified, once a named maintainer has checked it
source_url: https://eur-lex.europa.eu/eli/reg/2016/679/oj
license: >-
  Reuse permitted under Commission Decision 2011/833/EU. Only the text published
  in the Official Journal is authentic.
authoritative_language: en
translations: []               # each entry: lang, status (official or unofficial), license

documents:
  - slug: gdpr
    title:
      en: Regulation (EU) 2016/679 (General Data Protection Regulation)
    normative: true
    expected_clauses: 99       # top level files in this directory
  - slug: gdpr-recitals
    title:
      en: Regulation (EU) 2016/679 (General Data Protection Regulation), recitals
    normative: false
    expected_clauses: 173
```

`format` is the pack format the file is written in, and this one is 2. An engine refuses a
pack in a format it does not read, and says which it reads.

`expected_clauses` is a count the pack asserts about itself. The loader refuses a pack
whose files do not match it, so a clause lost between building the pack and committing it
is caught rather than quietly missing from every search.

`version` is the pack's own, a year and a number: `2026.1`, then `2026.2`. A released version
is never changed in place, because an instance that loaded it keeps it: a change is a new
version. `effective_date` is the day the law's text started to apply, which for the GDPR is
25 May 2018 (Article 99(2)), not the day it entered into force. A correction to how the pack
holds the law, with the law itself unchanged, keeps the law's date, and the newer version is
the one in force from that day. [Laws and their versions](https://dpolens.com/docs/laws) says how
an instance loads a version, and [CONTRIBUTING.md](../CONTRIBUTING.md#a-law-pack) how one is
released.

## How a law is named

`name`, `short_name`, `jurisdiction` and each document's `title` are written once per
language: in every language the pack has a text in, and in English, since every interface is
English. A law whose text is Arabic names itself in Arabic beside its Arabic text, and in
English on an English screen:

```yaml
name:
  ar: مرسوم بقانون اتحادي رقم (45) لسنة 2021 بشأن حماية البيانات الشخصية
  en: Federal Decree by Law No. (45) of 2021 Concerning the Protection of Personal Data
short_name:
  ar: قانون حماية البيانات الشخصية الإماراتي
  en: UAE PDPL
```

- `name` is the official name: the law's number and the short title it gives itself, where it
  gives one, else its title as printed. The GDPR's printed title runs to some fifty words, so
  its name is `Regulation (EU) 2016/679 (General Data Protection Regulation)`. A citation
  starts with it.
- `short_name` is what people call the law and search for. It is unique across the packs,
  which CI checks, and it names the place wherever the abbreviation is shared: `UAE PDPL`,
  never `PDPL`. Search reads it as well: every clause is embedded with its law's short name in
  front, in the clause's language.
- A document's `title` follows the same rule as `name`. A document that is part of the same
  act adds the part: `..., recitals`.
- Where no official text exists in English, the English names come from an official English
  source if there is one, such as the regulator's own pages, and otherwise from the pack's
  builder.
- `region` is where the law is listed: one of `Africa`, `Americas`, `Asia Pacific`, `Europe`
  and `Middle East`.

Prose the builder writes about the pack, such as `license`, stays in English.

## A clause file

```markdown
---
key: gdpr:art-17
title: Right to erasure ('right to be forgotten')
lang: en
cross_references:
  - key: gdpr:art-6:para-1
    text: Article 6(1)
---

## 1. {#para-1}

The data subject shall have the right to obtain from the controller the erasure of
personal data concerning him or her without undue delay.

### (a) {#pt-a}

the personal data are no longer necessary in relation to the purposes for which they
were collected or otherwise processed;
```

Front matter carries the metadata:

| Field | Required | Meaning |
| --- | --- | --- |
| `key` | yes | Canonical key of the clause this file holds |
| `label` | no | The numbering the text itself prints, such as `Article 17` |
| `title` | no | The clause's own heading, where the law gives one |
| `lang` | yes | BCP 47 code of the text in this file |
| `normative` | no | `false` for text that explains without obliging, such as a recital. Defaults to the document's setting |
| `cross_references` | no | Pointers this clause makes to other clauses, each with the target key and the wording used. Written by `pack build` from the references the text states, and only where the target exists |

The body carries the text. Each heading opens a child clause:

- The heading's visible part is the label the law itself uses: `1.`, `(a)`, `Article 17`.
- The `{#segment}` anchor is the key segment, appended to the parent's key. The heading
  above produces `gdpr:art-17:para-1`, and the one below it `gdpr:art-17:para-1:pt-a`.
- Heading depth is clause depth. A level 3 heading is a child of the level 2 heading
  above it.
- Everything between one heading and the next is that clause's text, stored verbatim. It
  is what citations quote and what verification checks character for character.

Structure is never guessed from the prose. A clause exists because a heading declares it,
which is what makes a pack reproducible and a review meaningful.

Files are read in the law's own order, so `art-2.md` comes before `art-10.md` whatever a plain
sort of the names would say.

## Translations

A clause file holds the text that prevails in law, in the language `pack.yaml` names as
`authoritative_language`. A translation sits beside it, with its language before `.md`:

```
packs/uae-pdpl/
    pack.yaml
    uae-pdpl/
        art-4.md        the Arabic, which prevails
        art-4.en.md     the official English translation
```

`pack.yaml` declares each one:

```yaml
authoritative_language: ar
translations:
  - lang: en
    status: official     # official when the state published it, unofficial otherwise
    license: >-
      Not protected by copyright, under the same exclusion as the Arabic.
    source_url: https://uaelegislation.gov.ae/en/legislations/1972/download
```

A translation holds the same clauses under the same keys, in the same order, with its labels
and headings in its own language: `### أ. {#pt-a}` in the Arabic is `### a. {#pt-a}` in the
English, so a citation resolves to the same clause in either. `expected_clauses` counts the
files without a language suffix.

The loader refuses a translation that is missing a clause or has one the original does not,
a file in a language `pack.yaml` does not declare, and a file whose name and `lang` disagree.
A translation covers the whole document or it is not loaded, because a partial one would
answer some questions in one language and silently not in the other.

A clause read in translation says which language prevails, and the MCP server puts that in
the citation it builds.

## Segment names

A key segment names what the clause is, so `art-17:para-1:pt-b` reads as article 17,
paragraph 1, point (b). The recognised prefixes cover the units the laws DPOLens is asked
for use:

| Prefix | Clause |
| --- | --- |
| `art-` | article |
| `para-` | paragraph |
| `sub-` | subparagraph, for the second and later subparagraphs of a paragraph |
| `pt-` | point |
| `sec-` | section |
| `rule-` | rule, as in India's Digital Personal Data Protection Rules |
| `reg-` | regulation, as in Singapore's Personal Data Protection Regulations |
| `sch-` | schedule, or `sch` alone for a law's only schedule |
| `cl-` | a schedule's clause, as in clause 4.3 of PIPEDA's Schedule 1 |
| `suppl` | supplementary provisions, as in Japan's APPI |
| `ch-` | chapter |
| `rec-` | recital |
| `annex-` | annex |

A number is written as the law prints it, in lower case, with dots and spaces as hyphens:
Article 55-A is `art-55-a`, Article 5 bis `art-5-bis`, section 26C `sec-26c`, section 10.1
`sec-10-1`, section 1798.199.100 `sec-1798-199-100`, and «المادة الأولى» `art-1`. A law that
brings a unit this list lacks adds one line to it, in the engine's `SEGMENT_TYPES`: the loader
refuses a segment it does not know.

A key is permanent. If a provision is repealed, its key is retired: it keeps resolving in
the versions that contained it and is never given to different text. Where a jurisdiction
reuses a number for unrelated content, the maintainer assigns a suffixed key such as
`art-12-2031` and says why in the pull request.

## When each text applies

Every text in a pack applies from the pack's `effective_date` unless the pack says
otherwise. A law that starts in stages, a provision no day has been set for yet, and one a
later law ends, are written in the document's `commencement` list, copied from whatever set
the dates. India's Digital Personal Data Protection Act starts in three steps:

```yaml
documents:
  - slug: dpdp
    ...
    commencement:
      - from: 2027-05-13
        keys: [dpdp:sec-3, dpdp:sec-4, dpdp:sec-5, dpdp:sec-6, dpdp:sec-44:para-2]
        source: G.S.R. 843(E), 13 November 2025
      - from: 2026-11-13
        keys: [dpdp:sec-6:para-9, dpdp:sec-27:para-1:pt-d]
        source: G.S.R. 843(E), 13 November 2025
```

- `from` is the day the provisions start to apply, or `pending` while nothing has set it, as
  for a section that comes into force on a day the government appoints, before it appoints one.
- `until` is the day they stop, as for a section another law repeals from a set day. An entry
  has `from`, `until`, or both.
- A key covers everything beneath it, and the most specific key wins: `dpdp:sec-6` applies
  from 13 May 2027, and `dpdp:sec-6:para-9` from 13 November 2026.
- `source` is whatever set the dates: the law's own article, a separate notice, or a rule of
  the text itself.
- Grace periods a law states in its own words are not written here: the text carries them.

An amendment that is law but does not apply yet sits in the same pack. The clause as the
amendment words it goes beside the clause in force, in a file named for the one it replaces
and the day it starts, with the amendment as its `source`:

```
packs/example/
    example/
        art-17.md               the words in force until 17 January 2027
        art-17@2027-01-17.md    the words the amendment gives it from that day
        art-17@2027-01-17.en.md their translation
```

```markdown
---
key: example:art-17
lang: ja
source: Act No. 56 of 2026
---
```

The words in force end the day the amendment starts, and a clause the amendment adds, whose
key the document does not have yet, applies from that day. A clause it leaves out ends that day
too. An amendment changes words, not the day a provision comes into force: a provision that
starts later, or has no day set yet, keeps its own, now with the amendment's words. `expected_clauses` counts only the
files without a day in their name. An instance switches to the amendment's words on the day,
with no new pack version.

A search returns a provision before it applies, marked, so a duty can be prepared for, and
carries an amendment's words beside the words in force. Words a law has ended are no longer
searched, and still read by key. [Laws and their versions](https://dpolens.com/docs/laws) says
what a result carries.

## Licensing

Every pack declares `source_url`, `license`, `authoritative_language` and, for each
translation, whether it is official and under what licence. Law-firm and commercial
translations are not accepted. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full
gate and for how a pack becomes `verified`.
