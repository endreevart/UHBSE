#!/usr/bin/env bash
# Save a Raft snapshot into git-ignored operator custody.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TLS_DIR="${ROOT}/ops/vault/tls"
OUT_DIR="${ROOT}/ops/vault/operator-custody/snapshots"
mkdir -p "${OUT_DIR}"
chmod 700 "${ROOT}/ops/vault/operator-custody" "${OUT_DIR}"

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

if [[ -z "${VAULT_TOKEN:-}" ]]; then
  eval "$("${SCRIPT_DIR}/decrypt-root-token.sh" --export)"
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
HOST_OUT="${OUT_DIR}/raft-${STAMP}.snap"
CONT_OUT="/vault/audit/raft-${STAMP}.snap"

docker exec \
  -e VAULT_ADDR=https://127.0.0.1:8200 \
  -e VAULT_CACERT=/vault/tls/ca.crt \
  -e VAULT_TOKEN \
  human-simulator-vault \
  vault operator raft snapshot save "${CONT_OUT}"

docker cp "human-simulator-vault:${CONT_OUT}" "${HOST_OUT}"
docker exec human-simulator-vault rm -f "${CONT_OUT}"
chmod 600 "${HOST_OUT}"
echo "snapshot saved under ops/vault/operator-custody/snapshots/ (git-ignored; not for review ZIP)"
