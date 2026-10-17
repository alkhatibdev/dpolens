<p align="center">
  <br>
  <br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/dpolens-logo-on-dark.svg">
    <img alt="DPOLens" src="docs/brand/dpolens-logo.svg" height="64">
  </picture>
  <br>
  <br>
</p>

<p align="center">
  <strong>Give your AI coding assistant access to your organisation's privacy policies and the
  law, with exact, versioned citations. A self-hosted MCP server.</strong>
</p>

<p align="center">
  <a href="https://github.com/alkhatibdev/dpolens/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/alkhatibdev/dpolens/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="Licence: Apache-2.0" src="https://img.shields.io/badge/licence-Apache--2.0-12784E"></a>
</p>

<p align="center">
  <a href="#getting-it-running">Get it running</a> ·
  <a href="docs/mcp.md#connecting">Connect your assistant</a> ·
  <a href="#does-it-actually-find-the-right-clause">Search scores</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

> [!NOTE]
> **Pre-release.** There is no published image yet: `docker compose up` builds a whole instance
> from source. Interfaces (the HTTP API, the pack format, the database schema) change without
> notice until 1.0. [What exists today](#what-exists-today) has the detail, and watching the
> repository tells you when v0.1 lands.

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

The first `up` builds the images, or downloads them once the version has been released, and
loads GDPR and the UAE law, which takes a few minutes. After that it takes seconds. When it returns, `docker compose ps` shows `db`, `api`,
`dashboard` and `mcp` as healthy, and `worker` as running.

**2. Create yourself an administrator**

```bash
docker compose exec api dpolens user create --email you@example.com \
  --name "Your Name" --role Admin

docker compose exec api dpolens user set-password you@example.com
```

This is the only account made on the command line. Everyone else is added in the
dashboard, and gets a one-time link to choose their own password.

**3. Open the dashboard and make a token**

Go to [http://localhost:8080](http://localhost:8080) and sign in with that email and
password. The first time, it asks which laws apply to your organisation: tick them, or decide
later, and until somebody chooses every search covers both. Under Tokens, create a token for
your assistant. It starts with `dpol_` and is shown once, so copy it now.

The library holds every law loaded, clause by clause and in each of its languages, with a
search box for asking it in your own words. Users and roles is where you add the people you
work with and decide what each role allows. Overview shows how much was asked, what answered
it and what found nothing, and Logs holds every question asked and every change made to the
instance. Selected laws changes which laws a search covers, and Settings shows how the
instance is set up, with [docs/configuration.md](docs/configuration.md) saying how to change
it.

**4. Connect your assistant**

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

**5. Ask a question**

Ask your assistant how long you may keep a deleted account, or whether you need consent to
log an IP address. The answer quotes the clause it relies on and cites it.

**If `docker compose up` stops**

`docker compose ps -a` shows which service stopped, and the end of its log says why, in one
line that names the cause and what to do about it:

```bash
docker compose logs setup
```

The usual cause is a password the database refuses. The database keeps the passwords that
were in `.env` when it was first created, so writing a new `.env` afterwards does not change
them. Put that `.env` back if you still have it. If you don't, starting over deletes the local
database, and with it every user, token and log entry on the instance:

```bash
docker compose down -v
docker compose up -d
```

After pulling a newer version, start it with `docker compose up -d --build`. Without
`--build`, Compose runs the images it built from the old code.

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

| Law | Held-out questions | recall@5 | 95% interval |
| --- | --- | --- | --- |
| GDPR | 30, from ICO and EDPB guidance | **0.77** | 0.60 to 0.90 |
| The UAE's data protection law | 19 topics, each asked in Arabic and in English | **0.55** | 0.37 to 0.74 |
| GDPR asked in Arabic | the same 30, in Arabic | **0.30** | 0.13 to 0.47 |

With multilingual-e5-small and convex fusion, measured 14 October 2026. That means that for
GDPR, the clause the guidance points at was among the top five answers 77% of the time. It does
not mean DPOLens answers 77% of privacy questions correctly. Asked in Arabic alone, the UAE law
scores 0.42, and in English 0.68. GDPR has no Arabic text, so an Arabic question about it has to
cross languages, and finds its clause far less often.
[docs/retrieval.md](docs/retrieval.md) has the method, every configuration measured, and the
commands to reproduce the numbers yourself.

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
clause read in English says that the Arabic prevails and carries the Arabic with it:

```bash
dpolens pack load packs/uae-pdpl
dpolens clause show uae-pdpl:art-23 --lang en
```

The text follows the official PDFs from the UAE Legislations portal, and every article was
checked against them, the English word by word and the Arabic letter by letter.
[packs/uae-pdpl/SOURCE.md](packs/uae-pdpl/SOURCE.md) says how, and gives each PDF's checksum.

A law gets new versions on its own schedule, apart from DPOLens's releases, and each is
released as a pack archive. `dpolens pack update` says which laws have a newer version, and
`dpolens pack update gdpr` loads it beside the version before it, so a citation of the old
text still reads that text. A server with no way to the internet imports the archive
instead. Nothing changes which version of a law an instance has unless somebody runs one of
these, an upgrade of DPOLens included, and every version loaded is written to the governance
log. [docs/releases.md](docs/releases.md#law-packs) says how:

```bash
dpolens pack update
dpolens pack update gdpr
dpolens pack import dpolens-pack-gdpr-2026.2.tar.gz
```

An administrator chooses which laws apply to the organisation. A search covers those and
the organisation's own policies, so a company in Dubai with no EU customers is not answered
from GDPR. Another law is searched only when a search names it, and its clauses come back
marked as outside the choice. Every change to the choice is written to the governance log,
and until somebody chooses, every loaded law is searched. The dashboard asks whoever may
choose as they sign in, until somebody has, and Selected laws changes the choice later; the
command line does it too:

```bash
dpolens laws list
dpolens laws select uae-pdpl
dpolens search "can we send customer data abroad" --law gdpr
```

An organisation's own policy, a Word or Markdown file, is read into clauses too, each with a
key and its text word for word. No AI model builds the tree: it comes from the file's heading
styles, automatic numbering and lists, then its type, then the numbers written into its
text, and anything those disagree about is flagged for a reviewer rather than guessed.
Tables become a clause for each row, and a cover page, a contents page or a version table is
set aside rather than searched. The command line shows the result for a file on your
computer, without storing anything:

```bash
dpolens policy parse retention-policy.docx --slug acme-retention
```

Uploaded, a policy becomes a draft that nothing searches. Somebody checks its flags against
the file, which the dashboard shows beside the clauses as it was read, and settles them. Where
the parser read a clause wrongly, they fix it without changing a word: split it, merge it with
the one before, make it a heading or text, or move it a level. Once published, the version
never changes: searches find it from the day it takes effect, by its words at once and by
meaning once the worker has embedded it. A new
version is matched to the one before it clause by clause, and every match a person should
confirm, such as a clause whose number changed, is a flag for the reviewer, who can say a
match is wrong as well as confirm it, and can say a new clause is the same rule as one that
nothing continues, which the review asks about when the two share most of their words. Keys follow the
numbers printed in the policy, and a citation names its version, so a citation of version
1's 4.2 still reads the rule it quoted, and says where that rule is in the version in force
today. The library lists every version, reads any of them as it stood, and compares any two. The file each version came from is kept and checked against its hash whenever it is
read, archiving a policy takes it out of search without deleting anything, and every step is
written to the governance log:

```bash
dpolens policy upload retention-policy.docx --slug acme-retention --effective-date 2026-01-01
dpolens policy draft acme-retention
dpolens policy fix acme-retention 4.1 split --before "4.2"
dpolens policy accept acme-retention --all
dpolens policy publish acme-retention
dpolens policy revise acme-retention retention-policy-v2.docx --effective-date 2026-07-01
dpolens policy compare acme-retention 1 2
```

A new instance starts with a made-up sample policy, so there is one to search before
yours are in.

[docs/policies.md](docs/policies.md) explains how clauses, keys and flags are decided, and
what happens to a policy from its upload to its archive.

Users, roles and the governance log are what every surface authenticates and records
against. The dashboard manages people, roles and tokens, and checks and exports the
governance log; the command line does too:

```bash
dpolens user create --email you@example.com --name "Your Name" --role Admin
dpolens user set-password you@example.com
dpolens token create --email you@example.com --name laptop --permission documents.read
dpolens role list
dpolens governance verify
dpolens governance export ./export-2026-09
```

Permissions are a fixed list in code and roles are data, so an organisation can invent
"Legal" without waiting for a release. Admin, DPO and Developer are seeded and editable,
and no seeded role can see who asked a question, Admin included: that permission has to be
granted to somebody on purpose. An administrator grants it by switching it on for a role,
and the governance log records who did and when.

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
for a law, the pack it came from and how far that pack has been checked. Policies are
uploaded, reviewed, published and archived through it too, with the file as the request
body. Failures are RFC 9457 problem details. [docs/api.md](docs/api.md) covers
authentication, the error shapes and every route, and [docs/openapi.json](docs/openapi.json)
is the contract itself.

Every call writes one row to the query log, with personal data taken out of the question and
an expiry the instance enforces itself. Telemetry never carries the words. An instance that
could rewrite its own governance log refuses to serve at all.

The MCP server is the surface your assistant talks to: four tools, two commands, and the
guidance that tells an assistant to look something up before writing code that touches
personal data. It never receives your token as its own credential. It asks the API whose
token it is, then acts with its own and names you, so the query log records the question as
yours. [docs/mcp.md](docs/mcp.md) covers the tools, the prompts and what each call records.

The dashboard is a client of the same API. A person signs in with an email and a password,
and the session lives in a cookie the page's scripts cannot read and no other site can
send. It ends after 30 minutes idle or 8 hours in all, and the governance log records every
sign-in. The library lists each document with the version in force and which of its
languages prevails, and reads a law article by article, its official translation beside the
text that prevails with the key between them. Every key copies the clause with the same
citation the MCP server gives an assistant. Search covers the selected laws, with another
law, a date or the recitals a click away.

Whoever may read every question starts on the Overview: how much was asked over the last 7
or 30 days, how much of it found a clause in force, the clauses cited most, and the questions
that found nothing, each of which may be a policy waiting to be written. The questions log
shows every question as it was stored, with a mark where personal data was taken out. Names
stay hidden unless you hold the permission to see who asked, and every look at them is
written to the governance log. Somebody who may read only their own questions sees just
those. The governance log reads as plain sentences, checks its hash chain each time it is
opened, and exports the same files as `dpolens governance export`. Settings shows how the
instance is set up: how long a question is kept and what is taken out of it, when a session
ends, where assistants connect, and that no AI provider is used.
[docs/configuration.md](docs/configuration.md) lists every setting and how to change it. The
interface is English, built so an Arabic one can follow, and it works on a phone. There is no
published image yet: `docker compose up` builds from source, and once a version is released it
downloads that version's images, built for amd64 and arm64 and attested.
[docs/releases.md](docs/releases.md) says what a release publishes and how to check that an
image was built here.

## Contributing

Law packs are the contribution that matters most, because nobody can structure and verify the
privacy law of every jurisdiction alone. See [CONTRIBUTING.md](CONTRIBUTING.md) for scope,
the licensing gate, trust tiers and what a pack pull request needs.

## Licence

Code is Apache-2.0, contributions certified by DCO sign-off, no CLA. `packs/` carries its
own licence: law text keeps its source's licence, declared per pack, while the structural
work around it (clause keys, the tree, eval questions) is CC-BY-4.0.
