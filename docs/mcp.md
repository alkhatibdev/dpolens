# The MCP server

This is how an AI coding assistant reads your policies and the law while you work. It presents
four tools and two prompts, it answers over HTTP, and it reads the corpus through
[the HTTP API](api.md), with no database connection of its own.

## What the AI assistant gets

| Tool | What it does |
| --- | --- |
| `search_policies` | A question in ordinary words, and the clauses that answer it |
| `get_clause` | One clause by its key, with where it sits and what sits beneath it |
| `list_documents` | What this instance can cite, with the version of each |
| `get_document` | One document's top level, so a key can be found by looking |

Every result carries the clause word for word, a citation line, the document, the version, the
date that version took effect, and for a law the jurisdiction, the trust tier and the source
the text was taken from. A clause shown in translation also carries the text that prevails,
in `prevailing_text`, and its citation says which language that is.

`search_policies` searches the laws the organisation has selected and its own policies, and
nothing else. It takes `query`, `limit`, `lang`, `as_of`, `include_explanatory` and `laws`.
`lang` can be left out: a question in Arabic letters is searched in Arabic, and any other in
English. A date in `as_of` reads the documents as they stood then, which is how to answer a
question about code written two years ago. `laws` keeps a search to some of the selected laws,
by slug. A law outside the selection is refused with a message saying an administrator can add
it in Selected laws, and so is every search until somebody has chosen. `get_clause` and the
document tools keep to the same laws.

A policy's keys follow the numbers printed in it, so a new version that inserts a clause gives
the clauses after it new keys. A citation names its version, which keeps it exact. `get_clause`,
reading a policy's clause in a version no longer in force, says in `now` where the same rule is
today and whether its words changed, and a key that named a different rule in the version
before says so in `formerly`. A clause of a policy the organisation has archived comes back
with `archived` true.

Two prompts arrive as commands in the clients that show them:

- **`policy_check`** reviews the change you are working on, names every place it touches
  personal data, and reports what each clause requires with its citation.
- **`policy_tour`** demonstrates the instance with a few real searches, which is the quickest
  way to see what it can cite.

Claude Code shows them as `/dpolens:policy-check` and `/dpolens:policy-tour`, and VS Code as
`/dpolens.policy_check` and `/dpolens.policy_tour`.

The server also sends instructions when a client connects, saying when to search, that a
remembered article number is not a citation, and that every call is recorded.

## Connecting

[../clients/](../clients/) holds a ready made configuration for Claude Code, Cursor and
VS Code. The short version: the URL of a local instance is `http://localhost:8765/mcp`, and
your own token goes in an `Authorization: Bearer` header.

## Who the instance thinks is asking

The token in that header is yours, not the server's, and the server never passes it on. It asks
the API whose token it is, then makes the real call with its own credential and two headers
naming you and your token. The API checks that pair rather than believing it.

So the query log names the developer who asked, not the server they went through, and your
permissions are the ones that apply. A token with nothing on it is refused by the API, and the
refusal reaches the AI assistant as a message it can read out.

Nothing about a token is cached. Revoking one stops the next call.

## The credential the server itself uses

The server cannot reach the database, so it cannot create anything for itself. The instance
provisions one credential for it and writes it to a file both containers can read:

```bash
dpolens token ensure-surface --out /run/dpolens/surface-token
```

The API container runs that as it starts. The credential carries no permissions at all: what it
is trusted with is naming the person it acts for, which is a flag on the token that only
somebody with shell access can set. Nothing prints it; it is only ever written to the file.

Running it again leaves a working credential alone. When the file no longer holds one, a new
credential is created and the one before it is revoked, so exactly one works at a time. The MCP
server rereads the file when the API refuses its credential, so provisioning a new one does not
need a restart.

## What is recorded

Every call writes one row to the query log, through the API: the operation, the outcome, the
developer and the token they used, which clauses came back, and the question with personal data
taken out. Rows are kept, unless the instance is set to delete them a number of days after
they were asked.

Each tool's description says so too, where a developer reads it before calling anything.

## Running it

`docker compose up` starts it beside the API, on port 8765. On its own:

```bash
export DPOLENS_MCP_API_URL=http://localhost:8000
export DPOLENS_MCP_SURFACE_TOKEN_FILE=/run/dpolens/surface-token
uv run dpolens-mcp
```

