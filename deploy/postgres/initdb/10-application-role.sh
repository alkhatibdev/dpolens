#!/bin/sh
# Create the role the application connects as.
#
# It is a different role from the one that owns the tables, which is what makes
# the governance log append only: the migrations take away this role's UPDATE
# and DELETE on it, and a role cannot give itself back what it does not own.
# Migrations never create roles, so this is where it happens, once, when the
# database is first initialised.
set -eu

: "${DPOLENS_APP_PASSWORD:?DPOLENS_APP_PASSWORD has to be set for the application role}"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v app_password="$DPOLENS_APP_PASSWORD" <<'SQL'
-- Quoted by psql rather than pasted in, so a password holding a quote creates
-- the role it was meant to create.
CREATE ROLE dpolens_app LOGIN PASSWORD :'app_password';
SQL
