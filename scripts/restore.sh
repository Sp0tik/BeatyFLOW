#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
  echo "Usage: ./scripts/restore.sh backups/salon-YYYYMMDD-HHMMSS.dump" >&2
  exit 2
fi
FILE="$1"
[ -f "$FILE" ] || { echo "Backup not found: $FILE" >&2; exit 2; }
cat "$FILE" | docker compose exec -T db pg_restore -U "${POSTGRES_USER:-salon}" -d "${POSTGRES_DB:-salon}" --clean --if-exists
