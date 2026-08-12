#!/usr/bin/env bash
# Provision userpass limited operator (uhbse-operator-limited).
# Password written only to private/ (git-ignored); never printed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TLS_DIR="${ROOT}/ops/vault/tls"
POLICY="${ROOT}/ops/vault/policies/uhbse-operator-limited.hcl"
PRIVATE_DIR="${ROOT}/private"
PASS_FILE="${PRIVATE_DIR}/uhbse-operator-limited.password"
USER_NAME="${UHBSE_OPERATOR_USERNAME:-uhbse-operator-limited}"
POLICY_NAME="uhbse-operator-limited"

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

mkdir -p "${PRIVATE_DIR}"
chmod 700 "${PRIVATE_DIR}"

docker cp "${POLICY}" human-simulator-vault:/tmp/uhbse-operator-limited.hcl
vault_exec policy write "${POLICY_NAME}" /tmp/uhbse-operator-limited.hcl >/dev/null
docker exec human-simulator-vault rm -f /tmp/uhbse-operator-limited.hcl

if ! vault_exec auth list -format=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if "userpass/" in d else 1)'; then
  vault_exec auth enable userpass >/dev/null
fi

if [[ ! -f "${PASS_FILE}" ]]; then
  umask 077
  python3 -c 'import secrets; print(secrets.token_urlsafe(32), end="")' >"${PASS_FILE}"
  chmod 600 "${PASS_FILE}"
fi

export OPERATOR_PASSWORD
OPERATOR_PASSWORD="$(cat "${PASS_FILE}")"
docker exec \
  -e VAULT_ADDR=https://127.0.0.1:8200 \
  -e VAULT_CACERT=/vault/tls/ca.crt \
  -e VAULT_TOKEN \
  -e OPERATOR_PASSWORD \
  -e USER_NAME="${USER_NAME}" \
  -e POLICY_NAME="${POLICY_NAME}" \
  human-simulator-vault \
  sh -c 'vault write "auth/userpass/users/${USER_NAME}" \
    password="${OPERATOR_PASSWORD}" \
    token_policies="${POLICY_NAME}" \
    token_ttl=15m \
    token_max_ttl=1h \
    token_type=service \
    token_no_default_policy=true' >/dev/null
unset OPERATOR_PASSWORD

echo "provisioned userpass user=${USER_NAME} policy=${POLICY_NAME} (password only in private/, not printed)"
