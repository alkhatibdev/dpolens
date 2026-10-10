# DPOLens

**Give your AI coding assistant access to your organisation's privacy policies and the law,
with exact, versioned citations. A self-hosted MCP server.**

---

> ### Status: pre-release
>
> There is no published image yet, and no dashboard. What runs today is a whole instance
> from source: `docker compose up` starts Postgres, the HTTP API and the MCP server, with
> GDPR and the UAE's data protection law loaded and the embedding model inside the image,
> and your assistant can search them. The UAE law is there in Arabic, which prevails, and in
> its official English translation. Two things are not built yet: searching in Arabic, and
> choosing which laws apply to an organisation, so every search covers both.
>
> Watch the repository to know when v0.1 lands. Interfaces (the HTTP API, the pack format,
> the database schema) change without notice until 1.0.

---

## Getting it running

You need Git, Docker with Compose, and an assistant that speaks MCP (Claude Code, Cursor or
VS Code).

**1. Get the code and start an instance**

```bash
git clone https://github.com/alkhatibdev/dpolens.git
cd dpolens
printf 'DPOLENS_OWNER_PASSWORD=%s\nDPOLENS_APP_PASSWORD=%s\n' \
  "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" > .env
docker compose up -d
```

The first `up` builds the images and loads GDPR and the UAE law, which takes a few minutes.
After that it takes seconds. When it returns, `docker compose ps` shows `db`, `api` and
`mcp` as healthy.

**2. Create yourself a user and a token**

```bash
docker compose exec api dpolens user create --email you@example.com \
  --name "Your Name" --role Developer
docker compose exec api dpolens token create --email you@example.com \
  --name laptop --permission documents.read
```

The token starts with `dpol_` and is shown once, so copy it now.

**3. Connect your assistant**

For Claude Code, install the plugin:

```bash
claude plugin marketplace add alkhatibdev/dpolens
claude plugin install dpolens@dpolens
```

The plugin needs two settings, the server address and your token. Open Claude Code and run
`/plugin configure dpolens@dpolens`, keep the default address (`http://localhost:8765/mcp`)
and paste the token. The token is kept in your operating system's credential store, not in a
file. Restart Claude Code, and `/mcp` lists `dpolens` as connected.

For Cursor and VS Code, [clients/](clients/) has the configuration.

**4. Ask a question**

Ask your assistant how long you may keep a deleted account, or whether you need consent to
log an IP address. The answer quotes the clause it relies on and cites it.

**If `setup` fails with "password authentication failed"**

The passwords in `.env` are fixed when the database is first created, so a new `.env` does
not reach a database that already exists. To start over, delete the local database and bring
the instance up again:

```bash
docker compose down -v
docker compose up -d
```

## Why this exists

Most weeks you write code that touches someone's personal data. You log an email address to debug a problem. You add a phone number column. You decide that deleted accounts stay in the database for ninety days, because ninety sounded about right.

Every one of those is a decision with rules attached, and the organisation is on the hook
for getting them wrong. Most developers have never read those rules. We are not lawyers,
nobody hands us the retention policy on the first day, and the law is long and written for
people who are.

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

## Does it actually find the right clause

GDPR: **recall@5 of 0.77** (95% confidence interval 0.60 to 0.90), on 30 held-out questions
drawn from ICO and EDPB guidance, using multilingual-e5-small and convex fusion, measured
26 September 2026.

That means the clause the guidance points at was among the top five answers 77% of the
time. It does not mean DPOLens answers 77% of privacy questions correctly.
[docs/retrieval.md](docs/retrieval.md) has the method, every configuration measured, and
the commands to reproduce the number yourself.

## Does an assistant actually use it

Claude Code with the DPOLens plugin searched before writing code in **36 of 36 runs** of tasks
that touch personal data, and in **3 of 45 runs** of tasks that do not: 30 held-out tasks, three
runs each, Claude Code 2.1.288 with `claude-sonnet-5-5`, measured 8 and 9 October 2026.

That means that asked to store the ID a driver checked, or to add a customer's email to an
analytics event, it looked the rules up before touching the code, every time, and asked to sort
the product list or add a dark theme, it did not. It does not mean every assistant behaves this
way: only Claude Code was measured, and whether a task should trigger a search is a judgment,
written down beside each one. [docs/trigger-test.md](docs/trigger-test.md) has the method, the
tasks, and the commands to run it yourself.

