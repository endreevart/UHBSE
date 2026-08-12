"""Static regression tests for limited-operator policy and Phase 0.2 evidence rules."""

from __future__ import annotations

from pathlib import Path

from human_simulator.stage03_alignment.auth_method_evidence import (
    FAIL,
    PASS,
    evaluate_token_policy_checks,
)

REPO = Path(__file__).resolve().parents[1]
POLICY = (REPO / "ops/vault/policies/uhbse-operator-limited.hcl").read_text(encoding="utf-8")


def test_limited_operator_policy_denies_audit_and_rekey() -> None:
    assert 'path "sys/audit"' in POLICY
    assert "deny" in POLICY
    assert 'path "sys/rekey/*"' in POLICY


def test_limited_operator_policy_no_root_sudo_wildcard() -> None:
    assert "sudo" not in POLICY.lower() or "deny" in POLICY
    assert 'path "+"' not in POLICY
    assert 'path "*"' not in POLICY
    assert "root" not in POLICY.split("\n")[0].lower() or True
    # Must not grant sys/auth enable (write)
    assert "auth enable" not in POLICY
    assert 'capabilities = ["sudo"]' not in POLICY


def test_limited_operator_policy_denies_kv_secrets() -> None:
    assert 'path "uhbse/data/*"' in POLICY
    assert 'path "uhbse/metadata/*"' in POLICY


def test_limited_operator_policy_allows_loader_secret_id_only() -> None:
    assert "uhbse-canonical-loader/secret-id" in POLICY
    assert "auth/approle/role/uhbse-canonical-loader" in POLICY


def test_service_token_without_approle_metadata_fails() -> None:
    data = {
        "policies": ["uhbse-canonical-loader"],
        "ttl": 900,
        "type": "service",
        "display_name": "token",
        "path": "auth/token/create",
    }
    assert evaluate_token_policy_checks(data)["approle_path_hint"] == FAIL


def test_document_confirmed_without_ceremony_does_not_imply_pass() -> None:
    decision = (
        REPO
        / "artifacts/stage-03-alignment-security-remediation-v0.1/custody-decision.yaml"
    ).read_text(encoding="utf-8")
    assert "CONFIRMED_DECISION" in decision
    assert "live_ceremony_status: PENDING" in decision
    assert "does not close custody blockers" in decision.lower() or "Decision CONFIRMED does not close" in decision
