#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
DUMP="${1:-dumps/stage_magerya_api.dump}"

if [[ ! -f "$DUMP" ]]; then
  echo "Dump not found: $DUMP" >&2
  exit 1
fi

echo "Waiting for PostgreSQL..."
until docker compose exec -T mg-db pg_isready -U magerya_api -d magerya_api >/dev/null 2>&1; do
  sleep 2
done

echo "Restoring from $DUMP ..."
docker compose exec -T mg-db pg_restore \
  -U magerya_api \
  -d magerya_api \
  --no-owner \
  --role=magerya_api \
  --verbose < "$DUMP"

echo "Done."
