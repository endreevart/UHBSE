"""Unit/static tests for runtime-auth v0.1.2 (comment-aware pins, env CM, wrap evidence)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from human_simulator.stage03_alignment import approle_hardening as ah
from human_simulator.stage03_alignment import hcl_secret_pins as pins
from human_simulator.stage03_alignment import token_lifecycle as tl
from human_simulator.stage03_alignment.hcl_secret_pins import (
    validate_version_pins,
)

REPO = Path(__file__).resolve().parents[1]

GOOD_HCL = f"""
auto_auth {{
  method {{
    type = "approle"
  }}
}}
template {{
  contents = <<EOT
{{{{ with secret "uhbse/data/canonical/hmac-subject-key?version=1" }}}}
{{{{ end }}}}
{{{{ with secret "uhbse/data/canonical/loader-credential?version=1" }}}}
{{{{ end }}}}
EOT
}}
exec {{
  command = ["/usr/local/bin/uhbse-synthetic-child"]
}}
"""


def test_production_hcl_pins_pass() -> None:
    hcl = (REPO / "ops/vault/runtime/vault-agent.hcl").read_text(encoding="utf-8")
    checks = validate_version_pins(hcl)
    assert checks["overall"] == pins.PASS
    assert "hmac-subject-key?version=1" in hcl
    assert "loader-credential?version=1" in hcl


def test_comment_only_version_pin_fails() -> None:
    text = """
# with secret "uhbse/data/canonical/hmac-subject-key?version=1"
# with secret "uhbse/data/canonical/loader-credential?version=1"
template {
  contents = "no pins here"
}
"""
    checks = validate_version_pins(text)
    assert checks["hmac_version_pin_active"] == pins.FAIL
    assert checks["loader_version_pin_active"] == pins.FAIL
    assert checks["overall"] == pins.FAIL


def test_template_block_comment_only_pin_fails() -> None:
    text = """
