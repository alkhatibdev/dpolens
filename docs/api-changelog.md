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
- A search covers the organisation's selected laws and its own policies, and nothing
  else. `laws` keeps it to some of them. A loaded law outside the selection is refused
  with `403` and the type `/problems/law-not-selected`, and until somebody has chosen,
  every search is refused with `409` and the type `/problems/no-laws-selected`. The
  response's `laws` lists what was searched. A law that is not loaded is refused with
  `422` and the type `/problems/unknown-law`, whose `laws` field lists the
  organisation's laws
- `GET /v1/clauses/{key}` and `GET /v1/clauses/{key}/subtree` read one clause and
  its branch
- `GET /v1/documents` and `GET /v1/documents/{slug}` list the selected laws and the
  policies, and return one document's outline. The outline carries no text, and names
  each clause in `lang` where it has text in that language. A document, and a clause
  read by key, says whether it is in the organisation's selected laws,
  `in_selected_laws`: a token is refused another law with `403` and
  `/problems/law-not-selected`, and the dashboard opens it marked. For a law, a
  document says which language prevails, `authoritative_language`
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
  as CSV, own questions only for `queries.read_own`. A question's `expires_at` is the day it
  was asked plus the retention, or null while questions are kept, which is the default. `identities=true` adds who asked, needs
  `queries.read_identities`, and is recorded as `query_log.identities_viewed`
- `GET /v1/governance/entries`, `GET /v1/governance/actors`, `GET /v1/governance/verification`
  and `POST /v1/governance/exports` read, check and export the governance log, for
  `governance.read`
- `GET /v1/overview` and `GET /v1/clauses/{key}/activity` count what was asked and what was
  cited, in the reader's time zone, for `queries.read_all`. A clause counts once a day for each
  person who cited it: a search's first result, or a read by key from an assistant or the
  API, never a read in the dashboard. Most cited lists the selected laws' clauses and the
  policies'
- `GET /v1/laws` lists the loaded laws, which of them a search covers, which are new, and
  the latest change to the selection. `PUT /v1/laws/selection` chooses which laws apply,
  written to the governance log, for `settings.manage`. A law that is not loaded gets `422`
  and `/problems/unknown-law`
- `GET /v1/settings` says how the instance is set up, for `settings.manage`. No route changes
  a setting: each is fixed when the instance starts. `questions_log.retention_days` is null
  while questions are kept
- `POST /v1/policies` uploads an organisation's policy, a Word or Markdown file sent as the
  request body (`application/octet-stream`) with its name in `filename`. It is read at once and
  comes back as a draft: its clauses, its flags, how much of the file reached a clause, and what
  was set aside. A file that cannot be read gets `422` and `/problems/unreadable-policy`, which
  says what to do; a slug in use gets `409` and `/problems/policy-exists`, and one that cannot be
  a slug gets `422` and `/problems/bad-slug`. `GET /v1/policies` lists the policies, for
  `documents.upload` or `documents.publish`: the version in force and its number, a version that
  takes effect later (`scheduled`), the open draft and how far its review has got (`review`), who
  last changed the policy and when (`last_change`), whether it is the made-up sample, the label a
  new version is published with (`next_label`), and whether the latest published version is
  embedded yet
- `POST /v1/policies/{slug}/versions` uploads a new version, matched to the version before it:
  each clause says which earlier clause it continues and how it changed. A policy has one draft
  at a time, so a second gets `409` and `/problems/draft-exists`, whose `version` names the open
  one, unless `replace=true` discards it
- `GET`, `PATCH` and `DELETE /v1/policies/{slug}/draft` read a draft, change its title,
  effective date or version label, and discard it. `POST /v1/policies/{slug}/draft/flags/accept`
  accepts flags as read, by their place in the draft's list. Reading a draft needs
  `documents.upload` or `documents.publish`, and changing one `documents.upload`. A policy that
  does not exist gets `404` and `/problems/policy-not-found`, a draft that does not exist
  `/problems/no-draft`, and a flag that does not exist `/problems/flag-not-found`
