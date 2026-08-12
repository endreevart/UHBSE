#!/usr/bin/env bash
# Operator checkpoint: unseal → bootstrap → audit → preflight.
# Token stays inside this process; not printed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$(cd "${SCRIPT_DIR}/../../.." && pwd)"

./ops/vault/scripts/unseal-pgp.sh
# shellcheck disable=SC1091
eval "$("./ops/vault/scripts/decrypt-root-token.sh" --export)"
./ops/vault/scripts/bootstrap-kv-approle.sh
./ops/vault/scripts/enable-audit.sh
./ops/vault/scripts/preflight.sh
unset VAULT_TOKEN
echo "checkpoint scripts finished"
