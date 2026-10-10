# The HTTP API

Every surface reaches DPOLens over this API: the MCP server, the dashboard, and
anything you write yourself. A surface can be written in any language, and it can
run somewhere the database is not.

> **Unstable until 1.0.** Routes, fields and error identifiers may change in any
> release before 1.0. Every change is recorded in
> [api-changelog.md](api-changelog.md), and [openapi.json](openapi.json) is
> published beside it.

## Authentication

Send a personal access token as a bearer credential:

```bash
curl -X POST http://localhost:8000/v1/search \
  -H "Authorization: Bearer dpol_..." \
  -H "Content-Type: application/json" \
  -d '{"query": "how long can we keep a deleted user'"'"'s data"}'
```

A token is created on the command line and shown once:

```bash
dpolens user create --email you@example.com --name "Your Name" --role Developer
dpolens token create --email you@example.com --name laptop --permission documents.read
```

What a token may do is fixed when it is created and can only narrow afterwards.
Every request takes the token's permissions intersected with whatever its owner
holds at that moment, so losing a role, or being deactivated, limits every token
that person owns. Revoking a token takes effect on the next call: nothing is
cached.

A surface that acts for other people, such as the MCP server, presents its own
credential and names the caller with two headers,
`DPOLens-On-Behalf-Of-User` and `DPOLens-On-Behalf-Of-Token`. They are honoured
only for a token created with `--trusted-surface`, and the pair is checked rather
than believed: the named token has to exist, still be usable, and belong to the
named user. A surface never passes a caller's token upstream.

## Errors

Failures are [RFC 9457](https://www.rfc-editor.org/info/rfc9457/) problem details,
with the media type `application/problem+json`:

```json
{
  "type": "/problems/permission-required",
  "title": "Permission required",
  "status": 403,
  "detail": "this token does not carry documents.read",
  "instance": "/v1/search",
  "permission": "documents.read"
}
```

`type` is the field to branch on, and it is stable. There is no second code field
beside it.

| `type` | Status | What happened |
| --- | --- | --- |
| `/problems/unauthenticated` | 401 | No usable credential, or one this instance does not know |
| `/problems/token-refused` | 401 | A token that exists and may not be used. `reason` says why |
| `/problems/permission-required` | 403 | The token does not carry the permission in `permission` |
| `/problems/delegation-not-permitted` | 403 | This token may not say who it is acting for |
| `/problems/not-found` | 404 | No such clause or document in the version in force |
| `/problems/invalid-request` | 400, 422 | The request does not make sense. `errors` names the fields |
| `/problems/unsupported-language` | 422 | The instance cannot search in that `lang`. `languages` lists the ones it can |
| `/problems/too-many-requests` | 429 | The quota for the minute is spent. `Retry-After` says when |
| `/problems/not-ready` | 503 | The database is not reachable |

## Rate limit

Sixty requests a minute per token, counted inside each worker, so an instance
running four workers allows four times that. A throttled response carries
`Retry-After` in seconds. The IETF `RateLimit` fields are still a draft whose
syntax can change, so nothing here emits them yet.

## Routes

### Search

`POST /v1/search`. The question goes in the body rather than a query string, so it
does not reach the access log of a proxy in front of the instance.

| Field | Default | What it does |
| --- | --- | --- |
| `query` | required | The question, in words. At most 1000 characters |
| `limit` | 10 | How many clauses to return, at most 50 |
| `lang` | `en` | The language of the question. Only `en` can be searched today |
| `expand` | `none` | Also return each hit's `siblings` or its `parent` |
| `as_of` | today | Read the corpus as it stood on this date |
| `include_explanatory` | false | Include text that explains without obliging, such as a recital |
| `explain` | false | Include each retriever's ranking, for debugging |

Every result carries what it takes to check it: the clause verbatim, its canonical
key, its breadcrumb, whether it obliges anyone, the document title and version, the
date that version took effect, the language and whether that language is
authoritative, and for a law the pack, the jurisdiction, the trust tier, the source
URL and the language that prevails. An organisation's own policy carries nulls
there, because it is its own source.

A clause comes back in `lang` where it has text in that language, and otherwise in
the language that prevails. A law published in two languages, such as the UAE's in
Arabic and English, has both texts under the same key: an English search returns
its English text, with `is_authoritative` false and `authoritative_language` saying
that the Arabic prevails.

The fusion rule is not a parameter. It is chosen by measurement, and
[retrieval.md](retrieval.md) publishes the measurement.

### Clauses

`GET /v1/clauses/{key}` returns one clause with its breadcrumb, its children and
the cross-references its text states. `GET /v1/clauses/{key}/subtree` returns that
clause and everything beneath it in reading order, which is what an assistant wants
once it has the top hit.

Both take `lang` and `as_of`. Without `lang`, or for a language the clause has no
text in, a clause comes back in the language that prevails.

### Documents

`GET /v1/documents` lists what can be cited today, with `limit` (at most 100),
`offset` and `as_of`. `GET /v1/documents/{slug}` returns one document and its
outline: the top level, without the text. The words come from the clause routes,
because a document of a thousand clauses does not belong in one response.

### Introspection

`POST /v1/tokens/introspect` answers what a token is and what it may do, for a
surface that is about to act on somebody's behalf. It is callable only by a token
created with `--trusted-surface`, so the API cannot be used to test other people's
tokens. A token that cannot be used comes back as `{"active": false}` rather than
as an error.

## Liveness and readiness

`GET /live` returns 200 while the process is running and touches nothing outside
it, because a liveness check that reaches the database restarts a healthy process
whenever the database blinks. `GET /ready` runs one `SELECT 1`. Neither needs a
credential and neither reports a version.

The embedding model and the governance log privileges are startup conditions
rather than probes: an instance that can rewrite its own audit log, or that has no
model, refuses to serve at all.

## What is recorded

Every call writes one row to the query log: the operation, the outcome, the
developer and the token they used, what was returned, and the question with
personal data taken out. Rows expire on the instance's retention, which defaults
to 365 days, and the instance deletes them itself.

Telemetry, the JSON the process writes to stdout, never carries the text of a
question, a clause or a document. It carries identifiers, counts and durations,
and a request id. Send `X-Request-Id` and it is used, provided it is a uuid, so one
question can be followed through a surface and the API together.

## The specification

[openapi.json](openapi.json) is generated from the routes and committed. After
changing a route:

```bash
uv run python scripts/api_contract.py --write
```

CI regenerates it, fails if it differs from the committed file, insists on a
changelog line when it changed, and reports separately whether the change is
breaking for existing clients.
