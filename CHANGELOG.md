# Changelog

Each release of DPOLens, newest first, written for the people who run an instance and decide
whether to upgrade. A release's notes start from the titles of the pull requests it holds and
are edited by hand. Changes to the HTTP API are listed one by one in
[docs/api-changelog.md](docs/api-changelog.md), and law packs have versions of their own.

## 0.1.0-rc.2

The second release candidate for 0.1.0. A search now keeps to the laws the organisation
selected, questions are kept unless a retention is set, the command line asks for what it
needs, and an instance can run as a community version that answers anyone's assistant. The
interfaces can still change before 1.0, and only the newest release gets fixes.

Before upgrading from 0.1.0-rc.1:

- **Questions are no longer deleted after 365 days.** The query log keeps every question unless
  `DPOLENS_QUERY_LOG_RETENTION_DAYS` is set. To keep 0.1.0-rc.1's rule, set it to `365`: it
  counts from the day each question was asked, so it covers the questions already kept.
- **A search needs selected laws.** An instance with none selected, including one that searched
  every law, refuses every search until somebody chooses. The dashboard asks the next
  administrator who signs in, and `docker compose exec api dpolens laws select` chooses from
  the command line. An instance whose laws were chosen keeps them.
- **Searching every law is gone**, with `DELETE /v1/laws/selection` and `dpolens laws clear`,
  and a search result no longer carries `in_selected_laws`.
  [docs/api-changelog.md](https://github.com/alkhatibdev/dpolens/blob/v0.1.0-rc.2/docs/api-changelog.md)
  lists every change to the HTTP API.

What changed:

- **Only the selected laws, everywhere.** Search, the library, the MCP server and the command
  line keep to the laws the organisation selected. A token asking for another law is refused
  with `403` and `/problems/law-not-selected`. The dashboard still opens it, marked, so a
  citation stays checkable after its law is unselected. A law an upgrade brings is marked new
  in Selected laws for 30 days. ([#42](https://github.com/alkhatibdev/dpolens/pull/42))
- **Questions are kept** unless a retention is set, and a retention applies to every question
  kept, counted from the day it was asked. Settings shows the rule.
  ([#45](https://github.com/alkhatibdev/dpolens/pull/45))
- **`dpolens init`** sets up an instance: the first administrator, their password for the
  dashboard, and the laws that apply. It does only what is missing, so it is safe to run again.
  Every other command asks in a terminal for what it needs, with a checklist for laws, roles
  and permissions, and with no terminal it fails naming the flag, as before.
  ([#46](https://github.com/alkhatibdev/dpolens/pull/46))
- **Most cited counts citations:** a search's first result, or a clause read by key from an
  assistant or the API, once per person per clause a day. Reading a clause in the dashboard
  never counts. ([#43](https://github.com/alkhatibdev/dpolens/pull/43))
- **One language at a time in the dashboard.** A law in two languages has a switch between
  them, remembered for each law, and the chip saying which text prevails stays. The API and the
  MCP server still give the prevailing text beside a translation.
  ([#44](https://github.com/alkhatibdev/dpolens/pull/44))
- **A community version.** An instance can answer anyone's assistant with no token, from the
  law alone, as one Community account that may only read, within limits for each address, each
  shared range and everybody together.
  [docs/mcp.md](https://github.com/alkhatibdev/dpolens/blob/v0.1.0-rc.2/docs/mcp.md#a-community-version)
  has every setting, including `DPOLENS_MCP_PATH`, which lets the MCP server answer at `/`.
  ([#47](https://github.com/alkhatibdev/dpolens/pull/47))
- **[SECURITY.md](https://github.com/alkhatibdev/dpolens/blob/v0.1.0-rc.2/SECURITY.md)** says
  how to report a vulnerability privately.
  ([#48](https://github.com/alkhatibdev/dpolens/pull/48))

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
