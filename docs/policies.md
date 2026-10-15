# Reading a policy

DPOLens turns an organisation's policy, a Word or Markdown file, into clauses. Each one has
a key that citations point at, its text word for word, and its place in the document. No AI
model builds or changes that tree: it comes from the file itself, read with the techniques
legal publishers used long before software could guess.

You can see the result for any file on your computer. Nothing is stored:

```bash
dpolens policy parse retention-policy.docx --slug acme-retention
```

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
