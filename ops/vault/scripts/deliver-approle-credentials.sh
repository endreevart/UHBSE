#!/usr/bin/env bash
# Deliver AppRole role_id and wrapped SecretID into tmpfs runtime dir.
# Never prints role_id, secret_id, wrapping token, or Vault token.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TLS_DIR="${ROOT}/ops/vault/tls"
RUNTIME_DIR="${UHBSE_VAULT_RUNTIME_DIR:-/run/uhbse-vault}"
WRAP_TTL="${UHBSE_WRAP_TTL:-2m}"

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

if [[ -z "${VAULT_TOKEN:-}" ]]; then
  # shellcheck disable=SC1091
  eval "$("${SCRIPT_DIR}/decrypt-root-token.sh" --export)"
fi

mkdir -p "${RUNTIME_DIR}/secrets"
chmod 700 "${RUNTIME_DIR}"
chmod 700 "${RUNTIME_DIR}/secrets"

vault_exec() {
  docker exec \
    -e VAULT_ADDR=https://127.0.0.1:8200 \
    -e VAULT_CACERT=/vault/tls/ca.crt \
    -e VAULT_TOKEN \
    human-simulator-vault \
    vault "$@"
}

# role_id → protected file (0600). Value never echoed.
ROLE_ID="$(vault_exec read -field=role_id auth/approle/role/uhbse-canonical-loader/role-id)"
umask 077
printf '%s' "${ROLE_ID}" > "${RUNTIME_DIR}/role-id"
chmod 600 "${RUNTIME_DIR}/role-id"
unset ROLE_ID

# Wrapped SecretID → stdin path into file (response wrapping).
# Vault returns a wrapping token; Agent unwraps via secret_id_response_wrapping_path.
WRAP_JSON="$(vault_exec write -format=json -wrap-ttl="${WRAP_TTL}" \
  auth/approle/role/uhbse-canonical-loader/secret-id)"
WRAP_TOKEN="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["wrap_info"]["token"])' <<<"${WRAP_JSON}")"
unset WRAP_JSON
printf '%s' "${WRAP_TOKEN}" > "${RUNTIME_DIR}/wrapped-secret-id"
chmod 600 "${RUNTIME_DIR}/wrapped-secret-id"
unset WRAP_TOKEN

echo "delivered role_id + wrapped SecretID to ${RUNTIME_DIR} (values not printed)"
