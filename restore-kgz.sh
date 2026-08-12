#!/usr/bin/env bash
# Restore kgz-20231204.dump into the isolated kgz-db service (database: kgz_raw).
# Requires an empty kgz_raw database — use `audit restore-preflight` first.
# Do not run without explicit confirmation via `audit restore-second-source --confirm`.
set -euo pipefail

cd "$(dirname "$0")"
DUMP="${1:-kgz-20231204.dump}"
TARGET_DB="${KGZ_TARGET_DATABASE:-kgz_raw}"
TARGET_USER="${KGZ_TARGET_USER:-kgz_raw}"

if [[ ! -f "$DUMP" ]]; then
  echo "Dump not found: $DUMP" >&2
  exit 1
fi

echo "Waiting for kgz-db PostgreSQL..."
until docker compose exec -T kgz-db pg_isready -U "$TARGET_USER" -d "$TARGET_DB" >/dev/null 2>&1; do
  sleep 2
done

echo "Restoring from $DUMP into database $TARGET_DB (no DROP, no overwrite guard in shell — use audit CLI) ..."
docker compose exec -T kgz-db pg_restore \
  -U "$TARGET_USER" \
  -d "$TARGET_DB" \
  --no-owner \
  --no-privileges \
  --role="$TARGET_USER" \
  --verbose < "$DUMP"

echo "Done."
