# DPOLens

**Grounds your AI coding assistant in your company's policies and the law, with citations
it can't make up.**

---

> ### Status: pre-release
>
> Nothing has shipped. There is no installable version, no Docker image and no packs yet.
> This repository is being built in the open, one slice at a time, and its history is the
> point as much as its contents.
>
> Watch the repository if you want to know when v0.1 lands. Interfaces (the HTTP API,
> the pack format, the database schema) change without notice until 1.0.

---

## The problem

A developer writes code that stores a user's phone number, or logs an email address, or
decides how long to keep a deleted account. Their AI assistant is happy to advise. It has
never read the company's data retention policy, and what it knows about the law is a
compressed memory of text it saw during training: good enough to sound right, not good
enough to cite.

## What DPOLens does

It gives the assistant a source to look things up in, and returns exact clauses rather
than recollections.

**For developers.** DPOLens runs an MCP server. Your assistant calls it while you work, and
gets back the verbatim text of the clauses that apply, each with a canonical key, a
breadcrumb, the document version, the effective date and its language. Every quote comes
from a stored, versioned source, so a claim about Article 17 can be checked in one click,
and a claim about *your* retention policy can be checked at all.

**For the DPO, legal and policy owners.** A web dashboard to upload policies, review how
they were parsed, publish immutable versions, choose which laws apply, and read the logs.

Two reasons this beats asking the model directly:

1. **It knows your company's own policies**: the one thing a general model cannot know,
   however good it gets.
2. **Its citations are real**: verbatim text from a versioned source, labelled with a
   trust tier, not a model's memory of an article number.

## Planned for v0.1

- `docker compose up` with **no API keys and no LLM anywhere**. Search runs on a small
  multilingual embedding model on the CPU, inside the container
- **GDPR and UAE PDPL** loaded on first start, plus a sample company policy
- **MCP server**: `search_policies`, `get_clause`, `list_documents`, `get_document`,
  with one-command setup for Claude Code and Cursor
- **Dashboard**: upload, review and publish DOCX and Markdown policies, with version
  history and diffs
- **Two logs**: a tamper-evident governance log, and a PII-redacted Q&A log that shows
  how the policies are being consulted without turning into developer surveillance
- **Published eval scores**, in CI, measuring whether search actually finds the right
  clause, including Arabic and cross-language questions

Arabic and English are both first-class. UAE PDPL is authoritative in Arabic, and it is a
launch pack.

## Client support

DPOLens is self-hosted, so it works with assistants that connect from your own machine:
**Claude Code, Cursor and VS Code**. Claude Desktop and claude.ai connect to MCP servers
from Anthropic's cloud rather than from your device, so they cannot reach an instance
running on a private network.

## What exists today

Design and decisions. Code starts with the pack pipeline: converting GDPR from EUR-Lex's
structured XML into a reviewable, versioned pack, then search and the eval harness on top
of it.

## Contributing

Law packs are the contribution that matters most, because nobody can structure and verify the
privacy law of every jurisdiction alone. See [CONTRIBUTING.md](CONTRIBUTING.md) for scope,
the licensing gate, trust tiers and what a pack pull request needs.

## Licence

Code is Apache-2.0, contributions certified by DCO sign-off, no CLA. `packs/` carries its
own licence: law text keeps its source's licence, declared per pack, while the structural
work around it (clause keys, the tree, eval questions) is CC-BY-4.0.
