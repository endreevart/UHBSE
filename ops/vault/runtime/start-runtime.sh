#!/usr/bin/env bash
# Start canonical-loader-runtime for one Agent cycle.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "${ROOT}"
NAME="${UHBSE_RUNTIME_CONTAINER:-human-simulator-canonical-loader-runtime}"

docker rm -f "${NAME}" >/dev/null 2>&1 || true
docker compose --profile runtime-auth build canonical-loader-runtime
docker compose --profile runtime-auth up -d --no-deps canonical-loader-runtime
echo "started ${NAME}"
