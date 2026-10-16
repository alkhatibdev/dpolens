# Your own policies

DPOLens turns an organisation's policy, a Word or Markdown file, into clauses. Each one has
a key that citations point at, its text word for word, and its place in the document. No AI
model builds or changes that tree: it comes from the file itself, read with the techniques
legal publishers used long before software could guess.

You can see the result for any file on your computer. Nothing is stored:

```bash
dpolens policy parse retention-policy.docx --slug acme-retention
```

Uploading the file makes it a draft, which somebody reviews and publishes, and from then on
assistants search it and cite it. [From a draft to a policy in force](#from-a-draft-to-a-policy-in-force)
describes those steps, and [Keys over time](#keys-over-time) what happens to a citation when
a new version renumbers the clauses it points at.

## What it reads

Word files (`.docx`) and Markdown files (`.md`). Older Word files (`.doc`), PDFs and
OpenDocument files are refused with what to do instead: save the file as `.docx`, or use the
Word or Markdown original a PDF was made from. A file with no text, such as a scanned
document, is refused rather than read as an empty policy.

A Word file is read from its own XML, so text in tables, content controls, text boxes,
fields and tracked changes is all found. Tracked changes are read as if every change were
accepted, and the parse says so. Headers, footers, footnotes and comments are not part of any
clause; the parse says when a file has footnotes or comments.

A file is treated as untrusted. One that unpacks to more than 256 MB is refused before it is
unpacked, and so is any part that declares a DTD, which Word never does.

## How the tree is built

Each paragraph is read for three kinds of evidence, in this order:

1. **The file's own structure**: heading styles and outline levels, Word's automatic
   numbering, Markdown headings and lists.
2. **Its type**: a short line in bold, in larger type or in capitals, where the file gives
   it no heading style.
3. **Numbers written into the text**: `1.`, `4.2`, `(a)`, `(iv)`, `2-2-1`, `Article 5`, and
   the forms Arabic drafting uses, such as `المادة (5)`, `أولاً`, `١-` and `أ-`.

The first kind of evidence that says something about a paragraph decides where its clause
begins and how deep it sits. The others confirm it. Where they disagree, the paragraph is
flagged for a reviewer instead of guessed. Depth follows one rule: a new style of heading or
number goes one level deeper, and a style seen before goes back up to where it was.

What becomes a clause:

- **A heading**, with everything under it as its children.
- **A numbered paragraph**, which can hold deeper ones, as 3.5 holds 3.5.1.
- **Any other paragraph** of text.
- **Each row of a table.** A header row names the columns, and a row merged across the table
  titles the rows below it.

A bulleted list is not a clause of its own. It stays in the text of the line that leads into
it, so "We collect:" and the list after it are cited together.

## Keys

A key starts with the document's slug and adds one part for each level, each taken from the
document:

- **The clause's number**, as the document writes it: `acme-retention:3.5.1`, or
  `acme-privacy:4:1` for a list that starts again at 1 inside section 4.
- **Its heading's first words**, where it has no number:
  `acme-privacy:personal-data-we-collect:from-you`. Arabic headings keep their Arabic
  letters.
- **Its position**, for a paragraph with neither: `acme-privacy:security:p2`.

## Set aside

Some text in a file is not a clause anyone should be answered from: the document's title, a
cover page and the metadata, approval and version tables before the policy begins, a
contents page, text boxes, and a table printed again on later pages. That text is set aside
with its reason. It is kept and counted, so nothing goes missing quietly, and it is never
searched.

## Checks and flags

Every parse checks two things:

- **Coverage**: every character of the file is in exactly one clause or one set-aside block.
- **Numbering**: numbered clauses under the same parent run in order, with no gap and no
  repeat.

What the checks find, and every place where the evidence disagreed, becomes a flag: one thing
for a reviewer to settle. A heading with no number among numbered ones is flagged, because it
may belong under the heading before it. Two clauses that are both numbered 1-1 are flagged
rather than one of them renumbered.

## An example

```text
$ dpolens policy parse council-privacy.docx --slug council-privacy
Data Protection and Privacy Policy
Word file, 15 clauses. Of its 442 characters, 380 are in clauses and 62 set aside.

1  OVERVIEW                                                          file
  1:p1  The Council is open about how it collects and uses personal… file
2  PRINCIPLES                                                        file
  2:p1  The Council follows seven principles:                        file
  2:1  Lawfulness, fairness and transparency.                        file
  2:2  Purpose limitation.                                           file
  2:3  Data minimisation.                                            file
3  DATA SECURITY                                                     file
  3:p1  The Council keeps personal data secure.                      file
paper-storage  Paper Storage:                                        file
  paper-storage:p1  • Paper records are kept in a locked cabinet.    file
4  RETENTION SCHEDULE                                                file
  4:document-minimum-retention-period-reason  DOCUMENT · MINIMUM …   file
    4:document-minimum-retention-period-reason:staff-records  Staff… file
    4:document-minimum-retention-period-reason:minutes  Minutes      file

Set aside, not searched: title (1 paragraph), contents (3 paragraphs).

For a reviewer to settle (1):
  boundary   paper-storage  "Paper Storage:" has no number, unlike the headings around it,
  so it may belong under the one before it.
```

The last column says what decided each clause: `file` for the file's own structure, `type`
for its typography, `number` for a number written into its text. `--json` prints everything,
including each clause's full text and its language.

## From a draft to a policy in force

Uploading a policy reads it at once, so a file that cannot be read is refused there and then,
with what to do about it. A file it can read becomes a **draft**: the clauses, the flags, how
much of the file reached a clause, and what was set aside. Nothing searches a draft.

```bash
dpolens policy upload retention-policy.docx --slug acme-retention --effective-date 2026-01-01
dpolens policy draft acme-retention
dpolens policy accept acme-retention 1 2
dpolens policy publish acme-retention
```

A reviewer reads each flag and accepts it, and publishing waits until every flag is accepted.
Uploading and reviewing need the permission `documents.upload`; publishing and archiving need
`documents.publish`, which the seeded Admin and DPO roles hold. A draft's title, effective
date and version label can be changed until it is published (`dpolens policy edit`), and a
draft can be discarded (`dpolens policy discard`).

Once published, a version never changes. Searches find it from the day it takes effect: by its
words straight away, and by meaning once the worker has embedded its clauses. The API reports
how far that has got as `indexing`.

Versions take effect in the order they are published: each one after the one before it. Each
has a label that citations show, `1`, `2` and so on unless you give it another, and no two
versions of a policy share one, because a citation names its version by its label.

The [HTTP API](api.md#policies) takes the same steps, with the file as the request body:

```bash
curl --data-binary @retention-policy.docx \
  -H "Authorization: Bearer $DPOLENS_TOKEN" -H "Content-Type: application/octet-stream" \
  "http://localhost:8000/v1/policies?filename=retention-policy.docx&slug=acme-retention"
```

On an instance started with Docker Compose, the command line runs in the `api` container, so
copy the file in first:

```bash
docker compose cp retention-policy.docx api:/tmp/
docker compose exec api dpolens policy upload /tmp/retention-policy.docx --slug acme-retention
```

Every step, from the upload to the publication, is written to the governance log with who took
it, and the upload's entry records the file's SHA-256.

## A new version

A new version of a policy is uploaded against the policy it replaces:

```bash
dpolens policy revise acme-retention retention-policy-v2.docx --effective-date 2026-07-01
```

Each clause of the new version is matched to the clause of the version before it that it
continues: first by identical words, then by the same number with at least half the same
wording, then by a different number with at least four fifths the same wording. Each clause is
then `same`, `reworded`, `new`, or renumbered (`was 4.2`), and a clause of the version before
that nothing continues is listed as removed.

Matching by wording can be wrong, because two rows of a retention schedule can share most of
their words, so three things become flags for a reviewer: a clause whose number changed, a
clause whose words changed so much that it may be a different rule (the flag quotes what it
said before), and a number that named a different rule in the version before. A policy has
one draft at a time. Uploading another while one is open is refused, unless you ask for the new
file to replace it (`--replace`).

## Keys over time

A policy's keys follow the numbers printed in it, so a reader can always find a key in the
document in front of them. When a new version inserts a clause, the clauses after it are
printed with new numbers, and their keys change with them:

```text
Version 1, in force from 1 January         Version 2, in force from 1 July
4.1  Customer records: 2 years              4.1  Customer records: 2 years
4.2  Staff records: 6 years                 4.2  Contractor records: 1 year     new
4.3  Supplier records: 5 years              4.3  Staff records: 6 years         was 4.2
                                            4.4  Supplier records: 6 years      was 4.3
```

A citation names its version as well as its key, and that is what keeps it exact. A citation
of `acme-retention:4.2` in version 1, read as of a date when version 1 was in force, still
gives the staff rule word for word, and says where that rule is now:

```text
$ dpolens clause show acme-retention:4.2 --as-of 2026-03-01
...
4.2  [acme-retention:4.2]
Staff records are kept for 6 years after employment ends.

In version 2, in force since 2026-07-01, this rule is acme-retention:4.3, word for word.
```

Read today, `acme-retention:4.2` is the contractor rule, and says what it named before:

```text
In version 1, acme-retention:4.2 was a different rule, which is acme-retention:4.3 now:
  Staff records are kept for 6 years after employment ends.
```

The HTTP API and the MCP server say the same, as `now` and `formerly`, so an assistant reading
an old citation is told where the rule went.

## Archiving

Archiving a policy takes it out of search and out of the library. Nothing is deleted: its
clauses still read by key, marked as archived, so a citation of one still resolves. Publishing
a new version of an archived policy brings it back.

```bash
dpolens policy archive acme-retention
```

## The original file

The file each version was read from is kept, under a name made from its SHA-256, and checked
against that hash whenever it is read, so a file that went missing or changed is an error
rather than a different download. Anyone who may read the policies can download it from the
API. An upload writes the file before its draft, so a failure can leave a file that nothing
points at, and the worker removes those once a day, after a day's grace.
[configuration.md](configuration.md) says where the files are kept.

## The sample policy

A new instance starts with a made-up policy for a made-up company,
`sample-data-protection`, so there is a policy of your own kind to search before yours are in.
Archive it when they are. It is published once: archived, it is never brought back.

