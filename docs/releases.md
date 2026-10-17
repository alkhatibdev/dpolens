# Releases

What a release of DPOLens publishes, which version an instance runs, how to check that an
image was built here, and how a release is made.

## What a release publishes

Four images on GitHub's container registry, each built for amd64 and arm64:

| Image | What it runs |
| --- | --- |
| `ghcr.io/alkhatibdev/dpolens` | The HTTP API, the worker, the one off setup and the command line, with the embedding model and the law packs inside |
| `ghcr.io/alkhatibdev/dpolens-mcp` | The MCP server your assistant connects to |
| `ghcr.io/alkhatibdev/dpolens-dashboard` | The dashboard, and the forward from `/v1` to the API |
| `ghcr.io/alkhatibdev/dpolens-postgres` | PostgreSQL 17 with pgvector and pg_textsearch |

Each image is tagged with its version, `0.1.0`, and with its minor version, `0.1`, which
always points at the newest 0.1 release. The newest release is also `latest`. A pre-release,
such as `0.1.0-rc.1`, is tagged with its own version only.

The release's page on GitHub holds its notes, which are the same as its section of
[CHANGELOG.md](../CHANGELOG.md).

There is no published release yet, so there are no images to download.

## Which version an instance runs

`compose.yaml` names each image at the version of the checkout it is in, so a checkout of a
release runs that release. `docker compose up` downloads the images. When there is nothing to
download, for a version that has not been released, it builds them from source instead, and
`docker compose up --build` always does.

To run another release from the same checkout, name it:

```bash
echo 'DPOLENS_VERSION=0.1.0' >> .env
docker compose up -d
```

The version is 0.x until the HTTP API is stable, and the interfaces (the API, the pack format,
the database schema) can change between releases until 1.0. Only the newest release gets
fixes.

## Checking an image

Every image is attested when it is published: GitHub signs a record of which workflow built
it, from which commit. The GitHub CLI, version 2.49 or later, checks it:

```bash
gh attestation verify oci://ghcr.io/alkhatibdev/dpolens:0.1.0 --repo alkhatibdev/dpolens
```

It succeeds only for an image that a workflow in this repository built and attested, and it
prints which workflow it was and which commit it built.

## How a release is made

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
   them, and opens a draft release with the changelog's section as its notes.
4. Somebody reads the draft and publishes it.

A pull request that changes how the images are built runs the same workflow, which builds
all four for both platforms and pushes nothing. So does starting it by hand from the Actions
tab.
