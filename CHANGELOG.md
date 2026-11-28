# Changelog

Each release of DPOLens, newest first, written for the people who run an instance and decide
whether to upgrade. A release's notes start from the titles of the pull requests it holds and
are edited by hand. Changes to the HTTP API are listed one by one in
[docs/api-changelog.md](docs/api-changelog.md), and law packs have versions of their own.

## 0.3.0

The release for finding the rule that answers: questions written beside every clause of both
laws help search find it, each result is a whole rule, each law is ranked by itself, and a law
is named in each of its languages. On held-out questions written by somebody who had not seen
what search returns, the clause the guidance points at is among the top five answers 90% of the
time for GDPR and 87% for the UAE's law, where 0.2.0 does so 55% and 60% of the time. The
interfaces (the HTTP API, the pack format, the database schema) can still change before 1.0,
and only the newest release gets fixes.

Before upgrading from 0.2.0:

- **Take a backup, and keep it until 0.3.0 runs as it should.** 0.3.0 changes the database, so
  the way back to 0.2.0 is the backup taken before upgrading.
  [Upgrading](https://dpolens.com/docs/releases#upgrading) takes it first, as written, and
  [Going back](https://dpolens.com/docs/releases#going-back) restores it.
- **The first start takes minutes.** Setup updates the database, embeds every clause of the
  laws again, since each clause is now embedded under its law's short name, and embeds the
  laws' search questions, about 5,800 of them. The API starts once that is done: about 11
  minutes with 2 processors and 6 with 4, where 0.2.0's first start took about 4 and 2. Later
  starts take seconds.
- **A search asks more of the database:** about six times the work it asked of 0.2.0, since each
  law is ranked by itself with its search questions and whole rules are read. With 2 processors,
  a search takes about 200 ms, where it took about 130. An instance that caps the database's
  processor time may need a higher cap.
- **Load the laws' new versions.** The image carries GDPR 2026.2 and the UAE PDPL 2026.3, and an
  instance keeps the versions it has until somebody loads newer ones:

  ```bash
  docker compose exec api dpolens pack update gdpr
  docker compose exec api dpolens pack update uae-pdpl
  ```

  Their words are searchable at once, and their meaning once the worker has embedded them: about
  3 minutes with 2 processors, while it holds about 1.2 GB of memory. Until they are loaded, an
  instance names each law in English alone, and holds the UAE law's definitions in one clause,
  Article 1, which `dpolens search-questions status` lists as a clause without questions. An
  instance with no way to the internet loads them from its image, as setup's log says:
  `dpolens pack load /opt/dpolens/packs/gdpr`, and the same for `uae-pdpl`.
- **Upgrade DPOLens before updating a law.** These versions are released under
  `packs/<slug>/<version>`, a tag 0.2.0 does not read, so on 0.2.0 `dpolens pack update` finds
  nothing newer than 2026.1.
- **If `.env` sets `DPOLENS_VERSION`,** set it to 0.3.0 or take it out: otherwise the instance
  keeps running the release it names.
- **A client of the HTTP API may need changing.** A search answers with whole rules, and `limit`
  counts rules. Results take turns by law, so they are not in `score` order across laws. A law's
  and a document's names are maps from language to name in `GET /v1/documents`, `GET /v1/laws`
  and `GET /v1/overview`.
  [The API changelog](https://github.com/alkhatibdev/dpolens/blob/v0.3.0/docs/api-changelog.md)
  lists every change. The MCP server's tools keep their names and arguments, so an AI assistant
  needs nothing.

What changed since 0.2.0:

- **Search questions.** Questions written beside each clause of GDPR and the UAE law, and
  checked against it, help search find the clause that answers. They are never shown, quoted or
  cited. `dpolens search-questions off` turns them off, `status` lists any clause left without
  them, and the Settings page says whether searches use them.
  ([#96](https://github.com/alkhatibdev/dpolens/pull/96),
  [#97](https://github.com/alkhatibdev/dpolens/pull/97),
  [#110](https://github.com/alkhatibdev/dpolens/pull/110),
  [#113](https://github.com/alkhatibdev/dpolens/pull/113))
- **Whole rules.** A result is the rule a match belongs to: the words that introduce it, and the
  clauses beneath them, each with its own key to cite it by. So GDPR Article 17(1)(b) comes with
  the paragraph that says there is a right to erasure where one of the grounds applies. In the
  API, the MCP server, the dashboard and `dpolens search`.
  ([#114](https://github.com/alkhatibdev/dpolens/pull/114),
  [#115](https://github.com/alkhatibdev/dpolens/pull/115))
- **Each law ranked by itself.** Each law a search covers, and the organisation's own policies,
  are ranked apart and take turns in the results, so a policy is not crowded out by a law with
  search questions. Results are ranked by standardised fusion, and a question that nearly quotes
  a clause gets that clause first.
  ([#110](https://github.com/alkhatibdev/dpolens/pull/110),
  [#111](https://github.com/alkhatibdev/dpolens/pull/111),
  [#125](https://github.com/alkhatibdev/dpolens/pull/125))
- **The same search, the same results.** Meaning search compares every vector, where an
  approximate index could return other clauses as the database's statistics changed. Search
  reads each document's version in force, and no longer matches the words of a version that was
  replaced.
  ([#99](https://github.com/alkhatibdev/dpolens/pull/99),
  [#109](https://github.com/alkhatibdev/dpolens/pull/109))
- **Setup gathers the database's statistics** once everything is loaded. The database gathers
  them for a table only once enough of it has changed, which a small table, such as each
  document's versions, may never reach, and a search planned without them takes longer.
  ([#126](https://github.com/alkhatibdev/dpolens/pull/126))
- **Laws named in their own languages, and the days each text applies.** Pack format 2 names a
  law in every language it has a text in, so an Arabic clause of the UAE law carries the law's
  Arabic title, and each clause is embedded under its law's short name, in its own language.
  Every clause says when its text applies, and a search returns a provision that does not apply
  yet, marked, so a duty can be prepared for.
  ([#92](https://github.com/alkhatibdev/dpolens/pull/92),
  [#93](https://github.com/alkhatibdev/dpolens/pull/93))
- **The UAE law's definitions** are clauses of their own in UAE PDPL 2026.3, each keyed by the
  term it defines, such as `uae-pdpl:art-1:def-personal-data`. Held in one clause, the twenty
  were too long for the search model, which read about the first 40% of them.
  ([#116](https://github.com/alkhatibdev/dpolens/pull/116))
- **Law packs** are released under `packs/<slug>/<version>`, and `dpolens pack scaffold` starts
  a new one. CI reads every pack in the repository as an instance reads it.
  ([#75](https://github.com/alkhatibdev/dpolens/pull/75),
  [#123](https://github.com/alkhatibdev/dpolens/pull/123))
- **The MCP server** asks for one question per search, saying what the code does with which
  data. On a community version, it asks for questions in general terms and allows each IP
  address 60 calls a minute, where it allowed 30. The Claude Code skill's description says
  personal data, not data, for what is sent to another service.
  ([#107](https://github.com/alkhatibdev/dpolens/pull/107),
  [#112](https://github.com/alkhatibdev/dpolens/pull/112),
  [#121](https://github.com/alkhatibdev/dpolens/pull/121),
  [#122](https://github.com/alkhatibdev/dpolens/pull/122))
- **The dashboard** fetches each page the first time it is opened, and carries the new logo.
  ([#102](https://github.com/alkhatibdev/dpolens/pull/102),
  [#117](https://github.com/alkhatibdev/dpolens/pull/117),
  [#118](https://github.com/alkhatibdev/dpolens/pull/118),
  [#119](https://github.com/alkhatibdev/dpolens/pull/119))
- **Search is scored on questions written blind**: questions a person wrote without seeing what
  search returns, and the searches Claude Code wrote during 40 coding tasks. `dpolens evals run
  --outcomes` keeps each question's outcome, and `dpolens evals compare` judges a change to
  search by a rule written down before it is measured.
  ([#98](https://github.com/alkhatibdev/dpolens/pull/98),
  [#101](https://github.com/alkhatibdev/dpolens/pull/101),
  [#125](https://github.com/alkhatibdev/dpolens/pull/125))

On the same held-out questions, how often each release puts the clause the guidance points at
among the top five answers, each law searched alone:

| Questions | GDPR, 0.2.0 | GDPR, 0.3.0 | The UAE law, 0.2.0 | The UAE law, 0.3.0 |
| --- | --- | --- | --- | --- |
| Asked by a person | 55% | 90% | 60% | 87% |
| Written by an AI assistant, on an instance of your own | 40% | 40% | 27% | 62% |
| Written by an AI assistant, on the community version | 35% | 55% | 33% | 79% |

[How it was measured](https://github.com/alkhatibdev/dpolens/blob/v0.3.0/evals/retrieval.md)
gives each set, the figures with both laws selected, and what the figures do not say.

## 0.2.0

The release for running an instance for real: backups taken while it answers, restores, a
first start in a third of the memory, a worker that holds no model between jobs, and logs that
keep nothing anybody asked. The interfaces (the HTTP API, the pack format, the database
schema) can still change before 1.0, and only the newest release gets fixes.

Before upgrading from 0.1.0:

- **Take the backup from the new checkout.** 0.1.0 has no backup service, so check out
  `v0.2.0` first and back up while 0.1.0 still runs, then start the new release:

  ```bash
  git fetch --tags
  git checkout v0.2.0
  DPOLENS_VERSION=0.1.0 docker compose run --rm --no-deps backup
  docker compose pull
  docker compose up -d --wait
  ```

  `DPOLENS_VERSION=0.1.0` takes the backup with the database image that is running and writes
  0.1.0 into it, and `--no-deps` leaves the running database as it is. From 0.2.0 on,
  [Upgrading](https://dpolens.com/docs/releases#upgrading) takes the backup first, as written.
- **If `.env` sets `DPOLENS_VERSION`,** set it to 0.2.0 or take it out: otherwise the instance
  keeps running the release it names.
- **No table has changed**, so going back to 0.1.0 is `git checkout v0.1.0` and
  `docker compose up -d`.
- **The API no longer serves `/docs` and `/redoc`.** The reference is at
  https://dpolens.com/docs/api, and `/openapi.json` describes the API to any tool.
- **The API writes no access log.** Each request is one `api.request` line in its JSON
  output, naming the route it matched rather than the address, and the dashboard's server logs
  each path without its query string. Anything that reads the old access log lines needs to
  read these instead.

What changed since 0.1.0:

- **Backups and restores.** `docker compose run --rm backup` copies the database and the
  original files into a folder of its own, with their checksums, while the instance keeps
  answering, and `DPOLENS_BACKUP_KEEP` keeps that many. `docker compose run --rm restore`
  checks a backup and loads it into an instance that holds nothing yet.
  ([#66](https://github.com/alkhatibdev/dpolens/pull/66))
- **`dpolens --version`**, beside `dpolens version`. On a community version, `dpolens init`
  names the laws and says that AI assistants connect with no token, and a search refused
  before any law is chosen says an administrator chooses them the next time they sign in.
  ([#67](https://github.com/alkhatibdev/dpolens/pull/67))
- **The first start needs a third of the memory, and is up to five times faster.** Setup
  embeds the laws in batches of clauses of about one length, with as many threads as its
  container may use: it peaks at 1.2 GB, down from 3.4 GB, and takes about 4 minutes on 2
  processors. The vectors and the search results are the same.
  ([#68](https://github.com/alkhatibdev/dpolens/pull/68))
- **The worker loads the model only to embed a policy, and frees it after**, so a running
  instance uses about 1.2 GB, down from 2 GB.
  ([#70](https://github.com/alkhatibdev/dpolens/pull/70))
- **Nothing an instance serves loads from another site.** FastAPI's `/docs` and `/redoc`
  pages are gone, and `.env.example` names `HTTPS_PROXY` and `NO_PROXY`, for the proxy
  `dpolens pack update` downloads through.
  ([#69](https://github.com/alkhatibdev/dpolens/pull/69))
- **What somebody asks stays out of the logs.** A database error no longer prints the values
  it was given, which put a failed search's question in the API's output word for word. The
  API names each request's route instead of writing its address, the dashboard's server leaves
  out query strings, and the MCP server no longer logs each call to the API or the words of a
  refusal. The questions log redacts a key or a slug as it redacts a question, and a question
  or an address carrying the NUL character is refused with 422 instead of failing.
  ([#72](https://github.com/alkhatibdev/dpolens/pull/72))

[Running an instance](https://dpolens.com/docs/running) says what machine an instance needs,
what it connects to, how to run it behind a proxy or with no internet, and how to back it up.

## 0.1.0

The first release of DPOLens, after three release candidates. Since 0.1.0-rc.3 it supports
Codex, has a plugin for Cursor's directories, and says "AI assistant" and "URL" wherever people
read them. The interfaces (the HTTP API, the pack format, the database schema) can still change
before 1.0, and only the newest release gets fixes.

Nothing needs doing before upgrading from 0.1.0-rc.3: no setting, route or table has changed.
From an earlier release candidate, the steps in its own section below apply as well.

What it holds:

- **An MCP server** that gives an AI coding assistant four tools to search and read the law
  and the organisation's own policies, with guidance that tells it to search before writing
  code that touches personal data. Every result is the clause word for word, with its key, its
  version and the date that version took effect. Claude Code has a plugin, and `clients/` has
  the files for Codex, Cursor and GitHub Copilot in VS Code.
- **GDPR, and the UAE's Personal Data Protection Law** in Arabic, which prevails, and in its
  official English translation. An administrator chooses which laws apply, and a search keeps
  to them. A law has releases of its own: `dpolens pack update` loads a newer version beside the
  one before it, and nothing changes the law in force unasked.
- **Search by words and by meaning** on the CPU, with no API key and no LLM. On held-out
  questions, the clause the guidance points at is among the top five answers 77% of the time
  for GDPR and 55% for the UAE's law.
- **The organisation's own policies**, uploaded as Word or Markdown files, read into clauses
  without an AI model, checked beside the file, and published as versions that never change.
  Any two versions can be compared.
- **A dashboard** for the library, search, policies, people, roles, tokens, the laws that
  apply, an overview of what was asked, and both logs: the governance log, append only and hash
  chained, and the questions asked, with personal data taken out, kept unless a retention is
  set.
- **A community version**: an instance can answer anyone's AI assistant with no token, from the
  law alone, within limits for each IP address, each shared range and everybody together.

What changed since 0.1.0-rc.3:

- **Codex**, beside Claude Code, Cursor and GitHub Copilot in VS Code: a configuration file in
  `clients/codex/`, and a Codex tab where the dashboard shows a new token. On a community
  version, the MCP server's instructions now say when to search before anything else, which is
  where Codex looks when it chooses a server.
  ([#60](https://github.com/alkhatibdev/dpolens/pull/60))
- **A Cursor plugin** for Cursor's directories. It connects Cursor to the community version,
  with a rule that says when to search; `clients/cursor/` still connects Cursor to your own
  instance. ([#61](https://github.com/alkhatibdev/dpolens/pull/61),
  [#62](https://github.com/alkhatibdev/dpolens/pull/62))
- **A search on a community version** says it searched the law alone, no longer the
  organisation's own policies too. ([#61](https://github.com/alkhatibdev/dpolens/pull/61))
- **"AI assistant" and "URL"** wherever people read them: the dashboard, the API's descriptions
  and the Compose file's comments. Only the words changed: no setting, field or route was
  renamed. ([#54](https://github.com/alkhatibdev/dpolens/pull/54),
  [#56](https://github.com/alkhatibdev/dpolens/pull/56))
- **The user docs are on [dpolens.com](https://dpolens.com/docs/introduction)**, each page
  linking to its source. ([#55](https://github.com/alkhatibdev/dpolens/pull/55))

## 0.1.0-rc.3

The third release candidate for 0.1.0, with three fixes a load test found in 0.1.0-rc.2. The
interfaces can still change before 1.0, and only the newest release gets fixes.

Before upgrading from 0.1.0-rc.2:

- **A retention now deletes.** Under Compose, 0.1.0-rc.2's worker was never given
  `DPOLENS_QUERY_LOG_RETENTION_DAYS`, so an instance that set it kept every question. The first
  daily purge after the upgrade deletes every question older than the retention.

From 0.1.0-rc.1, 0.1.0-rc.2's steps below apply as well.

What changed:

- **The worker is given the questions retention**, so the daily purge deletes by it.
  ([#50](https://github.com/alkhatibdev/dpolens/pull/50))
- **Threads share one tokenizer.** Each thread that embedded text kept its own copy, about 280
  MB, so the API's memory grew with concurrent searches until it ran out. In a load test it now
  stays under 1 GB however many search at once.
  ([#51](https://github.com/alkhatibdev/dpolens/pull/51))
- **A burst of searches no longer stalls the API.** More than 15 searches at once each held one
  database connection and waited for a second, until all of them failed after 30 seconds. The
  API now runs at most 7 requests at once and the rest wait their turn: 40 at once are answered
  within a few seconds. ([#52](https://github.com/alkhatibdev/dpolens/pull/52))

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
