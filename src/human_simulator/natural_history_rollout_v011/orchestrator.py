"""Orchestrator — freeze-only run-v0.1.1, then separate open-test-v0.1.1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.natural_history_rollout_v011.assembly import heldout_assembly
from human_simulator.natural_history_rollout_v011.baseline import verify_baseline
from human_simulator.natural_history_rollout_v011.defects import (
    acceptance_reconciliation,
    foundation_matrix,
    freeze_engine_defects,
    reproduce_v01_defects,
    verify_v01_publication_structure,
)
from human_simulator.natural_history_rollout_v011.engine import run_engine_shadow
from human_simulator.natural_history_rollout_v011.evaluate import evaluate_cell, increment_cell_for
from human_simulator.natural_history_rollout_v011.freeze import (
    mark_test_opened,
    verify_pretest_freeze,
    write_pretest_freeze,
)
from human_simulator.natural_history_rollout_v011.policy import (
    ARTIFACT_DIR,
    COVERAGE_HI,
    COVERAGE_LO,
    MIN_TEST_OVERLAP_GROUPS,
    MIN_TEST_SUBJECTS,
    MIN_TEST_TARGETS,
    MODELS_DIR,
    PREDECLARED_ABSOLUTE_GRID_DAYS,
    REVIEW_ZIP,
    RUNTIME_DIR,
    SECURITY_STAGE_STATUS,
    SEQ_DIR,
    TEST_PARQUET,
    TRAIN_VAL_PARQUET,
    VERSION,
    policy_snapshot,
)
from human_simulator.natural_history_rollout_v011.privacy import scan_public
from human_simulator.natural_history_rollout_v011.providers import train_providers
from human_simulator.natural_history_rollout_v011.registry import build_registry, public_registry
from human_simulator.natural_history_rollout_v011.residuals import fit_residuals
from human_simulator.natural_history_rollout_v011.sequences import (
    assert_no_test_parquet,
    audit_uis_m1,
    build_origins,
    grain_cell_inventory,
    load_series,
    load_split,
    write_origins,
)
from human_simulator.natural_history_rollout_v011.times import alignment_contract


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{hashlib.sha256((art / n).read_bytes()).hexdigest()}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )


def _status(bundle: dict[str, Any]) -> dict[str, Any]:
    lim = bundle.get("defects") or {}
    inv = bundle.get("inventory") or {}
    seq = bundle.get("sequences_public") or {}
    train = bundle.get("train") or {}
    reg = bundle.get("registry") or {}
    eng = bundle.get("engine") or {}
    freeze = bundle.get("freeze") or {}
    asm = bundle.get("assembly") or {}
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": (bundle.get("baseline") or {}).get("BASELINE_VERIFICATION_STATUS"),
        "V01_PUBLICATION_STRUCTURE_STATUS": (bundle.get("v01_struct") or {}).get(
            "V01_PUBLICATION_STRUCTURE_STATUS"
        ),
        "V01_ROLLOUT_DEFECT_REPRODUCTION_STATUS": lim.get("V01_ROLLOUT_DEFECT_REPRODUCTION_STATUS"),
        "V01_ONE_STEP_HELDOUT_CLAIM_STATUS": lim.get("V01_ONE_STEP_HELDOUT_CLAIM_STATUS"),
        "V01_RECURSIVE_ACCEPTANCE_RECONCILIATION_STATUS": lim.get(
            "V01_RECURSIVE_ACCEPTANCE_RECONCILIATION_STATUS"
        ),
        "V01_HORIZON_ALIGNMENT_STATUS": lim.get("V01_HORIZON_ALIGNMENT_STATUS"),
        "V01_FUTURE_SCHEDULE_LEAKAGE_STATUS": lim.get("V01_FUTURE_SCHEDULE_LEAKAGE_STATUS"),
        "V01_ENGINE_REQUESTED_HORIZON_IDENTITY_STATUS": lim.get(
            "V01_ENGINE_REQUESTED_HORIZON_IDENTITY_STATUS"
        ),
        "V01_FREEZE_COMPLETENESS_STATUS": lim.get("V01_FREEZE_COMPLETENESS_STATUS"),
        "V01_MODEL_IDENTITY_STATUS": lim.get("V01_MODEL_IDENTITY_STATUS"),
        "V01_ENGINE_REAL_STATE_CONTRACT_STATUS": lim.get("V01_ENGINE_REAL_STATE_CONTRACT_STATUS"),
        "V01_BOOTSTRAP_STATUS": lim.get("V01_BOOTSTRAP_STATUS"),
        "V01_RESIDUAL_PROCESS_STATUS": lim.get("V01_RESIDUAL_PROCESS_STATUS"),
        "V01_MULTI_OUTCOME_EVIDENCE_STATUS": lim.get("V01_MULTI_OUTCOME_EVIDENCE_STATUS"),
        "PRIOR_ROLLOUT_SEQUENCE_DATASET_STATUS": lim.get("PRIOR_ROLLOUT_SEQUENCE_DATASET_STATUS"),
        "PRIOR_ONE_STEP_HELDOUT_CONFIRMATION_STATUS": lim.get("PRIOR_ONE_STEP_HELDOUT_CONFIRMATION_STATUS"),
        "PRIOR_RECURSIVE_ROLLOUT_FOUNDATION_STATUS": lim.get("PRIOR_RECURSIVE_ROLLOUT_FOUNDATION_STATUS"),
        "PRIOR_ENGINE_ROLLOUT_STATUS": lim.get("PRIOR_ENGINE_ROLLOUT_STATUS"),
        "PRIOR_NATURAL_HISTORY_ROLLOUT_FOUNDATION_STATUS": lim.get(
            "PRIOR_NATURAL_HISTORY_ROLLOUT_FOUNDATION_STATUS"
        ),
        "ROLLOUT_GRAIN_ACCOUNTING_STATUS": inv.get("ROLLOUT_GRAIN_ACCOUNTING_STATUS"),
        "ROLLOUT_CELL_ACCOUNTING_STATUS": inv.get("ROLLOUT_CELL_ACCOUNTING_STATUS"),
        "ROLLOUT_SEQUENCE_DATASET_STATUS": bundle.get("dataset_status"),
        "ROLLOUT_SEQUENCE_ACCOUNTING_STATUS": "PASS" if seq.get("ok") and seq.get("unexplained_count") == 0 else "FAIL",
        "ROLLOUT_TEMPORAL_LEAKAGE_STATUS": seq.get("ROLLOUT_TEMPORAL_LEAKAGE_STATUS"),
        "ROLLOUT_FUTURE_SCHEDULE_LEAKAGE_STATUS": seq.get("ROLLOUT_FUTURE_SCHEDULE_LEAKAGE_STATUS"),
        "ROLLOUT_SPLIT_ISOLATION_STATUS": seq.get("ROLLOUT_SPLIT_ISOLATION_STATUS"),
        "ROLLOUT_TARGET_REUSE_STATUS": seq.get("ROLLOUT_TARGET_REUSE_STATUS"),
        "REQUESTED_TIME_GRID_CONTRACT_STATUS": "PREDECLARED_ABSOLUTE_OFFSETS",
        "TARGET_ALIGNMENT_CONTRACT_STATUS": seq.get("TARGET_ALIGNMENT_CONTRACT_STATUS"),
        "REQUESTED_HORIZON_IDENTITY_STATUS": "T0_PLUS_H",
        "ONE_STEP_PROVIDER_REGISTRY_STATUS": reg.get("ONE_STEP_PROVIDER_REGISTRY_STATUS"),
        "ONE_STEP_VALIDATION_SELECTED_CELL_COUNT": reg.get("ONE_STEP_VALIDATION_SELECTED_CELL_COUNT", 0),
        "ONE_STEP_VALIDATION_BASELINE_SUPPORTED_CELL_COUNT": reg.get(
            "ONE_STEP_VALIDATION_BASELINE_SUPPORTED_CELL_COUNT", 0
        ),
        "ONE_STEP_VALIDATION_INCREMENTAL_ACCEPTED_CELL_COUNT": reg.get(
            "ONE_STEP_VALIDATION_INCREMENTAL_ACCEPTED_CELL_COUNT", 0
        ),
        "ONE_STEP_HELDOUT_EVALUABLE_CELL_COUNT": reg.get("ONE_STEP_HELDOUT_EVALUABLE_CELL_COUNT", 0),
        "ONE_STEP_HELDOUT_CONFIRMED_CELL_COUNT": reg.get("ONE_STEP_HELDOUT_CONFIRMED_CELL_COUNT", 0),
        "ONE_STEP_VALIDATION_HELDOUT_INTERSECTION_COUNT": reg.get(
            "ONE_STEP_VALIDATION_HELDOUT_INTERSECTION_COUNT", 0
        ),
        "STOCHASTIC_RESIDUAL_DISTRIBUTION_STATUS": (bundle.get("residuals") or {}).get(
            "STOCHASTIC_RESIDUAL_DISTRIBUTION_STATUS"
        ),
        "STOCHASTIC_PATH_EVALUATION_STATUS": bundle.get("STOCHASTIC_PATH_EVALUATION_STATUS", "NOT_RUN"),
        "RESIDUAL_SERIAL_DEPENDENCE_STATUS": (bundle.get("residuals") or {}).get(
            "RESIDUAL_SERIAL_DEPENDENCE_STATUS"
        ),
        "RECURSIVE_ROLLOUT_VALIDATION_ACCEPTED_CELL_COUNT": reg.get(
            "RECURSIVE_ROLLOUT_VALIDATION_ACCEPTED_CELL_COUNT", 0
        ),
        "RECURSIVE_ROLLOUT_HELDOUT_CONFIRMED_CELL_COUNT": reg.get(
            "RECURSIVE_ROLLOUT_HELDOUT_CONFIRMED_CELL_COUNT", 0
        ),
        "RECURSIVE_ROLLOUT_EVALUATION_STATUS": bundle.get("RECURSIVE_ROLLOUT_EVALUATION_STATUS", "NOT_RUN"),
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "ACTIVE_RUNTIME_PAYLOAD_IDENTITY_STATUS": freeze.get("ACTIVE_RUNTIME_PAYLOAD_IDENTITY_STATUS")
        or ("FROZEN" if freeze.get("ok") else "NOT_FROZEN"),
        "TEST_ACCESS_LIFECYCLE_STATUS": bundle.get("test_lifecycle", "FROZEN_UNOPENED"),
        "MODEL_RELOAD_STATUS": eng.get("ENGINE_MODEL_ROUTING_STATUS", "NOT_RUN"),
        "MARGINAL_MULTI_OUTCOME_ASSEMBLY_CONTRACT_STATUS": asm.get(
            "MARGINAL_MULTI_OUTCOME_ASSEMBLY_CONTRACT_STATUS", "NOT_RUN"
        ),
        "MARGINAL_MULTI_OUTCOME_HELDOUT_EVALUATION_STATUS": asm.get(
            "MARGINAL_MULTI_OUTCOME_HELDOUT_EVALUATION_STATUS", "NOT_RUN"
        ),
        "MULTI_OUTCOME_DEPENDENCE_STATUS": "MARGINAL_ONLY_NO_JOINT_MODEL",
        "NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS": reg.get("NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS"),
        "ENGINE_MODEL_ROUTING_STATUS": eng.get("ENGINE_MODEL_ROUTING_STATUS", "NOT_RUN"),
        "ENGINE_REAL_STATE_INPUT_STATUS": eng.get("ENGINE_REAL_STATE_INPUT_STATUS", "NOT_RUN"),
        "ENGINE_REQUESTED_HORIZON_STATUS": eng.get("ENGINE_REQUESTED_HORIZON_STATUS", "NOT_RUN"),
        "ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS": eng.get("ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS", "NOT_RUN"),
        "ENGINE_DETERMINISTIC_REPLAY_STATUS": eng.get("ENGINE_DETERMINISTIC_REPLAY_STATUS", "NOT_RUN"),
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": eng.get(
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS", "NOT_RUN"
        ),
        "INTERVENTION_SLOT_CONTRACT_STATUS": "TYPED_UNAVAILABLE",
        "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": "NOT_CONSUMED_NOT_ACCEPTED",
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "SAFETY_BOUNDARY_CLASSIFIER_STATUS": "NOT_STARTED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "PUBLIC_DATA_MINIMIZATION_STATUS": (bundle.get("privacy") or {}).get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": bundle.get("REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS", "NOT_PACKED"),
        "PUBLICATION_INTEGRITY_STATUS": bundle.get("PUBLICATION_INTEGRITY_STATUS", "NOT_PUBLISHED"),
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "TECHNICAL_PASS": bool(bundle.get("ok")),
        "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS": inv.get("SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS"),
        "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS": train.get(
            "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS"
        ),
        "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": train.get("TRAIN_ONLY_PROVIDER_SELECTION_STATUS"),
    }


def _report(st: dict[str, Any], *, final: bool) -> str:
    status = "FINAL" if final else "DRAFT"
    lines = [
        f"# Unified Source-Aware Natural-History Stochastic Rollout Foundation v{VERSION}",
        "",
        f"Report status: {status}",
        "",
        "Correction of v0.1 horizon identity, freeze completeness, and engine state contract.",
        "Natural history only. Marginal trajectories. Not joint physiology, not intervention response.",
        "",
        "## Statuses",
        "",
    ]
    for k, v in st.items():
        if k.endswith("_STATUS") or k.endswith("_COUNT") or k in {
            "SCIENTIFIC_CROSS_SOURCE_PASS",
            "PRODUCTION_READINESS",
            "TECHNICAL_PASS",
        }:
            lines.append(f"- `{k}`={v}")
    lines += ["", "## Non-claims", "", "- `NATURAL_HISTORY_ONLY`", "- `CLINICAL_USE_PROHIBITED`", ""]
    return "\n".join(lines) + "\n"


def _write_public(root: Path, bundle: dict[str, Any], *, final: bool) -> None:
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    _write_json(art / "policy-snapshot.json", policy_snapshot())
    _write_json(art / "baseline-verification.json", bundle.get("baseline"))
    _write_json(art / "v01-publication-structure.json", bundle.get("v01_struct"))
    _write_json(art / "v01-rollout-defect-reproduction.json", bundle.get("defects"))
    _write_json(art / "v01-freeze-engine-defect-reproduction.json", bundle.get("freeze_defects"))
    _write_json(art / "v01-acceptance-reconciliation.json", bundle.get("recon"))
    _write_json(art / "v01-foundation-acceptance-matrix.json", bundle.get("matrix"))
    _write_json(art / "source-provider-inventory.json", bundle.get("inventory"))
    _write_json(art / "rollout-sequence-contract.json", bundle.get("sequences_public"))
    _write_json(art / "target-alignment-contract.json", alignment_contract())
    _write_json(art / "one-step-providers.json", {
        "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": (bundle.get("train") or {}).get(
            "TRAIN_ONLY_PROVIDER_SELECTION_STATUS"
        ),
        "n_cells": len((bundle.get("train") or {}).get("cells") or []),
        "no_medication_features": True,
        "p0_is_baseline_not_incremental": True,
    })
    _write_json(art / "residual-distributions.json", (bundle.get("residuals") or {}).get("public"))
    _write_json(art / "cell-registry-public.json", public_registry(bundle.get("registry") or {}))
    _write_json(art / "multi-outcome-assembly.json", bundle.get("assembly") or {"demo_outcome_used": False})
    _write_json(art / "pre-test-freeze.json", bundle.get("freeze"))
    _write_json(art / "engine-natural-history-shadow.json", bundle.get("engine") or {"status": "NOT_RUN"})
    _write_json(
        art / "intervention-slot-contract.json",
        {
            "INTERVENTION_SLOT_CONTRACT_STATUS": "TYPED_UNAVAILABLE",
            "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
            "no_hard_coded_drug_effect": True,
            "no_medication_residual_v01": True,
        },
    )
    (art / "REPRODUCE.md").write_text(
        "# Reproduce\n\n"
        "```bash\n"
        "audit --root . natural-history-rollout run-v0.1.1 --no-publish\n"
        "audit --root . natural-history-rollout open-test-v0.1.1\n"
        "audit --root . natural-history-rollout verify-v0.1.1\n"
        "audit --root . natural-history-rollout publish-v0.1.1\n"
        "```\n",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        "# Review guide\n\nAggregate-only. Horizon-aligned natural history. v0.1 ZIP is immutable.\n",
        encoding="utf-8",
    )
    st = _status(bundle)
    (art / "stage-report.md").write_text(_report(st, final=final), encoding="utf-8")
    _write_json(art / "status-contract.json", st)
    priv = scan_public(art)
    bundle["privacy"] = priv
    bundle["ok"] = bool(bundle.get("ok")) and bool(priv.get("ok"))
    st = _status(bundle)
    _write_json(art / "status-contract.json", st)
    _write_json(art / "public-privacy-scan.json", priv)
    (art / "stage-report.md").write_text(_report(st, final=final), encoding="utf-8")
    _write_json(
        art / "verification.json",
        {
            "version": VERSION,
            "ok": bool(bundle.get("ok"))
            and priv.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "PASS_AGGREGATE_ONLY",
            "generated_at": _now(),
            "final": final,
        },
    )
    write_manifest(art)


def _persist(root: Path, cells: list[dict[str, Any]], policy: dict[str, Any]) -> None:
    models = root / MODELS_DIR
    models.mkdir(parents=True, exist_ok=True)
    residual = {
        c.get("active_payload_sha256"): {
            "n_blocks": (c.get("residual_dist") or {}).get("n_blocks"),
            "sampling_contract": (c.get("residual_dist") or {}).get("sampling_contract"),
            "residual_distribution_sha256": (c.get("residual_dist") or {}).get(
                "residual_distribution_sha256"
            ),
        }
        for c in cells
        if c.get("active_payload_sha256")
    }
    for c in cells:
        ident = c.get("active_payload_sha256") or "none"
        payload = {
            "active_identity": c.get("active_identity_body"),
            "active_provider": c.get("active_provider"),
            "p1_payload": c.get("p1_payload") if c.get("active_provider") == "P1" else None,
            "residual_dist": c.get("residual_dist"),
        }
        (models / f"frozen-payload-{ident[:16]}.json").write_text(
            json.dumps(payload, separators=(",", ":"), default=str) + "\n"
        )
    (models / "pre-test-cells.json").write_text(
        json.dumps({"cells": cells}, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (models / "residual-payload.json").write_text(json.dumps(residual, indent=2) + "\n")
    (models / "policy-snapshot.json").write_text(json.dumps(policy, indent=2) + "\n")
    _write_json(models / "target-alignment-contract.json", alignment_contract())
    _write_json(
        models / "engine-eligibility.json",
        {
            "eligible_tiers": [
                "VALIDATION_BASELINE_SUPPORTED_P0",
                "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED",
            ],
            "mandatory_payload_identity": True,
        },
    )
    _write_json(
        models / "code-policy-hashes.json",
        {"policy_sha256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()},
    )


def _heldout_one_step(cell: dict[str, Any], metrics: dict[str, Any]) -> str:
    status = cell.get("one_step_status")
    if status == "VALIDATION_DATA_GATE_FAILED":
        return "HELDOUT_TEST_NOT_EVALUABLE"
    if status not in {
        "VALIDATION_BASELINE_SUPPORTED_P0",
        "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED",
    }:
        return "HELDOUT_TEST_NOT_CONFIRMED"
    n_s, n_t, n_g = metrics.get("n_subjects") or 0, metrics.get("n_targets") or 0, metrics.get("n_overlap_groups") or 0
    if n_s < MIN_TEST_SUBJECTS or n_t < MIN_TEST_TARGETS or n_g < MIN_TEST_OVERLAP_GROUPS:
        return "HELDOUT_TEST_NOT_EVALUABLE"
    if not metrics.get("finite"):
        return "HELDOUT_TEST_NOT_CONFIRMED"
    cov = metrics.get("coverage")
    if cov is None or not (COVERAGE_LO <= cov <= COVERAGE_HI):
        return "HELDOUT_TEST_NOT_CONFIRMED"
    if metrics.get("bootstrap", {}).get("lo") is None:
        return "HELDOUT_TEST_NOT_CONFIRMED"
    if status == "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED":
        if not metrics.get("direct_not_worse_than_p0"):
            return "HELDOUT_TEST_NOT_CONFIRMED"
    return "HELDOUT_TEST_CONFIRMED"


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / SEQ_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    assert_no_test_parquet(root)
    baseline = verify_baseline(root)
    v01_struct = verify_v01_publication_structure(root)
    defects = reproduce_v01_defects(root)
    freeze_def = freeze_engine_defects(root)
    recon = acceptance_reconciliation(root)
    matrix = foundation_matrix()
    split = load_split(root)
    allowed = {sid for sid, rec in split.items() if rec["split_role"] in {"train", "validation"}}
    series, series_pub = load_series(root, allowed_subjects=allowed)
    uis = audit_uis_m1(root)
    built = build_origins(series, split, roles={"train", "validation"})
    write_origins(root, built["rows"], TRAIN_VAL_PARQUET)
    assert_no_test_parquet(root)
    inv = grain_cell_inventory(built["rows"], series_pub, uis)
    train_rows = [r for r in built["rows"] if r["split_role"] == "train"]
    val_rows = [r for r in built["rows"] if r["split_role"] == "validation"]
    train = train_providers(train_rows, val_rows)
    residuals = fit_residuals(train_rows, train["cells"])
    for c in train["cells"]:
        inc = increment_cell_for(train["cells"], c)
        m = evaluate_cell(val_rows, c, inc, stochastic=True)
        c["direct_metrics"] = m
        c["recursive_validation_status"] = m.get("recursive_status")
    _persist(root, train["cells"], policy_snapshot())
    reg = build_registry(train["cells"])
    _write_json(root / MODELS_DIR / "registry.json", public_registry(reg))
    freeze = write_pretest_freeze(root)
    bundle = {
        "ok": bool(baseline.get("ok"))
        and bool(v01_struct.get("ok"))
        and bool(defects.get("ok"))
        and bool(freeze.get("ok"))
        and bool(built["public"].get("ok"))
        and bool(series_pub.get("ok")),
        "baseline": baseline,
        "v01_struct": v01_struct,
        "defects": defects,
        "freeze_defects": freeze_def,
        "recon": recon,
        "matrix": matrix,
        "inventory": inv,
        "sequences_public": {**built["public"], "series_meta": series_pub},
        "dataset_status": "BUILT_TRAIN_VALIDATION_HORIZON_ALIGNED",
        "train": train,
        "residuals": residuals,
        "registry": reg,
        "freeze": freeze,
        "engine": {"ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS": "NOT_RUN_UNTIL_OPEN_TEST"},
        "RECURSIVE_ROLLOUT_EVALUATION_STATUS": "VALIDATION_EVALUATED",
        "STOCHASTIC_PATH_EVALUATION_STATUS": "EVALUATED",
        "test_lifecycle": "FROZEN_UNOPENED",
        "assembly": {
            "MARGINAL_MULTI_OUTCOME_ASSEMBLY_CONTRACT_STATUS": "MARGINAL_SOURCE_SPECIFIC_MULTI_OUTCOME_ROLLOUT",
            "demo_outcome_used": False,
        },
    }
    _write_public(root, bundle, final=False)
    print(json.dumps({"phase": "freeze", "n_targets": len(built["rows"]), "n_cells": len(train["cells"])}), flush=True)
    return {
        "ok": bundle["ok"],
        "frozen": True,
        "test_opened": False,
        "artifact_dir": ARTIFACT_DIR,
        "no_publish": no_publish,
    }


def open_test(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    freeze = verify_pretest_freeze(root)
    if not freeze.get("ok"):
        return {"ok": False, "error": "freeze_not_verified", "freeze": freeze}
    mark_test_opened(root)
    cells = json.loads((root / MODELS_DIR / "pre-test-cells.json").read_text(encoding="utf-8"))["cells"]
    split = load_split(root)
    allowed = {sid for sid, rec in split.items() if rec["split_role"] == "test"}
    series, _ = load_series(root, allowed_subjects=allowed)
    built = build_origins(series, split, roles={"test"})
    write_origins(root, built["rows"], TEST_PARQUET)
    test_rows = built["rows"]
    for c in cells:
        inc = increment_cell_for(cells, c)
        hm = evaluate_cell(test_rows, c, inc, stochastic=True)
        c["heldout_metrics"] = hm
        c["one_step_heldout"] = _heldout_one_step(c, hm)
        if c.get("recursive_validation_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED":
            c["recursive_heldout_status"] = (
                "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
                if hm.get("recursive_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
                else "HELDOUT_NOT_CONFIRMED"
            )
        else:
            c["recursive_heldout_status"] = "NOT_PROMOTED_FROM_TEST"
    reg = build_registry(cells)
    engine = run_engine_shadow(root)
    asm = heldout_assembly(test_rows, cells)
    (root / MODELS_DIR / "post-test-cells.json").write_text(
        json.dumps({"cells": cells}, indent=2, default=str) + "\n", encoding="utf-8"
    )
    _write_json(root / MODELS_DIR / "heldout-metrics.json", {"n_cells": len(cells), "test_funnel": built["public"].get("funnel")})
    freeze2 = verify_pretest_freeze(root)
    bundle = {
        "ok": bool(freeze2.get("ok")) and bool(engine.get("ok")),
        "baseline": json.loads((root / ARTIFACT_DIR / "baseline-verification.json").read_text()),
        "v01_struct": json.loads((root / ARTIFACT_DIR / "v01-publication-structure.json").read_text()),
        "defects": json.loads((root / ARTIFACT_DIR / "v01-rollout-defect-reproduction.json").read_text()),
        "freeze_defects": json.loads((root / ARTIFACT_DIR / "v01-freeze-engine-defect-reproduction.json").read_text()),
        "recon": json.loads((root / ARTIFACT_DIR / "v01-acceptance-reconciliation.json").read_text()),
        "matrix": json.loads((root / ARTIFACT_DIR / "v01-foundation-acceptance-matrix.json").read_text()),
        "inventory": json.loads((root / ARTIFACT_DIR / "source-provider-inventory.json").read_text()),
        "sequences_public": {
            **json.loads((root / ARTIFACT_DIR / "rollout-sequence-contract.json").read_text()),
            "test_public": built["public"],
        },
        "dataset_status": "BUILT",
        "train": {
            "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS": "TRAINED_SOURCE_SPECIFIC",
            "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": "VALIDATION_ONLY",
            "cells": cells,
        },
        "residuals": {
            "STOCHASTIC_RESIDUAL_DISTRIBUTION_STATUS": "FITTED_TRAIN_OOF_OR_BASELINE",
            "RESIDUAL_SERIAL_DEPENDENCE_STATUS": "INDEPENDENT_STEP_INNOVATIONS_NO_SERIAL_RESIDUAL_MODEL",
            "public": json.loads((root / ARTIFACT_DIR / "residual-distributions.json").read_text()),
        },
        "registry": reg,
        "freeze": freeze2,
        "engine": engine,
        "RECURSIVE_ROLLOUT_EVALUATION_STATUS": "VALIDATION_AND_HELDOUT_REPORTED",
        "STOCHASTIC_PATH_EVALUATION_STATUS": "EVALUATED",
        "test_lifecycle": "OPENED",
        "assembly": asm,
    }
    _write_public(root, bundle, final=True)
    _update_docs(root)
    return {"ok": bundle["ok"], "artifact_dir": ARTIFACT_DIR, "test_opened": True}


def _update_docs(root: Path) -> None:
    st = json.loads((root / ARTIFACT_DIR / "status-contract.json").read_text(encoding="utf-8"))
    (root / "docs" / "current-stage.md").write_text(
        "\n".join(
            [
                "# Current stage",
                "",
                f"**Stage:** 03 — Unified Source-Aware Natural-History Stochastic Rollout Foundation v{VERSION}",
                "**Phase:** PUBLISHED — security PAUSED",
                f"**Last updated:** {_now()[:10]}",
                "",
                "## Published ZIP (immutable)",
                "",
                f"- `artifacts/external-review/{REVIEW_ZIP}`",
                "- SHA-256: see sidecar after publish-v0.1.1",
                f"- NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS={st.get('NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS')}",
                f"- ONE_STEP_VALIDATION_INCREMENTAL_ACCEPTED_CELL_COUNT={st.get('ONE_STEP_VALIDATION_INCREMENTAL_ACCEPTED_CELL_COUNT')}",
                f"- RECURSIVE_ROLLOUT_VALIDATION_ACCEPTED_CELL_COUNT={st.get('RECURSIVE_ROLLOUT_VALIDATION_ACCEPTED_CELL_COUNT')}",
                f"- INTERVENTION_EFFECT_STATUS=UNAVAILABLE",
                "",
                "v0.1 ZIP remains immutable. Natural history only.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    marker = "## Current stage"
    insert = f"""## Current stage

