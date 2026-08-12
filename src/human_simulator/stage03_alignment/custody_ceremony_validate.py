"""Structural validation for MULTI_CUSTODIAN_2_OF_3 ceremony evidence (sanitised)."""

from __future__ import annotations

from typing import Any

PASS = "PASS"
FAIL = "FAIL"

CUSTODY_BLOCKERS = (
    "vault_key_custody_decision_required",
    "pgp_keys_shared_keyring_empty_passphrase",
    "multi_custodian_separation_absent",
)


def validate_rekey_command_flags(flags: dict[str, Any]) -> dict[str, str]:
    """Validate planned/observed rekey initiation flags (no secrets)."""
    checks: dict[str, str] = {}
    checks["key_shares_3"] = PASS if flags.get("key_shares") == 3 else FAIL
    checks["key_threshold_2"] = PASS if flags.get("key_threshold") == 2 else FAIL
    checks["verify_flag_present"] = PASS if flags.get("verify") is True else FAIL
    pgp = flags.get("pgp_keys_count")
    checks["three_pgp_public_key_files"] = PASS if pgp == 3 else FAIL
    # Must not claim ASCII armor inputs
    checks["ascii_armor_not_used_as_pgp_keys"] = (
        PASS if flags.get("pgp_keys_encoding") in ("binary", "base64") else FAIL
    )
    return checks


def validate_ceremony_evidence(doc: dict[str, Any]) -> dict[str, Any]:
    """Accept or reject sanitised ceremony evidence for blocker closure eligibility."""
    checks: dict[str, str] = {}

    fps = doc.get("public_fingerprints") or []
    checks["three_fingerprints"] = PASS if isinstance(fps, list) and len(fps) == 3 else FAIL
    checks["fingerprints_distinct"] = (
        PASS if isinstance(fps, list) and len(set(fps)) == 3 else FAIL
    )
    checks["shares_3"] = PASS if doc.get("shares") == 3 else FAIL
    checks["threshold_2"] = PASS if doc.get("threshold") == 2 else FAIL

    flags = doc.get("rekey_flags") or {}
    flag_checks = validate_rekey_command_flags(flags)
    checks.update({f"rekey_{k}": v for k, v in flag_checks.items()})

    checks["rekey_initiated"] = PASS if doc.get("rekey_initiated") is True else FAIL
    checks["rekey_operation_nonce_recorded"] = (
        PASS if bool(doc.get("rekey_operation_nonce_recorded")) else FAIL
    )
    checks["verification_nonce_recorded"] = (
        PASS if bool(doc.get("verification_nonce_recorded")) else FAIL
    )
    checks["rekey_verification_pass"] = (
        PASS if doc.get("rekey_verification") == PASS else FAIL
    )
    checks["rekey_completed"] = PASS if doc.get("rekey_completed") is True else FAIL

    # Completed without verification must fail
    if doc.get("rekey_completed") is True and doc.get("rekey_verification") != PASS:
        checks["completed_requires_verification_pass"] = FAIL
    else:
        checks["completed_requires_verification_pass"] = PASS

    checks["current_and_new_holders_distinguished"] = (
        PASS if doc.get("current_and_new_share_holders_distinguished") is True else FAIL
    )

    slots = doc.get("unseal_drill_custodian_slots") or []
    checks["unseal_drill_two_distinct_slots"] = (
        PASS if isinstance(slots, list) and len(set(slots)) >= 2 else FAIL
    )
    checks["unseal_drill_pass"] = PASS if doc.get("seal_unseal_drill") == PASS else FAIL

    # Optional/missing drill cannot accept
    if doc.get("seal_unseal_drill") in (None, "SKIP", "OPTIONAL", "FAIL"):
        if doc.get("seal_unseal_drill") != PASS:
            checks["unseal_drill_mandatory"] = FAIL
    else:
        checks["unseal_drill_mandatory"] = PASS

    checks["no_single_human_controls_threshold"] = (
        PASS if doc.get("no_single_human_controls_threshold_shares") is True else FAIL
    )

    # Snapshot must not be claimed as rekey rollback
    rollback = str(doc.get("rollback_model") or "")
    checks["snapshot_not_treated_as_rekey_rollback"] = (
        PASS
        if rollback != "raft_snapshot_rekey_rollback"
        and doc.get("raft_snapshot_is_rekey_rollback") is not True
        else FAIL
    )

    retirement = doc.get("old_share_retirement") or {}
    early = retirement.get("retired_before_unseal_drill") is True
    checks["old_shares_not_retired_before_drill"] = PASS if not early else FAIL
    if retirement.get("retired") is True:
        allowed = (
            doc.get("rekey_verification") == PASS
            and doc.get("rekey_completed") is True
            and doc.get("seal_unseal_drill") == PASS
            and doc.get("three_custodian_receipt_confirmed") is True
            and doc.get("post_unseal_runtime_verification") == PASS
        )
        checks["old_share_retirement_gate"] = PASS if allowed else FAIL
    else:
        checks["old_share_retirement_gate"] = PASS

    # Documents alone never close blockers
    if doc.get("close_blockers_from_document_only") is True:
        checks["no_document_only_blocker_close"] = FAIL
    else:
        checks["no_document_only_blocker_close"] = PASS

    overall = PASS if all(v == PASS for v in checks.values()) else FAIL
    blockers_may_close = overall == PASS
    return {
        "overall_status": overall,
        "checks": checks,
        "custody_blockers_may_close": blockers_may_close,
        "custody_blockers": list(CUSTODY_BLOCKERS),
        "note": "Blockers stay OPEN unless overall_status PASS and live evidence is attached",
    }


def document_alone_cannot_close_blockers(decision_doc: dict[str, Any]) -> bool:
    """Return True when validator correctly refuses document-only closure."""
    # Simulates a CONFIRMED decision without ceremony fields
    evidence = {
        "public_fingerprints": decision_doc.get("fingerprints") or [],
        "shares": 3,
        "threshold": 2,
        "close_blockers_from_document_only": True,
        "rekey_flags": {"key_shares": 3, "key_threshold": 2, "verify": True, "pgp_keys_count": 3, "pgp_keys_encoding": "base64"},
        "rekey_initiated": False,
        "rekey_completed": False,
        "rekey_verification": FAIL,
        "current_and_new_share_holders_distinguished": True,
        "seal_unseal_drill": "SKIP",
        "no_single_human_controls_threshold_shares": True,
        "raft_snapshot_is_rekey_rollback": False,
    }
    result = validate_ceremony_evidence(evidence)
    return result["custody_blockers_may_close"] is False and result["overall_status"] == FAIL
