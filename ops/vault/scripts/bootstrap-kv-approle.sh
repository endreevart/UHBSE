#!/usr/bin/env bash
# Enable KV v2, policy, AppRole, version-1 secret shells, without logging secret values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TLS_DIR="${ROOT}/ops/vault/tls"
POLICY="${ROOT}/ops/vault/policies/uhbse-canonical-loader.hcl"

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

if [[ -z "${VAULT_TOKEN:-}" ]]; then
  # shellcheck disable=SC1091
  eval "$("${SCRIPT_DIR}/decrypt-root-token.sh" --export)"
fi

vault_exec() {
  docker exec \
    -e VAULT_ADDR=https://127.0.0.1:8200 \
    -e VAULT_CACERT=/vault/tls/ca.crt \
    -e VAULT_TOKEN \
    human-simulator-vault \
    vault "$@"
}

# Prefer host vault if present with CACERT; else docker exec.
if command -v vault >/dev/null 2>&1; then
  v() { VAULT_ADDR="${VAULT_ADDR}" VAULT_CACERT="${VAULT_CACERT}" VAULT_TOKEN="${VAULT_TOKEN}" vault "$@"; }
else
  v() { vault_exec "$@"; }
fi

# Mount
if ! v secrets list -format=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if "uhbse/" in d else 1)'; then
  v secrets enable -path=uhbse -version=2 kv
fi

# Policy — copy into container if using docker exec
docker cp "${POLICY}" human-simulator-vault:/tmp/uhbse-canonical-loader.hcl
vault_exec policy write uhbse-canonical-loader /tmp/uhbse-canonical-loader.hcl
docker exec human-simulator-vault rm -f /tmp/uhbse-canonical-loader.hcl

# AppRole
if ! vault_exec auth list -format=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if "approle/" in d else 1)'; then
  vault_exec auth enable approle
fi

vault_exec write auth/approle/role/uhbse-canonical-loader \
  bind_secret_id=true \
  secret_id_ttl=5m \
  secret_id_num_uses=1 \
  token_ttl=15m \
  token_max_ttl=1h \
  token_policies=uhbse-canonical-loader \
  token_type=service \
  token_no_default_policy=true >/dev/null

# Secret shells — generate material in memory; never echo
HMAC_MATERIAL="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
LOADER_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export HMAC_MATERIAL LOADER_PASSWORD

# Write via docker exec env without printing
docker exec \
  -e VAULT_ADDR=https://127.0.0.1:8200 \
  -e VAULT_CACERT=/vault/tls/ca.crt \
  -e VAULT_TOKEN \
  -e HMAC_MATERIAL \
  -e LOADER_PASSWORD \
  human-simulator-vault \
  sh -c 'vault kv put -mount=uhbse canonical/hmac-subject-key key_version=1 algorithm=HMAC-SHA256 key_material="$HMAC_MATERIAL" >/dev/null'

docker exec \
  -e VAULT_ADDR=https://127.0.0.1:8200 \
  -e VAULT_CACERT=/vault/tls/ca.crt \
  -e VAULT_TOKEN \
  -e LOADER_PASSWORD \
  human-simulator-vault \
  sh -c 'vault kv put -mount=uhbse canonical/loader-credential key_version=1 username=canonical_loader_login password="$LOADER_PASSWORD" >/dev/null'

unset HMAC_MATERIAL LOADER_PASSWORD
echo "bootstrap complete (secret values not printed; role_id/secret_id not written to disk)"
