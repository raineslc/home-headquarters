#!/usr/bin/env bash
# Copy the whole Render PostgreSQL database into Neon (FND-03). Run in Google Cloud Shell:
#   bash copy-database.sh
# Uses PostgreSQL 17 tools in a temporary Docker container. Connection strings are typed into
# hidden prompts and never written to disk. Re-running replaces Neon's copy with a fresh one.
# Before running: allow this Cloud Shell's address (printed below) in Render > database >
# Networking, and remove it again afterwards.
set -euo pipefail
echo "This Cloud Shell's public address (add it to Render's database access list): $(curl -s https://ifconfig.me)"
read -r -s -p "Render EXTERNAL database URL (Render > database > Connect > External): " SRC; echo
read -r -s -p "Neon DIRECT connection string (pooling off): " DST; echo
case "$DST" in *-pooler*) echo "Use Neon's direct (non-pooler) connection string."; exit 1 ;; esac

TABLES="auth_user organizer_household organizer_membership organizer_familymember organizer_activity organizer_task organizer_lunchplan organizer_assistantplan organizer_assistantsuggestion organizer_googleconnection organizer_googlecalendar organizer_setuprecord organizer_recoverypoint django_migrations"
docker run --rm -i -e SRC="$SRC" -e DST="$DST" -e TABLES="$TABLES" postgres:17 bash -s <<'COPY'
set -euo pipefail
counts() {
  for table in $TABLES; do
    printf '%s=%s ' "$table" "$(psql "$1" -At -c "select count(*) from $table" 2>/dev/null || echo missing)"
  done
}
echo "Dumping Render (PostgreSQL $(psql "$SRC" -At -c 'show server_version'))..."
pg_dump --no-owner --no-acl --format=custom --file=/tmp/hhq.dump "$SRC"
echo "Clearing Neon's previous copy, if any..."
psql "$DST" -q -v ON_ERROR_STOP=1 -c "drop schema if exists public cascade; create schema public;"
echo "Restoring into Neon..."
pg_restore --no-owner --no-acl --dbname="$DST" /tmp/hhq.dump || echo "pg_restore reported warnings; the row-count check below decides."
SOURCE=$(counts "$SRC"); TARGET=$(counts "$DST")
echo "Render: $SOURCE"
echo "Neon:   $TARGET"
if [ "$SOURCE" = "$TARGET" ]; then echo "Row counts match. Copy complete."; else echo "ROW COUNTS DIFFER - do not switch over."; exit 1; fi
COPY
unset SRC DST