template {
  contents = <<EOT
{{- /* with secret "uhbse/data/canonical/hmac-subject-key?version=1" */ -}}
{{- /* with secret "uhbse/data/canonical/loader-credential?version=1" */ -}}
EOT
}
"""
    checks = validate_version_pins(text)
    assert checks["overall"] == pins.FAIL


def test_one_path_without_version_fails() -> None:
    text = GOOD_HCL.replace(
        'with secret "uhbse/data/canonical/loader-credential?version=1"',
        'with secret "uhbse/data/canonical/loader-credential"',
    )
    checks = validate_version_pins(text)
    assert checks["loader_version_pin_active"] == pins.FAIL
    assert checks["overall"] == pins.FAIL


def test_version_latest_fails() -> None:
    text = GOOD_HCL.replace("?version=1", "?version=latest")
    checks = validate_version_pins(text)
    assert checks["hmac_forbidden_version"] == pins.FAIL
    assert checks["overall"] == pins.FAIL


def test_version_current_fails() -> None:
    text = GOOD_HCL.replace("?version=1", "?version=current")
    checks = validate_version_pins(text)
    assert checks["loader_forbidden_version"] == pins.FAIL
    assert checks["overall"] == pins.FAIL


def test_wrong_mount_path_fails() -> None:
    text = GOOD_HCL.replace("uhbse/data/canonical/", "secret/data/other/")
    checks = validate_version_pins(text)
    assert checks["hmac_version_pin_active"] == pins.FAIL
    assert checks["loader_version_pin_active"] == pins.FAIL
    assert checks["overall"] == pins.FAIL


def test_token_type_default_fails() -> None:
    observed = {
        "bind_secret_id": True,
        "secret_id_num_uses": 1,
        "secret_id_ttl": 300,
        "token_ttl": 900,
        "token_max_ttl": 3600,
        "token_type": "default",
        "token_no_default_policy": True,
        "token_policies": ["uhbse-canonical-loader"],
    }
    result = ah.validate_approle_observed(observed)
    assert result["checks"]["token_type"] == ah.FAIL


def test_exact_policies_pass() -> None:
    observed = {
        "bind_secret_id": True,
        "secret_id_num_uses": 1,
        "secret_id_ttl": 300,
        "token_ttl": 900,
        "token_max_ttl": 3600,
        "token_type": "service",
        "token_no_default_policy": True,
        "token_policies": ["uhbse-canonical-loader"],
    }
    assert ah.validate_approle_observed(observed)["overall_status"] == ah.PASS


def _fake_decrypt_success(*_a, **_k):
    class R:
        returncode = 0
        stdout = "hvs.test-token-not-for-artifacts\n"
        stderr = ""

    return R()


def test_isolated_vault_token_absent_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    with patch("human_simulator.stage03_alignment.token_lifecycle.subprocess.run", _fake_decrypt_success):
        with tl.isolated_vault_token(REPO) as token:
            assert token.startswith("hvs.")
            # CM must not permanently set process env
            assert "VAULT_TOKEN" not in os.environ
    assert "VAULT_TOKEN" not in os.environ


def test_isolated_vault_token_restores_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_TOKEN", "prior-operator-value")
    with patch("human_simulator.stage03_alignment.token_lifecycle.subprocess.run", _fake_decrypt_success):
        with tl.isolated_vault_token(REPO) as token:
            assert token.startswith("hvs.")
            os.environ["VAULT_TOKEN"] = "mutated-inside"
    assert os.environ.get("VAULT_TOKEN") == "prior-operator-value"


def test_isolated_vault_token_restores_after_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_TOKEN", "prior-on-error")
    with patch("human_simulator.stage03_alignment.token_lifecycle.subprocess.run", _fake_decrypt_success):
        with pytest.raises(RuntimeError, match="boom"):
            with tl.isolated_vault_token(REPO):
                os.environ["VAULT_TOKEN"] = "mutated"
                raise RuntimeError("boom")
    assert os.environ.get("VAULT_TOKEN") == "prior-on-error"


def test_isolated_vault_token_nested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    with patch("human_simulator.stage03_alignment.token_lifecycle.subprocess.run", _fake_decrypt_success):
        with tl.isolated_vault_token(REPO) as outer:
            assert outer.startswith("hvs.")
            with tl.isolated_vault_token(REPO) as inner:
                assert inner.startswith("hvs.")
                os.environ["VAULT_TOKEN"] = "nested-mut"
            # After inner exit, prior was absent at outer entry → cleared
            # Outer finally also clears
    assert "VAULT_TOKEN" not in os.environ


def test_env_test_values_not_in_artifact_patterns() -> None:
    """Guard: synthetic test tokens must not be written into evidence files if present."""
    evidence = REPO / "artifacts/stage-03-alignment-runtime-auth-v0.1.2"
    if not evidence.is_dir():
        return
    for path in evidence.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "hvs.test-token-not-for-artifacts" not in text
        assert "prior-operator-value" not in text
        assert "mutated-inside" not in text


def test_hard_coded_two_independent_not_in_runner_source() -> None:
    src = (REPO / "src/human_simulator/stage03_alignment/run_runtime_auth_v012.py").read_text(
        encoding="utf-8"
    )
    assert "two_independent_wrapped_secret_ids: true" not in src
    assert '"two_independent_wrapped_secret_ids": true' not in src


def test_hard_coded_publication_pass_not_in_publisher_source() -> None:
    src = (REPO / "src/human_simulator/stage03_alignment/publish_runtime_auth_v012.py").read_text(
        encoding="utf-8"
    )
    assert "compute_attestation_checks" in src
    # Must not hard-assign PASS in an attestation literal dict
    assert (
        re.search(
            r'attestation\s*=\s*\{[^}]*"publication_integrity_status"\s*:\s*"PASS"',
            src,
            flags=re.DOTALL,
        )
        is None
    )


def test_service_token_without_approle_evidence_fails() -> None:
    from human_simulator.stage03_alignment.auth_method_evidence import (
        FAIL,
        evaluate_token_policy_checks,
    )

    data = {
        "policies": ["uhbse-canonical-loader"],
        "ttl": 900,
        "type": "service",
        "display_name": "token",
        "path": "auth/token/create",
        "meta": {},
    }
    checks = evaluate_token_policy_checks(data)
    assert checks["policies_exact"] == "PASS"
    assert checks["approle_path_hint"] == FAIL


def test_correct_policy_without_auth_method_evidence_fails() -> None:
    from human_simulator.stage03_alignment.auth_method_evidence import FAIL, evaluate_token_policy_checks

    data = {
        "policies": ["uhbse-canonical-loader"],
        "ttl": 500,
        "type": "batch",
        "display_name": "service-token",
        "path": "",
    }
    assert evaluate_token_policy_checks(data)["approle_path_hint"] == FAIL


def test_approle_display_name_evidence_passes() -> None:
    from human_simulator.stage03_alignment.auth_method_evidence import PASS, evaluate_token_policy_checks

    data = {
        "policies": ["uhbse-canonical-loader"],
        "ttl": 900,
        "type": "service",
        "display_name": "approle-uhbse-canonical-loader",
        "path": "auth/approle/login",
    }
    checks = evaluate_token_policy_checks(data)
    assert checks["approle_path_hint"] == PASS


def test_deferred_extract_with_suites_passed_true_fails_validation() -> None:
    from human_simulator.stage03_alignment.publish_runtime_auth_v012 import (
        validate_pre_pack_test_results,
    )

    bad = {
        "extracted_bundle_suite": {"status": "DEFERRED_UNTIL_AFTER_ZIP"},
        "suites_passed": True,
    }
    assert validate_pre_pack_test_results(bad)["valid"] is False

    good = {
        "extracted_bundle_suite": {"status": "DEFERRED_UNTIL_AFTER_ZIP"},
        "pre_pack_suites_passed": True,
    }
    assert validate_pre_pack_test_results(good)["valid"] is True
