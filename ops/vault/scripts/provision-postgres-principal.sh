#!/usr/bin/env bash
# Provision canonical_loader_login using Vault v1 secrets (runtime only).
# Never prints tokens, passwords, role_id, or secret_id.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "${ROOT}"

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${ROOT}/ops/vault/tls/ca.crt}"
export GNUPGHOME="${ROOT}/ops/vault/pgp/gnupg"

# Touch Vault via docker (health) before decrypt so the operator path matches local tooling.
docker exec \
  -e VAULT_ADDR=https://127.0.0.1:8200 \
  -e VAULT_CACERT=/vault/tls/ca.crt \
  human-simulator-vault \
  vault status >/dev/null

TOKEN="$(./ops/vault/scripts/decrypt-root-token.sh)"
export VAULT_TOKEN="${TOKEN}"
unset TOKEN

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PY="${ROOT}/.venv/bin/python"
else
  PY="python3"
fi

"${PY}" -m human_simulator.stage03_alignment.run_postgres_principal
STATUS=$?
unset VAULT_TOKEN
exit "${STATUS}"
