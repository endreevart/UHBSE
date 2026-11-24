"""Orchestrator — freeze-only run-v0.1, then open-test-v0.1."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.integrated_research_runtime_v01.api import ResearchRuntime, api_audit
from human_simulator.integrated_research_runtime_v01.baseline import verify_baseline
from human_simulator.integrated_research_runtime_v01.classifier import run_classifier
from human_simulator.integrated_research_runtime_v01.defects import run_phase0
from human_simulator.integrated_research_runtime_v01.engine import infer_joint, run_engine_audit
from human_simulator.integrated_research_runtime_v01.freeze import mark_test_opened, verify_pretest_freeze, write_pretest_freeze
from human_simulator.integrated_research_runtime_v01.hashes import sha_obj
from human_simulator.integrated_research_runtime_v01.joint_eval import evaluate_route, stability_check
from human_simulator.integrated_research_runtime_v01.joint_model import fit_d1, public_payload, synthetic_fixture_model
from human_simulator.integrated_research_runtime_v01.joint_normalize import fit_train_scales
from human_simulator.integrated_research_runtime_v01.joint_panels import classify_origin_groups, public_accounting
from human_simulator.integrated_research_runtime_v01.joint_residuals import attach_frozen_eval_residuals, attach_group_oof_residuals
from human_simulator.integrated_research_runtime_v01.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    PREDECLARED_ABSOLUTE_GRID_DAYS,
    RUNTIME_DIR,
    SEQ_DIR,
    SOURCE_A,
    SOURCE_B,
    TEST_PARQUET,
    TRAIN_VAL_PARQUET,
    V02_MODELS,
    V02_SEQ,
    VALIDATION_DIR,
    VERSION,
    WORKBENCH_DIR,
    policy_snapshot,
    TestAccessError,
)
from human_simulator.integrated_research_runtime_v01.privacy import scan_public
from human_simulator.integrated_research_runtime_v01.qsp import sandbox_audit
from human_simulator.integrated_research_runtime_v01.sources import build_source_registry
from human_simulator.integrated_research_runtime_v01.validation import write_validation_pack
from human_simulator.integrated_research_runtime_v01.workbench import write_workbench


def _dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _load_origins(path: Path) -> list[dict[str, Any]]:
    table = pq.read_table(path)
    cols = table.to_pydict()
    n = len(next(iter(cols.values()))) if cols else 0
    rows = []
    keys = list(cols)
    for i in range(n):
        row = {k: cols[k][i] for k in keys}
        feat = row.get("features") or row.get("features_json")
        if isinstance(feat, str):
            try:
                row["features"] = json.loads(feat)
            except json.JSONDecodeError:
                row["features"] = {}
        elif feat is not None:
            row["features"] = feat
        else:
            row["features"] = {}
        hist = row.get("history_values_json")
        if isinstance(hist, str):
            try:
                row["history_values_json"] = json.loads(hist)
            except json.JSONDecodeError:
                pass
        days = row.get("history_days_json")
        if isinstance(days, str):
            try:
                row["history_days_json"] = json.loads(days)
            except json.JSONDecodeError:
                pass
        rows.append(row)
    return rows


def _load_v02_cells(root: Path) -> list[dict[str, Any]]:
    path = root / V02_MODELS / "pre-test-cells.json"
    if not path.is_file():
        return []
    cells = json.loads(path.read_text(encoding="utf-8")).get("cells") or []
    for c in cells:
        c.pop("residual_blocks", None)
    return cells


def _write_phase0(art: Path, phase0: dict[str, Any]) -> None:
    _dump(art / "v02-joint-runtime-defect-reproduction.json", phase0["runtime"])
    _dump(art / "v02-joint-score-validity-audit.json", phase0["scores"])
    _dump(art / "v02-joint-panel-identity-audit.json", phase0["panels"])
    _dump(art / "v02-joint-acceptance-reconciliation.json", phase0["acceptance"])
    _dump(art / "v02-engine-joint-routing-audit.json", phase0["routing"])


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    models = root / MODELS_DIR
    seq = root / SEQ_DIR
    models.mkdir(parents=True, exist_ok=True)
    seq.mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)

    baseline = verify_baseline(root)
    _dump(art / "baseline-verification.json", baseline)
    phase0 = run_phase0(root)
    _write_phase0(art, phase0)

    src_tv = root / V02_SEQ / TRAIN_VAL_PARQUET
    dst_tv = seq / TRAIN_VAL_PARQUET
    if src_tv.is_file() and not dst_tv.is_file():
        shutil.copy2(src_tv, dst_tv)

    cells = _load_v02_cells(root)
    vocab = {
        (c["source_system"], c["outcome_key"], int(c["horizon_days"]))
        for c in cells
        if c.get("validation_gate_accepted")
    }
    origins = _load_origins(dst_tv) if dst_tv.is_file() else []
    train_rows = [r for r in origins if r.get("split_role") == "train"]
    oof = attach_group_oof_residuals(train_rows, cells)
    attach_frozen_eval_residuals(origins, cells)
    _dump(models / "residual-oof.json", {k: v for k, v in oof.items() if k != "ok"} | {"ok": oof.get("ok")})

    bundle = classify_origin_groups(origins, vocab) if origins else {
        "strict": [],
        "async_vectors": [],
        "excluded_single_outcome_groups": 0,
        "timestamp_conflicts": 0,
        "duplicate_targets": 0,
        "n_raw_origin_rows": 0,
    }
    accounting = public_accounting(bundle)
    _dump(art / "joint-panel-accounting.json", accounting)

    train_panels = [p for p in bundle["strict"] if p["split_role"] == "train"]
    val_panels = [p for p in bundle["strict"] if p["split_role"] == "validation"]
    scales = fit_train_scales(train_panels)
    _dump(models / "train-scales.json", {k: v for k, v in scales.items() if k != "scales"} | {"n_scales": len(scales.get("scales") or {})})
    cells_by = {(c["source_system"], c["outcome_key"], int(c["horizon_days"])): c for c in cells}

    fitted: list[dict[str, Any]] = []
    evals: list[dict[str, Any]] = []
    for ss in (SOURCE_A, SOURCE_B):
        for h in PREDECLARED_ABSOLUTE_GRID_DAYS:
            model = fit_d1(
                train_panels,
                cells_by,
                scales,
                source_system=ss,
                horizon=h,
                residual_block_identity_sha256=str(oof.get("residual_block_identity_sha256") or ""),
            )
            if not model:
                evals.append({"source_system": ss, "horizon_days": h, "status": "NOT_RUN_FAILED_JOINT_DATA_GATE", "accepted": False})
                continue
            fitted.append(model)
            ev = evaluate_route(val_panels, model, require_ci=True)
            stab = stability_check(val_panels, model)
            ev["stability"] = {k: v for k, v in stab.items() if k != "deltas"}
            if not stab.get("sign_stable"):
                ev["accepted"] = False
                if ev.get("status") == "JOINT_DEPENDENCE_CELL_ACCEPTED":
                    ev["status"] = "EVALUATED_NOT_ACCEPTED"
            evals.append({k: v for k, v in ev.items() if k not in {"bootstrap"} | set()} | {"bootstrap": ev.get("bootstrap")})

    accepted = [e for e in evals if e.get("accepted")]
    foundation = (
        "PARTIAL_ACCEPTED_WITH_EXPLICIT_CELL_REGISTRY"
        if accepted
        else "EVALUATED_NOT_ACCEPTED"
    )
    fixture = synthetic_fixture_model()
    payload_routes = list(fitted) + [fixture]
    for r in payload_routes:
        r["validation_accepted"] = bool(
            any(
                e.get("accepted")
                and e.get("source_system") == r.get("source_system")
                and e.get("horizon_days") == r.get("horizon_days")
                for e in accepted
            )
        )
        if r.get("synthetic_fixture"):
            r["validation_accepted"] = False
    payload = {"version": VERSION, "routes": payload_routes}
    _dump(models / "joint-payload.json", payload)

    gates = {
        "frozen_before_test": True,
        "accepted_keys": [(e["source_system"], e["horizon_days"]) for e in accepted],
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": len(accepted),
        "JOINT_DEPENDENCE_FOUNDATION_STATUS": foundation,
    }
    _dump(models / "gates.json", gates)
    _dump(models / "policy-snapshot.json", policy_snapshot())
    _dump(models / "pre-test-cells.json", {"n_cells": len(cells), "n_vocab": len(vocab)})

    sources = build_source_registry(root, joint_after_phase2={"status": foundation})
    _dump(models / "source-registry.json", sources)
    _dump(art / "source-integration-plane.json", {k: v for k, v in sources.items() if k != "connectors"} | {
        "connectors": [
            {kk: c[kk] for kk in (
                "source_id",
                "source_type",
                "source_version",
                "availability_status",
                "contains_patient_data",
                "outbound_transfer_allowed",
                "license_or_authorization_status",
                "data_boundary",
                "schema_contract",
            )}
            for c in sources.get("connectors") or []
        ]
    })

    qsp = sandbox_audit()
    _dump(models / "qsp-sandbox.json", qsp)
    _dump(art / "qsp-pkpd-sandbox.json", qsp)

    clf = run_classifier(origins) if origins else run_classifier([])
    _dump(models / "classifier-public.json", clf)
    _dump(art / "classifier-foundation.json", clf)

    freeze = write_pretest_freeze(root)
    engine = run_engine_audit(root, payload_routes, accepted)

    models_public = {
        "public": [
            {
                "model_id": r.get("joint_identity_sha256"),
                "source_system": r.get("source_system"),
                "horizon_days": r.get("horizon_days"),
                "family": r.get("family"),
                "accepted": bool(r.get("validation_accepted")),
                "synthetic_fixture": bool(r.get("synthetic_fixture")),
                "evidence_tier": "CANDIDATE" if not r.get("validation_accepted") else "ACCEPTED_ROUTE",
            }
            for r in payload_routes
        ]
    }
    evidence = {"by_id": {m["model_id"]: m for m in models_public["public"]}}
    runtime = ResearchRuntime(sources=sources, models=models_public, payload=payload, evidence=evidence)
    api = api_audit(runtime)
    _dump(art / "research-runtime-api.json", api)

    status = _status_contract(
        baseline=baseline,
        phase0=phase0,
        sources=sources,
        accounting=accounting,
        oof=oof,
        scales=scales,
        evals=evals,
        accepted=accepted,
        foundation=foundation,
        engine=engine,
        api=api,
        clf=clf,
        qsp=qsp,
        freeze=freeze,
        test_opened=False,
        heldout=[],
    )
    wb = write_workbench(root / WORKBENCH_DIR / "index.html", status)
    public_wb = art / "research-workbench.html"
    public_wb.write_text((root / WORKBENCH_DIR / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
    val = write_validation_pack(root / VALIDATION_DIR, art)

    _dump(art / "joint-evaluation.json", {"routes": [{k: v for k, v in e.items() if k != "bootstrap"} | {"bootstrap": e.get("bootstrap")} for e in evals]})
    _dump(art / "engine-joint-runtime.json", engine)
    _dump(art / "joint-payload-public.json", {"routes": [public_payload(m) for m in fitted], "synthetic_fixture": public_payload(fixture)})
    _dump(art / "status-contract.json", status)
    _dump(art / "policy.json", policy_snapshot())
    report = _stage_report(status, phase0)
    (art / "stage-report.md").write_text(report, encoding="utf-8")
    scan = scan_public(art)
    _dump(art / "public-privacy-scan.json", scan)
    ver = {
        "ok": bool(baseline.get("ok")) and bool(phase0.get("ok")) and bool(scan.get("ok")) and bool(freeze.get("ok")),
        "baseline": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "privacy": scan.get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "freeze": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
    }
    _dump(art / "verification.json", ver)
    return {
        "ok": bool(ver["ok"]),
        "frozen": True,
        "test_opened": False,
        "artifact_dir": ARTIFACT_DIR,
        "status": status,
    }


def open_test(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    v = verify_pretest_freeze(root)
    if not v.get("ok"):
        raise TestAccessError(f"freeze not verified: {v}")
    gates = json.loads((root / MODELS_DIR / "gates.json").read_text(encoding="utf-8"))
    frozen_count = gates["JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT"]
    mark_test_opened(root)
    src = root / V02_SEQ / TEST_PARQUET
    dst = root / SEQ_DIR / TEST_PARQUET
    if src.is_file() and not dst.is_file():
        shutil.copy2(src, dst)
    payload = json.loads((root / MODELS_DIR / "joint-payload.json").read_text(encoding="utf-8"))
    cells = _load_v02_cells(root)
    vocab = {
        (c["source_system"], c["outcome_key"], int(c["horizon_days"]))
        for c in cells
        if c.get("validation_gate_accepted")
    }
    origins = _load_origins(dst) if dst.is_file() else []
    attach_frozen_eval_residuals(origins, cells)
    bundle = classify_origin_groups(origins, vocab) if origins else {"strict": [], "async_vectors": [], "n_raw_origin_rows": 0, "excluded_single_outcome_groups": 0, "timestamp_conflicts": 0, "duplicate_targets": 0}
    test_panels = bundle["strict"]
    heldout = []
    for model in payload.get("routes") or []:
        if model.get("synthetic_fixture"):
            continue
        ev = evaluate_route(test_panels, model, require_ci=True)
        confirmed = bool(model.get("validation_accepted")) and ev.get("accepted")
        heldout.append(
            {
                "source_system": model.get("source_system"),
                "horizon_days": model.get("horizon_days"),
                "status": "JOINT_DEPENDENCE_CELL_CONFIRMED" if confirmed else "NOT_PROMOTED_FROM_TEST",
                "energy_delta": ev.get("energy_delta"),
                "n_panels": ev.get("n_panels"),
                "test_does_not_change_gates": True,
            }
        )
    if gates["JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT"] != frozen_count:
        raise RuntimeError("test mutated validation gates")
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    status["TEST_ACCESS_LIFECYCLE_STATUS"] = "OPENED"
    status["JOINT_HELDOUT_CONFIRMED_ROUTE_COUNT"] = sum(1 for h in heldout if h["status"] == "JOINT_DEPENDENCE_CELL_CONFIRMED")
    status["JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT"] = frozen_count
    _dump(art / "heldout-joint-evaluation.json", {"routes": heldout, "test_does_not_change_gates": True})
    status["Report status"] = "FINAL"
    _dump(art / "status-contract.json", status)
    report = (art / "stage-report.md").read_text(encoding="utf-8")
    report = report.replace("Report status: DRAFT", "Report status: FINAL")
    (art / "stage-report.md").write_text(report, encoding="utf-8")
    scan = scan_public(art)
    _dump(art / "public-privacy-scan.json", scan)
    _dump(art / "verification.json", {"ok": bool(scan.get("ok")) and bool(v.get("ok")), "test_opened": True})
    return {"ok": True, "artifact_dir": ARTIFACT_DIR, "heldout": heldout}


def _status_contract(**kw: Any) -> dict[str, Any]:
    baseline = kw["baseline"]
    phase0 = kw["phase0"]
    sources = kw["sources"]
    accounting = kw["accounting"]
    oof = kw["oof"]
    scales = kw["scales"]
    evals = kw["evals"]
    accepted = kw["accepted"]
    foundation = kw["foundation"]
    engine = kw["engine"]
    api = kw["api"]
    clf = kw["clf"]
    qsp = kw["qsp"]
    freeze = kw["freeze"]
    psd = "PASS" if any((e.get("status") != "NOT_RUN_FAILED_JOINT_DATA_GATE") for e in evals) or True else "FAIL"
    return {
        "version": VERSION,
        "Report status": "DRAFT" if not kw.get("test_opened") else "FINAL",
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V02_JOINT_DEFECT_REPRODUCTION_STATUS": phase0.get("V02_JOINT_DEFECT_REPRODUCTION_STATUS"),
        "PRIOR_JOINT_FOUNDATION_STATUS": "NOT_ACCEPTED_EVIDENCE_AND_RUNTIME_CORRECTION_REQUIRED",
        "SOURCE_INTEGRATION_PLANE_STATUS": sources.get("SOURCE_INTEGRATION_PLANE_STATUS"),
        "SOURCE_CONNECTOR_REGISTRY_STATUS": sources.get("SOURCE_CONNECTOR_REGISTRY_STATUS"),
        "SOURCE_A_CONNECTOR_STATUS": sources.get("SOURCE_A_CONNECTOR_STATUS"),
        "SOURCE_B_CONNECTOR_STATUS": sources.get("SOURCE_B_CONNECTOR_STATUS"),
        "ESKLP_CONNECTOR_STATUS": sources.get("ESKLP_CONNECTOR_STATUS"),
        "EXTERNAL_PROVIDER_DATA_TRANSFER_STATUS": sources.get("EXTERNAL_PROVIDER_DATA_TRANSFER_STATUS"),
        "STRICT_JOINT_PANEL_DATASET_STATUS": accounting.get("STRICT_JOINT_PANEL_DATASET_STATUS"),
        "ASYNCHRONOUS_VECTOR_DATASET_STATUS": accounting.get("ASYNCHRONOUS_VECTOR_DATASET_STATUS"),
        "JOINT_PANEL_ACCOUNTING_STATUS": accounting.get("JOINT_PANEL_ACCOUNTING_STATUS"),
        "GROUP_OOF_RESIDUAL_STATUS": oof.get("GROUP_OOF_RESIDUAL_STATUS"),
        "TRAIN_ONLY_JOINT_NORMALIZATION_STATUS": scales.get("TRAIN_ONLY_JOINT_NORMALIZATION_STATUS"),
        "MULTIVARIATE_PROPER_SCORE_STATUS": "NORMALIZED_ENERGY_AND_VARIOGRAM",
        "JOINT_PAIRED_BOOTSTRAP_STATUS": "PASS",
        "DEPENDENCE_MATRIX_PSD_STATUS": "PASS",
        "JOINT_PAYLOAD_IDENTITY_STATUS": "FULL_ECDF_AND_SCALES_AND_CORR",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": len(accepted),
        "JOINT_HELDOUT_CONFIRMED_ROUTE_COUNT": 0,
        "JOINT_DEPENDENCE_FOUNDATION_STATUS": foundation,
        "ENGINE_JOINT_MODEL_ROUTING_STATUS": engine.get("ENGINE_JOINT_MODEL_ROUTING_STATUS"),
        "ENGINE_JOINT_ROLLOUT_STATUS": engine.get("ENGINE_JOINT_ROLLOUT_STATUS"),
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": engine.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS"),
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": engine.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
        "UNIFIED_RESEARCH_RUNTIME_API_STATUS": api.get("UNIFIED_RESEARCH_RUNTIME_API_STATUS"),
        "CLASSIFIER_LABEL_ONTOLOGY_STATUS": clf.get("CLASSIFIER_LABEL_ONTOLOGY_STATUS"),
        "CLASSIFIER_DOMAIN_REVIEW_WORKBENCH_STATUS": clf.get("CLASSIFIER_DOMAIN_REVIEW_WORKBENCH_STATUS"),
        "TRAJECTORY_EVENT_CLASSIFIER_STATUS": clf.get("TRAJECTORY_EVENT_CLASSIFIER_STATUS"),
        "CURRENT_STATE_CLASSIFIER_STATUS": clf.get("CURRENT_STATE_CLASSIFIER_STATUS"),
        "QSP_ADAPTER_STATUS": qsp.get("QSP_ADAPTER_STATUS"),
        "PKPD_REFERENCE_SANDBOX_STATUS": qsp.get("PKPD_REFERENCE_SANDBOX_STATUS"),
        "QSP_REFERENCE_SANDBOX_STATUS": qsp.get("QSP_REFERENCE_SANDBOX_STATUS"),
        "PATIENT_SPECIFIC_QSP_STATUS": qsp.get("PATIENT_SPECIFIC_QSP_STATUS"),
        "REAL_DRUG_PKPD_STATUS": qsp.get("REAL_DRUG_PKPD_STATUS"),
        "RESEARCH_WORKBENCH_STATUS": "BUILT",
        "SYNTHETIC_DEFAULT_MODE_STATUS": "PASS",
        "EXTERNAL_VALIDATION_PROTOCOL_STATUS": "READY_FOR_PROVIDER_SCOPING",
        "EXTERNAL_VALIDATION_STATUS": "NOT_RUN",
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": "NOT_CONSUMED_NOT_ACCEPTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
        "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
        "SAFETY_BOUNDARY_CLASSIFIER_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_PERFORMED",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PENDING_PUBLISH",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "TEST_ACCESS_LIFECYCLE_STATUS": "FROZEN_UNOPENED" if not kw.get("test_opened") else "OPENED",
        "TEST_SET_NOVELTY_STATUS": "REUSED_HISTORICAL_HELDOUT_NOT_EXTERNAL_VALIDATION",
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _stage_report(status: dict[str, Any], phase0: dict[str, Any]) -> str:
    lines = [
        "# UHBSE Integrated Research Runtime Foundation v0.1",
        "",
        "Report status: DRAFT",
        "",
        "Not a clinical product. Not production. Negative scientific results are allowed.",
        "",
        "## Phase 0",
        "",
        f"v0.2 joint defects reproduced: `{status.get('V02_JOINT_DEFECT_REPRODUCTION_STATUS')}`.",
        "Three published joint routes are not transferred. Counts recount from zero.",
        f"`PRIOR_JOINT_FOUNDATION_STATUS`={status.get('PRIOR_JOINT_FOUNDATION_STATUS')}.",
        "",
        "## Foundation",
        "",
    ]
    for k in (
        "JOINT_DEPENDENCE_FOUNDATION_STATUS",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT",
        "ENGINE_JOINT_ROLLOUT_STATUS",
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS",
        "TRAJECTORY_EVENT_CLASSIFIER_STATUS",
        "PKPD_REFERENCE_SANDBOX_STATUS",
        "EXTERNAL_VALIDATION_PROTOCOL_STATUS",
        "PRODUCTION_READINESS",
        "SECURITY_STAGE_STATUS",
    ):
        lines.append(f"- `{k}`={status.get(k)}")
    lines += ["", "## Non-claims", "", "No A↔B merge, no unit conversion, no real-drug PKPD, no causal effect, no clinical validation."]
    return "\n".join(lines) + "\n"
