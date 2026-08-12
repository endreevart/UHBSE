#!/usr/bin/env bash
# Harden AppRole uhbse-canonical-loader (sanitised; never prints role_id/secret_id).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TLS_DIR="${ROOT}/ops/vault/tls"
POLICY="${ROOT}/ops/vault/policies/uhbse-canonical-loader.hcl"
OUT="${ROOT}/artifacts/stage-03-alignment-candidate/approle-hardening.json"

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

docker cp "${POLICY}" human-simulator-vault:/tmp/uhbse-canonical-loader.hcl
vault_exec policy write uhbse-canonical-loader /tmp/uhbse-canonical-loader.hcl >/dev/null
docker exec human-simulator-vault rm -f /tmp/uhbse-canonical-loader.hcl

if ! vault_exec auth list -format=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if "approle/" in d else 1)'; then
  vault_exec auth enable approle >/dev/null
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

# Avoid pipe+heredoc stdin conflict: materialise role JSON, then parse from file.
ROLE_JSON_TMP="$(mktemp)"
trap 'rm -f "${ROLE_JSON_TMP}"' EXIT
vault_exec read -format=json auth/approle/role/uhbse-canonical-loader >"${ROLE_JSON_TMP}"

python3 - "${OUT}" "${ROLE_JSON_TMP}" <<'PY'
import json
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
raw = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
data = raw.get("data") or {}
allowed = [
    "bind_secret_id",
    "secret_id_ttl",
    "secret_id_num_uses",
    "token_ttl",
    "token_max_ttl",
    "token_policies",
    "token_type",
    "token_no_default_policy",
    "token_bound_cidrs",
    "secret_id_bound_cidrs",
]
observed = {k: data[k] for k in allowed if k in data}

def ttl_ok(val, seconds: int) -> bool:
    return val in (seconds, f"{seconds}", f"{seconds}s")

ok = True
if observed.get("bind_secret_id") is not True:
    ok = False
if observed.get("secret_id_num_uses") != 1:
    ok = False
if list(observed.get("token_policies") or []) != ["uhbse-canonical-loader"]:
    ok = False
if observed.get("token_type") not in ("service", "default"):
    if observed.get("token_type") != "service":
        ok = False
if not ttl_ok(observed.get("secret_id_ttl"), 300):
    ok = False
if not ttl_ok(observed.get("token_ttl"), 900):
    ok = False
if not ttl_ok(observed.get("token_max_ttl"), 3600):
    ok = False

doc = {
    "approle": "uhbse-canonical-loader",
    "observed_sanitised": observed,
    "expected": {
        "bind_secret_id": True,
        "secret_id_ttl": "5m",
        "secret_id_num_uses": 1,
        "token_ttl": "15m",
        "token_max_ttl": "1h",
        "token_policies": ["uhbse-canonical-loader"],
        "token_type": "service",
        "cidr_binding": None,
        "secret_id_response_wrapping_path": "auth/approle/role/uhbse-canonical-loader/secret-id",
        "wrapped_secret_id_ttl": "2m",
    },
    "forbidden_in_evidence": ["role_id", "secret_id", "wrapping_token", "vault_token"],
    "secrets_recorded": False,
    "overall_status": "PASS" if ok else "FAIL",
}
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out_path} status={doc['overall_status']}")
PY

echo "approle hardened (ids not recorded)"
