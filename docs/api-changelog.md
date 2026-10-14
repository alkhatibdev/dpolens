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
  clause has text in that language, and otherwise in the language that prevails.
  `lang` is `en` or `ar`, and left out it is read from the letters the question is
  written in. A language the instance cannot search in is refused with `422` and the
  type `/problems/unsupported-language`, whose `languages` field lists the ones it can
- A search covers the organisation's selected laws, or every loaded law until it has
  chosen, and its own policies. `laws` names others to search instead; a clause from
  a law outside the selection has `in_selected_laws` false. The response's `laws`
  lists what was searched. A law that is not loaded is refused with `422` and the type
  `/problems/unknown-law`, whose `laws` field lists the loaded ones
- `GET /v1/clauses/{key}` and `GET /v1/clauses/{key}/subtree` read one clause and
  its branch
- `GET /v1/documents` and `GET /v1/documents/{slug}` list what can be cited and
  return one document's outline. The outline carries no text, and names each clause
  in `lang` where it has text in that language. A document says whether it is in the
  organisation's selected laws, `in_selected_laws`, and for a law which language
  prevails, `authoritative_language`
- Every clause carries `authoritative_language`: for a law, the language whose text
  prevails where its texts disagree. A clause returned in an official translation has
  `is_authoritative` false, this field says which text to rely on instead, and
  `authoritative_text` holds that text
- `POST /v1/tokens/introspect` answers what a token is, for a trusted surface only
- `GET /live` and `GET /ready` are the two probes
- Failures are RFC 9457 problem details with the media type
  `application/problem+json`. `type` is the stable identifier to branch on
- Authentication is a personal access token as a bearer credential. A trusted
  surface may name the caller with `DPOLens-On-Behalf-Of-User` and
  `DPOLens-On-Behalf-Of-Token`
- `POST /v1/sessions` signs a person in to the dashboard with an email and a password
  and sets a session cookie, which every route accepts in place of a token, from the
  dashboard's own pages only (`Sec-Fetch-Site: same-origin`). `GET /v1/sessions/current`
  says who is signed in, and `DELETE /v1/sessions/current` signs out. The problems are
  `/problems/sign-in-refused`, `/problems/too-many-attempts`, `/problems/session-ended`,
  whose `reason` says why, and `/problems/cross-site-request`
- Sixty requests a minute per token, answered with `429` and `Retry-After`
