# The pack format

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
slug: gdpr
name: General Data Protection Regulation
jurisdiction: European Union
version: "2026.1"
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
    title: General Data Protection Regulation
    normative: true
    expected_clauses: 99       # top level files in this directory
  - slug: gdpr-recitals
    title: GDPR recitals
    normative: false
    expected_clauses: 173
```

`expected_clauses` is a count the pack asserts about itself. The loader refuses a pack
whose files do not match it, so a clause lost between building the pack and committing it
is caught rather than quietly missing from every search.

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
| `title` | no | The clause's own heading, where the law gives one |
| `lang` | yes | BCP 47 code of the text in this file |
| `normative` | no | `false` for text that explains without obliging, such as a recital. Defaults to the document's setting |
| `cross_references` | no | Pointers this clause makes to other clauses, each with the target key and the wording used |

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

## Segment names

A key segment names what the clause is, so `art-17:para-1:pt-b` reads as article 17,
paragraph 1, point (b). The recognised prefixes are:

| Prefix | Clause |
| --- | --- |
| `art-` | article |
| `para-` | paragraph |
| `pt-` | point |
| `sec-` | section |
| `ch-` | chapter |
| `rec-` | recital |
| `annex-` | annex |

A key is permanent. If a provision is repealed, its key is retired: it keeps resolving in
the versions that contained it and is never given to different text. Where a jurisdiction
reuses a number for unrelated content, the maintainer assigns a suffixed key such as
`art-12-2031` and says why in the pull request.

## Licensing

Every pack declares `source_url`, `license`, `authoritative_language` and, for each
translation, whether it is official and under what licence. Law-firm and commercial
translations are not accepted. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full
gate and for how a pack becomes `verified`.