Current stage: **STAGE 03 — UNIFIED SOURCE-AWARE NATURAL-HISTORY STOCHASTIC ROLLOUT FOUNDATION v{VERSION}**
(PUBLISHED)

Owner override: security stage is `PAUSED_NOT_ACCEPTED_BY_OWNER`; security gates are
`ADVISORY_ONLY` and must not block core development. Authorised Source A clinical-row reads and
canonical/derived writes are enabled. See `docs/owner-priority-override-core-first.md`.

```bash
audit --root . natural-history-rollout run-v0.1.1 --no-publish
audit --root . natural-history-rollout open-test-v0.1.1
audit --root . natural-history-rollout verify-v0.1.1
audit --root . natural-history-rollout publish-v0.1.1
```

Do not reopen the probability stream. Do not overwrite prior review ZIPs.

Do not resume Vault rekey, PGP ceremony, or security FINAL/ACCEPTED without literal
`confirm security stage: <exact scope>`.

Historical Stage 01–02 and prior Stage 03 review ZIPs remain immutable.

"""
    if marker in agents:
        rest = agents.split(marker, 1)[1]
        if "## Stage 01 workflow" in rest:
            rest = rest[rest.index("## Stage 01 workflow") :]
        else:
            rest = ""
        (root / "AGENTS.md").write_text(agents.split(marker, 1)[0] + insert + rest, encoding="utf-8")
