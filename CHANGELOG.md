# Changelog

Each release of DPOLens, newest first, written for the people who run an instance and decide
whether to upgrade. A release's notes start from the titles of the pull requests it holds and
are edited by hand. Changes to the HTTP API are listed one by one in
[docs/api-changelog.md](docs/api-changelog.md), and law packs have versions of their own.

## 0.1.0-rc.1

A release candidate for 0.1.0, and the first build of DPOLens published as images. It is here
so that every step of a release can be tried before 0.1.0 itself. The interfaces (the HTTP
API, the pack format, the database schema) can still change before 1.0, and only the newest
release gets fixes.

What it holds:

- **An MCP server** that gives an AI coding assistant four tools to search and read the law
  and the organisation's own policies. Every result is the clause word for word, with its key,
  its version and the date that version took effect.
- **GDPR, and the UAE's Personal Data Protection Law** in Arabic, which prevails, and in its
  official English translation. A law has releases of its own: `dpolens pack update` loads a
  newer version beside the one before it, and nothing changes the law in force unasked.
- **Search by words and by meaning** on the CPU, with no API key and no LLM. On held-out
  questions, the clause the guidance points at is among the top five answers 77% of the time
  for GDPR and 55% for the UAE's law.
- **The organisation's own policies**, uploaded as Word or Markdown files, read into clauses,
  checked beside the file, and published as versions that never change. Any two versions can
  be compared.
- **A dashboard** for the library, policies, people, roles, tokens, the laws that apply, and
  both logs: the governance log, append only and hash chained, and the questions asked, with
  personal data taken out.
