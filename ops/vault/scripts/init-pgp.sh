#!/usr/bin/env bash
# PGP-encrypted Vault operator init. Ciphertext only under ops/vault/operator-custody/.
# Never writes plaintext shares/tokens to /tmp or the repository.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PGP_DIR="${ROOT}/ops/vault/pgp"
CUSTODY="${ROOT}/ops/vault/operator-custody"
TLS_DIR="${ROOT}/ops/vault/tls"
OUT="${CUSTODY}/init-encrypted.json"

mkdir -p "${CUSTODY}"
chmod 700 "${CUSTODY}"

for i in 1 2 3; do
  [[ -f "${PGP_DIR}/op${i}.asc" ]] || { echo "missing ${PGP_DIR}/op${i}.asc — run generate-operator-pgp.sh" >&2; exit 1; }
done
[[ -f "${TLS_DIR}/ca.crt" ]] || { echo "missing TLS CA — run generate-tls.sh" >&2; exit 1; }

# Copy public keys into the container for -pgp-keys paths.
docker exec human-simulator-vault mkdir -p /vault/pgp
for i in 1 2 3; do
  docker cp "${PGP_DIR}/op${i}.asc" "human-simulator-vault:/vault/pgp/op${i}.asc"
done

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

# Init inside container; capture JSON ciphertext to custody (not /tmp).
docker exec \
  -e VAULT_ADDR=https://127.0.0.1:8200 \
  -e VAULT_CACERT=/vault/tls/ca.crt \
  human-simulator-vault \
  vault operator init \
    -key-shares=3 \
    -key-threshold=2 \
    -pgp-keys=/vault/pgp/op1.asc,/vault/pgp/op2.asc,/vault/pgp/op3.asc \
    -root-token-pgp-key=/vault/pgp/op1.asc \
    -format=json >"${OUT}"

chmod 600 "${OUT}"
echo "wrote PGP-encrypted init material to ops/vault/operator-custody/init-encrypted.json"
echo "plaintext shares/tokens were not written to /tmp"
