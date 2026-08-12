#!/usr/bin/env bash
# Logout / revoke current VAULT_TOKEN (limited operator).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TLS_DIR="${ROOT}/ops/vault/tls"

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

if [[ -z "${VAULT_TOKEN:-}" ]]; then
  echo "VAULT_TOKEN not set" >&2
  exit 1
fi

docker exec \
  -e VAULT_ADDR=https://127.0.0.1:8200 \
  -e VAULT_CACERT=/vault/tls/ca.crt \
  -e VAULT_TOKEN \
  human-simulator-vault \
  vault token revoke-self >/dev/null

echo "revoked current token (value not printed)"
