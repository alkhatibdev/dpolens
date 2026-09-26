# DPOLens

DPOLens returns the exact text of privacy laws and an organisation's own policies, so that
AI coding assistants and policy owners can cite them. This file fixes the words the
project uses for that material.

## Language

### Documents

**Organisation**:
The body that runs an instance, of any kind: a company, a university, a hospital, an NGO
or a public authority. One instance serves one organisation. Written in full in prose,
shortened to `org` in code and the schema (`org_id`, `org_packs`).
_Avoid_: Company, tenant, customer, account, organization (the American spelling)

**Instance**:
One deployment of DPOLens, serving one organisation, with its own database, policies and
logs.
_Avoid_: Installation, tenant, environment

**Surface**:
A way into the system: the dashboard, the MCP server, the HTTP API, and later Slack and
the GitHub Action. Every surface reaches the system through the HTTP API.
_Avoid_: Client, channel, integration, interface

**Document**:
A single text that DPOLens stores and cites: either an organisation policy or a law
document.
_Avoid_: Source, file, policy (as the umbrella word)

**Organisation policy**:
A document written by the organisation that runs the instance, uploaded and published
through the dashboard.
_Avoid_: Company policy, policy (on its own, when laws are also meant), internal rule

**Law**:
A statutory data-protection or privacy law, such as GDPR or UAE PDPL.
_Avoid_: Regulation (except inside a proper name), legislation, statute

**Implementing regulation**:
A separate official instrument issued under a law, such as executive regulations, kept in
the same pack as its parent law.
_Avoid_: Regulation (on its own), bylaw

**Pack**:
One law plus its official companion texts (recitals, implementing regulations), each held
as a separate document, and named after the law rather than the place.
_Avoid_: Regulation pack, jurisdiction pack, law bundle

**Jurisdiction**:
The place a law applies to, recorded on a pack as a description. Several packs can share
one jurisdiction, and a jurisdiction never identifies a pack.
_Avoid_: Region, country (when a sub-national area is meant)

### Clauses

**Clause**:
Anything in a document that has a canonical key and can be cited: an article, paragraph,
point, recital or policy section. A clause with a heading and no text of its own (such as
a chapter) appears in browsing and breadcrumbs, but search never returns it on its own.
_Avoid_: Node, provision, section (as the general word)

**Canonical key**:
The permanent, readable identity of a clause, such as `gdpr:art-17:para-1:pt-b`, the same
in every version of its document.
_Avoid_: Clause id, node id, reference

**Breadcrumb**:
The chain of ancestor headings above a clause, from the document down to its parent.
_Avoid_: Path, context, trail

**Subtree**:
A clause together with everything beneath it.
_Avoid_: Branch, section, context

**Cross-reference**:
A pointer from one clause to another, written in the text itself, such as "referred to in
Article 6(1)(f)". It may point into another document.
_Avoid_: Link, citation, reference

**Retired key**:
A canonical key whose clause was removed. It still resolves in the versions that
contained it, and it is never given to a different clause.
_Avoid_: Deleted key, free key

### Versions

**Version**:
One fixed state of a document's text. Once published it never changes.
_Avoid_: Revision, edition, snapshot

**Draft**:
A version that is still being reviewed. Search never sees a draft.
_Avoid_: Pending version, unpublished version

**Published**:
The state of a version that has been approved and can no longer change.
_Avoid_: Released, live, active

**In force**:
The latest published version whose effective date has passed. This is the version search
returns by default, for laws and organisation policies alike.
_Avoid_: Current, active, live

**Scheduled**:
A published version whose effective date has not arrived yet. It appears in the library
but search does not return it by default.
_Avoid_: Future version, upcoming, pending

**Pinned**:
A law held at a chosen version by the organisation, so that search keeps returning that
text even after a newer version comes into force.
_Avoid_: Frozen, locked, held

### Upload and review

**Check**:
Something the parser verifies on every upload, such as whether every character of the
source landed in exactly one clause, or whether numbering runs without gaps.
_Avoid_: Validation, test, rule

**Flag**:
One place in a draft that a reviewer must resolve or accept before publishing, whatever
raised it.
_Avoid_: Confidence flag, flagged spot, warning, issue

**Parse layer**:
Which technique decided a clause's boundary and depth: the file's own structure,
typography, numbering patterns, or a reviewer by hand.
_Avoid_: Parse method, strategy, pass

### People and access

**User**:
An identity that acts in an instance, either a **person** or a **service account**.
_Avoid_: Account (on its own), member, actor

**Service account**:
A user that stands for a system rather than a person, such as a GitHub Action. It owns
tokens and appears in both logs, cannot sign in to the dashboard, and cannot satisfy the
lockout guard.
_Avoid_: Service identity, bot, machine user, system user

**Personal access token**:
A revocable credential a user creates for a surface that is not the dashboard. Its
permissions are chosen at creation and can never exceed its owner's current permissions.
_Avoid_: API key, secret, credential

### Trust and authority

**Authoritative text**:
The language version of a clause that prevails in law, such as the Arabic text of UAE
PDPL. Other languages are translations of it.
_Avoid_: Binding text, official text, master text

**Non-normative**:
A clause that explains the law without creating an obligation, such as a GDPR recital.
Search returns it, and every result says it is non-normative.
_Avoid_: Non-binding, informational, advisory

**Trust tier**:
How far a pack has been checked: `verified` (a named maintainer compared it with the
official source) or `community` (it passed CI only). Packs have a trust tier, documents
written by the organisation do not.
_Avoid_: Confidence, quality level, verification status

### Search

**Result**:
One clause that search returned, identified by document version, canonical key and
language.
_Avoid_: Hit, match, citation (when nothing quotes it)

**Citation**:
A result that an answer quotes or points to. Only generated answers produce citations, so
v0.1 has none.
_Avoid_: Reference, source, result

**Selected laws**:
The packs an admin has chosen for the organisation. Search covers them plus the
organisation's published policies; anything else is searched only on request and labelled
"not in your selected laws". Selecting a law is a setting, not a legal finding.
_Avoid_: Applicable laws, active laws, enabled packs

**Starter question**:
An example question shipped in a pack or built from a policy's headings, shown to someone
who does not know what to ask.
_Avoid_: Suggested question, sample question

**Eval harness**:
The code that runs a question set through retrieval and scores what comes back: recall, MRR
and the confidence interval behind the published number.
_Avoid_: Benchmark, test suite (which means the unit and integration tests)

**Eval question**:
A question with the clause keys it should retrieve, used to score search. It belongs
either to the **tuning set**, used while improving search, or to the **held-out set**,
which produces the published score.
_Avoid_: Test question, golden question

### Logs

**Governance log**:
The append-only, hash-chained record of actions that change the system: publishing,
permission changes, token creation, logins, and every view of identities in the query log.
_Avoid_: Audit log, admin log, system log

**Query log**:
The record of searches, clause lookups and (from v0.2) answers, with the query text
PII-redacted and a retention period after which entries are deleted.
_Avoid_: Q&A log, audit log, usage log, history

This glossary is kept by review, not by a CI check for now. A term used loosely in a pull
request is a review comment, not a failed build.

## Flagged ambiguities

- "Context" is not a word this project uses on its own. Say breadcrumb, subtree,
  cross-reference or **context recipe** (the versioned rule for building the string that
  gets embedded), so that nothing is confused with an assistant's context
  window or with this file.
- The MCP tool `search_policies` and the prompts `/policy-check` and `/policy-tour` search
  laws as well as organisation policies. The names are kept on purpose, because they may
  help assistants decide to call the tool. They do not change what **organisation policy**
  means.
