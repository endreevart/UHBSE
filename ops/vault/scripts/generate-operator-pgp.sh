#!/usr/bin/env bash
# Generate three operator PGP keypairs for Vault init encryption (git-ignored).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PGP_DIR="${ROOT}/ops/vault/pgp"
mkdir -p "${PGP_DIR}"
chmod 700 "${PGP_DIR}"

export GNUPGHOME="${PGP_DIR}/gnupg"
mkdir -p "${GNUPGHOME}"
chmod 700 "${GNUPGHOME}"

if ! command -v gpg >/dev/null 2>&1; then
  echo "gpg is required" >&2
  exit 1
fi

for i in 1 2 3; do
  uid="UHBSE Vault Operator ${i} <vault-op${i}@uhbse.local>"
  asc="${PGP_DIR}/op${i}.asc"
  if [[ -f "${asc}" && "${VAULT_PGP_FORCE:-0}" != "1" ]]; then
    echo "exists ${asc}"
    continue
  fi
  gpg --batch --pinentry-mode loopback --passphrase '' \
    --quick-generate-key "${uid}" rsa4096 cert,encrypt never
  fpr="$(gpg --list-keys --with-colons "${uid}" | awk -F: '/^fpr:/ {print $10; exit}')"
  gpg --batch --yes --export --armor "${fpr}" >"${asc}"
  chmod 600 "${asc}"
  echo "wrote ${asc}"
done

echo "PGP public keys ready under ops/vault/pgp/ (git-ignored private keyring in ops/vault/pgp/gnupg/)."
