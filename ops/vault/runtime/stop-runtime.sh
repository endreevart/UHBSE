#!/usr/bin/env bash
# Stop and remove runtime container; tmpfs secrets vanish with the container.
set -euo pipefail
NAME="${UHBSE_RUNTIME_CONTAINER:-human-simulator-canonical-loader-runtime}"
docker rm -f "${NAME}" >/dev/null 2>&1 || true
echo "removed ${NAME} (tmpfs secrets discarded)"
