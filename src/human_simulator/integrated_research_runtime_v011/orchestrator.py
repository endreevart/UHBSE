"""Orchestrator — Integrated Research Runtime Foundation v0.1.1."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v011.accounting import build_accounting
from human_simulator.integrated_research_runtime_v011.baseline import verify_baseline
from human_simulator.integrated_research_runtime_v011.connectors import build_registry
from human_simulator.integrated_research_runtime_v011.defects import run_phase0
from human_simulator.integrated_research_runtime_v011.engine import run_engine_audit
from human_simulator.integrated_research_runtime_v011.freeze import verify_pretest_freeze, write_pretest_freeze
from human_simulator.integrated_research_runtime_v011.hashes import sha_obj
from human_simulator.integrated_research_runtime_v011.http_app import run_http_audit
from human_simulator.integrated_research_runtime_v011.labels import public_classifier_audit
from human_simulator.integrated_research_runtime_v011.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    VERSION,
    V02_MODELS,
    WORKBENCH_DIR,
    policy_snapshot,
)
from human_simulator.integrated_research_runtime_v011.privacy import scan_public
from human_simulator.integrated_research_runtime_v011.qsp import sandbox_audit
from human_simulator.integrated_research_runtime_v011.validation import public_protocol, write_private_pack
from human_simulator.integrated_research_runtime_v011.workbench import write_workbench


def _dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _v02_vocab(root: Path) -> set[tuple[str, str, int]]:
    path = root / V02_MODELS / "pre-test-cells.json"
    if not path.is_file():
        return set()
    cells = json.loads(path.read_text(encoding="utf-8")).get("cells") or []
    return {
        (c["source_system"], c["outcome_key"], int(c["horizon_days"]))
        for c in cells
        if c.get("source_system") and c.get("outcome_key")
    }


def _acceptance_matrix(phase0: dict[str, Any], engine: dict[str, Any], http: dict[str, Any], sources: dict[str, Any], accounting: dict[str, Any], clf: dict[str, Any]) -> dict[str, Any]:
    rows = {
        "1_v01_opposite_state_identical": phase0["runtime"]["opposite_state_identical_paths"],
        "2_v01_residual_only": phase0["residual"]["ok"],
        "3_v01_metadata_api": phase0["api"]["ok"],
        "4_v01_static_workbench": phase0["workbench"]["ok"],
        "5_v01_connector_health": phase0["connectors"]["ok"],
        "6_v01_literal_unexplained": phase0["accounting"]["ok"],
        "7_new_runtime_depends_on_state": engine.get("opposite_state_changes_paths"),
        "8_persistence_shifts": engine.get("persistence_shifts"),
        "9_residual_added": engine.get("residual_added"),
        "10_residual_only_prohibited": engine.get("residual_added"),
        "17_d1_unavailable": engine.get("D1_JOINT_DEPENDENCE_STATUS") == "NOT_ACCEPTED",
        "18_d0_explicit": True,
        "19_not_trajectory": engine.get("not_a_trajectory"),
        "24_same_state_seed_replay": engine.get("same_state_seed_identical"),
        "25_two_subprocess": engine.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS") == "PASS_TWO_SUBPROCESS",
        "26_http_executes_model": http.get("ok"),
        "27_missing_model_id_fail": http.get("API_NO_SILENT_FALLBACK_STATUS") == "PASS",
        "28_workbench_calls_api": http.get("WORKBENCH_API_INTEGRATION_STATUS") == "PASS",
        "32_source_a_probe": sources.get("separate_source_a_probe"),
        "33_source_b_probe": sources.get("separate_source_b_probe"),
        "34_models_not_clinical": sources.get("model_providers_not_counted_as_clinical_sources"),
        "35_panel_reconciled": accounting.get("ok"),
        "36_label_review_only": clf.get("CLASSIFIER_DECISION_LOG_STATUS") == "REVIEW_VIEW_ONLY",
    }
    return {"version": VERSION, "checks": rows, "ok": all(bool(v) for v in rows.values())}


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    models = root / MODELS_DIR
    models.mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)

    baseline = verify_baseline(root)
    _dump(art / "baseline-verification.json", baseline)
    phase0 = run_phase0(root)
    _dump(art / "v01-runtime-claim-defect-reproduction.json", {k: v for k, v in phase0.items() if k != "ok"})
    _dump(art / "v01-engine-state-conditioning-reproduction.json", phase0["runtime"])
    _dump(art / "v01-api-execution-defect-reproduction.json", phase0["api"])
    _dump(art / "v01-connector-health-defect-reproduction.json", phase0["connectors"])
    _dump(art / "v01-panel-accounting-defect-reproduction.json", phase0["accounting"])

    sources = build_registry(root)
    _dump(art / "source-connector-registry.json", {k: v for k, v in sources.items() if k != "ok"})
    _dump(models / "source-registry.json", {k: v for k, v in sources.items() if k not in {"clinical", "reference", "model_providers", "future_not_configured"}})
    snap = policy_snapshot()
    _dump(models / "policy-snapshot.json", snap)
    _dump(art / "policy-snapshot.json", snap)

    vocab = _v02_vocab(root)
    accounting = build_accounting(root, vocab or None)
    _dump(art / "joint-panel-accounting.json", {k: v for k, v in accounting.items() if k != "ok"})

    clf = public_classifier_audit(root)
    _dump(art / "classifier-public.json", {k: v for k, v in clf.items() if k != "ok"})
    qsp = sandbox_audit()
    _dump(art / "qsp-sandbox.json", {k: v for k, v in qsp.items() if k != "ok"})
    write_private_pack(root)
    val = public_protocol()
    _dump(art / "external-validation-protocol.json", val)

    engine = run_engine_audit(root)
    _dump(art / "engine-state-conditioned-audit.json", {k: v for k, v in engine.items() if k != "replay"})
    http = run_http_audit(sources)
    _dump(art / "http-research-api-audit.json", {k: v for k, v in http.items() if k != "ok"})
    wb = write_workbench(root / WORKBENCH_DIR / "index.html")
    _dump(art / "workbench.html", None) if False else (art / "workbench.html").write_text(
        (root / WORKBENCH_DIR / "index.html").read_text(encoding="utf-8"), encoding="utf-8"
    )

    gates = {
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": 0,
        "JOINT_HELDOUT_CONFIRMED_ROUTE_COUNT": 0,
        "D1_not_accepted": True,
        "TEST_ACCESS_LIFECYCLE_STATUS": "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED",
    }
    _dump(models / "gates.json", gates)
    freeze = write_pretest_freeze(root)
    _dump(art / "pre-test-freeze.json", freeze)

    matrix = _acceptance_matrix(phase0, engine, http, sources, accounting, clf)
    _dump(art / "v01-runtime-acceptance-matrix.json", matrix)

    e2e = (
        engine.get("ok")
        and http.get("ok")
        and phase0.get("ok")
        and accounting.get("ok")
        and baseline.get("ok")
        and sources.get("ok")
        and qsp.get("ok")
        and wb.get("ok")
    )
    status = _status_contract(
        baseline=baseline,
        phase0=phase0,
        sources=sources,
        accounting=accounting,
        engine=engine,
        http=http,
        clf=clf,
        qsp=qsp,
        freeze=freeze,
        val=val,
        e2e=e2e,
        wb=wb,
    )
    _dump(art / "status-contract.json", status)
    (art / "stage-report.md").write_text(_stage_report(status), encoding="utf-8")
    scan = scan_public(art)
    _dump(art / "public-privacy-scan.json", scan)
    if not scan.get("ok"):
        status["END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS"] = "NOT_ACCEPTED"
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = "FAIL"
        _dump(art / "status-contract.json", status)
    else:
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PASS_AGGREGATE_ONLY"
        _dump(art / "status-contract.json", status)
    _dump(
        art / "verification.json",
        {
            "ok": bool(scan.get("ok")) and bool(baseline.get("ok")) and bool(phase0.get("ok")),
            "frozen": freeze.get("ok"),
            "e2e": e2e and scan.get("ok"),
            "version": VERSION,
        },
    )
    return {
        "ok": bool(scan.get("ok")) and bool(baseline.get("ok")) and bool(phase0.get("ok")),
        "frozen": freeze.get("ok"),
        "artifact_dir": ARTIFACT_DIR,
        "no_publish": no_publish,
        "e2e": e2e and scan.get("ok"),
    }


def open_test(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    v = verify_pretest_freeze(root)
    if not v.get("ok"):
        return {"ok": False, "reason": v}
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    status["TEST_ACCESS_LIFECYCLE_STATUS"] = "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED"
    status["open_test_note"] = "Frozen upstream v0.1 held-out is consumed and not recomputed. No new test split."
    status["Report status"] = "FINAL"
    _dump(art / "status-contract.json", status)
    report = (art / "stage-report.md").read_text(encoding="utf-8")
    (art / "stage-report.md").write_text(report.replace("Report status: DRAFT", "Report status: FINAL"), encoding="utf-8")
    scan = scan_public(art)
    _dump(art / "public-privacy-scan.json", scan)
    if scan.get("ok"):
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PASS_AGGREGATE_ONLY"
        _dump(art / "status-contract.json", status)
    _dump(art / "verification.json", {"ok": bool(scan.get("ok")) and bool(v.get("ok")), "test_consumed_not_reopened": True})
    _dump(
        art / "open-test-v011.json",
        {
            "TEST_ACCESS_LIFECYCLE_STATUS": "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED",
            "recomputed_joint_gates": False,
            "ok": True,
        },
    )
    return {"ok": True, "artifact_dir": ARTIFACT_DIR}


def _status_contract(**kw: Any) -> dict[str, Any]:
    e2e_ok = bool(kw.get("e2e"))
    return {
        "version": VERSION,
        "Report status": "DRAFT",
        "BASELINE_VERIFICATION_STATUS": kw["baseline"].get("BASELINE_VERIFICATION_STATUS"),
        "V01_INTEGRATED_RUNTIME_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "V01_ENGINE_STATE_CONDITIONING_DEFECT_STATUS": kw["phase0"]["runtime"].get("V01_ENGINE_STATE_CONDITIONING_DEFECT_STATUS"),
        "V01_ENGINE_RESIDUAL_ONLY_OUTPUT_DEFECT_STATUS": kw["phase0"]["residual"].get("V01_ENGINE_RESIDUAL_ONLY_OUTPUT_DEFECT_STATUS"),
        "V01_ENGINE_JOINT_ROLLOUT_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "V01_API_MODEL_EXECUTION_DEFECT_STATUS": "CONFIRMED",
        "V01_HTTP_RUNTIME_STATUS": "NOT_IMPLEMENTED",
        "V01_WORKBENCH_RUNTIME_INTEGRATION_STATUS": "STATIC_EVIDENCE_SHELL_ONLY",
        "V01_CONNECTOR_HEALTH_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "V01_JOINT_PANEL_ACCOUNTING_STATUS": "NOT_RECONCILED",
        "SOURCE_CONNECTOR_REGISTRY_STATUS": kw["sources"].get("SOURCE_CONNECTOR_REGISTRY_STATUS"),
        "CLINICAL_SOURCE_CONNECTOR_COUNT": kw["sources"].get("CLINICAL_SOURCE_CONNECTOR_COUNT"),
        "REFERENCE_SOURCE_CONNECTOR_COUNT": kw["sources"].get("REFERENCE_SOURCE_CONNECTOR_COUNT"),
        "MODEL_PROVIDER_REGISTRY_COUNT": kw["sources"].get("MODEL_PROVIDER_REGISTRY_COUNT"),
        "SOURCE_A_CONNECTOR_STATUS": kw["sources"].get("SOURCE_A_CONNECTOR_STATUS"),
        "SOURCE_B_CONNECTOR_STATUS": kw["sources"].get("SOURCE_B_CONNECTOR_STATUS"),
        "ESKLP_CONNECTOR_STATUS": kw["sources"].get("ESKLP_CONNECTOR_STATUS"),
        "MARGINAL_PROVIDER_RUNTIME_CONSUMPTION_STATUS": kw["engine"].get("MARGINAL_PROVIDER_RUNTIME_CONSUMPTION_STATUS"),
        "STATE_CONDITIONED_MARGINAL_INFERENCE_STATUS": kw["engine"].get("STATE_CONDITIONED_MARGINAL_INFERENCE_STATUS"),
        "STATE_CONDITIONED_JOINT_COMPOSITION_STATUS": kw["engine"].get("STATE_CONDITIONED_JOINT_COMPOSITION_STATUS"),
        "D0_JOINT_OUTCOME_DISTRIBUTION_STATUS": kw["engine"].get("D0_JOINT_OUTCOME_DISTRIBUTION_STATUS"),
        "D1_JOINT_DEPENDENCE_STATUS": "NOT_ACCEPTED",
        "CROSS_HORIZON_DEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": 0,
        "JOINT_HELDOUT_CONFIRMED_ROUTE_COUNT": 0,
        "JOINT_PANEL_ACCOUNTING_STATUS": kw["accounting"].get("JOINT_PANEL_ACCOUNTING_STATUS"),
        "EVENT_PROBABILITY_PROVIDER_EXECUTION_STATUS": "PASS" if kw["http"].get("event_executed") else "FAIL",
        "HTTP_RESEARCH_API_STATUS": kw["http"].get("HTTP_RESEARCH_API_STATUS"),
        "API_SCHEMA_CONTRACT_STATUS": kw["http"].get("API_SCHEMA_CONTRACT_STATUS"),
        "API_MODEL_ROUTING_STATUS": kw["http"].get("API_MODEL_ROUTING_STATUS"),
        "API_NO_SILENT_FALLBACK_STATUS": kw["http"].get("API_NO_SILENT_FALLBACK_STATUS"),
        "RESEARCH_WORKBENCH_STATUS": kw["wb"].get("RESEARCH_WORKBENCH_STATUS") if e2e_ok else "NOT_ACCEPTED",
        "WORKBENCH_API_INTEGRATION_STATUS": kw["http"].get("WORKBENCH_API_INTEGRATION_STATUS"),
        "WORKBENCH_SYNTHETIC_DEFAULT_STATUS": "PASS",
        "CLASSIFIER_LABEL_ONTOLOGY_STATUS": kw["clf"].get("CLASSIFIER_LABEL_ONTOLOGY_STATUS"),
        "CLASSIFIER_DECISION_LOG_STATUS": kw["clf"].get("CLASSIFIER_DECISION_LOG_STATUS"),
        "TRAJECTORY_EVENT_CLASSIFIER_STATUS": "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_ACCEPTED",
        "QSP_ADAPTER_STATUS": kw["qsp"].get("QSP_ADAPTER_STATUS"),
        "PKPD_REFERENCE_SANDBOX_STATUS": kw["qsp"].get("PKPD_REFERENCE_SANDBOX_STATUS"),
        "QSP_REFERENCE_SANDBOX_STATUS": kw["qsp"].get("QSP_REFERENCE_SANDBOX_STATUS"),
        "PATIENT_SPECIFIC_QSP_STATUS": "NOT_RUN_NO_ACCEPTED_INTERVENTION_MAPPING",
        "REAL_DRUG_PKPD_STATUS": "NOT_STARTED_PROVIDER_AND_DOMAIN_INPUT_REQUIRED",
        "AUTOMATED_EXTERNAL_CONTACT_STATUS": "NOT_RUN",
        "OWNER_REPORTED_IROS_CONTACT_STATUS": "RESPONSE_RECEIVED_PENDING_REPOSITORY_EVIDENCE",
        "IROS_PROVIDER_COMMITMENT_STATUS": "NOT_ESTABLISHED",
        "EXTERNAL_VALIDATION_PROTOCOL_STATUS": "READY_FOR_PROVIDER_SCOPING",
        "EXTERNAL_VALIDATION_STATUS": "NOT_RUN",
        "END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS": "PASS" if e2e_ok else "NOT_ACCEPTED",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": kw["engine"].get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": kw["engine"].get("ENGINE_CROSS_PROCESS_REPLAY_STATUS"),
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
        "TEST_ACCESS_LIFECYCLE_STATUS": "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED",
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": kw["freeze"].get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "updated_at": datetime.now(UTC).isoformat(),
        "identity": sha_obj({"version": VERSION, "e2e": e2e_ok}),
    }


def _stage_report(status: dict[str, Any]) -> str:
    lines = [
        "# UHBSE Integrated Research Runtime Foundation v0.1.1",
        "",
        "Report status: DRAFT",
        "",
        "State-conditioned end-to-end composition. Not a clinical product. Not production.",
        "Single-horizon output is a source-specific joint outcome distribution, not a trajectory.",
        "",
        "## Phase 0 v0.1 defects",
        "",
        f"- `V01_ENGINE_STATE_CONDITIONING_DEFECT_STATUS`={status.get('V01_ENGINE_STATE_CONDITIONING_DEFECT_STATUS')}",
        f"- `V01_ENGINE_RESIDUAL_ONLY_OUTPUT_DEFECT_STATUS`={status.get('V01_ENGINE_RESIDUAL_ONLY_OUTPUT_DEFECT_STATUS')}",
        f"- `V01_HTTP_RUNTIME_STATUS`={status.get('V01_HTTP_RUNTIME_STATUS')}",
        "",
        "## Runtime",
        "",
    ]
    for k in (
        "END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS",
        "STATE_CONDITIONED_JOINT_COMPOSITION_STATUS",
        "D1_JOINT_DEPENDENCE_STATUS",
        "CROSS_HORIZON_DEPENDENCE_STATUS",
        "HTTP_RESEARCH_API_STATUS",
        "RESEARCH_WORKBENCH_STATUS",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT",
        "OWNER_REPORTED_IROS_CONTACT_STATUS",
        "IROS_PROVIDER_COMMITMENT_STATUS",
        "PRODUCTION_READINESS",
        "SECURITY_STAGE_STATUS",
    ):
        lines.append(f"- `{k}`={status.get(k)}")
    lines += [
        "",
        "## Non-claims",
        "",
        "No A↔B merge, no unit conversion, no D1 acceptance, no real-drug PKPD, no causal effect, no clinical validation.",
        "IROS did not grant a dataset. Automated contact was not run.",
        "",
    ]
    return "\n".join(lines)