## What exists today

The commands below are the command line, which runs inside the container
(`docker compose exec api dpolens ...`) or from a source checkout.

GDPR is converted from EUR-Lex's structured XML into a reviewable pack of 99 articles and
173 recitals, loaded into Postgres as immutable versions, indexed for BM25 and meaning
search, and searched:

```bash
dpolens pack load packs/gdpr
dpolens index build
dpolens search "how long can we keep a deleted user's data"
dpolens clause show gdpr:art-17 --subtree
```

The UAE's Personal Data Protection Law, Federal Decree by Law No. (45) of 2021, is a pack of
31 articles in Arabic, which prevails, and in the official English translation. Both texts
sit under the same keys, so a citation points at the same clause in either language, and a
clause read in English says that the Arabic prevails:

```bash
dpolens pack load packs/uae-pdpl
dpolens clause show uae-pdpl:art-23 --lang en
```

The text follows the official PDFs from the UAE Legislations portal, and every article was
checked against them, the English word by word and the Arabic letter by letter.
[packs/uae-pdpl/SOURCE.md](packs/uae-pdpl/SOURCE.md) says how, and gives each PDF's checksum.

Users, roles and the governance log are what every surface authenticates and records
against:

```bash
dpolens user create --email you@example.com --name "Your Name" --role Admin
dpolens token create --email you@example.com --name laptop --permission documents.read
dpolens role list
dpolens governance verify
dpolens governance export ./export-2026-09
```

Permissions are a fixed list in code and roles are data, so an organisation can invent
"Legal" without waiting for a release. Admin, DPO and Developer are seeded and editable,
and no seeded role can see who asked a question: that permission has to be granted to
somebody on purpose.

The governance log is append-only and hash-chained. The application's database role holds
`INSERT` and `SELECT` on it and nothing else, triggers refuse an update, a delete or a
truncation whoever runs them, and an export verifies from its files alone with no DPOLens
in the loop. [docs/governance-log.md](docs/governance-log.md) is the specification,
including the hash recipe, so the export can be checked by something other than this
project.

A token is printed once and stored only as its SHA-256. What it may do is fixed when it is
created and can only narrow afterwards: every request takes the token's permissions
intersected with whatever its owner holds at that moment, so losing a role, or being
deactivated, limits every token that person owns straight away.

The HTTP API is the door every surface uses:

```bash
uvicorn --factory dpolens.api.app:create_app

curl -X POST http://localhost:8000/v1/search \
  -H "Authorization: Bearer dpol_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "how long can we keep a deleted user'"'"'s data"}'
```

Search, one clause, a clause and its subtree, and the documents in force, each result
carrying the text verbatim with its key, its version, the date that version took effect and,
for a law, the pack it came from and how far that pack has been checked. Failures are RFC
9457 problem details. [docs/api.md](docs/api.md) covers authentication, the error shapes and
every route, and [docs/openapi.json](docs/openapi.json) is the contract itself.

Every call writes one row to the query log, with personal data taken out of the question and
an expiry the instance enforces itself. Telemetry never carries the words. An instance that
could rewrite its own governance log refuses to serve at all.

The MCP server is the surface your assistant talks to: four tools, two commands, and the
guidance that tells an assistant to look something up before writing code that touches
personal data. It never receives your token as its own credential. It asks the API whose
token it is, then acts with its own and names you, so the query log records the question as
yours. [docs/mcp.md](docs/mcp.md) covers the tools, the prompts and what each call records.

There is no login yet, so a token is the only credential, and there is no published image:
`docker compose up` builds from source. The dashboard is coming.

## Contributing

Law packs are the contribution that matters most, because nobody can structure and verify the
privacy law of every jurisdiction alone. See [CONTRIBUTING.md](CONTRIBUTING.md) for scope,
the licensing gate, trust tiers and what a pack pull request needs.

## Licence

Code is Apache-2.0, contributions certified by DCO sign-off, no CLA. `packs/` carries its
own licence: law text keeps its source's licence, declared per pack, while the structural
work around it (clause keys, the tree, eval questions) is CC-BY-4.0.
