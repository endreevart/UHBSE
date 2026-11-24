"""Phase 0 — reproduce v0.1.1 defects. Do not rewrite v0.1.1 ZIP."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import reconcile_review_index
from human_simulator.joint_dependence_rollout_v02.groups import audit_overlap_groups
from human_simulator.joint_dependence_rollout_v02.hashes import sha256_file
from human_simulator.joint_dependence_rollout_v02.policy import (
    PRIOR_ZIPS,
    V011_ARTIFACT_DIR,
    V011_EXPECTED_INDEXED,
    V011_EXPECTED_MEMBERS,
    V011_SRC,
    VERSION,
)


def verify_v011_publication_structure(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    external = root / "artifacts" / "external-review"
    name, exp = PRIOR_ZIPS["nhr_v011"]
    zpath = external / name
    dig = sha256_file(zpath) if zpath.is_file() else ""
    sidecar = (external / f"{name}.sha256").read_text(encoding="utf-8").split()[0]
    att = json.loads((external / name.replace(".zip", ".attestation.json")).read_text(encoding="utf-8"))
    import zipfile

    with zipfile.ZipFile(zpath) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        parquet = [n for n in names if n.endswith(".parquet") or n.endswith(".jsonl")]
        private = [n for n in names if "/private/" in f"/{n}" or n.startswith("private/")]
        idx_name = next((n for n in names if n.endswith("REVIEW_INDEX.md")), None)
        recon = {"ok": False}
        if idx_name:
            idx = zf.read(idx_name).decode("utf-8")
            payloads = {n: zf.read(n) for n in names if n != idx_name}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
    ok = (
        dig == exp
        and sidecar == exp
        and att.get("sha256") == exp
        and len(names) == V011_EXPECTED_MEMBERS
        and recon.get("indexed_members") == V011_EXPECTED_INDEXED
        and bool(recon.get("ok"))
        and not parquet
        and not private
    )
    return {
        "V011_PUBLICATION_STRUCTURE_STATUS": "PASS" if ok else "FAIL",
        "sha256": dig,
        "expected_sha256": exp,
        "members": len(names),
        "indexed": recon.get("indexed_members"),
        "ok": ok,
    }


def _hash_two_processes(token: str) -> dict[str, Any]:
    env = os.environ.copy()
    env.pop("PYTHONHASHSEED", None)
    code = "import sys; print(hash(sys.argv[1]))"
    a = subprocess.check_output([sys.executable, "-c", code, token], env=env, text=True).strip()
    b = subprocess.check_output([sys.executable, "-c", code, token], env=env, text=True).strip()
    return {
        "process_a": a,
        "process_b": b,
        "equal": a == b,
        "process_dependent": a != b,
        "PYTHONHASHSEED_required_for_stability": True,
    }


def reproduce_v011_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    src = root / V011_SRC
    evaluate = (src / "evaluate.py").read_text(encoding="utf-8")
    engine = (src / "engine.py").read_text(encoding="utf-8")
    sequences = (src / "sequences.py").read_text(encoding="utf-8")
    residuals = (src / "residuals.py").read_text(encoding="utf-8")
    seq_pub = json.loads((root / V011_ARTIFACT_DIR / "rollout-sequence-contract.json").read_text())
    st = json.loads((root / V011_ARTIFACT_DIR / "status-contract.json").read_text())
    builtin_hash = "hash(row[\"target_id\"])" in evaluate or "hash(row['target_id'])" in evaluate
    hash_audit = _hash_two_processes("opaque-target-token")
    null_collapse = 'str(og or "")' in sequences
    error_growth_imported = "ERROR_GROWTH_LIMIT" in evaluate
    error_growth_applied = "ERROR_GROWTH_LIMIT *" in evaluate or "ERROR_GROWTH_LIMIT *" in engine
    funnel = seq_pub.get("funnel") or {}
    test_funnel = (seq_pub.get("test_public") or {}).get("funnel") or {}
    rec_identity = {
        "validates_requested_cell_then_runs_increment": "recursive_n_steps(horizon)" in engine
        and "RECURSIVE_BASE_INCREMENT_DAYS" in engine,
        "composite_increment_payload_in_identity": "increment_payload_sha256" not in engine,
        "shadow_direct_not_recursive_route": '"mode": "direct"' in engine,
        "eligibility_validation_selected_not_recursive": "VALIDATION_BASELINE_SUPPORTED_P0" in engine,
    }
    rec_eval = {
        "single_stochastic_endpoint_for_mae": "rec.get(\"endpoint\")" in evaluate,
        "path_quantiles_without_empirical_path_coverage": "mean_crps" in evaluate
        and "empirical_path_coverage" not in evaluate,
        "direct_coverage_used_for_recursive_gate": "COVERAGE_LO <= cov" in evaluate,
        "recursive_crps_absent": "mae_recursive" in evaluate and "crps_recursive" not in evaluate,
        "error_growth_imported_not_applied": error_growth_imported and not error_growth_applied,
        "rng_uses_builtin_hash": builtin_hash,
    }
    ok = (
        builtin_hash
        and hash_audit["process_dependent"]
        and null_collapse
        and int(funnel.get("target_rows") or 0) == 554541
        and int(funnel.get("duplicate_target_assignment") or 0) == 86918
        and int(test_funnel.get("target_rows") or 0) == 97201
        and int(test_funnel.get("duplicate_target_assignment") or 0) == 14902
        and seq_pub.get("ROLLOUT_TARGET_REUSE_STATUS") == "PASS"
        and rec_eval["error_growth_imported_not_applied"]
        and rec_identity["composite_increment_payload_in_identity"]
    )
    return {
        "version": VERSION,
        "V011_DEFECT_REPRODUCTION_STATUS": "PASS" if ok else "FAIL",
        "PRIOR_V011_NATURAL_HISTORY_ROLLOUT_FOUNDATION_STATUS": "CORRECTION_REQUIRED",
        "builtin_hash_in_evaluate": builtin_hash,
        "hash_two_processes": hash_audit,
        "PROCESS_INDEPENDENT_RNG_STATUS": "FAIL_BUILTIN_HASH" if builtin_hash else "PASS",
        "null_overlap_collapsed_to_empty_string": null_collapse,
        "target_reuse_published_as_pass": seq_pub.get("ROLLOUT_TARGET_REUSE_STATUS"),
        "train_val_target_rows": funnel.get("target_rows"),
        "train_val_duplicate_target_assignment": funnel.get("duplicate_target_assignment"),
        "test_target_rows": test_funnel.get("target_rows"),
        "test_duplicate_target_assignment": test_funnel.get("duplicate_target_assignment"),
        "horizon_window": (seq_pub.get("alignment") or {}).get("window"),
        "published_horizon_identity": st.get("REQUESTED_HORIZON_IDENTITY_STATUS"),
        "recursive_evaluation": rec_eval,
        "recursive_runtime": rec_identity,
        "v011_recursive_validation_accepted": st.get("RECURSIVE_ROLLOUT_VALIDATION_ACCEPTED_CELL_COUNT"),
        "do_not_transfer_single_recursive_cell": True,
        "v011_one_step_heldout_confirmed": st.get("ONE_STEP_HELDOUT_CONFIRMED_CELL_COUNT"),
        "do_not_copy_84_15_1": True,
        "ok": ok,
    }


def stochastic_reproducibility_audit(root: Path) -> dict[str, Any]:
    doc = reproduce_v011_defects(root)
    return {
        "version": VERSION,
        "PROCESS_INDEPENDENT_RNG_STATUS": doc["PROCESS_INDEPENDENT_RNG_STATUS"],
        "CROSS_PROCESS_REPLAY_STATUS": "FAIL_UNDER_V011_HASH" if doc["hash_two_processes"]["process_dependent"] else "PASS",
        "hash_two_processes": doc["hash_two_processes"],
        "PYTHONHASHSEED_must_not_be_reproducibility_condition": True,
        "ok": doc["builtin_hash_in_evaluate"] and doc["hash_two_processes"]["process_dependent"],
    }


def target_alignment_reuse_audit(root: Path) -> dict[str, Any]:
    seq = json.loads((root / V011_ARTIFACT_DIR / "rollout-sequence-contract.json").read_text())
    funnel = seq.get("funnel") or {}
    test = (seq.get("test_public") or {}).get("funnel") or {}
    return {
        "version": VERSION,
        "cross_role_target_reuse_v011": seq.get("cross_role_target_reuse"),
        "train_val_target_rows": funnel.get("target_rows"),
        "train_val_duplicate_target_assignment": funnel.get("duplicate_target_assignment"),
        "test_target_rows": test.get("target_rows"),
        "test_duplicate_target_assignment": test.get("duplicate_target_assignment"),
        "ROLLOUT_TARGET_REUSE_STATUS_v011": seq.get("ROLLOUT_TARGET_REUSE_STATUS"),
        "claim_pass_despite_within_role_duplicates": seq.get("ROLLOUT_TARGET_REUSE_STATUS") == "PASS"
        and int(funnel.get("duplicate_target_assignment") or 0) > 0,
        "alignment_window_overlaps": True,
        "ok": True,
    }


def recursive_runtime_identity_audit(root: Path) -> dict[str, Any]:
    doc = reproduce_v011_defects(root)
    return {
        "version": VERSION,
        "RECURSIVE_RUNTIME_COMPOSITE_IDENTITY_STATUS": "MISSING_INCREMENT_PAYLOAD",
        "engine": doc["recursive_runtime"],
        "evaluation": doc["recursive_evaluation"],
        "ok": True,
    }


def corrective_gate(root: Path) -> dict[str, Any]:
    defects = reproduce_v011_defects(root)
    hash_doc = stochastic_reproducibility_audit(root)
    og = audit_overlap_groups(root)
    reuse = target_alignment_reuse_audit(root)
    rec = recursive_runtime_identity_audit(root)
    reproduced = bool(defects.get("ok") and hash_doc.get("ok") and reuse.get("ok"))
    return {
        "version": VERSION,
        "V011_CORRECTIVE_GATE_STATUS": "REPRODUCTION_PASS_CORRECTION_REQUIRED"
        if reproduced
        else "FAIL",
        "PRIOR_V011_NATURAL_HISTORY_ROLLOUT_FOUNDATION_STATUS": "CORRECTION_REQUIRED",
        "defects_ok": defects.get("ok"),
        "overlap_audit_ok": og.get("ok"),
        "hash_ok": hash_doc.get("ok"),
        "overlap_summary": {
            "known": og.get("subjects_with_known_upstream_group"),
            "null": og.get("subjects_with_null_upstream_group"),
            "distinct_upstream": og.get("distinct_non_null_upstream_groups"),
            "effective_groups": og.get("effective_groups"),
            "cross_role": og.get("effective_groups_crossing_roles"),
        },
        "ok": reproduced,
    }
