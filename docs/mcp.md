# The MCP server

This is how an AI coding assistant reads your policies and the law while you work. It presents
four tools and two prompts, it answers over HTTP, and it reads the corpus through
[the HTTP API](api.md), with no database connection of its own.

## What the assistant gets

| Tool | What it does |
| --- | --- |
| `search_policies` | A question in ordinary words, and the clauses that answer it |
| `get_clause` | One clause by its key, with where it sits and what sits beneath it |
| `list_documents` | What this instance can cite, with the version of each |
| `get_document` | One document's top level, so a key can be found by looking |

Every result carries the clause word for word, a citation line, the document, the version, the
date that version took effect, and for a law the jurisdiction, the trust tier and the source
the text was taken from.

`search_policies` searches every pack loaded on the instance and the organisation's own
policies. It takes `query`, `limit`, `lang`, `as_of` and `include_explanatory`. A date in
`as_of` reads the documents as they stood then, which is how to answer a question about code
written two years ago.

Two prompts arrive as commands in the clients that show them:

- **`policy_check`** reviews the change you are working on, names every place it touches
  personal data, and reports what each clause requires with its citation.
- **`policy_tour`** demonstrates the instance with a few real searches, which is the quickest
  way to see what is loaded.

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
refusal reaches the assistant as a message it can read out.

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
taken out. Rows expire on the instance's retention, which defaults to 365 days.

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

`GET /live` answers 200 while the process runs and needs no credential. The MCP endpoint itself
is `/mcp`.

The server answers to `localhost` and `127.0.0.1` and refuses any other name in the `Host`
header. That is what keeps a page in a browser from reaching an instance on a private network.
An instance other people connect to has to name itself:

```bash
DPOLENS_MCP_ALLOWED_HOSTS='["dpolens.example.com:8765"]'
```

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
