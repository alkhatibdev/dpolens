#!/bin/sh
# Restores a backup into an instance that holds nothing yet: the database in one transaction,
# then the original files. The backup is checked against its checksums before anything is
# loaded, and every original the database points at against its hash afterwards.
# `docker compose run --rm restore <name>` runs it, <name> being a folder of the backups.
set -eu

backups=/backups
originals=/var/lib/dpolens/originals
shown=${DPOLENS_BACKUP_DIR:-./backups}

fail() {
  echo "$*" >&2
  exit 1
}

query() {
  psql --no-psqlrc --tuples-only --no-align --quiet --command="$1"
}

[ $# -eq 1 ] || fail "Name the backup to restore, one of the folders in $shown: docker compose run --rm restore <name>"
name=$(basename "$1")
folder="$backups/$name"
[ -f "$folder/backup.json" ] || fail "There is no backup called $name in $shown."

(cd "$folder" && sha256sum --check --quiet --strict SHA256SUMS) ||
  fail "$shown/$name has changed since it was written, so nothing was restored."

if [ "$(query "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")" != 0 ] ||
  [ -n "$(ls -A "$originals")" ]; then
  fail "This instance already holds data, and a backup is only restored into one that holds nothing yet. To replace its data with the backup, delete the data first, which cannot be undone:

  docker compose down -v
  docker compose run --rm restore $name
  docker compose up -d"
fi

pg_restore --single-transaction --exit-on-error --dbname="$PGDATABASE" "$folder/database.dump"
tar --extract --file="$folder/originals.tar" --numeric-owner --same-owner --same-permissions \
  --directory="$originals"

expected=$(query "SELECT DISTINCT source_sha256 || '  ' || source_key FROM document_versions
                  WHERE source_key IS NOT NULL")
if [ -n "$expected" ]; then
  printf '%s\n' "$expected" | (cd "$originals" && sha256sum --check --quiet --strict) ||
    fail "The database was restored, but the original files listed above are missing or changed. Empty the instance again with docker compose down -v, then restore another backup."
fi

made=$(sed -n 's/^  "dpolens": "\(.*\)",$/\1/p' "$folder/backup.json")
echo "Restored $shown/$name, taken by DPOLens $made. Start the instance with: docker compose up -d"
if [ -n "${DPOLENS_VERSION:-}" ] && [ "$made" != "$DPOLENS_VERSION" ]; then
  echo "This checkout is DPOLens $DPOLENS_VERSION: starting it updates the restored database for it, which works from an older release to a newer one only."
fi
