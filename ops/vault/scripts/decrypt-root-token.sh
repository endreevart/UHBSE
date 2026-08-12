#!/usr/bin/env bash
# Decrypt PGP root token. Use: eval "$(./ops/vault/scripts/decrypt-root-token.sh --export)"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PGP_DIR="${ROOT}/ops/vault/pgp"
INIT_JSON="${ROOT}/ops/vault/operator-custody/init-encrypted.json"
export GNUPGHOME="${PGP_DIR}/gnupg"
TMP_BIN="$(mktemp)"
trap 'rm -f "${TMP_BIN}"' EXIT

[[ -f "${INIT_JSON}" ]] || { echo "missing init-encrypted.json" >&2; exit 1; }

python3 - "${INIT_JSON}" "${TMP_BIN}" <<'PY'
import json, sys, base64, pathlib
doc = json.loads(pathlib.Path(sys.argv[1]).read_text())
rt = doc.get("root_token")
if not rt:
    raise SystemExit("root_token missing")
pathlib.Path(sys.argv[2]).write_bytes(base64.b64decode(rt))
PY

token="$(gpg --batch --yes --pinentry-mode loopback --passphrase '' --decrypt "${TMP_BIN}" 2>/dev/null || true)"
if [[ -z "${token}" ]]; then
  echo "failed to decrypt root token" >&2
  exit 1
fi

if [[ "${1:-}" == "--export" ]]; then
  printf 'export VAULT_TOKEN=%q\n' "${token}"
else
  printf '%s\n' "${token}"
fi
