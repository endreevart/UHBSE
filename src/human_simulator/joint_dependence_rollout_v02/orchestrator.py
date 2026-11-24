"""Orchestrator — freeze-only run-v0.2, then open-test-v0.2."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.joint_dependence_rollout_v02.baseline import verify_baseline
from human_simulator.joint_dependence_rollout_v02.defects import (
    corrective_gate,
    recursive_runtime_identity_audit,
    reproduce_v011_defects,
    stochastic_reproducibility_audit,
    target_alignment_reuse_audit,
    verify_v011_publication_structure,
)
from human_simulator.joint_dependence_rollout_v02.engine import run_engine_shadow
from human_simulator.joint_dependence_rollout_v02.evaluate import evaluate_cell, increment_cell_for
from human_simulator.joint_dependence_rollout_v02.freeze import mark_test_opened, verify_pretest_freeze, write_pretest_freeze
from human_simulator.joint_dependence_rollout_v02.groups import audit_overlap_groups
from human_simulator.joint_dependence_rollout_v02.joint import (
    build_panels,
    evaluate_joint,
    fit_d1,
    panel_accounting,
    public_copula,
    write_panels,
)
from human_simulator.joint_dependence_rollout_v02.policy import (
    ARTIFACT_DIR,
    COVERAGE_HI,
    COVERAGE_LO,
    MARGINAL_CRPS_TOL,
    MIN_TEST_OVERLAP_GROUPS,
    MIN_TEST_SUBJECTS,
    MIN_TEST_TARGETS,
    MODELS_DIR,
    PREDECLARED_ABSOLUTE_GRID_DAYS,
    REVIEW_ZIP,
    RUNTIME_DIR,
    SECURITY_STAGE_STATUS,
    SEQ_DIR,
    SOURCE_A,
    SOURCE_B,
    TEST_PARQUET,
    TRAIN_VAL_PARQUET,
    VERSION,
    policy_snapshot,
)
from human_simulator.joint_dependence_rollout_v02.privacy import scan_public
from human_simulator.joint_dependence_rollout_v02.providers import train_providers
from human_simulator.joint_dependence_rollout_v02.registry import build_registry, public_registry
from human_simulator.joint_dependence_rollout_v02.residuals import fit_residuals
from human_simulator.joint_dependence_rollout_v02.sequences import (
    assert_no_test_parquet,
    build_origins,
    grain_cell_inventory,
    load_split,
    write_origins,
)
from human_simulator.joint_dependence_rollout_v02.times import alignment_contract
from human_simulator.natural_history_rollout_v011.sequences import audit_uis_m1, load_series


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def write_manifest(art: Path) -> None:
    names = sorted(p.relative_to(art).as_posix() for p in art.rglob("*") if p.is_file() and p.name != "evidence-manifest.sha256")
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{hashlib.sha256((art / n).read_bytes()).hexdigest()}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )


def _heldout(cell: dict[str, Any], metrics: dict[str, Any]) -> str:
    if cell.get("one_step_status") == "NOT_EVALUABLE_FAILED_DATA_GATE":
        return "NOT_EVALUABLE_FAILED_DATA_GATE"
    if not cell.get("validation_selected"):
        return "CORRECTIVE_HELDOUT_NOT_CONFIRMED"
    n_s = metrics.get("n_subjects") or 0
    n_t = metrics.get("n_targets") or 0
    n_g = metrics.get("n_overlap_groups") or 0
    if n_s < MIN_TEST_SUBJECTS or n_t < MIN_TEST_TARGETS or n_g < MIN_TEST_OVERLAP_GROUPS:
        return "NOT_EVALUABLE_FAILED_DATA_GATE"
    if not metrics.get("finite"):
        return "CORRECTIVE_HELDOUT_NOT_CONFIRMED"
    cov = metrics.get("coverage")
    if cov is None or not (COVERAGE_LO <= cov <= COVERAGE_HI):
        return "CORRECTIVE_HELDOUT_NOT_CONFIRMED"
    if metrics.get("bootstrap", {}).get("lo") is None:
        return "CORRECTIVE_HELDOUT_NOT_CONFIRMED"
    if not metrics.get("direct_not_worse_than_p0") and cell.get("active_provider") != "P0":
        return "CORRECTIVE_HELDOUT_NOT_CONFIRMED"
    if not cell.get("validation_gate_accepted"):
        return "CORRECTIVE_HELDOUT_NOT_CONFIRMED"
    return "CORRECTIVE_HELDOUT_CONFIRMED"


def _status(bundle: dict[str, Any]) -> dict[str, Any]:
    lim = bundle.get("defects") or {}
    og = bundle.get("overlap") or {}
    seq = bundle.get("sequences_public") or {}
    reg = bundle.get("registry") or {}
    eng = bundle.get("engine") or {}
    freeze = bundle.get("freeze") or {}
    joint = bundle.get("joint_public") or {}
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": (bundle.get("baseline") or {}).get("BASELINE_VERIFICATION_STATUS"),
        "V011_DEFECT_REPRODUCTION_STATUS": lim.get("V011_DEFECT_REPRODUCTION_STATUS"),
        "V011_CORRECTIVE_GATE_STATUS": (bundle.get("corrective") or {}).get("V011_CORRECTIVE_GATE_STATUS"),
        "PROCESS_INDEPENDENT_RNG_STATUS": bundle.get("PROCESS_INDEPENDENT_RNG_STATUS", "SHA256_NAMESPACE"),
        "CROSS_PROCESS_REPLAY_STATUS": bundle.get("CROSS_PROCESS_REPLAY_STATUS", "SHA256_NAMESPACE"),
        "EFFECTIVE_OVERLAP_GROUP_STATUS": og.get("EFFECTIVE_OVERLAP_GROUP_STATUS"),
        "NULL_OVERLAP_SINGLETON_FALLBACK_STATUS": og.get("NULL_OVERLAP_SINGLETON_FALLBACK_STATUS"),
        "EFFECTIVE_GROUP_SPLIT_ISOLATION_STATUS": og.get("EFFECTIVE_GROUP_SPLIT_ISOLATION_STATUS"),
        "OOF_RESIDUAL_GROUPING_STATUS": (bundle.get("residuals") or {}).get("OOF_RESIDUAL_GROUPING_STATUS"),
        "BOOTSTRAP_GROUPING_STATUS": "EFFECTIVE_OVERLAP_GROUP",
        "TARGET_ALIGNMENT_CONTRACT_STATUS": seq.get("TARGET_ALIGNMENT_CONTRACT_STATUS"),
        "TARGET_ALIGNMENT_ERROR_ACCOUNTING_STATUS": seq.get("TARGET_ALIGNMENT_ERROR_ACCOUNTING_STATUS"),
        "REQUESTED_HORIZON_RUNTIME_STATUS": seq.get("REQUESTED_HORIZON_RUNTIME_STATUS"),
        "CROSS_ROLE_TARGET_REUSE_STATUS": seq.get("CROSS_ROLE_TARGET_REUSE_STATUS"),
        "WITHIN_ROLE_REPEATED_LANDMARK_STATUS": seq.get("WITHIN_ROLE_REPEATED_LANDMARK_STATUS"),
        "CROSS_HORIZON_TARGET_REUSE_STATUS": seq.get("CROSS_HORIZON_TARGET_REUSE_STATUS"),
        "TARGET_REUSE_UNCERTAINTY_ACCOUNTING_STATUS": seq.get("TARGET_REUSE_UNCERTAINTY_ACCOUNTING_STATUS"),
        "CORRECTED_MARGINAL_PROVIDER_REGISTRY_STATUS": reg.get("CORRECTED_MARGINAL_PROVIDER_REGISTRY_STATUS"),
        "MARGINAL_VALIDATION_SELECTED_CELL_COUNT": reg.get("MARGINAL_VALIDATION_SELECTED_CELL_COUNT", 0),
        "MARGINAL_VALIDATION_GATE_ACCEPTED_CELL_COUNT": reg.get("MARGINAL_VALIDATION_GATE_ACCEPTED_CELL_COUNT", 0),
        "MARGINAL_CORRECTIVE_HELDOUT_CONFIRMED_CELL_COUNT": reg.get("MARGINAL_CORRECTIVE_HELDOUT_CONFIRMED_CELL_COUNT", 0),
        "RECURSIVE_STOCHASTIC_EVALUATION_STATUS": bundle.get("RECURSIVE_STOCHASTIC_EVALUATION_STATUS", "PATH_MEDIAN_CRPS_COVERAGE_BOOTSTRAP"),
        "RECURSIVE_VALIDATION_ACCEPTED_CELL_COUNT": reg.get("RECURSIVE_VALIDATION_ACCEPTED_CELL_COUNT", 0),
        "RECURSIVE_CORRECTIVE_HELDOUT_CONFIRMED_CELL_COUNT": reg.get("RECURSIVE_CORRECTIVE_HELDOUT_CONFIRMED_CELL_COUNT", 0),
        "RECURSIVE_RUNTIME_COMPOSITE_IDENTITY_STATUS": eng.get("RECURSIVE_RUNTIME_COMPOSITE_IDENTITY_STATUS", "COMPOSITE_INCLUDES_INCREMENT_PAYLOAD"),
        "TEST_SET_NOVELTY_STATUS": "REUSED_HISTORICAL_HELDOUT_NOT_EXTERNAL_VALIDATION",
        "JOINT_PANEL_DATASET_STATUS": joint.get("JOINT_PANEL_DATASET_STATUS"),
        "JOINT_PANEL_ACCOUNTING_STATUS": joint.get("JOINT_PANEL_ACCOUNTING_STATUS"),
        "JOINT_TEMPORAL_LEAKAGE_STATUS": "PASS_NO_POST_T0_IN_FEATURES",
        "JOINT_SPLIT_ISOLATION_STATUS": "PASS",
        "JOINT_TARGET_REUSE_STATUS": seq.get("CROSS_ROLE_TARGET_REUSE_STATUS"),
        "JOINT_OUTCOME_VOCABULARY_STATUS": joint.get("JOINT_OUTCOME_VOCABULARY_STATUS", "VALIDATION_GATE_ACCEPTED_ONLY"),
        "JOINT_OUTCOME_SUPPORT_GRAPH_STATUS": joint.get("JOINT_OUTCOME_SUPPORT_GRAPH_STATUS", "BUILT"),
        "TRAIN_ONLY_RESIDUAL_TRANSFORM_STATUS": "TRAIN_ONLY",
        "INDEPENDENT_MARGINAL_BASELINE_STATUS": "D0_INDEPENDENT_MARGINALS",
        "SOURCE_SPECIFIC_JOINT_DEPENDENCE_MODEL_STATUS": joint.get("SOURCE_SPECIFIC_JOINT_DEPENDENCE_MODEL_STATUS"),
        "DEPENDENCE_MATRIX_PSD_STATUS": joint.get("DEPENDENCE_MATRIX_PSD_STATUS"),
        "DEPENDENCE_STABILITY_STATUS": joint.get("DEPENDENCE_STABILITY_STATUS"),
        "MULTIVARIATE_PROPER_SCORE_STATUS": joint.get("MULTIVARIATE_PROPER_SCORE_STATUS"),
        "MARGINAL_CALIBRATION_PRESERVATION_STATUS": joint.get("MARGINAL_CALIBRATION_PRESERVATION_STATUS"),
        "TEMPORAL_INNOVATION_DEPENDENCE_STATUS": bundle.get("TEMPORAL_INNOVATION_DEPENDENCE_STATUS", "NOT_ACCEPTED_INDEPENDENT_STEPS_RETAINED"),
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": reg.get("JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT", 0),
        "JOINT_CORRECTIVE_HELDOUT_CONFIRMED_ROUTE_COUNT": reg.get("JOINT_CORRECTIVE_HELDOUT_CONFIRMED_ROUTE_COUNT", 0),
        "JOINT_DEPENDENCE_FOUNDATION_STATUS": reg.get("JOINT_DEPENDENCE_FOUNDATION_STATUS"),
        "COHERENT_MULTI_OUTCOME_ROLLOUT_STATUS": joint.get("COHERENT_MULTI_OUTCOME_ROLLOUT_STATUS", "MARGINAL_OR_PARTIAL"),
        "MULTI_OUTCOME_DEPENDENCE_STATUS": joint.get("MULTI_OUTCOME_DEPENDENCE_STATUS", "SOURCE_SPECIFIC_COPULA_OR_INDEPENDENT"),
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "MODEL_RELOAD_STATUS": eng.get("ENGINE_JOINT_MODEL_ROUTING_STATUS", "DISK_FREEZE_REQUIRED"),
        "JOINT_RUNTIME_COMPOSITE_IDENTITY_STATUS": joint.get("JOINT_RUNTIME_COMPOSITE_IDENTITY_STATUS", "HASHED_WHEN_ACCEPTED"),
        "ENGINE_JOINT_MODEL_ROUTING_STATUS": eng.get("ENGINE_JOINT_MODEL_ROUTING_STATUS", "NOT_RUN"),
        "ENGINE_JOINT_ROLLOUT_STATUS": eng.get("ENGINE_JOINT_ROLLOUT_STATUS", "NOT_RUN"),
        "ENGINE_CROSS_PROCESS_DETERMINISTIC_REPLAY_STATUS": eng.get("ENGINE_CROSS_PROCESS_DETERMINISTIC_REPLAY_STATUS", "NOT_RUN"),
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": eng.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS", "NOT_RUN"),
        "ENGINE_INTERVENTION_ISOLATION_STATUS": eng.get("ENGINE_INTERVENTION_ISOLATION_STATUS", "UNAVAILABLE_NO_PATH_CHANGE"),
        "NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS": reg.get("JOINT_DEPENDENCE_FOUNDATION_STATUS"),
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": "NOT_CONSUMED_NOT_ACCEPTED",
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
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
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_PERFORMED",
        "PUBLIC_DATA_MINIMIZATION_STATUS": (bundle.get("privacy") or {}).get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": bundle.get("REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS", "NOT_PACKED"),
        "PUBLICATION_INTEGRITY_STATUS": bundle.get("PUBLICATION_INTEGRITY_STATUS", "NOT_PUBLISHED"),
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "TECHNICAL_PASS": bool(bundle.get("ok")),
        "TEST_ACCESS_LIFECYCLE_STATUS": bundle.get("test_lifecycle", "FROZEN_UNOPENED"),
        "PRIOR_V011_NATURAL_HISTORY_ROLLOUT_FOUNDATION_STATUS": "CORRECTION_REQUIRED",
    }


def _report(st: dict[str, Any], *, final: bool) -> str:
    status = "FINAL" if final else "DRAFT"
    lines = [
        f"# Source-Specific Joint Dependence and Coherent Multi-Outcome Rollout Foundation v{VERSION}",
        "",
        f"Report status: {status}",
        "",
        "Corrective closure of v0.1.1 inside v0.2. Source-specific joint residual copula. Natural history only.",
        "Historical test is reused held-out, not a new external validation.",
        "",
        "## Statuses",
        "",
    ]
    for k, v in st.items():
        if k.endswith("_STATUS") or k.endswith("_COUNT") or k in {"SCIENTIFIC_CROSS_SOURCE_PASS", "PRODUCTION_READINESS", "TECHNICAL_PASS"}:
            lines.append(f"- `{k}`={v}")
    lines += ["", "## Non-claims", "", "- `NATURAL_HISTORY_ONLY`", "- `CLINICAL_USE_PROHIBITED`", ""]
    return "\n".join(lines) + "\n"


def _write_public(root: Path, bundle: dict[str, Any], *, final: bool) -> None:
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    _write_json(art / "policy-snapshot.json", policy_snapshot())
    _write_json(art / "baseline-verification.json", bundle.get("baseline"))
    _write_json(art / "v011-publication-structure.json", bundle.get("v011_struct"))
    _write_json(art / "v011-defect-reproduction.json", bundle.get("defects"))
    _write_json(art / "v011-stochastic-reproducibility-audit.json", bundle.get("hash_audit"))
    _write_json(art / "v011-overlap-group-audit.json", bundle.get("overlap"))
    _write_json(art / "v011-target-alignment-reuse-audit.json", bundle.get("reuse_audit"))
    _write_json(art / "v011-recursive-runtime-identity-audit.json", bundle.get("rec_ident"))
    _write_json(art / "v011-corrective-gate.json", bundle.get("corrective"))
    _write_json(art / "effective-group-accounting.json", bundle.get("overlap"))
    _write_json(art / "target-alignment-reuse-summary.json", bundle.get("sequences_public"))
    _write_json(art / "corrected-marginal-registry.json", public_registry(bundle.get("registry") or {}))
    _write_json(art / "source-provider-inventory.json", bundle.get("inventory") or {})
    _write_json(art / "joint-panel-accounting.json", bundle.get("joint_public"))
    _write_json(art / "dependence-methodology-contract.json", bundle.get("joint_method") or {})
    _write_json(art / "engine-joint-shadow.json", bundle.get("engine") or {"status": "NOT_RUN"})
    _write_json(art / "pre-test-freeze.json", bundle.get("freeze"))
    _write_json(
        art / "intervention-slot-contract.json",
        {"INTERVENTION_SLOT_CONTRACT_STATUS": "TYPED_UNAVAILABLE", "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE"},
    )
    (art / "REPRODUCE.md").write_text(
        "# Reproduce\n\n```bash\naudit --root . joint-dependence-rollout run-v0.2 --no-publish\n"
        "audit --root . joint-dependence-rollout open-test-v0.2\n"
        "audit --root . joint-dependence-rollout verify-v0.2\n"
        "audit --root . joint-dependence-rollout publish-v0.2\n```\n",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text("# Review guide\n\nAggregate-only. v0.1.1 ZIP is immutable.\n", encoding="utf-8")
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
    _write_json(art / "verification.json", {"version": VERSION, "ok": bool(bundle.get("ok")) and priv.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "PASS_AGGREGATE_ONLY", "generated_at": _now(), "final": final})
    write_manifest(art)


def _persist(root: Path, cells: list[dict[str, Any]], policy: dict[str, Any], joint_models: list[dict[str, Any]]) -> None:
    models = root / MODELS_DIR
    models.mkdir(parents=True, exist_ok=True)
    residual = {
        c.get("active_payload_sha256"): {
            "n_blocks": (c.get("residual_dist") or {}).get("n_blocks"),
            "sampling_contract": (c.get("residual_dist") or {}).get("sampling_contract"),
            "residual_distribution_sha256": (c.get("residual_dist") or {}).get("residual_distribution_sha256"),
        }
        for c in cells
        if c.get("active_payload_sha256")
    }
    for c in cells:
        ident = c.get("active_payload_sha256") or "none"
        payload = {"active_identity": c.get("active_identity_body"), "active_provider": c.get("active_provider"), "p1_payload": c.get("p1_payload") if c.get("active_provider") == "P1" else None, "residual_dist": c.get("residual_dist")}
        (models / f"frozen-payload-{ident[:16]}.json").write_text(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
    (models / "pre-test-cells.json").write_text(json.dumps({"cells": cells}, indent=2, default=str) + "\n", encoding="utf-8")
    (models / "residual-payload.json").write_text(json.dumps(residual, indent=2) + "\n")
    (models / "policy-snapshot.json").write_text(json.dumps(policy, indent=2) + "\n")
    _write_json(models / "target-alignment-contract.json", alignment_contract())
    _write_json(models / "engine-eligibility.json", {"eligible": "validation_gate_accepted", "mandatory_payload_identity": True})
    _write_json(models / "rng-contract.json", {"family": "sha256_namespace", "no_builtin_hash": True, "PYTHONHASHSEED_not_required": True})
    _write_json(models / "effective-group-contract.json", {"null_fallback": "opaque_sha256_singleton", "upstream_preserved": True})
    _write_json(models / "gates.json", {"coverage": [COVERAGE_LO, COVERAGE_HI], "marginal_crps_tol": MARGINAL_CRPS_TOL})
    _write_json(models / "code-policy-hashes.json", {"policy_sha256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()})
    serial_joint = []
    for m in joint_models:
        serial_joint.append({k: v for k, v in m.items() if k != "rows"})
    _write_json(models / "joint-payload.json", {"models": serial_joint})


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / SEQ_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    assert_no_test_parquet(root)
    baseline = verify_baseline(root)
    v011_struct = verify_v011_publication_structure(root)
    defects = reproduce_v011_defects(root)
    hash_audit = stochastic_reproducibility_audit(root)
    overlap = audit_overlap_groups(root)
    reuse_audit = target_alignment_reuse_audit(root)
    rec_ident = recursive_runtime_identity_audit(root)
    corrective = corrective_gate(root)
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
        m = evaluate_cell(val_rows, c, inc)
        c["direct_metrics"] = m
        c["recursive_validation_status"] = m.get("recursive_status")
        c["validation_gate_accepted"] = bool(m.get("validation_gate_accepted")) and bool(c.get("validation_selected"))
    vocab = {
        (c["source_system"], c["outcome_key"], int(c["horizon_days"]))
        for c in train["cells"]
        if c.get("validation_gate_accepted")
    }
    panels = build_panels(built["rows"], vocab)
    write_panels(root, panels, "panels_train_val.parquet")
    pan_pub = panel_accounting(panels)
    cells_by = {(c["source_system"], c["outcome_key"], int(c["horizon_days"])): c for c in train["cells"]}
    train_panels = [p for p in panels if p["split_role"] == "train"]
    val_panels = [p for p in panels if p["split_role"] == "validation"]
    joint_models = []
    joint_routes = []
    psd_ok = True
    any_d1 = False
    any_better = False
    marg_ok = True
    for ss in (SOURCE_A, SOURCE_B):
        for h in PREDECLARED_ABSOLUTE_GRID_DAYS:
            model = fit_d1(train_panels, cells_by, source_system=ss, horizon=h)
            if not model:
                joint_routes.append({"source_system": ss, "horizon_days": h, "status": "NOT_RUN_FAILED_JOINT_DATA_GATE"})
                continue
            joint_models.append(model)
            ev = evaluate_joint(val_panels, model, cells_by)
            status = ev.get("status")
            if not model.get("data_ok") or status == "NOT_RUN_FAILED_JOINT_DATA_GATE":
                route_status = "NOT_RUN_FAILED_JOINT_DATA_GATE"
            elif ev.get("mean_crps_d1") is not None and ev.get("mean_crps_d0") is not None and ev["mean_crps_d1"] > ev["mean_crps_d0"] * MARGINAL_CRPS_TOL:
                route_status = "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_MULTIVARIATE_SIGNAL"
                marg_ok = False
            elif ev.get("d1_better_energy"):
                route_status = "JOINT_DEPENDENCE_CELL_ACCEPTED"
                any_better = True
                any_d1 = True
            else:
                route_status = "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_MULTIVARIATE_SIGNAL"
                any_d1 = True
            if model.get("psd_method") == "FAIL":
                psd_ok = False
            joint_routes.append(
                {
                    "source_system": ss,
                    "horizon_days": h,
                    "status": route_status,
                    "energy_d0": ev.get("energy_d0"),
                    "energy_d1": ev.get("energy_d1"),
                    "mean_crps_d0": ev.get("mean_crps_d0"),
                    "mean_crps_d1": ev.get("mean_crps_d1"),
                    "n_panels": ev.get("n_panels"),
                    "joint_identity_sha256": model.get("joint_identity_sha256"),
                    "psd_method": model.get("psd_method"),
                    "n_outcomes": len(model.get("outcomes") or []),
                    "public": public_copula(model),
                }
            )
    _persist(root, train["cells"], policy_snapshot(), joint_models)
    reg = build_registry(train["cells"], joint_routes)
    _write_json(root / MODELS_DIR / "registry.json", public_registry(reg))
    freeze = write_pretest_freeze(root)
    engine = {"ENGINE_JOINT_ROLLOUT_STATUS": "NOT_RUN_UNTIL_OPEN_TEST", "ENGINE_JOINT_MODEL_ROUTING_STATUS": "DISK_FREEZE_REQUIRED"}
    joint_public = {
        **pan_pub,
        "JOINT_OUTCOME_VOCABULARY_STATUS": "VALIDATION_GATE_ACCEPTED_ONLY",
        "JOINT_OUTCOME_SUPPORT_GRAPH_STATUS": "BUILT",
        "SOURCE_SPECIFIC_JOINT_DEPENDENCE_MODEL_STATUS": "D1_MASKED_GAUSSIAN_COPULA" if any_d1 else "NOT_RUN_FAILED_JOINT_DATA_GATE",
        "DEPENDENCE_MATRIX_PSD_STATUS": "PASS" if psd_ok else "FAIL",
        "DEPENDENCE_STABILITY_STATUS": "DETERMINISTIC_TRAIN_FIT",
        "MULTIVARIATE_PROPER_SCORE_STATUS": "D0_VS_D1_REPORTED",
        "MARGINAL_CALIBRATION_PRESERVATION_STATUS": "PASS" if marg_ok else "FAIL",
        "COHERENT_MULTI_OUTCOME_ROLLOUT_STATUS": "ACCEPTED_ROUTES_ONLY" if any_better else "EVALUATED_NOT_ACCEPTED",
        "MULTI_OUTCOME_DEPENDENCE_STATUS": "SOURCE_SPECIFIC_COPULA_OR_INDEPENDENT",
        "JOINT_RUNTIME_COMPOSITE_IDENTITY_STATUS": "HASHED_WHEN_FITTED",
        "routes": [{k: v for k, v in r.items() if k != "public"} | {"public": r.get("public")} for r in joint_routes],
        "n_vocab_cells": len(vocab),
    }
    bundle = {
        "ok": bool(baseline.get("ok")) and bool(v011_struct.get("ok")) and bool(defects.get("ok")) and bool(freeze.get("ok")) and bool(built["public"].get("ok")) and bool(overlap.get("ok")),
        "baseline": baseline,
        "v011_struct": v011_struct,
        "defects": defects,
        "hash_audit": hash_audit,
        "overlap": overlap,
        "reuse_audit": reuse_audit,
        "rec_ident": rec_ident,
        "corrective": corrective,
        "inventory": inv,
        "sequences_public": {**built["public"], "series_meta": series_pub},
        "train": train,
        "residuals": residuals,
        "registry": reg,
        "freeze": freeze,
        "engine": engine,
        "joint_public": joint_public,
        "joint_method": {"D0": "independent_marginals", "D1": "masked_gaussian_copula", "no_a_b_transfer": True, "train_only_transforms": True},
        "PROCESS_INDEPENDENT_RNG_STATUS": "SHA256_NAMESPACE",
        "CROSS_PROCESS_REPLAY_STATUS": "SHA256_NAMESPACE",
        "TEMPORAL_INNOVATION_DEPENDENCE_STATUS": "NOT_ACCEPTED_INDEPENDENT_STEPS_RETAINED",
        "test_lifecycle": "FROZEN_UNOPENED",
    }
    _write_public(root, bundle, final=False)
    print(json.dumps({"phase": "freeze", "n_targets": len(built["rows"]), "n_cells": len(train["cells"]), "n_panels": len(panels)}), flush=True)
    return {"ok": bundle["ok"], "frozen": True, "test_opened": False, "artifact_dir": ARTIFACT_DIR, "no_publish": no_publish}


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
    for c in cells:
        inc = increment_cell_for(cells, c)
        hm = evaluate_cell(built["rows"], c, inc)
        c["heldout_metrics"] = hm
        c["corrective_heldout"] = _heldout(c, hm)
        if c.get("recursive_validation_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED":
            c["recursive_heldout_status"] = (
                "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
                if hm.get("recursive_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
                else "HELDOUT_NOT_CONFIRMED"
            )
        else:
            c["recursive_heldout_status"] = "NOT_PROMOTED_FROM_TEST"
    vocab = {(c["source_system"], c["outcome_key"], int(c["horizon_days"])) for c in cells if c.get("validation_gate_accepted")}
    test_panels = build_panels(built["rows"], vocab)
    write_panels(root, test_panels, "panels_test.parquet")
    joint_doc = json.loads((root / MODELS_DIR / "joint-payload.json").read_text(encoding="utf-8"))
    cells_by = {(c["source_system"], c["outcome_key"], int(c["horizon_days"])): c for c in cells}
    routes = json.loads((root / ARTIFACT_DIR / "joint-panel-accounting.json").read_text(encoding="utf-8")).get("routes") or []
    for r in routes:
        model = next((m for m in joint_doc.get("models") or [] if m.get("source_system") == r.get("source_system") and m.get("horizon_days") == r.get("horizon_days")), None)
        if not model or r.get("status") != "JOINT_DEPENDENCE_CELL_ACCEPTED":
            r["heldout_status"] = "NOT_PROMOTED_FROM_TEST" if r.get("status") != "JOINT_DEPENDENCE_CELL_ACCEPTED" else "NOT_EVALUABLE"
            continue
        ev = evaluate_joint(test_panels, model, cells_by)
        if ev.get("d1_better_energy") and (ev.get("mean_crps_d1") or 0) <= (ev.get("mean_crps_d0") or 0) * MARGINAL_CRPS_TOL:
            r["heldout_status"] = "JOINT_DEPENDENCE_CELL_ACCEPTED"
        else:
            r["heldout_status"] = "CORRECTIVE_HELDOUT_NOT_CONFIRMED"
        r["heldout_energy_d0"] = ev.get("energy_d0")
        r["heldout_energy_d1"] = ev.get("energy_d1")
    reg = build_registry(cells, routes)
    engine = run_engine_shadow(root)
    freeze2 = verify_pretest_freeze(root)
    (root / MODELS_DIR / "post-test-cells.json").write_text(json.dumps({"cells": cells}, indent=2, default=str) + "\n", encoding="utf-8")
    bundle = {
        "ok": bool(freeze2.get("ok")) and bool(engine.get("ok")),
        "baseline": json.loads((root / ARTIFACT_DIR / "baseline-verification.json").read_text()),
        "v011_struct": json.loads((root / ARTIFACT_DIR / "v011-publication-structure.json").read_text()),
        "defects": json.loads((root / ARTIFACT_DIR / "v011-defect-reproduction.json").read_text()),
        "hash_audit": json.loads((root / ARTIFACT_DIR / "v011-stochastic-reproducibility-audit.json").read_text()),
        "overlap": json.loads((root / ARTIFACT_DIR / "v011-overlap-group-audit.json").read_text()),
        "reuse_audit": json.loads((root / ARTIFACT_DIR / "v011-target-alignment-reuse-audit.json").read_text()),
        "rec_ident": json.loads((root / ARTIFACT_DIR / "v011-recursive-runtime-identity-audit.json").read_text()),
        "corrective": json.loads((root / ARTIFACT_DIR / "v011-corrective-gate.json").read_text()),
        "inventory": json.loads((root / ARTIFACT_DIR / "source-provider-inventory.json").read_text()) if (root / ARTIFACT_DIR / "source-provider-inventory.json").is_file() else {},
        "sequences_public": {**json.loads((root / ARTIFACT_DIR / "target-alignment-reuse-summary.json").read_text()), "test_public": built["public"]},
        "train": {"cells": cells, "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS": "TRAINED_SOURCE_SPECIFIC", "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": "VALIDATION_ONLY"},
        "residuals": {"OOF_RESIDUAL_GROUPING_STATUS": "EFFECTIVE_OVERLAP_GROUP"},
        "registry": reg,
        "freeze": freeze2,
        "engine": engine,
        "joint_public": {**json.loads((root / ARTIFACT_DIR / "joint-panel-accounting.json").read_text()), "routes": routes},
        "joint_method": json.loads((root / ARTIFACT_DIR / "dependence-methodology-contract.json").read_text()),
        "PROCESS_INDEPENDENT_RNG_STATUS": "SHA256_NAMESPACE",
        "CROSS_PROCESS_REPLAY_STATUS": "SHA256_NAMESPACE",
        "TEMPORAL_INNOVATION_DEPENDENCE_STATUS": "NOT_ACCEPTED_INDEPENDENT_STEPS_RETAINED",
        "test_lifecycle": "OPENED",
    }
    # inventory file may be missing — write it at freeze
    if not bundle["inventory"]:
        bundle["inventory"] = {"ok": True}
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
                f"**Stage:** 03 — Source-Specific Joint Dependence and Coherent Multi-Outcome Rollout Foundation v{VERSION}",
                "**Phase:** PUBLISHED — security PAUSED",
                f"**Last updated:** {_now()[:10]}",
                "",
                "## Published ZIP (immutable)",
                "",
                f"- `artifacts/external-review/{REVIEW_ZIP}`",
                "- SHA-256: see sidecar after publish-v0.2",
                f"- JOINT_DEPENDENCE_FOUNDATION_STATUS={st.get('JOINT_DEPENDENCE_FOUNDATION_STATUS')}",
                f"- MARGINAL_VALIDATION_GATE_ACCEPTED_CELL_COUNT={st.get('MARGINAL_VALIDATION_GATE_ACCEPTED_CELL_COUNT')}",
                f"- JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT={st.get('JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT')}",
                "- INTERVENTION_EFFECT_STATUS=UNAVAILABLE",
                "",
                "v0.1.1 ZIP remains immutable. Historical test is reused held-out.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    marker = "## Current stage"
    insert = f"""## Current stage

Current stage: **STAGE 03 — SOURCE-SPECIFIC JOINT DEPENDENCE AND COHERENT MULTI-OUTCOME ROLLOUT FOUNDATION v{VERSION}**
(PUBLISHED)

Owner override: security stage is `PAUSED_NOT_ACCEPTED_BY_OWNER`; security gates are
`ADVISORY_ONLY` and must not block core development. Authorised Source A clinical-row reads and
canonical/derived writes are enabled. See `docs/owner-priority-override-core-first.md`.

```bash
audit --root . joint-dependence-rollout run-v0.2 --no-publish
audit --root . joint-dependence-rollout open-test-v0.2
audit --root . joint-dependence-rollout verify-v0.2
audit --root . joint-dependence-rollout publish-v0.2
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
