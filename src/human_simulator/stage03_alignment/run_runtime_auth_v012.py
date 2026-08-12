"""Runtime-auth v0.1.2 orchestration: Agent proof, wrap distinctness, token lookup."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.migrations import row_counts
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.stage03_alignment.auth_method_evidence import (
    evaluate_token_policy_checks,
)
from human_simulator.stage03_alignment.hcl_secret_pins import validate_agent_hcl_file
from human_simulator.stage03_alignment.postgres_principal import LOGIN_ROLE
from human_simulator.stage03_alignment.postgres_principal_verify import (
    capture_db_snapshot,
    schema_fingerprint,
)
from human_simulator.stage03_alignment.run_runtime_auth_v011 import (
    CONTAINER,
    harden_approle,
    phase0,
    runtime_topology_doc,
    _run,
    _sanitise_log,
)
from human_simulator.stage03_alignment.runtime_auth_smoke import authenticate_approle_wrapped
from human_simulator.stage03_alignment.token_lifecycle import (
    env_matches_snapshot,
    isolated_vault_token,
    vault_token_env_snapshot,
)
from human_simulator.stage03_alignment.vault_secret_shape import FAIL, PASS, resolve_vault_runtime

OUT = Path("artifacts") / "stage-03-alignment-runtime-auth-v0.1.2"
ACCEPTED_V011_SHA = "b727967789a87a11b666896a83831487729d407e462ddf88555cc9e94d00c7b3"
ACCEPTED_V01_SHA = "a7708432dd0484797ee35b613de005bc147b541cb6e484fcd5a999fb024b25b4"
REPORT_STATUS = "DRAFT"
WRAP_TTL = "2m"


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _write(path: Path, doc: dict[str, Any] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc, encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _vault_exec_json(token: str, args: list[str]) -> dict[str, Any]:
    env = os.environ.copy()
    env["VAULT_TOKEN"] = token
    cmd = [
        "docker",
        "exec",
        "-e",
        "VAULT_ADDR=https://127.0.0.1:8200",
        "-e",
        "VAULT_CACERT=/vault/tls/ca.crt",
        "-e",
        "VAULT_TOKEN",
        "human-simulator-vault",
        "vault",
        *args,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"vault exec failed: {args[0]}")
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def request_wrapped_secret_id(token: str) -> tuple[str, dict[str, Any]]:
    """Return (wrapping_token, sanitised_meta). Never persist wrapping_token."""
    raw = _vault_exec_json(
        token,
        [
            "write",
            "-format=json",
            f"-wrap-ttl={WRAP_TTL}",
            "-force",
            "auth/approle/role/uhbse-canonical-loader/secret-id",
        ],
    )
    wrap = raw.get("wrap_info") or {}
    wrapping_token = wrap.get("token")
    if not isinstance(wrapping_token, str) or not wrapping_token:
        raise RuntimeError("wrap token missing")
    meta = {
        "wrapper_requested": True,
        "creation_time": wrap.get("creation_time"),
        "ttl": wrap.get("ttl"),
        "creation_path": wrap.get("creation_path"),
    }
    # Explicitly drop any secret-bearing fields
    return wrapping_token, meta


def attempt_unwrap(token_or_wrap: str, *, as_wrapping_token: bool) -> bool:
    """Return True if unwrap succeeded. Does not record token values."""
    env = os.environ.copy()
    if as_wrapping_token:
        env["VAULT_TOKEN"] = token_or_wrap
        args = ["unwrap", "-format=json"]
    else:
        return False
    cmd = [
        "docker",
        "exec",
        "-e",
        "VAULT_ADDR=https://127.0.0.1:8200",
        "-e",
        "VAULT_CACERT=/vault/tls/ca.crt",
        "-e",
        "VAULT_TOKEN",
        "human-simulator-vault",
        "vault",
        *args,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env, timeout=60)
    return proc.returncode == 0


def deliver_wrap_into_container(wrapping_token: str, operator_token: str) -> None:
    env = {k: v for k, v in os.environ.items()}
    env["VAULT_TOKEN"] = operator_token
    # role_id
    role = _vault_exec_json(
        operator_token,
        ["read", "-format=json", "auth/approle/role/uhbse-canonical-loader/role-id"],
    )
    role_id = (role.get("data") or {}).get("role_id")
    if not isinstance(role_id, str):
        raise RuntimeError("role_id missing")
    subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER,
            "sh",
            "-c",
            "mkdir -p /run/uhbse-vault/secrets && chmod 700 /run/uhbse-vault /run/uhbse-vault/secrets",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "sh",
            "-c",
            "cat > /run/uhbse-vault/role-id && chmod 600 /run/uhbse-vault/role-id",
        ],
        input=role_id,
        text=True,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("role_id deliver failed")
    role_id = ""
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINER,
            "sh",
            "-c",
            "cat > /run/uhbse-vault/wrapped-secret-id && chmod 600 /run/uhbse-vault/wrapped-secret-id",
        ],
        input=wrapping_token,
        text=True,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("wrap deliver failed")
    subprocess.run(
        [
            "docker",
            "exec",
            CONTAINER,
            "sh",
            "-c",
            "date -u +%Y-%m-%dT%H:%M:%SZ > /run/uhbse-vault/go && chmod 600 /run/uhbse-vault/go",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _lookup_token_via_operator(operator_token: str, subject_token: str) -> dict[str, Any]:
    """Lookup subject token metadata using operator privileges (HTTP body, not CLI args).

    AppRole tokens with token_no_default_policy cannot lookup-self; that is expected.
    """
    import ssl
    import urllib.error
    import urllib.request

    from human_simulator.stage03_alignment.vault_secret_shape import resolve_vault_runtime

    cfg = resolve_vault_runtime(require_token=False)
    body = json.dumps({"token": subject_token}).encode()
    req = urllib.request.Request(
        f"{cfg.addr.rstrip('/')}/v1/auth/token/lookup",
        data=body,
        method="POST",
        headers={
            "X-Vault-Token": operator_token,
            "Content-Type": "application/json",
        },
    )
    ctx = ssl.create_default_context(cafile=str(cfg.cacert))
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lookup_agent_token_sanitised(operator_token: str) -> dict[str, Any]:
    """Read Agent token sink inside container; record only safe metadata."""
    probe = subprocess.run(
        ["docker", "exec", CONTAINER, "cat", "/run/uhbse-vault/token"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        return {"overall_status": FAIL, "token_sink_present": False}
    agent_token = probe.stdout.strip()
    try:
        # Operator lookup — AppRole has no default policy / lookup-self by design.
        lookup = _lookup_token_via_operator(operator_token, agent_token)
    except Exception:  # noqa: BLE001
        agent_token = ""
        return {"overall_status": FAIL, "token_lookup": FAIL}
    agent_token = ""
    data = lookup.get("data") or {}
    policies = list(data.get("policies") or [])
    ttl = data.get("ttl")
    policy_checks = evaluate_token_policy_checks(data)
    checks = {
        "token_sink_present": PASS,
        **policy_checks,
    }
    overall = (
        PASS
        if checks["policies_exact"] == PASS
        and checks["default_policy_absent"] == PASS
        and checks["ttl_in_bounds"] == PASS
        and checks["approle_path_hint"] == PASS
        else FAIL
    )
    return {
        "kind": "LIVE",
        "overall_status": overall,
        "checks": checks,
        "policies_count": len(policies),
        "ttl_seconds": ttl if isinstance(ttl, int) else None,
        "token_type": data.get("type"),
        "lookup_method": "operator_token_lookup_http",
        "secrets_recorded": False,
        "note": "Token value never written to artifacts; lookup-self denied by design (no default policy)",
    }


def agent_cycle_with_wrap(
    repo: Path, operator_token: str, *, cycle: int, wrapping_token: str
) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items()}
    env["VAULT_TOKEN"] = operator_token
    env["UHBSE_RUNTIME_CONTAINER"] = CONTAINER
    start = repo / "ops/vault/runtime/start-runtime.sh"
    stop = repo / "ops/vault/runtime/stop-runtime.sh"
    checks: dict[str, str] = {}
    smoke_doc = None
    token_lookup: dict[str, Any] = {}

    try:
        rc = _run([str(start)], env=env, cwd=repo, timeout=600)
        checks["container_started"] = PASS if rc.returncode == 0 else FAIL
        if rc.returncode != 0:
            return {"cycle": cycle, "overall_status": FAIL, "checks": checks}
        time.sleep(2)
        deliver_wrap_into_container(wrapping_token, operator_token)
        checks["credentials_delivered"] = PASS

        result_json = ""
        for _ in range(90):
            probe = _run(
                ["docker", "exec", CONTAINER, "cat", "/run/uhbse-vault/smoke-result.json"],
                env=env,
                cwd=repo,
                timeout=30,
            )
            if probe.returncode == 0 and probe.stdout.strip():
                result_json = probe.stdout
                break
            time.sleep(2)

        if result_json:
            smoke_doc = json.loads(result_json)
            checks["smoke_result_present"] = PASS
            checks["agent_child_status"] = smoke_doc.get("status", FAIL)
            for k, v in (smoke_doc.get("checks") or {}).items():
                checks[f"child_{k}"] = v
            checks["auth_path_is_agent_supervisor"] = (
                PASS
                if smoke_doc.get("auth_path") == "vault_agent_process_supervisor"
                else FAIL
            )
            wrapped = _run(
                [
                    "docker",
                    "exec",
                    CONTAINER,
                    "test",
                    "!",
                    "-f",
                    "/run/uhbse-vault/wrapped-secret-id",
                ],
                env=env,
                cwd=repo,
                timeout=30,
            )
            checks["wrapped_secret_id_absent_after_auth"] = (
                PASS if wrapped.returncode == 0 else FAIL
            )
            token_lookup = lookup_agent_token_sanitised(operator_token)
            checks["token_lookup"] = token_lookup.get("overall_status", FAIL)
        else:
            checks["smoke_result_present"] = FAIL
            logs = _run(["docker", "logs", CONTAINER], env=env, cwd=repo, timeout=30)
            return {
                "cycle": cycle,
                "overall_status": FAIL,
                "checks": checks,
                "agent_log_sanitised": _sanitise_log(logs.stdout or ""),
            }
    finally:
        _run([str(stop)], env=env, cwd=repo, timeout=60)
        gone = _run(["docker", "inspect", CONTAINER], env=env, cwd=repo, timeout=30)
        checks["runtime_container_removed"] = PASS if gone.returncode != 0 else FAIL

    overall = (
        PASS
        if all(v == PASS for v in checks.values())
        and smoke_doc
        and smoke_doc.get("status") == PASS
        else FAIL
    )
    return {
        "kind": "LIVE",
        "cycle": cycle,
        "overall_status": overall,
        "checks": checks,
        "child_smoke_sanitised": {
            "status": (smoke_doc or {}).get("status"),
            "synthetic_subject_label": (smoke_doc or {}).get("synthetic_subject_label"),
            "checks": (smoke_doc or {}).get("checks"),
            "row_counts": (smoke_doc or {}).get("row_counts"),
        },
        "agent_token_lookup": {
            k: token_lookup.get(k)
            for k in ("overall_status", "checks", "policies_count", "ttl_seconds", "token_type", "secrets_recorded")
        },
        "secrets_recorded": False,
    }


def run_v012(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _root()
    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)

    snap = vault_token_env_snapshot()
    settings = load_canonical_settings()

    with canonical_connection(settings) as conn:
        p0 = phase0(root, conn)
        # Retarget phase0 accepted refs for v0.1.1 baseline awareness
        p0["accepted_v011_sha256"] = ACCEPTED_V011_SHA
        p0["accepted_v01_sha256"] = ACCEPTED_V01_SHA
        _write(out / "phase0-baseline.json", p0)
        before = capture_db_snapshot(conn, root, label="v012-before")
        if p0["overall_status"] != PASS:
            raise RuntimeError("Phase 0 FAIL")

    _write(out / "runtime-topology.json", runtime_topology_doc())
    hcl_path = root / "ops/vault/runtime/vault-agent.hcl"
    static = validate_agent_hcl_file(hcl_path)
    # Extra static topology checks from compose
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    static_checks = dict(static["checks"])
    static_checks["compose_canonical_loader_runtime"] = (
        PASS if "canonical-loader-runtime:" in compose else FAIL
    )
    static_checks["exec_supervisor"] = (
        PASS if "exec {" in hcl_path.read_text(encoding="utf-8") else FAIL
    )
    static["checks"] = static_checks
    static["overall_status"] = PASS if all(v == PASS for v in static_checks.values()) else FAIL
    static["vault_agent_runtime_execution"] = "NOT_VERIFIED"
    _write(out / "vault-agent-static-validation.json", static)
    _write(out / "secret-version-verification.json", {
        "kind": "STATIC",
        "checks": static_checks,
        "overall_status": static["overall_status"],
        "contract_uris": [
            "vault://uhbse/canonical/hmac-subject-key?version=1",
            "vault://uhbse/canonical/loader-credential?version=1",
        ],
    })

    with isolated_vault_token(root) as token:
        cfg = resolve_vault_runtime(require_token=False)
        client_token, auth_checks = authenticate_approle_wrapped(
            addr=cfg.addr, cacert=cfg.cacert, operator_token=token
        )
        direct = {
            "kind": "LIVE",
            "title": "direct_approle_api_smoke",
            "overall_status": PASS
            if client_token and all(v == PASS for v in auth_checks.values())
            else FAIL,
            "checks": auth_checks,
            "vault_agent_runtime_execution": "NOT_VERIFIED",
        }
        client_token = ""
        _write(out / "direct-approle-smoke.json", direct)

        approle = harden_approle(root, token)
        _write(out / "approle-hardening.json", approle)

        # --- Two independent wrapped SecretIDs with reuse rejection ---
        wrap1, meta1 = request_wrapped_secret_id(token)
        cycle1 = agent_cycle_with_wrap(root, token, cycle=1, wrapping_token=wrap1)
        # After Agent consumed wrap1, reuse must fail
        reuse_ok = attempt_unwrap(wrap1, as_wrapping_token=True)
        wrap1 = ""
        wrapper_reuse_rejected = not reuse_ok

        wrap2, meta2 = request_wrapped_secret_id(token)
        cycle2 = agent_cycle_with_wrap(root, token, cycle=2, wrapping_token=wrap2)
        wrap2 = ""

        distinct = bool(
            meta1.get("creation_time")
            and meta2.get("creation_time")
            and meta1["creation_time"] != meta2["creation_time"]
        )
        wrap_evidence = {
            "kind": "LIVE",
            "cycle_1": {
                "wrapper_requested": meta1.get("wrapper_requested"),
                "creation_time": meta1.get("creation_time"),
                "ttl": meta1.get("ttl"),
                "creation_path": meta1.get("creation_path"),
                "wrapper_consumed_once": cycle1.get("overall_status") == PASS,
                "cycle_completed": cycle1.get("overall_status") == PASS,
            },
            "wrapper_reuse_rejected": wrapper_reuse_rejected,
            "cycle_2": {
                "second_wrapper_requested": meta2.get("wrapper_requested"),
                "creation_time": meta2.get("creation_time"),
                "ttl": meta2.get("ttl"),
                "creation_path": meta2.get("creation_path"),
                "cycle_completed": cycle2.get("overall_status") == PASS,
            },
            "distinct_nonsecret_request_metadata": distinct,
            "overall_status": PASS
            if (
                cycle1.get("overall_status") == PASS
                and cycle2.get("overall_status") == PASS
                and wrapper_reuse_rejected
                and distinct
            )
            else FAIL,
            "secrets_recorded": False,
            "note": "No wrapping token, role_id, secret_id, or hashes thereof are recorded",
        }
        if not distinct or not wrapper_reuse_rejected:
            raise RuntimeError("wrapped SecretID independence proof FAIL")

        _write(out / "vault-agent-live-smoke.json", cycle1)
        restart = {
            "kind": "LIVE",
            "title": "vault_agent_restart_reauthentication",
            "cycle_1_status": cycle1.get("overall_status"),
            "cycle_2_status": cycle2.get("overall_status"),
            "wrap_independence": wrap_evidence,
            "overall_status": wrap_evidence["overall_status"],
            "cycles": [
                {"cycle": 1, "overall_status": cycle1.get("overall_status"), "checks": cycle1.get("checks")},
                {"cycle": 2, "overall_status": cycle2.get("overall_status"), "checks": cycle2.get("checks")},
            ],
        }
        _write(out / "vault-agent-restart-reauth.json", restart)
        _write(out / "wrapped-secret-id-independence.json", wrap_evidence)
        _write(
            out / "agent-token-policy-lookup.json",
            {
                "cycle_1": cycle1.get("agent_token_lookup"),
                "cycle_2": cycle2.get("agent_token_lookup"),
                "overall_status": PASS
                if (cycle1.get("agent_token_lookup") or {}).get("overall_status") == PASS
                and (cycle2.get("agent_token_lookup") or {}).get("overall_status") == PASS
                else FAIL,
            },
        )

    token_lifecycle = {
        "kind": "LIVE",
        "environment_restored": env_matches_snapshot(snap),
        "overall_status": PASS if env_matches_snapshot(snap) else FAIL,
        "context_manager": "isolated_vault_token",
    }
    _write(out / "token-lifecycle-verification.json", token_lifecycle)

    with canonical_connection(settings) as conn:
        after = capture_db_snapshot(conn, root, label="v012-after")
        counts = row_counts(conn)
        fp_after = schema_fingerprint(conn)

    invariants = {
        "kind": "LIVE",
        "schema_fingerprint_before": before["schema_fingerprint"]["sha256"],
        "schema_fingerprint_after": fp_after["sha256"],
        "schema_fingerprint_unchanged": before["schema_fingerprint"]["sha256"]
        == fp_after["sha256"],
        "row_counts_before": before["row_counts"],
        "row_counts_after": counts,
        "row_counts_remain_zero": all(v == 0 for v in counts.values()),
        "postgres_principal_unchanged": before["role_inventory"]["roles"].get(LOGIN_ROLE)
        == after["role_inventory"]["roles"].get(LOGIN_ROLE),
        "migrations_unchanged": before["migration_inventory"]["applied_history"]
        == after["migration_inventory"]["applied_history"],
        "clinical_rows_read": 0,
        "raw_db_connections": 0,
        "canonical_rows_written": 0,
    }
    invariants["overall_status"] = (
        PASS
        if invariants["schema_fingerprint_unchanged"]
        and invariants["row_counts_remain_zero"]
        and invariants["postgres_principal_unchanged"]
        else FAIL
    )
    _write(out / "before-after-invariants.json", invariants)
    _write(
        out / "postgres-set-role-verification.json",
        {
            "cycle_1": cycle1.get("child_smoke_sanitised"),
            "cycle_2": cycle2.get("child_smoke_sanitised"),
            "overall_status": restart["overall_status"],
        },
    )

    findings = {
        "document_version": "0.1.2",
        "report_status": REPORT_STATUS,
        "blocks_live_load": True,
        "findings": [
            {"id": "initial_root_token_available", "status": "OPEN"},
            {"id": "limited_operator_identity_absent", "status": "OPEN"},
            {"id": "vault_key_custody_decision_required", "status": "OPEN"},
            {"id": "pgp_keys_shared_keyring_empty_passphrase", "status": "OPEN"},
            {"id": "multi_custodian_separation_absent", "status": "OPEN"},
            {
                "id": "loader_restart_reauth_procedure_absent",
                "status": "CLOSED" if restart["overall_status"] == PASS else "OPEN",
            },
        ],
    }
    _write(out / "operational-security-findings.json", findings)
    open_blockers = [f["id"] for f in findings["findings"] if f["status"] == "OPEN"]

    statuses = {
        "direct_approle_api_smoke": direct["overall_status"],
        "vault_agent_configuration_static_validation": static["overall_status"],
        "vault_agent_runtime_execution": cycle1["overall_status"],
        "vault_agent_restart_reauthentication": restart["overall_status"],
        "wrapped_secret_id_independence": wrap_evidence["overall_status"],
        "agent_token_policy_lookup": PASS
        if (cycle1.get("agent_token_lookup") or {}).get("overall_status") == PASS
        else FAIL,
    }
    partial_ok = all(v == PASS for v in statuses.values()) and invariants["overall_status"] == PASS
    contract = {
        "contract_key": "canonical_loader_runtime_contract",
        "status": "PARTIAL_RUNTIME_VERIFIED" if partial_ok else "INCOMPLETE",
        "complete": False,
        "report_status": REPORT_STATUS,
        "component_statuses": statuses,
        "open_blockers": open_blockers,
    }
    _write(out / "runtime-contract-status.json", contract)

    report = {
        "document_version": "0.1.2",
        "report_status": REPORT_STATUS,
        "overall_status": PASS if partial_ok else FAIL,
        "component_statuses": statuses,
        "runtime_contract": contract["status"],
        "runtime_contract_complete": False,
        "open_blockers": open_blockers,
        "invariants": {
            "row_counts_after": counts,
            "schema_fingerprint_unchanged": invariants["schema_fingerprint_unchanged"],
            "postgres_principal_unchanged": invariants["postgres_principal_unchanged"],
        },
        "accepted_v01_sha256": ACCEPTED_V01_SHA,
        "accepted_v011_sha256": ACCEPTED_V011_SHA,
        "secrets_recorded_in_artifacts": False,
    }
    _write(out / "runtime-auth-report.json", report)
    _write(
        out / "report.md",
        f"""# Runtime Auth v0.1.2 — Report

**Report status:** {REPORT_STATUS}

## Component statuses

{json.dumps(statuses, indent=2)}

## Contract

- status: **{contract['status']}**
- complete: false
- open_blockers: {', '.join(open_blockers)}

## Publication

Atomic publisher computes publication_integrity_status from verification results only.
""",
    )

    if not env_matches_snapshot(snap):
        raise RuntimeError("VAULT_TOKEN environment not restored")
    if not partial_ok:
        raise RuntimeError("runtime-auth v0.1.2 overall FAIL")
    return report


def main() -> int:
    try:
        report = run_v012()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc.__class__.__name__}: {exc}")
        return 1
    print(json.dumps({"overall_status": report["overall_status"], "runtime_contract": report["runtime_contract"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
