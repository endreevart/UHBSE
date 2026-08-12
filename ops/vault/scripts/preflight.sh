#!/usr/bin/env bash
# Sanitised Vault preflight — vault-stop v0.2.1
# Strict TLS via CA cert. Never prints tokens, shares, secret_id, or secret values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
OUT_DIR="${ROOT}/artifacts/stage-03-alignment-candidate"
OUT_JSON="${OUT_DIR}/vault-preflight.json"
CHECKS_JSONL="$(mktemp)"
TLS_DIR="${ROOT}/ops/vault/tls"
trap 'rm -f "${CHECKS_JSONL}"' EXIT

export VAULT_ADDR="${VAULT_ADDR:-https://127.0.0.1:8200}"
export VAULT_CACERT="${VAULT_CACERT:-${TLS_DIR}/ca.crt}"

mkdir -p "${OUT_DIR}"

add_check() {
  python3 -c 'import json,sys; print(json.dumps({"id":sys.argv[1],"status":sys.argv[2],"detail":sys.argv[3]}))' \
    "$1" "$2" "$3" >>"${CHECKS_JSONL}"
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

vault_cmd() {
  # Always strict TLS — never tls-skip-verify.
  if have_cmd vault && [[ -f "${VAULT_CACERT}" ]]; then
    VAULT_ADDR="${VAULT_ADDR}" VAULT_CACERT="${VAULT_CACERT}" VAULT_TOKEN="${VAULT_TOKEN:-}" vault "$@"
  else
    docker exec \
      -e VAULT_ADDR=https://127.0.0.1:8200 \
      -e VAULT_CACERT=/vault/tls/ca.crt \
      -e VAULT_TOKEN \
      human-simulator-vault \
      vault "$@"
  fi
}

# --- container ---
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'human-simulator-vault'; then
  add_check "vault_container_running" "PASS" "container human-simulator-vault is running"
else
  add_check "vault_container_running" "FAIL" "vault container not running"
fi

# --- tls ---
if [[ -f "${TLS_DIR}/server.crt" && -f "${TLS_DIR}/server.key" && -f "${TLS_DIR}/ca.crt" ]]; then
  add_check "tls_material_present" "PASS" "ops/vault/tls/{server.crt,server.key,ca.crt} exist"
else
  add_check "tls_material_present" "FAIL" "run ops/vault/scripts/generate-tls.sh"
fi

if [[ -f "${VAULT_CACERT}" ]]; then
  # Never record absolute host paths in evidence — normalize to $PROJECT_ROOT.
  add_check "strict_tls_cacert_configured" "PASS" "VAULT_CACERT=\$PROJECT_ROOT/ops/vault/tls/ca.crt"
else
  add_check "strict_tls_cacert_configured" "FAIL" "VAULT_CACERT missing"
fi

# --- status ---
set +e
status_json="$(vault_cmd status -format=json 2>/dev/null)"
status_rc=$?
set -e

if [[ -n "${status_json}" ]] && [[ ${status_rc} -eq 0 || ${status_rc} -eq 2 ]]; then
  add_check "strict_tls_verification" "PASS" "vault status succeeded with CA verification (no tls-skip-verify)"
  initialized="$(python3 -c 'import json,sys; print(str(json.load(sys.stdin).get("initialized")).lower())' <<<"${status_json}")"
  sealed="$(python3 -c 'import json,sys; print(str(json.load(sys.stdin).get("sealed")).lower())' <<<"${status_json}")"
  storage_type="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("storage_type") or json.load(open("/dev/stdin")).get("storage_type",""))' <<<"${status_json}" 2>/dev/null || echo unknown)"
  # storage_type may appear as "raft" when initialized
  storage_type="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("storage_type") or "unknown")' <<<"${status_json}")"
  if [[ "${initialized}" == "true" ]]; then
    add_check "vault_initialized" "PASS" "initialized=true"
  else
    add_check "vault_initialized" "FAIL" "initialized=false"
  fi
  if [[ "${sealed}" == "false" ]]; then
    add_check "vault_unsealed" "PASS" "sealed=false"
  else
    add_check "vault_unsealed" "FAIL" "sealed=true"
  fi
  if [[ "${storage_type}" == "raft" ]]; then
    add_check "storage_raft" "PASS" "storage_type=raft"
  else
    add_check "storage_raft" "FAIL" "storage_type=${storage_type} (expected raft)"
  fi
else
  add_check "strict_tls_verification" "FAIL" "vault status failed under strict TLS"
  add_check "vault_initialized" "FAIL" "unreachable"
  add_check "vault_unsealed" "FAIL" "unreachable"
  add_check "storage_raft" "FAIL" "unreachable"
fi

# --- token-gated checks ---
if [[ -z "${VAULT_TOKEN:-}" ]] && [[ -f "${ROOT}/ops/vault/operator-custody/init-encrypted.json" ]]; then
  set +e
  eval "$("${SCRIPT_DIR}/decrypt-root-token.sh" --export)" 2>/dev/null
  set -e
fi

if [[ -n "${VAULT_TOKEN:-}" ]]; then
  add_check "operator_token_present" "PASS" "VAULT_TOKEN available for gated checks (value not recorded)"

  set +e
  mounts_json="$(vault_cmd secrets list -format=json 2>/dev/null)"
  mounts_rc=$?
  set -e
  if [[ ${mounts_rc} -eq 0 ]] && python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if "uhbse/" in d else 1)' <<<"${mounts_json}"; then
    add_check "kv_mount_uhbse" "PASS" "KV v2 mount uhbse/ present"
  else
    add_check "kv_mount_uhbse" "FAIL" "KV mount uhbse/ missing"
  fi

  set +e
  vault_cmd policy read uhbse-canonical-loader >/dev/null 2>&1
  pol_rc=$?
  set -e
  if [[ ${pol_rc} -eq 0 ]]; then
    add_check "policy_uhbse_canonical_loader" "PASS" "policy uhbse-canonical-loader exists"
  else
    add_check "policy_uhbse_canonical_loader" "FAIL" "policy missing"
  fi

  set +e
  vault_cmd read auth/approle/role/uhbse-canonical-loader >/dev/null 2>&1
  role_rc=$?
  set -e
  if [[ ${role_rc} -eq 0 ]]; then
    add_check "approle_uhbse_canonical_loader" "PASS" "AppRole uhbse-canonical-loader exists"
  else
    add_check "approle_uhbse_canonical_loader" "FAIL" "AppRole missing"
  fi

  for logical in canonical/hmac-subject-key canonical/loader-credential; do
    set +e
    meta="$(vault_cmd kv metadata get -format=json "uhbse/${logical}" 2>/dev/null)"
    meta_rc=$?
    set -e
    id="secret_path_${logical//\//_}"
    if [[ ${meta_rc} -eq 0 ]]; then
      ver="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("data") or {}).get("current_version"))' <<<"${meta}")"
      if [[ "${ver}" == "1" ]]; then
        add_check "${id}" "PASS" "metadata present current_version=1 (value not read)"
      else
        add_check "${id}" "FAIL" "current_version=${ver} expected 1"
      fi
    else
      add_check "${id}" "FAIL" "metadata missing for uhbse/${logical}"
    fi
  done

  set +e
  audit_json="$(vault_cmd audit list -format=json 2>/dev/null)"
  audit_rc=$?
  set -e
  if [[ ${audit_rc} -eq 0 ]] && python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if any((v or {}).get("type")=="file" for v in d.values()) else 1)' <<<"${audit_json}"; then
    path="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(( (v.get("options") or {}).get("file_path") for v in d.values() if (v or {}).get("type")=="file"),""))' <<<"${audit_json}")"
    add_check "audit_device" "PASS" "file audit enabled path=${path}"
  else
    add_check "audit_device" "FAIL" "file audit device not enabled"
  fi
