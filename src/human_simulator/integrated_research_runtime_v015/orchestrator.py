"""Orchestrator — Integrated Research Runtime Foundation v0.1.5."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v015.accounting import build_accounting
from human_simulator.integrated_research_runtime_v015.baseline import verify_baseline
from human_simulator.integrated_research_runtime_v015.connectors import build_registry
from human_simulator.integrated_research_runtime_v015.defects import run_phase0
from human_simulator.integrated_research_runtime_v015.engine import run_engine_audit
from human_simulator.integrated_research_runtime_v015.freeze import verify_pretest_freeze, write_pretest_freeze
from human_simulator.integrated_research_runtime_v015.hashes import sha256_file, sha_obj
from human_simulator.integrated_research_runtime_v015.http_app import run_http_audit
from human_simulator.integrated_research_runtime_v015.labels import public_classifier_audit
from human_simulator.integrated_research_runtime_v015.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    PRIOR_ZIPS,
    RUNTIME_DIR,
    VERSION,
    V02_MODELS,
    V014_EXPECTED_SHA256,
    WORKBENCH_DIR,
    policy_snapshot,
)
from human_simulator.integrated_research_runtime_v015.presence_audit import missing_vs_null_direct, run_direct_presence_audit
from human_simulator.integrated_research_runtime_v015.privacy import scan_public
from human_simulator.integrated_research_runtime_v015.qsp import sandbox_audit
from human_simulator.integrated_research_runtime_v015.validation import public_protocol, write_private_pack
from human_simulator.integrated_research_runtime_v015.workbench import write_workbench


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


def _acceptance_matrix(
    phase0: dict[str, Any],
    engine: dict[str, Any],
    http: dict[str, Any],
    sources: dict[str, Any],
    accounting: dict[str, Any],
    clf: dict[str, Any],
    qsp: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    defects = {int(d["id"]): d for d in phase0.get("defects") or []}
    rows = {
        "p0_1_defect_reproduced": phase0.get("n_reproduced") == 1 and phase0.get("ok"),
        "p0_falsey_future_field_bypass": bool((defects.get(1) or {}).get("reproduced")),
        "baseline_v014_sha": baseline.get("BASELINE_VERIFICATION_STATUS") == "PASS",
        "falsey_future_field_rejection": http.get("FALSEY_FUTURE_FIELD_REJECTION_STATUS") == "PASS",
        "future_field_presence_contract": http.get("FUTURE_FIELD_PRESENCE_CONTRACT_STATUS") == "PASS",
        "http_explicit_field_presence": http.get("HTTP_EXPLICIT_FIELD_PRESENCE_STATUS") == "PASS",
        "lep_route_boundary": http.get("LEP_ROUTE_BOUNDARY_STATUS") == "PASS",
        "state_conditioned_lep_not_implemented": http.get("STATE_CONDITIONED_LEP_STATUS") == "NOT_IMPLEMENTED",
        "synthetic_e2e": engine.get("SYNTHETIC_E2E_STATUS") == "PASS",
        "timestamp_verified": engine.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") == "PASS",
        "declared_summary": engine.get("DECLARED_PRE_T0_SUMMARY_STATUS") == "PASS",
        "source_namespace_binding": engine.get("SOURCE_NAMESPACE_BINDING_STATUS") == "PASS",
        "identity_complete": engine.get("PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS") == "PASS",
        "source_a_frozen": engine.get("SOURCE_A_FROZEN_INFERENCE_STATUS") == "PASS",
        "source_b_frozen": engine.get("SOURCE_B_FROZEN_INFERENCE_STATUS") == "PASS",
        "exact_identity": engine.get("EXACT_PROVIDER_IDENTITY_STATUS") == "PASS",
        "no_silent_fallback": engine.get("NO_SILENT_PROVIDER_FALLBACK_STATUS") == "PASS",
        "d1_unavailable": engine.get("D1_JOINT_DEPENDENCE_STATUS") == "NOT_ACCEPTED",
        "cross_horizon_not_established": engine.get("CROSS_HORIZON_DEPENDENCE_STATUS") == "NOT_ESTABLISHED",
        "two_subprocess_replay": engine.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS") == "PASS_TWO_SUBPROCESS",
        "http_typed": http.get("HTTP_TYPED_SCHEMA_STATUS") == "PASS",
        "http_deterministic_error": http.get("HTTP_DETERMINISTIC_ERROR_STATUS") == "PASS",
        "http_no_cors_wildcard": bool(http.get("no_cors_wildcard")),
        "http_timestamp_verified": bool(http.get("timestamp_verified_http")),
        "clinical_source_system_count_2": sources.get("CLINICAL_SOURCE_SYSTEM_COUNT") == 2,
        "unified_not_third_source": bool(sources.get("unified_layer_not_a_third_clinical_source")),
        "filtered_reads": sources.get("SOURCE_CONNECTOR_FILTERED_READ_STATUS") == "PASS",
        "row_accounting": accounting.get("JOINT_PANEL_ROW_ACCOUNTING_STATUS") == "RECONCILED",
        "label_review_only": clf.get("CLASSIFIER_DECISION_LOG_STATUS") == "REVIEW_VIEW_ONLY",
        "qsp_unavailable": bool(qsp.get("INTERVENTION_EFFECT_UNAVAILABLE")),
        "browser_pass": http.get("WORKBENCH_BROWSER_INTEGRATION_STATUS") == "PASS",
        "frozen_lep_reference_probe": http.get("FROZEN_LEP_REFERENCE_PROBE_STATUS") == "PASS",
        "two_state_lep_abstains": bool((http.get("two_state_lep") or {}).get("ok")),
        "falsey_future_field_rejection": http.get("FALSEY_FUTURE_FIELD_REJECTION_STATUS") == "PASS",
        "future_field_presence_contract": http.get("FUTURE_FIELD_PRESENCE_CONTRACT_STATUS") == "PASS",
        "http_explicit_field_presence": http.get("HTTP_EXPLICIT_FIELD_PRESENCE_STATUS") == "PASS",
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
    _dump(art / "prior-zip-sha-before.json", baseline.get("prior_sha_before") or {})

    phase0 = run_phase0(root)
    _dump(art / "v014-falsey-future-field-defect-reproduction.json", {k: v for k, v in phase0.items() if k != "ok"})
    names = {
        1: "v014-falsey-future-field-bypass-defect.json",
    }
    for block in phase0.get("defects") or []:
        fname = names.get(int(block["id"]))
        if fname:
            _dump(art / fname, block)

    direct_presence = run_direct_presence_audit()
    _dump(art / "direct-api-future-field-presence-audit.json", {k: v for k, v in direct_presence.items() if k != "cases"})
    _dump(art / "direct-api-future-field-presence-matrix.json", direct_presence)
    _dump(art / "missing-vs-null-direct.json", missing_vs_null_direct())

    sources = build_registry(root)
    _dump(art / "source-connector-registry.json", {k: v for k, v in sources.items() if k != "ok"})
    _dump(
        models / "source-registry.json",
        {
            k: v
            for k, v in sources.items()
            if k not in {"clinical", "reference", "model_providers", "future_not_configured", "materialized_layers"}
        },
    )
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
    _dump(
        art / "engine-state-conditioned-audit.json",
        {k: v for k, v in engine.items() if k not in {"replay", "paths"}},
    )
    _dump(
        art / "frozen-provider-identities.json",
        {
            "source_a": engine.get("frozen_a_cells_public"),
            "source_b": engine.get("frozen_b_cells_public"),
            "SOURCE_A_FROZEN_INFERENCE_STATUS": engine.get("SOURCE_A_FROZEN_INFERENCE_STATUS"),
            "SOURCE_B_FROZEN_INFERENCE_STATUS": engine.get("SOURCE_B_FROZEN_INFERENCE_STATUS"),
        },
    )
    http = run_http_audit(root, sources)
    _dump(art / "live-http-future-field-presence-audit.json", http.get("presence_http") or {})
    _dump(art / "live-http-future-field-presence-matrix.json", {"cases": http.get("presence_http_cases") or []})
    _dump(art / "browser-audit.json", http.get("browser") or {})
    falsey_ok = (
        direct_presence.get("FALSEY_FUTURE_FIELD_REJECTION_STATUS") == "PASS"
        and http.get("FALSEY_FUTURE_FIELD_REJECTION_STATUS") == "PASS"
    )
    presence_ok = direct_presence.get("FUTURE_FIELD_PRESENCE_CONTRACT_STATUS") == "PASS" and http.get(
        "FUTURE_FIELD_PRESENCE_CONTRACT_STATUS"
    ) == "PASS"
    http = {
        **http,
        "FALSEY_FUTURE_FIELD_REJECTION_STATUS": "PASS" if falsey_ok else "FAIL",
        "FUTURE_FIELD_PRESENCE_CONTRACT_STATUS": "PASS" if presence_ok else "FAIL",
    }
    _dump(
        art / "http-research-api-audit.json",
        {k: v for k, v in http.items() if k not in {"ok", "presence_http_cases"}},
    )
    _dump(
        art / "field-presence-contract-matrix.json",
        {
            "direct_ok": direct_presence.get("ok"),
            "http_ok": (http.get("presence_http") or {}).get("ok"),
            "FALSEY_FUTURE_FIELD_REJECTION_STATUS": http.get("FALSEY_FUTURE_FIELD_REJECTION_STATUS"),
            "FUTURE_FIELD_PRESENCE_CONTRACT_STATUS": http.get("FUTURE_FIELD_PRESENCE_CONTRACT_STATUS"),
            "HTTP_EXPLICIT_FIELD_PRESENCE_STATUS": http.get("HTTP_EXPLICIT_FIELD_PRESENCE_STATUS"),
            "missing_vs_null": missing_vs_null_direct(),
            "note": "Presence is original request keys / raw HTTP JSON keys. Truthiness is not used.",
        },
    )
    wb = write_workbench(root / WORKBENCH_DIR / "index.html")
    (art / "workbench.html").write_text(
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

    matrix = _acceptance_matrix(phase0, engine, http, sources, accounting, clf, qsp, baseline)
    _dump(art / "v015-runtime-acceptance-matrix.json", matrix)

    browser_status = http.get("WORKBENCH_BROWSER_INTEGRATION_STATUS") or "NOT_VERIFIED"
    syn_ok = engine.get("SYNTHETIC_E2E_STATUS") == "PASS"
    a_ok = engine.get("SOURCE_A_FROZEN_INFERENCE_STATUS") == "PASS"
    b_ok = engine.get("SOURCE_B_FROZEN_INFERENCE_STATUS") == "PASS"
    ts_ok = engine.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") == "PASS" and bool(http.get("timestamp_verified_http"))
    e2e_gates = {
        "timestamp_verified_path": ts_ok,
        "source_identity": engine.get("SOURCE_NAMESPACE_BINDING_STATUS") == "PASS"
        and http.get("SOURCE_NAMESPACE_BINDING_STATUS") == "PASS",
        "complete_identities": engine.get("PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS") == "PASS",
        "frozen_a": a_ok,
        "frozen_b": b_ok,
        "http": http.get("HTTP_TYPED_SCHEMA_STATUS") == "PASS" and http.get("HTTP_DETERMINISTIC_ERROR_STATUS") == "PASS",
        "browser": browser_status == "PASS",
        "exact_identity": engine.get("EXACT_PROVIDER_IDENTITY_STATUS") == "PASS",
        "no_silent_fallback": engine.get("NO_SILENT_PROVIDER_FALLBACK_STATUS") == "PASS",
        "phase0": bool(phase0.get("ok")),
        "baseline": bool(baseline.get("ok")),
        "d1_not_accepted": engine.get("D1_JOINT_DEPENDENCE_STATUS") == "NOT_ACCEPTED",
        "replay": engine.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS") == "PASS_TWO_SUBPROCESS",
        "frozen_http": bool(http.get("frozen_http_ok")),
        "state_conditioned_lep_not_implemented": http.get("STATE_CONDITIONED_LEP_STATUS") == "NOT_IMPLEMENTED",
        "lep_route_boundary": http.get("LEP_ROUTE_BOUNDARY_STATUS") == "PASS",
        "falsey_future_field_rejection": http.get("FALSEY_FUTURE_FIELD_REJECTION_STATUS") == "PASS",
        "future_field_presence_contract": http.get("FUTURE_FIELD_PRESENCE_CONTRACT_STATUS") == "PASS",
        "http_explicit_field_presence": http.get("HTTP_EXPLICIT_FIELD_PRESENCE_STATUS") == "PASS",
    }
    e2e_blockers = [k for k, v in e2e_gates.items() if not v]
    e2e = syn_ok and not e2e_blockers
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
        e2e_blockers=e2e_blockers,
        e2e_gates=e2e_gates,
        wb=wb,
        browser_status=browser_status,
    )
    _dump(art / "status-contract.json", status)
    (art / "stage-report.md").write_text(_stage_report(status), encoding="utf-8")
    _write_current_stage(root, status)
    external = root / "artifacts" / "external-review"
    after_priors = {
        label: sha256_file(external / name) if (external / name).is_file() else ""
        for label, (name, _exp) in PRIOR_ZIPS.items()
    }
    priors_unchanged = after_priors == (baseline.get("prior_sha_before") or {})
    v014_unchanged = after_priors.get("irr_v014") == V014_EXPECTED_SHA256
    _dump(art / "prior-zip-sha-after.json", after_priors)
    if not priors_unchanged or not v014_unchanged:
        status["END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS"] = "NOT_ACCEPTED"
        status["e2e_blockers"] = list(status.get("e2e_blockers") or []) + ["prior_zip_sha_changed"]
        _dump(art / "status-contract.json", status)
        e2e = False
    tests_proc = subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "pytest",
            "-q",
            "tests/test_integrated_research_runtime_v015_unit.py",
            "tests/test_integrated_research_runtime_v015_contracts.py",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    tests_out = (tests_proc.stdout or "") + (tests_proc.stderr or "")
    tests_ok = tests_proc.returncode == 0
    _dump(
        art / "tests-report.json",
        {
            "ok": tests_ok,
            "returncode": tests_proc.returncode,
            "output_tail": tests_out[-4000:],
            "files": [
                "tests/test_integrated_research_runtime_v015_unit.py",
                "tests/test_integrated_research_runtime_v015_contracts.py",
            ],
        },
    )
    if not tests_ok:
        status["END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS"] = "NOT_ACCEPTED"
        status["e2e_blockers"] = list(status.get("e2e_blockers") or []) + ["unit_contract_tests"]
        _dump(art / "status-contract.json", status)
        e2e = False
    scan = scan_public(art)
    _dump(art / "public-privacy-scan.json", scan)
    if not scan.get("ok"):
        status["END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS"] = "NOT_ACCEPTED"
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = "FAIL"
        _dump(art / "status-contract.json", status)
    else:
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PASS_AGGREGATE_ONLY"
        _dump(art / "status-contract.json", status)
    ver_ok = (
        bool(scan.get("ok"))
        and bool(baseline.get("ok"))
        and bool(phase0.get("ok"))
        and bool(matrix.get("ok"))
        and priors_unchanged
        and v014_unchanged
        and tests_ok
    )
    _dump(
        art / "verification.json",
        {
            "ok": ver_ok,
            "frozen": freeze.get("ok"),
            "e2e": e2e and scan.get("ok") and priors_unchanged and v014_unchanged and tests_ok,
            "prior_zips_unchanged": priors_unchanged,
            "v014_unchanged": v014_unchanged,
            "tests_ok": tests_ok,
            "version": VERSION,
        },
    )
    return {
        "ok": ver_ok,
        "frozen": freeze.get("ok"),
        "artifact_dir": ARTIFACT_DIR,
        "no_publish": no_publish,
        "e2e": e2e and scan.get("ok") and tests_ok,
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
        art / "open-test-v015.json",
        {
            "TEST_ACCESS_LIFECYCLE_STATUS": "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED",
            "recomputed_joint_gates": False,
            "ok": True,
        },
    )
    return {"ok": True, "artifact_dir": ARTIFACT_DIR}


def _status_contract(**kw: Any) -> dict[str, Any]:
    e2e_ok = bool(kw.get("e2e"))
    http = kw["http"]
    engine = kw["engine"]
    sources = kw["sources"]
    return {
        "version": VERSION,
        "Report status": "DRAFT",
        "BASELINE_VERIFICATION_STATUS": kw["baseline"].get("BASELINE_VERIFICATION_STATUS"),
        "V014_INTEGRATED_RUNTIME_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "FALSEY_FUTURE_FIELD_REJECTION_STATUS": http.get("FALSEY_FUTURE_FIELD_REJECTION_STATUS"),
        "FUTURE_FIELD_PRESENCE_CONTRACT_STATUS": http.get("FUTURE_FIELD_PRESENCE_CONTRACT_STATUS"),
        "HTTP_EXPLICIT_FIELD_PRESENCE_STATUS": http.get("HTTP_EXPLICIT_FIELD_PRESENCE_STATUS"),
        "LEP_ROUTE_BOUNDARY_STATUS": http.get("LEP_ROUTE_BOUNDARY_STATUS"),
        "e2e_scope": "NHR_P0_D0_HTTP_WORKBENCH",
        "state_conditioned_lep_not_used_as_e2e_pass": True,
        "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": engine.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"),
        "DECLARED_PRE_T0_SUMMARY_STATUS": engine.get("DECLARED_PRE_T0_SUMMARY_STATUS"),
        "SOURCE_NAMESPACE_BINDING_STATUS": engine.get("SOURCE_NAMESPACE_BINDING_STATUS"),
        "PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS": engine.get("PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS"),
        "FROZEN_LEP_REFERENCE_PROBE_STATUS": http.get("FROZEN_LEP_REFERENCE_PROBE_STATUS"),
        "STATE_CONDITIONED_LEP_STATUS": http.get("STATE_CONDITIONED_LEP_STATUS") or "NOT_IMPLEMENTED",
        "JOINT_PANEL_ROW_ACCOUNTING_STATUS": kw["accounting"].get("JOINT_PANEL_ROW_ACCOUNTING_STATUS"),
        "JOINT_PANEL_COUNT_BRIDGE_STATUS": kw["accounting"].get("JOINT_PANEL_COUNT_BRIDGE_STATUS"),
        "e2e_gates": kw.get("e2e_gates"),
        "e2e_blockers": kw.get("e2e_blockers") or [],
        "summary_only_not_used_as_e2e_gate": True,
        "lep_reference_probe_not_used_as_e2e_gate": True,
        "SYNTHETIC_E2E_STATUS": engine.get("SYNTHETIC_E2E_STATUS"),
        "SOURCE_A_FROZEN_INFERENCE_STATUS": engine.get("SOURCE_A_FROZEN_INFERENCE_STATUS"),
        "SOURCE_B_FROZEN_INFERENCE_STATUS": engine.get("SOURCE_B_FROZEN_INFERENCE_STATUS"),
        "FROZEN_LEP_EXECUTION_STATUS": http.get("FROZEN_LEP_EXECUTION_STATUS"),
        "SYNTHETIC_EVENT_PROBABILITY_STATUS": http.get("SYNTHETIC_EVENT_PROBABILITY_STATUS"),
        "EXACT_PROVIDER_IDENTITY_STATUS": engine.get("EXACT_PROVIDER_IDENTITY_STATUS"),
        "NO_SILENT_PROVIDER_FALLBACK_STATUS": engine.get("NO_SILENT_PROVIDER_FALLBACK_STATUS"),
        "HTTP_TYPED_SCHEMA_STATUS": http.get("HTTP_TYPED_SCHEMA_STATUS"),
        "HTTP_DETERMINISTIC_ERROR_STATUS": http.get("HTTP_DETERMINISTIC_ERROR_STATUS"),
        "WORKBENCH_BROWSER_INTEGRATION_STATUS": kw.get("browser_status"),
        "SOURCE_CONNECTOR_FILTERED_READ_STATUS": sources.get("SOURCE_CONNECTOR_FILTERED_READ_STATUS"),
        "JOINT_PANEL_ACCOUNTING_STATUS": kw["accounting"].get("JOINT_PANEL_ACCOUNTING_STATUS"),
        "SOURCE_CONNECTOR_REGISTRY_STATUS": sources.get("SOURCE_CONNECTOR_REGISTRY_STATUS"),
        "CLINICAL_SOURCE_SYSTEM_COUNT": sources.get("CLINICAL_SOURCE_SYSTEM_COUNT"),
        "CLINICAL_SOURCE_CONNECTOR_COUNT": sources.get("CLINICAL_SOURCE_CONNECTOR_COUNT"),
        "MATERIALIZED_LAYER_COUNT": sources.get("MATERIALIZED_LAYER_COUNT"),
        "REFERENCE_SOURCE_CONNECTOR_COUNT": sources.get("REFERENCE_SOURCE_CONNECTOR_COUNT"),
        "FROZEN_MODEL_REGISTRY_COUNT": sources.get("FROZEN_MODEL_REGISTRY_COUNT"),
        "MODEL_PROVIDER_REGISTRY_COUNT": sources.get("MODEL_PROVIDER_REGISTRY_COUNT"),
        "SOURCE_A_CONNECTOR_STATUS": sources.get("SOURCE_A_CONNECTOR_STATUS"),
        "SOURCE_B_CONNECTOR_STATUS": sources.get("SOURCE_B_CONNECTOR_STATUS"),
        "ESKLP_CONNECTOR_STATUS": sources.get("ESKLP_CONNECTOR_STATUS"),
        "MARGINAL_PROVIDER_RUNTIME_CONSUMPTION_STATUS": engine.get("MARGINAL_PROVIDER_RUNTIME_CONSUMPTION_STATUS"),
        "STATE_CONDITIONED_MARGINAL_INFERENCE_STATUS": engine.get("STATE_CONDITIONED_MARGINAL_INFERENCE_STATUS"),
        "STATE_CONDITIONED_JOINT_COMPOSITION_STATUS": engine.get("STATE_CONDITIONED_JOINT_COMPOSITION_STATUS"),
        "D0_JOINT_OUTCOME_DISTRIBUTION_STATUS": engine.get("D0_JOINT_OUTCOME_DISTRIBUTION_STATUS"),
        "D1_JOINT_DEPENDENCE_STATUS": "NOT_ACCEPTED",
        "CROSS_HORIZON_DEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": 0,
        "JOINT_HELDOUT_CONFIRMED_ROUTE_COUNT": 0,
        "HTTP_RESEARCH_API_STATUS": http.get("HTTP_RESEARCH_API_STATUS"),
        "API_SCHEMA_CONTRACT_STATUS": http.get("API_SCHEMA_CONTRACT_STATUS"),
        "API_MODEL_ROUTING_STATUS": http.get("API_MODEL_ROUTING_STATUS"),
        "API_NO_SILENT_FALLBACK_STATUS": http.get("API_NO_SILENT_FALLBACK_STATUS"),
        "RESEARCH_WORKBENCH_STATUS": kw["wb"].get("RESEARCH_WORKBENCH_STATUS"),
        "WORKBENCH_API_INTEGRATION_STATUS": kw["wb"].get("WORKBENCH_API_INTEGRATION_STATUS"),
        "WORKBENCH_SYNTHETIC_DEFAULT_STATUS": kw["wb"].get("WORKBENCH_SYNTHETIC_DEFAULT_STATUS"),
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
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": engine.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": engine.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS"),
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
        "ZIP_CONTENT_VERIFICATION_STATUS": "PENDING_PUBLISH",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PENDING_PUBLISH",
        "PUBLICATION_INTEGRITY_STATUS": "DETACHED_SIDECAR_AUTHORITATIVE",
        "PUBLICATION_CONFIRMED_BY": "detached_sidecar_and_attestation_after_pack",
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
        "# UHBSE Integrated Research Runtime Foundation v0.1.5",
        "",
        "Report status: DRAFT",
        "",
        "Point correction of published v0.1.4: future-field presence vs truthiness.",
        "Not a new model stage. Not a clinical product. Not production.",
        "Global E2E PASS is the confirmed NHR P0→D0→HTTP→workbench path.",
        "STATE_CONDITIONED_LEP_STATUS remains NOT_IMPLEMENTED until a verified source-specific adapter exists.",
        "Data-bearing future fields are rejected by presence, including null/0/false/empty.",
        "`has_future_values=false` is allowed and is not temporal proof.",
        "",
        "## Required statuses",
        "",
    ]
    for k in (
        "V014_INTEGRATED_RUNTIME_CLAIM_STATUS",
        "FALSEY_FUTURE_FIELD_REJECTION_STATUS",
        "FUTURE_FIELD_PRESENCE_CONTRACT_STATUS",
        "HTTP_EXPLICIT_FIELD_PRESENCE_STATUS",
        "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS",
        "DECLARED_PRE_T0_SUMMARY_STATUS",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS",
        "SOURCE_NAMESPACE_BINDING_STATUS",
        "PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS",
        "SOURCE_A_FROZEN_INFERENCE_STATUS",
        "SOURCE_B_FROZEN_INFERENCE_STATUS",
        "FROZEN_LEP_REFERENCE_PROBE_STATUS",
        "STATE_CONDITIONED_LEP_STATUS",
        "LEP_ROUTE_BOUNDARY_STATUS",
        "JOINT_PANEL_ROW_ACCOUNTING_STATUS",
        "JOINT_PANEL_COUNT_BRIDGE_STATUS",
        "WORKBENCH_BROWSER_INTEGRATION_STATUS",
        "END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS",
        "PUBLIC_DATA_MINIMIZATION_STATUS",
        "PUBLICATION_INTEGRITY_STATUS",
        "HTTP_TYPED_SCHEMA_STATUS",
        "D1_JOINT_DEPENDENCE_STATUS",
        "PRODUCTION_READINESS",
        "SECURITY_STAGE_STATUS",
    ):
        lines.append(f"- `{k}`={status.get(k)}")
    lines += [
        "",
        "## Non-claims",
        "",
        "No A↔B merge, no unit conversion, no D1 acceptance, no real-drug PKPD, no causal effect, no clinical validation.",
        "IROS did not grant a dataset. Automated contact was not run. No replacement model was trained.",
        "ZIP inner PUBLICATION_INTEGRITY_STATUS is DETACHED_SIDECAR_AUTHORITATIVE; publication PASS is the sidecar/attestation.",
        f"E2E scope: {status.get('e2e_scope')}. E2E blockers: {status.get('e2e_blockers')}",
        "",
    ]
    return "\n".join(lines)


def _write_current_stage(root: Path, status: dict[str, Any]) -> None:
    stage = root / "docs" / "current-stage.md"
    agents = root / "AGENTS.md"
    text = f"""# Current stage

