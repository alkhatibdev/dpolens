#!/bin/sh
# Everything that has to happen once before an instance can answer anything.
#
# It runs as the role that owns the tables, because migrations grant privileges
# the application role is not allowed to grant itself. Every step is safe to
# run again, so this is the first service to start and the first to finish.
set -eu

echo "Migrating ..."
alembic upgrade head

# Only a law this instance has no version of. An upgrade can carry a newer
# version of a law, and loading it would change which text is in force without
# anybody asking: `dpolens pack update` or `dpolens pack load` does that by hand.
for pack in /opt/dpolens/packs/*/; do
    echo "Loading $(basename "$pack") ..."
    dpolens pack load --unless-loaded "$pack"
done

# A made-up policy, so a new instance has a policy of its own to search. It is
# published once: archived, it stays archived.
dpolens policy sample

# Only the clauses that are not embedded yet, so restarting an instance does not
# embed a corpus it has already embedded.
dpolens index build --skip-embedded

echo "Ready. The API can start."