- A draft carries its `revision`, also as the `ETag`. Every change to it, publishing and
  discarding included, may send it in `If-Match`, and a change made against an older one gets
  `412` and `/problems/edit-conflict`, naming who changed the draft and when. It carries
  `next_label` as well, the label it is published with
- A renumbered or reworded clause of a new version carries `earlier`, the clause it continues as
  the version before has it. `POST /v1/policies/{slug}/draft/matches/{key}/reject` says a match
  is wrong: the clause becomes new, the earlier clause becomes removed, and the flag about the
  match is resolved. A key with no match gets `404` and `/problems/no-match`. A flag is settled
  once it is accepted (`accepted_by`, `accepted_at`) or resolved by a change (`resolved_by`,
  `resolved_at` and `resolution`); `paragraph` names the paragraph of the file a flag is about
- `POST /v1/policies/{slug}/draft/edits` fixes how a clause was read without changing a word:
  `split` (at `at`), `merge`, `make-text`, `make-heading`, `move-under` or `move-out`. Keys follow
  from where each clause ends up, and the answer is the draft with `clause`, the key the clause
  has now. A clause carries `fixes`, the fixes it can take, `splits`, where it can be split, and
  once fixed the layer `reviewer` and `fixed`. A flag carries `suggestion`, the fix the parser
  would make, and once a fix settles it `resolution_key`, the clause the fix named. A key the
  draft does not have gets `404` and `/problems/no-clause`, and a fix that cannot be made `409`
  and `/problems/fix-refused`
- `POST /v1/policies/{slug}/draft/matches/{key}`, with `continues`, says a new clause of a new
  version is the same rule as a clause of the version before that nothing continues, and the
  clause continues it. A new clause carries `candidates`, the clauses it can be paired with,
  closest first, each with its `closeness`. A flag that asks whether a new clause is the same
  rule as such a clause carries it as `candidate`, and `.../reject` answers that it is not. A
  clause that continues one already, or an earlier clause that is continued already, gets `409`
  and `/problems/match-refused`. Either decision settles the flag on the clause, with
  `resolution` `match-made` or `match-rejected` and `resolution_key` the earlier clause
- `POST /v1/policies/{slug}/draft/publish` publishes a draft, for `documents.publish`. It waits
  until every flag is settled (`409`, `/problems/flags-open`, whose `flags` lists the open ones), takes effect
  after the version published before it (`409`, `/problems/effective-date-too-early`), and needs
  a version label no other version has (`409`, `/problems/version-label-taken`). Publishing a
  new version of an archived policy brings it back
- `POST /v1/policies/{slug}/archive` takes a policy out of search and the library, for
  `documents.publish`. Its clauses still read by key, with `archived` true
- `GET /v1/policies/{slug}/versions` lists a policy's versions with each one's `state`
  (`in_force`, `scheduled`, `replaced`, and for those who upload or publish, `draft`), its
  effective date, `until`, who uploaded and published it, and its original file, for
  `documents.read`. `GET /v1/policies/{slug}/compare?from=&to=` compares two published versions
  clause by clause, following each rule through the versions between them; a version compared
  with itself gets `400` and `/problems/invalid-request`, and one that is not published `404` and
  `/problems/policy-not-found`
- `GET /v1/policies/{slug}/versions/{number}/original` returns the file a version was read from,
  checked against the hash it was stored with. A file that is missing or has changed gets `500`
  and `/problems/original-unavailable` instead of a download
- `GET /v1/policies/{slug}/versions/{number}/file` returns the file as it was read: every
  paragraph in order, with what it looked like, the clause it went to, or why it was set aside,
  and `clauses`, every clause that holds part of it. A published version's file and original need
  `documents.read`; a draft's, or a discarded one's, need `documents.upload` or
  `documents.publish`
- `GET /v1/clauses/{key}` carries `now` for a policy's clause read in a version no longer in
  force: where the same rule is today, and whether its number or its words changed. It carries
  `formerly` when the key named a different rule in the version before
- A request body larger than 25 MB gets `413` and `/problems/too-large`, before it is read
- `GET /v1/governance/entries` takes the category `policies`: uploads, flags accepted, matches
  made or said to be wrong, clauses fixed, drafts changed and discarded, versions published, and
  policies archived