**Stage:** 04 — UHBSE Integrated Research Runtime Foundation v0.1.5
**Phase:** RUN COMPLETE — security PAUSED
**Last updated:** 2026-10-14

## This stage

Point correction of published v0.1.4: future-field checks use presence, not truthiness. Not a new model stage.

Immutable baseline:

- `artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.4-review.zip`
- SHA-256: `1c3d8ed10c069fb46f75fbd5052b7cb398e6f4697be34e24c9e3e3e5bd15ebf7`
- members/indexed: 956/955

`END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS`={status.get("END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS")} (NHR P0→D0→HTTP→workbench)
`TEMPORAL_TIMESTAMP_VERIFICATION_STATUS`={status.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS")}
`FALSEY_FUTURE_FIELD_REJECTION_STATUS`={status.get("FALSEY_FUTURE_FIELD_REJECTION_STATUS")}
`FUTURE_FIELD_PRESENCE_CONTRACT_STATUS`={status.get("FUTURE_FIELD_PRESENCE_CONTRACT_STATUS")}
`HTTP_EXPLICIT_FIELD_PRESENCE_STATUS`={status.get("HTTP_EXPLICIT_FIELD_PRESENCE_STATUS")}
`JOINT_PANEL_COUNT_BRIDGE_STATUS`={status.get("JOINT_PANEL_COUNT_BRIDGE_STATUS")}
`LEP_ROUTE_BOUNDARY_STATUS`={status.get("LEP_ROUTE_BOUNDARY_STATUS")}
`STATE_CONDITIONED_LEP_STATUS`={status.get("STATE_CONDITIONED_LEP_STATUS")}
`FROZEN_LEP_REFERENCE_PROBE_STATUS`={status.get("FROZEN_LEP_REFERENCE_PROBE_STATUS")}
`D1_JOINT_DEPENDENCE_STATUS`={status.get("D1_JOINT_DEPENDENCE_STATUS")}
`CROSS_HORIZON_DEPENDENCE_STATUS`={status.get("CROSS_HORIZON_DEPENDENCE_STATUS")}

## Commands

```bash
audit --root . integrated-runtime run-v0.1.5 --no-publish
audit --root . integrated-runtime open-test-v0.1.5
audit --root . integrated-runtime verify-v0.1.5
audit --root . integrated-runtime publish-v0.1.5
```

open-test consumes frozen upstream v0.1 held-out and does not recompute joint gates.

## Publish target

- `artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.5-review.zip`
- SHA-256: see sidecar after publish-v0.1.5

Prior review ZIPs remain byte-for-byte immutable, including v0.1.4, v0.1.3, v0.1.2, v0.1.1 and v0.1.
"""
    stage.write_text(text, encoding="utf-8")
    if agents.is_file():
        ag = agents.read_text(encoding="utf-8")
        start = ag.find("## Current stage")
        end = ag.find("## Required behavior")
        block = """## Current stage

Current stage: **STAGE 04 — UHBSE INTEGRATED RESEARCH RUNTIME FOUNDATION v0.1.5**
(Falsey Future-Field Presence Correction)

Point correction of published v0.1.4. Not a new model stage.

```bash
audit --root . integrated-runtime run-v0.1.5 --no-publish
audit --root . integrated-runtime open-test-v0.1.5
audit --root . integrated-runtime verify-v0.1.5
audit --root . integrated-runtime publish-v0.1.5
```

"""
        if start != -1 and end != -1 and start < end:
            ag = ag[:start] + block + ag[end:]
            agents.write_text(ag, encoding="utf-8")
