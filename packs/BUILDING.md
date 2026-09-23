# Building a pack

A pack is built once, by a person, and committed. No DPOLens instance ever parses law text
for itself, so whatever you produce here is what every installation will quote.

This page takes you from an official source to a pack that is ready for review.
[README.md](README.md) is the reference for the file format itself.

## 1. Find the official source

Only the text published by the state counts. A law firm's reproduction, a booklet issued
by an institute, or a tidy copy on a commentary site all fail the licensing gate, however
convenient they are.

Check whether your jurisdiction excludes legal texts from copyright, cite the provision
that says so in your pull request, and note anything the portal says about which language
prevails.

## 2. Get the text

### Where the source is already structured

EU law is published as Formex XML, which needs converting rather than retyping. Ask the
Publications Office repository for a CELEX identifier and a Formex media type:

```bash
# Consolidated text: the articles in force, with an empty preamble
curl -L -H "Accept: application/zip;mtype=fmx4" -H "Accept-Language: eng" \
  https://publications.europa.eu/resource/celex/02016R0679-20160504 -o consolidated.zip

# Original act: carries the recitals
curl -L -H "Accept: application/zip;mtype=fmx4" -H "Accept-Language: eng" \
  https://publications.europa.eu/resource/celex/32016R0679 -o original.zip
```

Three things to know:

- `Accept-Language` is not optional. The same act exists in 24 languages, and without it
  the server cannot choose.
- Each zip holds two files. The large one is the act. The small `.doc.xml` is a
  bibliographic wrapper you do not need.
- A consolidated text carries the current articles and no recitals at all, so a pack that
  wants both takes them from two different files.

### Where the source is a PDF or a web page

There is no converter, and there will not be a reliable one. Write the clause files by
hand, following [README.md](README.md). It is slower than it sounds worth, and it is how a
pack earns its trust tier: somebody read every provision.

The checks in step 4 still apply, and they are what stops manual work from quietly losing
an article.

## 3. Convert

```bash
uv run dpolens pack build --out packs/gdpr \
  --articles consolidated/CL2016R0679EN0000020.0001.xml --articles-slug gdpr \
  --recitals original/L_2016119EN.01000101.xml --recitals-slug gdpr-recitals
```

It writes one file per article and per recital, and prints the clause counts and the
SHA-256 of each source file. Both go into `pack.yaml`.

### What the converter does with the text

The publisher already decided the structure, so the converter translates it rather than
interpreting it. Specifically:

- **Keys follow the law's own numbering.** Article 17, paragraph 1, point (b) becomes
  `gdpr:art-17:para-1:pt-b`.
- **Labels are kept as printed**, so a clause can be shown the way the reader expects:
  `Article 17`, `1.`, `(b)`.
- **The first subparagraph stays part of its paragraph**, because that is how citations
  are written: point (f) of Article 6(1) is `gdpr:art-6:para-1:pt-f`. A second or later
  subparagraph becomes a clause of its own, keyed `sub-2`, `sub-3`, which is also how it
  is cited.
- **An article with no numbered paragraphs keeps its points.** GDPR Article 4 is shaped
  this way, and its definitions are cited constantly, so they need keys of their own.
- **Dash items are numbered by position**, since the source gives them no number.
- **Footnotes are left out of clause text.** They cite the Official Journal and are not
  part of the provision a citation quotes.
- **Quotation marks are preserved exactly**, so a defined term reads as the source prints
  it.

### What it does with references

A link exists only where the text states one:

| The text says | Result |
| --- | --- |
| `Article 6(1)` | Linked to `gdpr:art-6:para-1` |
| `point (a) of Article 9(2)` | Linked to `gdpr:art-9:para-2:pt-a` |
| `Article 25(6) of Directive 95/46/EC` | Ignored: it names another law |
| `Article 99(9)`, which does not exist | Reported, not stored |

A wrong link is worse than no link, because it looks authoritative while pointing at the
wrong clause. Anything the build reports as unresolved is worth reading: it usually means
the text cites something the document does not contain.

## 4. Know what the checks prove

`pack build` and the test suite between them guarantee:

- **Coverage.** Every article is compared with its source, character by character,
  ignoring only whitespace. Text that was dropped or duplicated fails the build. This is
  the check that catches a lost paragraph, which is the worst thing that can happen to a
  pack, because nothing downstream can detect a clause that is simply absent.
- **Counts.** `pack.yaml` declares how many clauses each document has, and the numbers are
  checked when the pack loads as well as when it is built.
- **Format.** Front matter is validated, keys must be unique, heading depth must not skip
  a level, and an unknown key segment is an error.

What they do not prove, and what review is for:

- that a link points at the clause the text meant
- that a clause boundary matches the source's intent
- that the translation is the official one
- that the text is current

That last list is the whole reason a pack starts as `community` and becomes `verified`
only when a named maintainer with local legal context has checked it against the source.

## 5. Fill in pack.yaml

Copy the counts and checksums the build printed. Record where each document came from, so
a rebuild can prove it used the same text:

```yaml
documents:
  - slug: gdpr
    title: General Data Protection Regulation
    normative: true
    expected_clauses: 99
    source_url: https://publications.europa.eu/resource/celex/02016R0679-20160504
    source_sha256: 28524c5589d9c80dee357fe96498302b4fefb29b3cc9ada7dcad52c967e3f15c
```

Set `effective_date` to the date the law applies from, not the date of the file. Set
`trust_tier` to `community`. Put anything the portal says about authenticity into
`license`, including which language prevails.

Recitals, guidance and other text that explains without obliging are marked
`normative: false` on the document, so every result can say so.

## 6. Read your own pack before opening the pull request

Open three or four files next to the official text and read them:

- one long article with points and subparagraphs
- one definitions article, if the law has one
- the last article, which is where truncation shows up
- one clause whose text carries a cross reference

Then check that a deep key resolves the way a lawyer would cite it, and that the counts in
`pack.yaml` match what the build printed.

## 7. When the build refuses

| Message | What it means |
| --- | --- |
| `no ARTICLE elements found` | The preamble file was passed as the articles file, or the wrapper file was passed instead of the act |
| `no CONSID elements found` | Recitals were taken from a consolidated text, which has none |
| `pack.yaml expects N clauses, found M` | Files were added or lost since the counts were written |
| `does not carry the source text exactly` | Text was dropped or duplicated. The message names the clause and shows the first difference |
| `a heading opens a clause, so it needs a key segment anchor` | A hand-written file has a heading without `{#segment}` |
| `unknown key segment` | A segment prefix outside the list in README.md |

Everything above is a refusal rather than a warning, because a pack that loads with a
provision missing is worse than a pack that does not load.
