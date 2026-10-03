#!/bin/sh
# Everything that has to happen once before an instance can answer anything.
#
# It runs as the role that owns the tables, because migrations grant privileges
# the application role is not allowed to grant itself. Every step is safe to
# run again, so this is the first service to start and the first to finish.
set -eu

echo "Migrating ..."
alembic upgrade head

for pack in /opt/dpolens/packs/*/; do
    echo "Loading $(basename "$pack") ..."
    dpolens pack load "$pack"
done

# Only the clauses that are not embedded yet, so restarting an instance does not
# embed a corpus it has already embedded.
dpolens index build --skip-embedded

echo "Ready. The API can start."
