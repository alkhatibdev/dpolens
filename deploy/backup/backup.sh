#!/bin/sh
# Backs up a running instance into a folder of its own: the database, then the original files
# of uploaded policies. `docker compose run --rm backup` runs it in the database's own image, so
# pg_dump is the server's version.
#
# The folder is written under a hidden name and renamed once it is complete, so a folder with a
# backup.json in it is always a whole backup.
set -eu

backups=/backups
originals=/var/lib/dpolens/originals
shown=${DPOLENS_BACKUP_DIR:-./backups}
keep=${DPOLENS_BACKUP_KEEP:-}

fail() {
  echo "$*" >&2
  exit 1
}

if [ -n "$keep" ]; then
  case "$keep" in
    *[!0-9]* | 0*) fail "DPOLENS_BACKUP_KEEP is how many backups to keep, 1 or more, not \"$keep\"." ;;
  esac
fi

query() {
  psql --no-psqlrc --tuples-only --no-align --quiet --command="$1"
}

# "1 question", "2 questions".
counted() {
  if [ "$1" = 1 ]; then echo "1 $2"; else echo "$1 $2s"; fi
}

# Backups belong to whoever owns the checkout, rather than to root. Docker makes a missing
# ./backups as root, so the first backup hands that folder over too. Where the host does not let
# a container change owners, as on Docker Desktop, they stay as they are.
owner=$(stat -c %u:%g "$(dirname "$0")")
if [ "$shown" = ./backups ] && [ "$(stat -c %u "$backups")" = 0 ] && [ -z "$(ls -A "$backups")" ]; then
  chown "$owner" "$backups" 2>/dev/null || true
fi

umask 077
now=$(date -u +%s)
name=$(date -u -d "@$now" +%Y-%m-%dT%H%M%SZ)
partial="$backups/.$name.partial"
mkdir "$partial" || fail "Could not start a backup in $shown."
trap 'rm -rf "$partial"' EXIT

# The database first: an original is written before the row that points at it, so every file
# the dump points at is already in the folder when the folder is copied.
pg_dump --format=custom --file="$partial/database.dump"
tar --create --file="$partial/originals.tar" --numeric-owner --exclude='*.partial' \
  --directory="$originals" .

schema=$(query "SELECT version_num FROM alembic_version")
questions=$(query "SELECT count(*) FROM query_log_entries")
files=$(tar --list --file="$partial/originals.tar" | grep -vc '/$' || true)

(cd "$partial" && sha256sum database.dump originals.tar > SHA256SUMS)
cat > "$partial/backup.json" <<EOF
{
  "dpolens": "${DPOLENS_VERSION:-unknown}",
  "schema": "$schema",
  "taken": "$(date -u -d "@$now" +%Y-%m-%dT%H:%M:%SZ)",
  "originals": $files,
  "questions": $questions
}
EOF

chown -R "$owner" "$partial" 2>/dev/null || true
mv "$partial" "$backups/$name"
trap - EXIT

echo "Backed up to $shown/$name ($(du -sh "$backups/$name" | cut -f1)): the database, with $(counted "$questions" question), and $(counted "$files" "original file")."
if [ "$questions" -gt 0 ] && [ -n "${DPOLENS_QUERY_LOG_RETENTION_DAYS:-}" ]; then
  echo "The instance deletes a question $DPOLENS_QUERY_LOG_RETENTION_DAYS days after it was asked, but this backup keeps the questions in it for as long as the backup is kept."
fi

if [ -n "$keep" ]; then
  # Only whole backups, found by their names, oldest first. Nothing else in the folder is touched.
  for found in "$backups"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z; do
    [ -f "$found/backup.json" ] && basename "$found"
  done | sort | head -n "-$keep" | while read -r old; do
    rm -rf "${backups:?}/$old"
    echo "Deleted the older backup $shown/$old."
  done
fi