| Variable | Default | What it does |
| --- | --- | --- |
| `DPOLENS_MCP_API_URL` | required | Where the DPOLens API is |
| `DPOLENS_MCP_SURFACE_TOKEN_FILE` | `/run/dpolens/surface-token` | The file holding the server's own credential |
| `DPOLENS_MCP_HOST` | `127.0.0.1` | Which address to listen on. A container sets `0.0.0.0` |
| `DPOLENS_MCP_PORT` | `8765` | Which port to listen on |
| `DPOLENS_MCP_ALLOWED_HOSTS` | loopback | Host headers to answer, as a JSON list |
| `DPOLENS_MCP_REQUEST_TIMEOUT_SECONDS` | `30` | How long to wait for the API |
| `DPOLENS_MCP_CREDENTIAL_WAIT_SECONDS` | `120` | How long to wait at startup for the credential file |
| `DPOLENS_MCP_LOG_LEVEL` | `INFO` | How much the process says |
| `DPOLENS_MCP_PATH` | `/mcp` | Where the MCP endpoint answers. A server with a hostname of its own can answer at `/` |

`GET /live` answers 200 while the process runs and needs no credential. The MCP endpoint itself
is `/mcp` unless `DPOLENS_MCP_PATH` says otherwise.

The server answers to `localhost` and `127.0.0.1` and refuses any other name in the `Host`
header. That is what keeps a page in a browser from reaching an instance on a private network.
An instance other people connect to has to name itself:

```bash
DPOLENS_MCP_ALLOWED_HOSTS='["dpolens.example.com:8765"]'
```

## A community version

A community version answers anyone, with no token, from the law it holds and no
organisation's policies. The settings below turn an instance into one.

Every question is asked as one service account, Community, which may read documents and
nothing else, so the questions log records nobody. The API makes the account when it starts
with `DPOLENS_COMMUNITY=true`, and writes its id and its token's id to a file the MCP server
reads. The file holds no secret: the server names the account with its own credential, as it
names a person, and revoking the account's token closes the community version. On such an
instance, setup publishes no sample policy.

The server holds every caller to three limits, kept in memory and never written down: one for
each address, a larger one shared by each range that carries many people's calls, and one for
everybody together. claude.ai, Claude Desktop and ChatGPT call from their platforms' own
servers, so every person using one of them arrives from the same few addresses: name those
ranges in `DPOLENS_MCP_SHARED_RANGES`, from what each platform publishes. A refused call gets
`429` and `Retry-After`. The AI assistant is told, in the server's instructions and the search
tool's description, how long questions are kept.

| Variable | Read by | Default | What it does |
| --- | --- | --- | --- |
| `DPOLENS_COMMUNITY` | API and setup | `false` | Make the Community account as the API starts, and publish no sample policy |
| `DPOLENS_COMMUNITY_FILE` | API | `/run/dpolens/community` | Where the API writes the account's ids |
| `DPOLENS_MCP_COMMUNITY` | MCP server | `false` | Answer anyone without a token, as the Community account |
| `DPOLENS_MCP_COMMUNITY_FILE` | MCP server | `/run/dpolens/community` | Where the server reads the account's ids |
| `DPOLENS_MCP_CLIENT_ADDRESS_HEADER` | MCP server | none | A header carrying the caller's address, such as `CF-Connecting-IP`, when a proxy in front always sets it |
| `DPOLENS_MCP_SHARED_RANGES` | MCP server | `[]` | Address ranges that share one allowance, as a JSON list |
| `DPOLENS_MCP_PER_ADDRESS_PER_MINUTE` | MCP server | `30` | Calls one address may make a minute |
| `DPOLENS_MCP_PER_RANGE_PER_MINUTE` | MCP server | `120` | Calls one shared range may make a minute |
| `DPOLENS_MCP_OVERALL_PER_MINUTE` | MCP server | `300` | Calls everybody together may make a minute |
| `DPOLENS_QUERY_LOG_RETENTION_DAYS` | API and MCP server | none | How long questions are kept. The server reads the same variable, to tell the AI assistant |

The API still limits each token, so on a community version `DPOLENS_RATE_LIMIT_PER_MINUTE`
has to allow at least the overall limit, or the Community account's one token reaches its own
limit first.

## When something does not work

**The client says the server needs authentication.** The token in the header is not one this
instance can use: unknown, revoked, expired, or belonging to somebody who has been deactivated.
`dpolens token list` shows which. There is no login to go and find: DPOLens tokens are made on
the command line.

**The container will not start, and the log says there is no credential.** The API container
writes it as it starts. `docker compose logs api` says whether it got that far, and
`dpolens token ensure-surface` creates one by hand.

**The client connects but every call fails.** The API is refusing the server's own credential or
cannot be reached. The MCP server's log says which, and it is the operator's to fix rather than
the developer's.

**A call is refused with a permission.** The message names the permission the token lacks. A
token's permissions are fixed when it is created and narrowed by its owner's roles, so granting
the role is what changes it.
