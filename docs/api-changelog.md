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
- `GET /v1/users`, `POST /v1/users`, `PATCH /v1/users/{id}` and `PUT /v1/users/{id}/roles`
  list, add, deactivate and reactivate people, and set their roles, for `users.manage`. Giving
  someone a role needs every permission it carries
- `POST /v1/users/{id}/sign-in-links` makes a one-time link, valid 72 hours, for a person to
  choose a password, and needs every permission its owner holds. `POST /v1/sessions/from-link`
  spends it and signs the person in; a link that was used or ran out gets `410` and
  `/problems/sign-in-link-unusable`, and a password too short gets `422` and
  `/problems/weak-password`. `POST /v1/sign-in-links/lookup` says who a link is for without
  spending it
- `PUT /v1/sessions/current/password` changes the signed-in person's password, given the
  current one. A wrong one gets `403` and `/problems/wrong-password`
- `GET /v1/permissions` lists the permission catalog. `GET /v1/roles`, `POST /v1/roles`, and
  `GET`, `PATCH` and `DELETE /v1/roles/{id}` read and change roles. A role carries its
  revision as an `ETag`; a change with an older one in `If-Match` gets `412` and
  `/problems/edit-conflict`. A held role cannot be deleted (`409`, `/problems/role-in-use`),
  and a change that would leave nobody able to manage roles gets `409` and
  `/problems/lockout-refused`
- `GET /v1/tokens`, `POST /v1/tokens` and `DELETE /v1/tokens/{id}` list, make and revoke
  tokens. A token is made from a dashboard session only (`403`, `/problems/session-required`)
- `/problems/permission-required` carries `permissions` when any of several would do, and a
  name or an address already taken gets `409` and `/problems/already-exists`
- `GET /v1/instance` gives the version and the MCP server's address, `DPOLENS_PUBLIC_MCP_URL`
- The signed-in account carries its `id`
- `GET /v1/queries` and `GET /v1/queries/export` read the questions log, a page at a time or
  as CSV, own questions only for `queries.read_own`. `identities=true` adds who asked, needs
  `queries.read_identities`, and is recorded as `query_log.identities_viewed`
- `GET /v1/governance/entries`, `GET /v1/governance/actors`, `GET /v1/governance/verification`
  and `POST /v1/governance/exports` read, check and export the governance log, for
  `governance.read`
- `GET /v1/overview` and `GET /v1/clauses/{key}/activity` count what was asked and what was
  cited, in the reader's time zone, for `queries.read_all`
- `GET /v1/laws` lists the loaded laws, which of them a search covers, and the latest change
  to the selection. `PUT /v1/laws/selection` chooses which laws apply and
  `DELETE /v1/laws/selection` goes back to every law, each written to the governance log, for
  `settings.manage`. A law that is not loaded gets `422` and `/problems/unknown-law`
- `GET /v1/settings` says how the instance is set up, for `settings.manage`. No route changes
  a setting: each is fixed when the instance starts
- `POST /v1/policies` uploads an organisation's policy, a Word or Markdown file sent as the
  request body (`application/octet-stream`) with its name in `filename`. It is read at once and
  comes back as a draft: its clauses, its flags, how much of the file reached a clause, and what
  was set aside. A file that cannot be read gets `422` and `/problems/unreadable-policy`, which
  says what to do; a slug in use gets `409` and `/problems/policy-exists`, and one that cannot be
  a slug gets `422` and `/problems/bad-slug`. `GET /v1/policies` lists the policies, with the
  version in force, any open draft, and whether the latest published version is embedded yet
- `POST /v1/policies/{slug}/versions` uploads a new version, matched to the version before it:
  each clause says which earlier clause it continues and how it changed. A policy has one draft
  at a time, so a second gets `409` and `/problems/draft-exists`, whose `version` names the open
  one, unless `replace=true` discards it
- `GET`, `PATCH` and `DELETE /v1/policies/{slug}/draft` read a draft, change its title,
  effective date or version label, and discard it. `POST /v1/policies/{slug}/draft/flags/accept`
  accepts flags by their place in the draft's list. Each needs `documents.upload`. A policy that
  does not exist gets `404` and `/problems/policy-not-found`, a draft that does not exist
  `/problems/no-draft`, and a flag that does not exist `/problems/flag-not-found`
- `POST /v1/policies/{slug}/draft/publish` publishes a draft, for `documents.publish`. It waits
  for every flag (`409`, `/problems/flags-open`, whose `flags` lists the open ones), takes effect
  after the version published before it (`409`, `/problems/effective-date-too-early`), and needs
  a version label no other version has (`409`, `/problems/version-label-taken`). Publishing a
  new version of an archived policy brings it back
- `POST /v1/policies/{slug}/archive` takes a policy out of search and the library, for
  `documents.publish`. Its clauses still read by key, with `archived` true
- `GET /v1/policies/{slug}/versions/{number}/original` returns the file a version was read from,
  for `documents.read`, checked against the hash it was stored with. A file that is missing or
  has changed gets `500` and `/problems/original-unavailable` instead of a download
- `GET /v1/clauses/{key}` carries `now` for a policy's clause read in a version no longer in
  force: where the same rule is today, and whether its number or its words changed. It carries
  `formerly` when the key named a different rule in the version before
- A request body larger than 25 MB gets `413` and `/problems/too-large`, before it is read
- `GET /v1/governance/entries` takes the category `policies`: uploads, flags accepted, drafts
  changed and discarded, versions published, and policies archived