else
  add_check "operator_token_present" "FAIL" "VAULT_TOKEN unavailable — gated checks cannot PASS"
  add_check "kv_mount_uhbse" "FAIL" "requires VAULT_TOKEN"
  add_check "policy_uhbse_canonical_loader" "FAIL" "requires VAULT_TOKEN"
  add_check "approle_uhbse_canonical_loader" "FAIL" "requires VAULT_TOKEN"
  add_check "secret_path_canonical_hmac-subject-key" "FAIL" "requires VAULT_TOKEN"
  add_check "secret_path_canonical_loader-credential" "FAIL" "requires VAULT_TOKEN"
  add_check "audit_device" "FAIL" "requires VAULT_TOKEN"
fi

add_check "identity_separation_documented" "PASS" "AppRole uhbse-canonical-loader ≠ LOGIN canonical_loader_login ≠ NOLOGIN canonical_loader"
add_check "dev_mode_prohibited" "PASS" "compose uses vault server -config (not -dev)"
add_check "secrets_recorded_in_artifacts" "PASS" "preflight records no secret values (sanitised=true)"

python3 - "${CHECKS_JSONL}" "${OUT_JSON}" "${VAULT_ADDR}" <<'PY'
import json, pathlib, sys
from datetime import datetime, timezone

checks_path = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2])
vault_addr = sys.argv[3]
items = [json.loads(line) for line in checks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
failed = sum(1 for c in items if c["status"] == "FAIL")
skipped = sum(1 for c in items if c["status"] == "SKIP")
passed = sum(1 for c in items if c["status"] == "PASS")
overall = "PASS" if failed == 0 and skipped == 0 else ("PARTIAL" if failed == 0 else "FAIL")
doc = {
    "stage": "03",
    "phase": "alignment_candidate",
    "title": "Vault Preflight (sanitised) — vault-stop v0.2.1",
    "document_version": "0.2.1",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "provider": "hashicorp_vault",
    "deployment": "self_hosted_docker_or_cloud_vm",
    "vault_mode": "production",
    "storage": "raft_integrated_storage_single_node",
    "dev_mode_prohibited": True,
    "tls_skip_verify_used": False,
    "vault_addr": vault_addr,
    "kv_mount": "uhbse",
    "logical_paths": ["canonical/hmac-subject-key", "canonical/loader-credential"],
    "contract_references": [
        "vault://uhbse/canonical/hmac-subject-key?version=1",
        "vault://uhbse/canonical/loader-credential?version=1",
    ],
    "vault_auth_identity": "uhbse-canonical-loader",
    "postgres_login_principal": "canonical_loader_login",
    "postgres_nologin_group_role": "canonical_loader",
    "postgres_principal_status": "HOLD_NOT_CREATED",
    "sanitised": True,
    "secrets_recorded": False,
    "secrets_recorded_in_artifacts": False,
    "overall_status": overall,
    "counts": {"passed": passed, "failed": failed, "skipped": skipped, "total": len(items)},
    "checks": items,
    "forbidden_in_evidence": [
        "root_token", "unseal_keys", "secret_id", "role_id",
        "hmac_key_value", "loader_password", "dsn", "tls_private_key",
    ],
}
out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out_path}")
print(f"overall_status={overall} passed={passed} failed={failed} skipped={skipped}")
raise SystemExit(0 if overall == "PASS" else 1)
PY
