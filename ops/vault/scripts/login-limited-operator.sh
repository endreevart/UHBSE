#!/usr/bin/env bash
# Login as limited operator — prints only a short-lived token to stdout for callers.
# Prefer: eval "$(./ops/vault/scripts/login-limited-operator.sh --export)"
# Never logs password.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TLS_DIR="${ROOT}/ops/vault/tls"
PASS_FILE="${ROOT}/private/uhbse-operator-limited.password"
USER_NAME="${UHBSE_OPERATOR_USERNAME:-uhbse-operator-limited}"
EXPORT=0
if [[ "${1:-}" == "--export" ]]; then
  EXPORT=1
fi

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

if [[ ! -f "${PASS_FILE}" ]]; then
  echo "missing ${PASS_FILE}; run provision-limited-operator.sh first" >&2
  exit 1
fi

export PASSWORD
PASSWORD="$(cat "${PASS_FILE}")"
TOKEN="$(
  docker exec \
    -e VAULT_ADDR=https://127.0.0.1:8200 \
    -e VAULT_CACERT=/vault/tls/ca.crt \
    -e PASSWORD \
    -e USER_NAME="${USER_NAME}" \
    human-simulator-vault \
    sh -c 'vault write -field=token "auth/userpass/login/${USER_NAME}" password="${PASSWORD}"'
)"
unset PASSWORD

if [[ -z "${TOKEN}" ]]; then
  echo "login failed" >&2
  exit 1
fi

if [[ "${EXPORT}" -eq 1 ]]; then
  printf 'export VAULT_TOKEN=%q\n' "${TOKEN}"
else
  printf '%s\n' "${TOKEN}"
fi
unset TOKEN
