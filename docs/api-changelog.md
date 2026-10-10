# API changelog

Every change to the HTTP contract, newest first, because the people building
against this API have no other way to find out. [openapi.json](openapi.json) is
the contract itself.

Until 1.0, a release may change anything in this file's list. After 1.0, a
breaking change needs a new major version.

## Unreleased

First version of the API. Everything below is new rather than changed.

- `POST /v1/search` returns the clauses that answer a question. The question goes
  in the body rather than a query string, so it does not reach a proxy's access
  log. `include_explanatory` is off by default, and the fusion rule is not a
  parameter
- A search returns each clause in `lang`, the language of the question, where the
  clause has text in that language, and otherwise in the language that prevails. A
  language the instance cannot search in is refused with `422` and the type
  `/problems/unsupported-language`, whose `languages` field lists the ones it can
- `GET /v1/clauses/{key}` and `GET /v1/clauses/{key}/subtree` read one clause and
  its branch
- `GET /v1/documents` and `GET /v1/documents/{slug}` list what can be cited and
  return one document's outline. The outline carries no text
- Every clause carries `authoritative_language`: for a law, the language whose text
  prevails where its texts disagree. A clause returned in an official translation has
  `is_authoritative` false, and this field says which text to rely on instead
- `POST /v1/tokens/introspect` answers what a token is, for a trusted surface only
- `GET /live` and `GET /ready` are the two probes
- Failures are RFC 9457 problem details with the media type
  `application/problem+json`. `type` is the stable identifier to branch on
- Authentication is a personal access token as a bearer credential. A trusted
  surface may name the caller with `DPOLens-On-Behalf-Of-User` and
  `DPOLens-On-Behalf-Of-Token`
- Sixty requests a minute per token, answered with `429` and `Retry-After`
