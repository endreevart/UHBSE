#!/usr/bin/env bash
# Enable persistent file audit device (after init/unseal).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TLS_DIR="${ROOT}/ops/vault/tls"

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

if [[ -z "${VAULT_TOKEN:-}" ]]; then
  eval "$("${SCRIPT_DIR}/decrypt-root-token.sh" --export)"
fi

docker exec human-simulator-vault mkdir -p /vault/audit

docker exec \
  -e VAULT_ADDR=https://127.0.0.1:8200 \
  -e VAULT_CACERT=/vault/tls/ca.crt \
  -e VAULT_TOKEN \
  human-simulator-vault \
  vault audit enable file file_path=/vault/audit/vault-audit.log >/dev/null 2>&1 \
  || docker exec \
    -e VAULT_ADDR=https://127.0.0.1:8200 \
    -e VAULT_CACERT=/vault/tls/ca.crt \
    -e VAULT_TOKEN \
    human-simulator-vault \
    vault audit list -format=json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert any(v.get("type")=="file" for v in d.values())'

echo "file audit device enabled at /vault/audit/vault-audit.log (contents not exported)"
