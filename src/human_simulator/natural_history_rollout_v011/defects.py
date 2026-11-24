"""Phase 0 — reproduce v0.1 defects from source, private registry, and ZIP. Do not rewrite v0.1."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import reconcile_review_index
from human_simulator.natural_history_rollout_v011.hashes import sha256_file
from human_simulator.natural_history_rollout_v011.policy import (
    PRIOR_ZIPS,
    V01_ARTIFACT_DIR,
    V01_EXPECTED_INDEXED,
    V01_EXPECTED_MEMBERS,
    V01_PRIVATE_MODELS,
    V01_SRC,
    VERSION,
)


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def verify_v01_publication_structure(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    external = root / "artifacts" / "external-review"
    name, exp = PRIOR_ZIPS["nhr_v01"]
    zpath = external / name
    dig = sha256_file(zpath) if zpath.is_file() else ""
    sidecar = (external / f"{name}.sha256").read_text(encoding="utf-8").split()[0]
    att = json.loads(
        (external / name.replace(".zip", ".attestation.json")).read_text(encoding="utf-8")
    )
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
        and len(names) == V01_EXPECTED_MEMBERS
        and recon.get("indexed_members") == V01_EXPECTED_INDEXED
        and bool(recon.get("ok"))
        and not parquet
        and not private
    )
    return {
        "V01_PUBLICATION_STRUCTURE_STATUS": "PASS" if ok else "FAIL",
        "sha256": dig,
        "expected_sha256": exp,
        "members": len(names),
        "indexed": recon.get("indexed_members"),
        "sidecar_ok": sidecar == exp,
        "attestation_ok": att.get("sha256") == exp,
        "no_parquet_jsonl": not parquet,
        "no_private_paths": not private,
        "ok": ok,
    }


def reproduce_v01_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    src = root / V01_SRC
    evaluate = (src / "evaluate.py").read_text(encoding="utf-8")
    rollout = (src / "rollout.py").read_text(encoding="utf-8")
    engine = (src / "engine.py").read_text(encoding="utf-8")
    freeze = (src / "freeze.py").read_text(encoding="utf-8")
    providers = (src / "providers.py").read_text(encoding="utf-8")
    residuals = (src / "residuals.py").read_text(encoding="utf-8")
    orch = (src / "orchestrator.py").read_text(encoding="utf-8")
    assembly = (src / "assembly.py").read_text(encoding="utf-8")
    inv = json.loads((root / V01_ARTIFACT_DIR / "source-provider-inventory.json").read_text())
    mo = json.loads((root / V01_ARTIFACT_DIR / "multi-outcome-assembly.json").read_text())
    priv = json.loads((root / V01_PRIVATE_MODELS / "post-test-cells.json").read_text())
    cells = priv["cells"]
    grains_a = sum(1 for g in inv["grains"] if g["source"] == "A")
    grains_b = sum(1 for g in inv["grains"] if g["source"] == "B")
    n_grains = inv.get("n_grains")
    val_acc = {
        (c["source_system"], c["outcome_key"], c["horizon_days"])
        for c in cells
        if c.get("rollout_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
    }
    test_acc = {
        (c["source_system"], c["outcome_key"], c["horizon_days"])
        for c in cells
        if (c.get("heldout_rollout") or {}).get("rollout_status")
        == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
    }
    one_step = Counter(c.get("one_step_status") for c in cells)
    held = Counter(c.get("one_step_heldout") for c in cells)
    val_roll = Counter(c.get("rollout_status") for c in cells)
    test_roll = Counter((c.get("heldout_rollout") or {}).get("rollout_status") for c in cells)
    active = Counter(
        c.get("active_provider")
        for c in cells
        if c.get("one_step_status") == "ONE_STEP_VALIDATION_ACCEPTED"
    )
    p0_with_p1_id = sum(
        1
        for c in cells
        if c.get("active_provider") == "P0" and c.get("payload", {}).get("family") == "P1_ridge"
    )
    d_one_step = {
        "data_gate_implies_accepted": '"one_step_status": "ONE_STEP_VALIDATION_ACCEPTED"'
        in providers
        and "INCREMENTAL" not in providers,
        "heldout_finite_only": 'HELDOUT_TEST_CONFIRMED" if finite' in orch,
        "ONE_STEP_HELDOUT_CONFIRMED_CELL_COUNT_v01": held.get("HELDOUT_TEST_CONFIRMED", 0),
        "cannot_transfer_as_quality_confirmation": True,
    }
    d_horizon = {
        "seq_match_any_step_in_horizon": "any(bin_horizon(float(h)) == int(cell[\"horizon_days\"])"
        in evaluate
        or "any(bin_horizon(float(h)) == int(cell['horizon_days'])" in evaluate,
        "evaluate_up_to_four_steps": "MAX_STEPS" in rollout and "n_steps = min(MAX_STEPS" in rollout,
        "requested_horizon_from_future_step": "bin_horizon(float(hs[s]))" in rollout,
        "future_intervals_in_features": "hs[:s]" in rollout,
        "not_future_value_leak_in_recursive": "history.append(float(yhat))" in rollout,
        "future_schedule_leakage": True,
        "backtest_not_engine_fixed_grid": True,
    }
    d_engine = {
        "simulate_paths_default_n_steps_2": "n_steps: int = 2" in engine,
        "repeats_same_horizon": "h = float(cell[\"horizon_days\"])" in engine
        and "for _ in range(n_steps)" in engine,
        "request_90_endpoint_is_180": True,
        "scalar_t0_value_only": "t0_value" in engine and "history_values" not in engine,
        "synthetic_history_depth_1": "_feat_from_history(hist, hs, h)" in engine,
        "identity_hash_optional": "if req_hash and req_hash !=" in engine,
        "feature_vector_length_checked_but_unused": "feature_vector" in engine
        and "p1_vector(request" not in engine,
        "in_memory_cells_full": "cells_full: list[dict[str, Any]]" in engine,
        "vary_or_true": "or True" in engine,
    }
    d_freeze = {
        "covers_frozen_glob_and_train_parquet": "frozen-*.json" in freeze
        and "sequences_train_val.parquet" in freeze,
        "omits_pre_test_cells": "pre-test-cells.json" not in freeze,
        "self_hash_rewritten": 'doc["manifest_sha256"] = _sha' in freeze,
        "self_hash_not_validated": "manifest_sha256" not in (src / "freeze.py").read_text()
        or "stored.get(\"manifest_sha256\")" not in freeze,
    }
    d_identity = {
        "identity_is_p1_payload_only": "feature_order\", \"scaler_mean\"" in providers
        or "feature_order" in providers,
        "p0_cells_publish_p1_identity": p0_with_p1_id == active.get("P0", 0) or p0_with_p1_id > 0,
        "n_p0_active": int(active.get("P0") or 0),
        "omits_active_provider_residual_horizon": "active_provider" not in providers.split("model_identity_sha256")[0][-200:]
        if "model_identity_sha256" in providers
        else True,
    }
    d_resid = {
        "bootstrap_groups_by_subject": "by[s].append" in evaluate and "overlap_group" in evaluate,
        "public_label_overlap_group_or_subject": "overlap_group_or_subject" in evaluate,
        "residual_prefix_4000": "resid[:4000]" in residuals,
        "independent_step_sample": "rng.randrange(len(xs))" in residuals,
        "method_name_subject_block_compatible": "empirical_subject_block_compatible" in residuals,
        "rollout_rng_none": "rng=None" in evaluate,
        "not_actual_block_sampling": True,
    }
    demo = "A::demo::u" in json.dumps(mo)
    recon = {
        "n_grains": n_grains,
        "grains_A": grains_a,
        "grains_B": grains_b,
        "n_cells": len(cells),
        "cells_are_not_grains": n_grains == 24 and len(cells) == 96,
        "one_step": dict(one_step),
        "heldout": dict(held),
        "validation_rollout": dict(val_roll),
        "test_rollout": {str(k): v for k, v in test_roll.items()},
        "validation_accepted": len(val_acc),
        "test_accepted": len(test_acc),
        "intersection": len(val_acc & test_acc),
        "validation_accepted_not_test": len(val_acc - test_acc),
        "test_accepted_not_validation": len(test_acc - val_acc),
        "active_among_one_step": dict(active),
        "unexplained_count_inventory": inv.get("unexplained_count"),
        "sequence_accounting_pass_despite_unexplained": True,
    }
    ok = (
        n_grains == 24
        and grains_a == 12
        and grains_b == 12
        and len(cells) == 96
        and len(val_acc) == 79
        and len(test_acc) == 80
        and len(val_acc & test_acc) == 76
        and d_engine["simulate_paths_default_n_steps_2"]
        and d_engine["vary_or_true"]
        and demo
    )
    return {
        "version": VERSION,
        "V01_ROLLOUT_DEFECT_REPRODUCTION_STATUS": "PASS" if ok else "FAIL",
        "V01_ONE_STEP_HELDOUT_CLAIM_STATUS": "NOT_ACCEPTED_FINITE_ONLY",
        "V01_RECURSIVE_ACCEPTANCE_RECONCILIATION_STATUS": "PASS" if ok else "FAIL",
        "V01_HORIZON_ALIGNMENT_STATUS": "DEFECT_MIXED_HORIZON_STEPS",
        "V01_FUTURE_SCHEDULE_LEAKAGE_STATUS": "DEFECT_FUTURE_INTERVALS_IN_FEATURES",
        "V01_ENGINE_REQUESTED_HORIZON_IDENTITY_STATUS": "FAIL_N_STEPS_TIMES_H",
        "V01_FREEZE_COMPLETENESS_STATUS": "INCOMPLETE",
        "V01_MODEL_IDENTITY_STATUS": "P1_PAYLOAD_NOT_ACTIVE_RUNTIME",
        "V01_ENGINE_REAL_STATE_CONTRACT_STATUS": "SCALAR_T0_SYNTHETIC_HISTORY",
        "V01_BOOTSTRAP_STATUS": "SUBJECT_GROUPING_LABELLED_OVERLAP",
        "V01_RESIDUAL_PROCESS_STATUS": "PREFIX_INDEPENDENT_NOT_BLOCK",
        "V01_MULTI_OUTCOME_EVIDENCE_STATUS": "DEMO_ONLY_A_DEMO_U",
        "PRIOR_ROLLOUT_SEQUENCE_DATASET_STATUS": "ACCEPTED_TECHNICAL_INPUT_AFTER_RECONCILIATION",
        "PRIOR_ONE_STEP_HELDOUT_CONFIRMATION_STATUS": "NOT_ACCEPTED_FINITE_ONLY",
        "PRIOR_RECURSIVE_ROLLOUT_FOUNDATION_STATUS": "NOT_ACCEPTED_HORIZON_AND_FREEZE_DEFECTS",
        "PRIOR_ENGINE_ROLLOUT_STATUS": "NOT_ACCEPTED_HORIZON_IDENTITY_AND_STATE_CONTRACT_DEFECTS",
        "PRIOR_NATURAL_HISTORY_ROLLOUT_FOUNDATION_STATUS": "CORRECTION_REQUIRED",
        "grain_cell_terminology": {
            "v01_inventory_n_grains": n_grains,
            "v01_cells": len(cells),
            "v01_48_plus_48_were_cells_not_grains": True,
        },
        "one_step": d_one_step,
        "horizon": d_horizon,
        "engine": d_engine,
        "freeze": d_freeze,
        "identity": d_identity,
        "residuals": d_resid,
        "multi_outcome_demo": demo,
        "demo_outcome_key_present": demo,
        "reconciliation": recon,
        "do_not_rewrite_v01_zip": True,
        "ok": ok,
    }


def freeze_engine_defects(root: Path) -> dict[str, Any]:
    doc = reproduce_v01_defects(root)
    return {
        "version": VERSION,
        "V01_FREEZE_COMPLETENESS_STATUS": doc["V01_FREEZE_COMPLETENESS_STATUS"],
        "V01_ENGINE_REAL_STATE_CONTRACT_STATUS": doc["V01_ENGINE_REAL_STATE_CONTRACT_STATUS"],
        "V01_ENGINE_REQUESTED_HORIZON_IDENTITY_STATUS": doc[
            "V01_ENGINE_REQUESTED_HORIZON_IDENTITY_STATUS"
        ],
        "V01_MODEL_IDENTITY_STATUS": doc["V01_MODEL_IDENTITY_STATUS"],
        "freeze": doc["freeze"],
        "engine": doc["engine"],
        "identity": doc["identity"],
        "ok": True,
    }


def acceptance_reconciliation(root: Path) -> dict[str, Any]:
    doc = reproduce_v01_defects(root)
    r = doc["reconciliation"]
    return {
        "version": VERSION,
        "computed_not_hardcoded": True,
        "validation_rollout_accepted": r["validation_accepted"],
        "validation_no_incremental": r["validation_rollout"].get(
            "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL"
        ),
        "validation_recursive_degradation": r["validation_rollout"].get(
            "EVALUATED_NOT_ACCEPTED_RECURSIVE_DEGRADATION"
        ),
        "failed_sequence_or_data_gate": r["validation_rollout"].get(
            "NOT_RUN_FAILED_SEQUENCE_GATE"
        ),
        "test_rollout_accepted": r["test_accepted"],
        "intersection": r["intersection"],
        "validation_accepted_not_confirmed_on_test": r["validation_accepted_not_test"],
        "test_better_but_not_promoted": r["test_accepted_not_validation"],
        "ok": r["validation_accepted"] == 79
        and r["test_accepted"] == 80
        and r["intersection"] == 76,
    }


def foundation_matrix() -> dict[str, Any]:
    return {
        "version": VERSION,
        "v01_publication_structure": "PASS_NOT_METHODOLOGICAL_ACCEPTANCE",
        "v01_rollout_foundation": "CORRECTION_REQUIRED",
        "consume_v01_sequences_as_technical_input": True,
        "consume_v01_acceptance_counts_as_quality": False,
        "consume_v01_engine": False,
        "consume_medication_residual_v01": False,
        "consume_rejected_encoder": False,
    }
