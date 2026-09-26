# DPOLens

**Give your AI coding assistant access to your organisation's privacy policies and the law,
with exact, versioned citations. A self-hosted MCP server.**

---

> ### Status: pre-release
>
> There is no installable version and no Docker image yet. What works today is the command
> line: the GDPR pack loads, and search is measured.
>
> Watch the repository to know when v0.1 lands. Interfaces (the HTTP API, the pack format,
> the database schema) change without notice until 1.0.

---

## Why this exists

Most of times you write code that touches someone's personal data. You log an email address to debug a problem. You add a phone number column. You decide that deleted accounts stay in the database for ninety days, because ninety sounded about right.

Every one of those is a decision with rules attached, and the organisation is on the hook
for getting them wrong. Most developers, have never read those rules. We are
not lawyers, nobody hands us the retention policy on the first day, and the law is long and
written for people who are.

Now the AI assistant writes a lot of that code. It is fast, it sounds sure of itself, and it
has never seen your organisation's policies. What it knows about the law is a blurry memory
from training: close enough to sound right, not close enough to act on.

So more code that touches personal data gets written, faster, by something that knows the
rules less well than you do.

## What DPOLens does

It gives the AI assistant somewhere to look the rules up, and hands back the exact clause
rather than a recollection of one.

**For developers.** DPOLens runs an MCP server, so your AI assistant can search it while you
work. What comes back is the clause itself, word for word, and where it came from: which
document, which version, and the date that version took effect. A claim about Article 17 can
be checked in one click, and a claim about *your* retention policy can be checked at all.

**For the DPO, legal and policy owners.** A web dashboard to upload policies, review how
they were parsed, publish immutable versions, choose which laws apply, and read the logs.

Two reasons this beats asking the model directly:

1. **It knows your organisation's own policies**: the one thing a general model cannot
   know, however good it gets.
2. **Its citations are real**: verbatim text from a versioned source, labelled with a
   trust tier, not a model's memory of an article number.

## Planned for v0.1

- `docker compose up` with **no API keys and no LLM anywhere**. Search runs on a small
  multilingual embedding model on the CPU, inside the container
- **GDPR and UAE PDPL** loaded on first start, plus a sample organisation policy
- **MCP server**: `search_policies`, `get_clause`, `list_documents`, `get_document`,
  with one-command setup for Claude Code and Cursor
- **Dashboard**: upload, review and publish DOCX and Markdown policies, with version
  history and diffs
- **Two logs**: a tamper-evident governance log, and a PII-redacted query log that shows
  how the policies are being consulted without turning into developer surveillance
- **Published eval scores**, in CI, measuring whether search actually finds the right
  clause, including Arabic and cross-language questions

Arabic and English are both first-class. UAE PDPL is authoritative in Arabic, and it is a
launch pack.

## Client support

DPOLens is self-hosted, so it works with assistants that connect from your own machine:
**Claude Code, Cursor and VS Code**.

## Does it actually find the right clause

GDPR: **recall@5 of 0.77** (95% confidence interval 0.60 to 0.90), on 30 held-out questions
drawn from ICO and EDPB guidance, using multilingual-e5-small and convex fusion, measured
26 September 2026.

That means the clause the guidance points at was among the top five answers 77% of the
time. It does not mean DPOLens answers 77% of privacy questions correctly.
[docs/retrieval.md](docs/retrieval.md) has the method, every configuration measured, and
the commands to reproduce the number yourself.

## Does it actually find the right clause

GDPR: **recall@5 of 0.77** (95% confidence interval 0.60 to 0.90), on 30 held-out questions
drawn from ICO and EDPB guidance, using multilingual-e5-small and convex fusion, measured
26 September 2026.

That means the clause the guidance points at was among the top five answers 77% of the
time. It does not mean DPOLens answers 77% of privacy questions correctly.
[docs/retrieval.md](docs/retrieval.md) has the method, every configuration measured, and
the commands to reproduce the number yourself.

## What exists today

Retrieval runs, and is measured. GDPR is converted from EUR-Lex's structured XML into a
reviewable pack of 99 articles and 173 recitals, loaded into Postgres as immutable
versions, indexed for BM25 and meaning search, and searched:

```bash
dpolens pack load packs/gdpr
dpolens index build
dpolens search "how long can we keep a deleted user's data"
dpolens clause show gdpr:art-17 --subtree
```

The HTTP API, the MCP server and the dashboard come next. There is still no server to run
and no published image.

## Contributing

Law packs are the contribution that matters most, because nobody can structure and verify the
privacy law of every jurisdiction alone. See [CONTRIBUTING.md](CONTRIBUTING.md) for scope,
the licensing gate, trust tiers and what a pack pull request needs.

## Licence

Code is Apache-2.0, contributions certified by DCO sign-off, no CLA. `packs/` carries its
own licence: law text keeps its source's licence, declared per pack, while the structural
work around it (clause keys, the tree, eval questions) is CC-BY-4.0.
