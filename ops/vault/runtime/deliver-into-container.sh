#!/usr/bin/env bash
# Deliver RoleID + wrapped SecretID into container-local tmpfs (not host /run).
# Values via stdin/docker exec files — never CLI args, never Compose env, never echoed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CONTAINER="${UHBSE_RUNTIME_CONTAINER:-human-simulator-canonical-loader-runtime}"
WRAP_TTL="${UHBSE_WRAP_TTL:-2m}"
TLS_DIR="${ROOT}/ops/vault/tls"

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

if [[ -z "${VAULT_TOKEN:-}" ]]; then
  echo "VAULT_TOKEN required in caller env (isolated)" >&2
  exit 1
fi

vault_exec() {
  docker exec \
    -e VAULT_ADDR=https://127.0.0.1:8200 \
    -e VAULT_CACERT=/vault/tls/ca.crt \
    -e VAULT_TOKEN \
    human-simulator-vault \
    vault "$@"
}

# Ensure runtime dir exists inside container tmpfs
docker exec "${CONTAINER}" sh -c 'mkdir -p /run/uhbse-vault/secrets && chmod 700 /run/uhbse-vault /run/uhbse-vault/secrets'

ROLE_ID="$(vault_exec read -field=role_id auth/approle/role/uhbse-canonical-loader/role-id)"
printf '%s' "${ROLE_ID}" | docker exec -i "${CONTAINER}" sh -c 'cat > /run/uhbse-vault/role-id && chmod 600 /run/uhbse-vault/role-id'
unset ROLE_ID

WRAP_JSON="$(vault_exec write -format=json -wrap-ttl="${WRAP_TTL}" -force \
  auth/approle/role/uhbse-canonical-loader/secret-id)"
WRAP_TOKEN="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["wrap_info"]["token"])' <<<"${WRAP_JSON}")"
unset WRAP_JSON
printf '%s' "${WRAP_TOKEN}" | docker exec -i "${CONTAINER}" sh -c 'cat > /run/uhbse-vault/wrapped-secret-id && chmod 600 /run/uhbse-vault/wrapped-secret-id'
unset WRAP_TOKEN

# Release Agent wait loop
docker exec "${CONTAINER}" sh -c 'date -u +%Y-%m-%dT%H:%M:%SZ > /run/uhbse-vault/go && chmod 600 /run/uhbse-vault/go'

echo "delivered credentials into container-local tmpfs (values not printed)"
