# Releases

What a release of DPOLens publishes, which version an instance runs, how to check that an
image was built here, how a release is made, and how a law gets a newer version.

## What a release publishes

Four images on GitHub's container registry, each built for amd64 and arm64:

| Image | What it runs |
| --- | --- |
| `ghcr.io/alkhatibdev/dpolens` | The HTTP API, the worker, the one off setup and the command line, with the embedding model and the law packs inside |
| `ghcr.io/alkhatibdev/dpolens-mcp` | The MCP server your AI assistant connects to |
| `ghcr.io/alkhatibdev/dpolens-dashboard` | The dashboard, and the forward from `/v1` to the API |
| `ghcr.io/alkhatibdev/dpolens-postgres` | PostgreSQL 17 with pgvector and pg_textsearch |

Each image is tagged with its version, `0.1.0`, and with its minor version, `0.1`, which
always points at the newest 0.1 release. The newest release is also `latest`. A pre-release,
such as `0.1.0-rc.1`, is tagged with its own version only.

The release's page on GitHub holds its notes, which are the same as its section of
[CHANGELOG.md](../CHANGELOG.md), and a pack archive of every law the release carries, for an
instance with no way to the internet.

The repository's [releases](https://github.com/alkhatibdev/dpolens/releases) list every one,
the app's and each law pack's.

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
   them, writes and attests a pack archive of every law, and opens a draft release with the
   changelog's section as its notes and the archives attached.
4. Somebody reads the draft and publishes it. GitHub's form offers None, Pre-release and
   Latest: the app's release is published as Latest, so the repository's page shows it, and a
   pre-release, such as `0.1.0-rc.1`, which the workflow has already marked as one, as
   Pre-release.

A pull request that changes how the images are built runs the same workflow, short of
publishing anything. It builds all four images for both platforms, checks that each has one
build for each platform to join, and writes the pack archives and the release notes. So does
starting it by hand from the Actions tab.

## Law packs

A law is amended on its legislature's schedule, so a law pack has versions and releases of its
own, apart from the app's. A pack's release is tagged `pack/<slug>/<version>`, for example
`pack/gdpr/2026.2`, and publishes one file, its pack archive,
`dpolens-pack-gdpr-2026.2.tar.gz`: the pack's folder as it is in the repository, beside the
licence that covers every pack. The archive's SHA-256 is in a file beside it,
`dpolens-pack-gdpr-2026.2.tar.gz.sha256`, in the format `sha256sum` writes.

### A newer version of a law

Nothing changes which version of a law an instance has unless somebody asks for it, an
upgrade of DPOLens included. An instance loads each law in its image the first time it
starts, and after that leaves the laws it has alone: when an upgraded image carries a newer
version, starting says so and loads nothing.

`dpolens pack update` lists each pack the instance has and whether a newer version is
published. Naming a pack loads its newest version:

```bash
docker compose exec api dpolens pack update
docker compose exec api dpolens pack update gdpr
```

The archive is downloaded from the releases of the repository named by
`DPOLENS_PACKS_REPOSITORY`, which is this one unless it is set, checked against its SHA-256
before anything in it is read, and loaded beside the version before it. Its words are
searchable at once, and its meaning once the worker has embedded it. A citation of the old
version still reads the text it quoted. An update sends nothing about the instance: it reads
the repository's public list of releases and downloads the two files, through an HTTPS proxy
when one is set in the environment.

An instance with no way to the internet imports the archive instead. Copy it and its `.sha256`
to where the instance can read them, side by side, and import it:

```bash
docker compose cp dpolens-pack-gdpr-2026.2.tar.gz api:/tmp/
docker compose cp dpolens-pack-gdpr-2026.2.tar.gz.sha256 api:/tmp/
docker compose exec api dpolens pack import /tmp/dpolens-pack-gdpr-2026.2.tar.gz
```

Without the `.sha256` beside it, `--sha256` takes the checksum from the release page instead.
An archive that does not match is refused, and so is a version older than the one loaded.
Every version loaded is written to the governance log, with where it came from: the
instance's image, a folder, a file, or, for an update, the repository it was downloaded from.

### Checking a pack archive

```bash
sha256sum -c dpolens-pack-gdpr-2026.2.tar.gz.sha256
gh attestation verify dpolens-pack-gdpr-2026.2.tar.gz --repo alkhatibdev/dpolens
```

The first says the file is the one the release published (`shasum -a 256 -c` does the same on
a Mac). The second says a workflow in this repository built it, and from which commit.

### How a pack is released

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

