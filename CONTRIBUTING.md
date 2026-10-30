# Contributing to DPOLens

DPOLens grounds AI coding assistants in an organisation's own policies and the privacy laws
that apply to it, with citations that can be verified against a versioned source.

> **Project status: 0.2.** Until 1.0, a release can change the HTTP API, the pack format
> and the database schema, and [CHANGELOG.md](CHANGELOG.md) says what each one changed. If
> you build on DPOLens now, pin a release.

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

**Docs.** The user docs are on [dpolens.com/docs](https://dpolens.com/docs/get-started), from
the [alkhatibdev/dpolens.com](https://github.com/alkhatibdev/dpolens.com) repository, and every
page links to its own source. A pull request here that changes a setting, a command, an API
route, an MCP tool or a law pack changes that page too, in a pull request of its own there,
merged when the release ships.

**Bug reports.** Open an issue with what you did, what happened and what you expected.
Include the DPOLens version and the pack version if a citation is involved. A security problem
is the exception: report it privately, as [SECURITY.md](SECURITY.md) says.

## Before you start

Open a GitHub Discussion for anything that isn't a small, obvious fix. A short exchange
before you write code is cheaper than a rejected pull request, especially before 1.0,
while the shape is still moving.

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

You do **not** need an API key for anything. DPOLens uses no LLM.

The dashboard needs Node 24. With the API running on port 8000, the development server
forwards `/v1` to it, so the browser sees one origin as it does in production:

```bash
cd dashboard
npm ci
npm run dev             # http://localhost:5173
npm run lint
npm run typecheck
npm test
npm run format:check
```

To run a whole instance from your checkout, build it: `docker compose up -d --build`. Without
`--build`, Compose downloads the images of the version the checkout names once that version is
released, and those are not your changes. Images are named after the version, so a second
checkout on the same machine would share them. Give a branch a version and ports of its own:

```bash
DPOLENS_VERSION=my-branch DPOLENS_API_PORT=8010 DPOLENS_DASHBOARD_PORT=8090 DPOLENS_MCP_PORT=8775 \
  docker compose -p my-branch up -d --build
```

The dashboard's API client is typed from `docs/openapi.json`. After changing a route, run
`uv run python scripts/api_contract.py --write`, then `npm run api` in `dashboard/`, and
commit both files: CI fails when either is stale.

## How the code is organised

Two Python packages in a uv workspace:

- **`dpolens`**: the engine, the HTTP API, the background worker and the CLI.
- **`dpolens-mcp`**: the MCP server. It talks to the HTTP API and nothing else.

Plus `dashboard/` (React and TypeScript), `packs/`, `evals/`, `clients/` (the
configuration an editor needs) and `deploy/` (the images and the init scripts
`compose.yaml` builds from).

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
  `docs:`, `chore:`. A release's notes are drafted from them, as
  [Releases](#releases) describes.
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

[packs/BUILDING.md](packs/BUILDING.md) walks through the whole process: finding the
official text, fetching it, running the converter, what the converter does with
paragraphs, footnotes and references, and what the automatic checks do and do not prove.

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

## Releases

What a release publishes, and how to check an image or a pack archive, is on dpolens.com:
[Releases and upgrades](https://dpolens.com/docs/releases) and
[Laws and their versions](https://dpolens.com/docs/laws). This is how each is made.

### The app

1. A pull request sets the new version everywhere it is kept, the two Python packages, the
   lock file and `compose.yaml`, with `python scripts/release.py bump 0.1.0`, and adds the
   release's section to `CHANGELOG.md`. `uvx git-cliff --unreleased --tag v0.1.0` drafts it
   from the titles of the pull requests since the last release, and the draft is edited by
   hand into something a person deciding whether to upgrade can use.
2. Once that is merged, the commit on `main` is tagged `v0.1.0` and the tag pushed.
3. The release workflow (`.github/workflows/release.yml`) checks the tag against every
   version in the repository and refuses to go on if one disagrees, if the tagged commit is
   not on `main`, or if the changelog has no section for it. It builds the four images for
   both platforms, each on a machine of that kind, publishes them with their tags, attests
   them, writes and attests a pack archive of every law, and opens a draft release with the
   changelog's section as its notes and the archives attached.
4. Somebody reads the draft and publishes it. GitHub's form offers None, Pre-release and
   Latest: the app's release is published as Latest, so the repository's page shows it, and a
   pre-release, such as `0.1.0-rc.1`, which the workflow has already marked as one, as
   Pre-release.
5. Once the community version runs the release, its entry in the
   [MCP Registry](https://registry.modelcontextprotocol.io) is published from `server.json`,
   which `bump` gave the new version. The entry's name, `com.dpolens/dpolens`, is proven by a
   TXT record on dpolens.com that holds the public half of the maintainer's key:
   `mcp-publisher login dns --domain dpolens.com --private-key <key>`, then
   `mcp-publisher publish` from the repository's root. A version the registry has seen is
   refused, so each release is published once.

A pull request that changes how the images are built runs the same workflow, short of
publishing anything. It builds all four images for both platforms, checks that each has one
build for each platform to join, and writes the pack archives and the release notes. So does
starting it by hand from the Actions tab.

### A law pack

1. A pull request changes the pack and gives it its next version in `pack.yaml`.
2. Once that is merged, the commit on `main` is tagged `pack/<slug>/<version>`, for example
   `pack/gdpr/2026.2`, and the tag pushed.
3. The pack release workflow (`.github/workflows/pack-release.yml`) refuses a tag that is not
   on `main` or does not name the version in the pack's `pack.yaml`. It writes the archive and
   its checksum with `dpolens pack archive`, attests the archive, and opens a draft release
   with both files.
4. Somebody reads the draft and publishes it as None. As Latest, it would take the
   repository's page from the app's release, and as Pre-release it would never be offered:
   `pack update` skips pre-releases.

## Code of conduct

Be straightforward and assume good faith. Disagreement about technical decisions is
welcome and expected; personal hostility is not. Problems can be raised privately with
the maintainer.

## Licence

Code is Apache-2.0. Contributions are accepted under the same licence, certified by your
DCO sign-off. `packs/` carries its own licence: law text keeps its source's licence, and
the structural work around it (clause keys, the tree, eval questions) is CC-BY-4.0.
