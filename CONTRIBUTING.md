# Contributing to DPOLens

DPOLens grounds AI coding assistants in an organisation's own policies and the privacy laws
that apply to it, with citations that can be verified against a versioned source.

> **Project status: pre-release.** v0.1 has not shipped. The codebase is being built in
> the open, in thin slices. Interfaces change without notice until 1.0, including the
> HTTP API, the pack format and the database schema. If you build on DPOLens now, pin a
> commit.

## Ways to contribute

**Law packs are the most valuable contribution.** A pack is the structured text of a
statutory privacy law, reviewed against its official source. Nobody can build these for
every jurisdiction alone. The person who knows whether a Brazilian clause has been
translated correctly is usually Brazilian. See [Law packs](#law-packs) below.

**Eval questions.** Every pack ships question sets that measure whether search finds the
right clause. Questions drawn from regulator guidance (the kind that already names the
article it answers) are worth more than questions written from intuition.

**Code.** Bug fixes and focused improvements are welcome. For anything larger, open a
discussion first: the project has a written architecture and a change that cuts against
it will be hard to merge however good the code is.

**Bug reports.** Open an issue with what you did, what happened and what you expected.
Include the DPOLens version and the pack version if a citation is involved.

## Before you start

Open a GitHub Discussion for anything that isn't a small, obvious fix. A short exchange
before you write code is cheaper than a rejected pull request, especially while the
project is pre-release and the shape is still moving.

## Development setup

```bash
git clone https://github.com/<owner>/dpolens.git
cd dpolens
uv sync                 # installs both Python packages and dev dependencies
uv run pytest           # tests start their own Postgres via testcontainers
uv run ruff check .
uv run mypy
```

You need Docker running for the tests: they start a real PostgreSQL with pgvector,
because several of the guarantees DPOLens makes (the append-only governance log, the
immutability of published document versions) exist only in the database and cannot be
tested against anything else.

You do **not** need an API key for anything. DPOLens uses no LLM in v0.1.

## How the code is organised

Two Python packages in a uv workspace:

- **`dpolens`**: the engine, the HTTP API, the background worker and the CLI.
- **`dpolens-mcp`**: the MCP server. It talks to the HTTP API and nothing else.

Plus `dashboard/` (React and TypeScript), `packs/`, `evals/` and `deploy/`.

Three boundaries are enforced in CI by `import-linter`, not by convention:

1. `dpolens-mcp` never imports `dpolens`. Every surface reaches the system through the
   HTTP API, which is what lets a surface be written in any language.
2. The API layer never imports the ORM. Route handlers authenticate, call one engine
   function and return the result; anything building a query has leaked upward.
3. Only tests and the eval harness import the engine directly.

If a change needs one of these relaxed, say so in the pull request and explain why.
The answer may be yes, but it should be a decision rather than a drift.

## Commits and pull requests

- **Sign off every commit**: `git commit -s`. This is the
  [Developer Certificate of Origin](https://developercertificate.org/). It states that
  you have the right to submit the work. There is no CLA. CI rejects unsigned-off commits.
- **[Conventional Commits](https://www.conventionalcommits.org/)**: `feat:`, `fix:`,
  `docs:`, `chore:`. The changelog is generated from them.
- **One concern per pull request.** A refactor bundled with a fix is two reviews.
- **Fill in the template**: what changed, why, and how you verified it. The "how you
  verified it" line is the one that gets a pull request merged quickly.
- CI must pass: lint, types, tests, the retrieval evals and pack validation.

## Law packs

A pack is one statutory privacy law plus its official companion texts (recitals,
implementing regulations), structured into clauses with stable keys, so that a citation
can point at exactly `gdpr:art-17:para-1:pt-b` and be checked. Each of those texts is a
separate document inside the pack.

A pack is named after its law rather than its place, because one jurisdiction can have
several: `packs/gdpr/`, `packs/uae-pdpl/`, `packs/difc-dpl/`. Where the same abbreviation
is used in two countries, the slug carries the country (`sg-pdpa`, `th-pdpa`). The slug
becomes the prefix of every clause key in the pack, so it is permanent: renaming it
invalidates every citation ever made from that pack.

### What we accept

Statutory data-protection and privacy laws and their official regulations. That is the
whole scope, deliberately.

We do **not** accept paywalled standards (ISO 27001, SOC 2), sector-specific rules
(HIPAA, PCI), or any law text under a licence that does not permit redistribution.

### Licensing is a hard gate

Every pack declares, in `pack.yaml`:

- `source_url`: the official government or regulator source the text came from
- `license`: the licence of the law text itself
- `authoritative_language`: the language that is legally binding
- `translation_source`: for each translation: official or unofficial, and its licence

CI rejects a pack missing any of these. **Law-firm and commercial translations are not
accepted**, however good they are: they are copyrighted works belonging to someone else.
Official translations published by the same government that passed the law are fine.

Many jurisdictions exclude the text of laws from copyright entirely. Check yours, cite
the provision that says so in the pull request, and note anything the official portal
says about which language prevails in case of conflict.

### Structure

A pack is a directory of small text files, one per article and one per recital, plus
`pack.yaml`. That is deliberate: a pack is reviewed by reading a diff, so a correction to
one article should be a few readable lines, not a change buried in a megabyte of JSON.

Where the official source is already structured (EUR-Lex publishes EU law as Formex XML,
for instance), convert it rather than re-typing it. Where it is a PDF, expect careful
manual work. No LLM builds pack structure, in either case.

### Trust tiers

Every pack carries a tier, shown in every citation it produces:

- **`community`**: passed CI, not yet reviewed against the official source by a named
  maintainer.
- **`verified`**: a named pack maintainer with local legal context has checked it
  against the official source.

A pack is promoted when someone qualified adopts it. Maintainers are recorded in
`CODEOWNERS` per pack.

### A pack pull request needs

1. Schema validation passing.
2. An official source URL, and the four licensing fields above.
3. Eval questions in English **and** in the authoritative language, with the expected
   clause keys, drawn from regulator guidance where possible.
4. Approval from the pack's maintainer, or from the project maintainer where none exists.

Looking for somewhere to start? Issues labelled `wanted-pack` list jurisdictions we would
like covered.

## Code of conduct

Be straightforward and assume good faith. Disagreement about technical decisions is
welcome and expected; personal hostility is not. Problems can be raised privately with
the maintainer.

## Licence

Code is Apache-2.0. Contributions are accepted under the same licence, certified by your
DCO sign-off. `packs/` carries its own licence: law text keeps its source's licence, and
the structural work around it (clause keys, the tree, eval questions) is CC-BY-4.0.
