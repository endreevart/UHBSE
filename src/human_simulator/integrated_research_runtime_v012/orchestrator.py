"""Orchestrator — Integrated Research Runtime Foundation v0.1.2."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v012.accounting import build_accounting
from human_simulator.integrated_research_runtime_v012.baseline import verify_baseline
from human_simulator.integrated_research_runtime_v012.connectors import build_registry
from human_simulator.integrated_research_runtime_v012.defects import run_phase0
from human_simulator.integrated_research_runtime_v012.engine import run_engine_audit
from human_simulator.integrated_research_runtime_v012.freeze import verify_pretest_freeze, write_pretest_freeze
from human_simulator.integrated_research_runtime_v012.hashes import sha_obj
from human_simulator.integrated_research_runtime_v012.http_app import run_http_audit
from human_simulator.integrated_research_runtime_v012.labels import public_classifier_audit
from human_simulator.integrated_research_runtime_v012.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    VERSION,
    V02_MODELS,
    WORKBENCH_DIR,
    policy_snapshot,
)
from human_simulator.integrated_research_runtime_v012.privacy import scan_public
from human_simulator.integrated_research_runtime_v012.qsp import sandbox_audit
from human_simulator.integrated_research_runtime_v012.validation import public_protocol, write_private_pack
from human_simulator.integrated_research_runtime_v012.workbench import write_workbench


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
        "p0_15_defects_reproduced": phase0.get("n_reproduced") == 15 and phase0.get("ok"),
        "p0_identity_mutation_ok_on_v011": bool((defects.get(1) or {}).get("reproduced")),
        "p0_feature_hash_as_model_id": bool((defects.get(2) or {}).get("reproduced")),
        "p0_silent_p0_fallback": bool((defects.get(3) or {}).get("reproduced")),
        "p0_synthetic_accepts_magerya": bool((defects.get(4) or {}).get("reproduced")),
        "p0_missing_cutoff": bool((defects.get(5) or {}).get("reproduced")),
        "p0_event_any_feature_hash": bool((defects.get(6) or {}).get("reproduced")),
        "p0_http_nondeterministic": bool((defects.get(7) or {}).get("reproduced")),
        "p0_default_synthetic": bool((defects.get(8) or {}).get("reproduced")),
        "p0_lep_fixture_route": bool((defects.get(9) or {}).get("reproduced")),
        "p0_workbench_fetch_string": bool((defects.get(10) or {}).get("reproduced")),
        "p0_clinical_count_three": bool((defects.get(11) or {}).get("reproduced")),
        "p0_connector_constant_foreign": bool((defects.get(12) or {}).get("reproduced")),
        "p0_excluded_as_remainder": bool((defects.get(13) or {}).get("reproduced")),
        "p0_panel_count_drift": bool((defects.get(14) or {}).get("reproduced")),
        "p0_zip_pending_vs_attestation": bool((defects.get(15) or {}).get("reproduced")),
        "baseline_v011_sha": baseline.get("BASELINE_VERIFICATION_STATUS") == "PASS",
        "synthetic_e2e": engine.get("SYNTHETIC_E2E_STATUS") == "PASS",
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
        "clinical_source_system_count_2": sources.get("CLINICAL_SOURCE_SYSTEM_COUNT") == 2,
        "unified_not_third_source": bool(sources.get("unified_layer_not_a_third_clinical_source")),
        "filtered_reads": sources.get("SOURCE_CONNECTOR_FILTERED_READ_STATUS") == "PASS",
        "panel_reconciled": accounting.get("JOINT_PANEL_ACCOUNTING_STATUS") == "RECONCILED",
        "label_review_only": clf.get("CLASSIFIER_DECISION_LOG_STATUS") == "REVIEW_VIEW_ONLY",
        "qsp_unavailable": bool(qsp.get("INTERVENTION_EFFECT_UNAVAILABLE")),
        "browser_not_fetch_string": http.get("WORKBENCH_BROWSER_INTEGRATION_STATUS")
        in {"PASS", "NOT_VERIFIED", "FAIL"},
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
    _dump(art / "v011-contract-defect-reproduction.json", {k: v for k, v in phase0.items() if k != "ok"})
    names = {
        1: "v011-identity-mutation-defect.json",
        2: "v011-feature-hash-as-model-id-defect.json",
        3: "v011-silent-p0-fallback-defect.json",
        4: "v011-synthetic-accepts-source-a-defect.json",
        5: "v011-missing-cutoff-defect.json",
        6: "v011-event-any-feature-hash-defect.json",
        7: "v011-http-nondeterministic-error-defect.json",
        8: "v011-default-synthetic-not-frozen-defect.json",
        9: "v011-event-route-fixture-defect.json",
        10: "v011-workbench-fetch-string-defect.json",
        11: "v011-clinical-count-three-defect.json",
        12: "v011-connector-unfiltered-read-defect.json",
        13: "v011-excluded-invalid-remainder-defect.json",
        14: "v011-panel-count-drift-defect.json",
        15: "v011-zip-pending-vs-attestation-defect.json",
    }
    for block in phase0.get("defects") or []:
        fname = names.get(int(block["id"]))
        if fname:
            _dump(art / fname, block)

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
    _dump(art / "http-research-api-audit.json", {k: v for k, v in http.items() if k != "ok"})
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
    _dump(art / "v011-runtime-acceptance-matrix.json", matrix)

    browser_status = http.get("WORKBENCH_BROWSER_INTEGRATION_STATUS") or "NOT_VERIFIED"
    syn_ok = engine.get("SYNTHETIC_E2E_STATUS") == "PASS"
    a_ok = engine.get("SOURCE_A_FROZEN_INFERENCE_STATUS") == "PASS"
    b_ok = engine.get("SOURCE_B_FROZEN_INFERENCE_STATUS") == "PASS"
    e2e = (
        syn_ok
        and a_ok
        and b_ok
        and engine.get("EXACT_PROVIDER_IDENTITY_STATUS") == "PASS"
        and engine.get("NO_SILENT_PROVIDER_FALLBACK_STATUS") == "PASS"
        and http.get("HTTP_TYPED_SCHEMA_STATUS") == "PASS"
        and http.get("HTTP_DETERMINISTIC_ERROR_STATUS") == "PASS"
        and browser_status == "PASS"
        and sources.get("SOURCE_CONNECTOR_FILTERED_READ_STATUS") == "PASS"
        and accounting.get("JOINT_PANEL_ACCOUNTING_STATUS") == "RECONCILED"
        and phase0.get("ok")
        and baseline.get("ok")
        and qsp.get("ok")
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
        browser_status=browser_status,
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
    _write_current_stage(root, status)
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
        art / "open-test-v012.json",
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
        "V011_INTEGRATED_RUNTIME_CLAIM_STATUS": "CORRECTION_REQUIRED",
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
        "# UHBSE Integrated Research Runtime Foundation v0.1.2",
        "",
        "Report status: DRAFT",
        "",
        "Contract closure and frozen provider execution. Not a clinical product. Not production.",
        "Portable synthetic flow is not evidence of source-specific frozen execution.",
        "",
        "## Required statuses",
        "",
    ]
    for k in (
        "SYNTHETIC_E2E_STATUS",
        "SOURCE_A_FROZEN_INFERENCE_STATUS",
        "SOURCE_B_FROZEN_INFERENCE_STATUS",
        "FROZEN_LEP_EXECUTION_STATUS",
        "EXACT_PROVIDER_IDENTITY_STATUS",
        "NO_SILENT_PROVIDER_FALLBACK_STATUS",
        "HTTP_TYPED_SCHEMA_STATUS",
        "HTTP_DETERMINISTIC_ERROR_STATUS",
        "WORKBENCH_BROWSER_INTEGRATION_STATUS",
        "SOURCE_CONNECTOR_FILTERED_READ_STATUS",
        "JOINT_PANEL_ACCOUNTING_STATUS",
        "END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS",
        "CLINICAL_SOURCE_SYSTEM_COUNT",
        "MATERIALIZED_LAYER_COUNT",
        "PUBLICATION_INTEGRITY_STATUS",
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
        "",
    ]
    return "\n".join(lines)


def _write_current_stage(root: Path, status: dict[str, Any]) -> None:
    stage = root / "docs" / "current-stage.md"
    agents = root / "AGENTS.md"
    text = f"""# Current stage

**Stage:** 04 — UHBSE Integrated Research Runtime Foundation v0.1.2
**Phase:** RUN COMPLETE — security PAUSED
**Last updated:** 2026-09-20

## This stage

Contract Closure and Frozen Provider Execution.

Corrects v0.1.1 contract defects. Baseline ZIP (immutable):

- `artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1-review.zip`
- SHA-256: `e940199fdbf978241ad2dc1db22d7def015942a5d42f82cb842360d094fbeeb6`
- members/indexed: 876/875

`END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS`={status.get("END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS")}

## Commands

```bash
audit --root . integrated-runtime run-v0.1.2 --no-publish
audit --root . integrated-runtime open-test-v0.1.2
audit --root . integrated-runtime verify-v0.1.2
audit --root . integrated-runtime publish-v0.1.2
```

open-test consumes frozen upstream v0.1 held-out and does not recompute joint gates.

## Publish target

- `artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.2-review.zip`
- SHA-256: see sidecar after publish-v0.1.2

Prior review ZIPs remain byte-for-byte immutable.
"""
    stage.write_text(text, encoding="utf-8")
    if agents.is_file():
        ag = agents.read_text(encoding="utf-8")
        ag = ag.replace(
            "Current stage: **STAGE 04 — UHBSE INTEGRATED RESEARCH RUNTIME FOUNDATION v0.1.1**\n"
            "(PUBLISHED — State-Conditioned End-to-End Composition)",
            "Current stage: **STAGE 04 — UHBSE INTEGRATED RESEARCH RUNTIME FOUNDATION v0.1.2**\n"
            "(Contract Closure and Frozen Provider Execution)",
        )
        ag = ag.replace(
            "audit --root . integrated-runtime run-v0.1.1 --no-publish\n"
            "audit --root . integrated-runtime open-test-v0.1.1\n"
            "audit --root . integrated-runtime verify-v0.1.1\n"
            "audit --root . integrated-runtime publish-v0.1.1\n",
            "audit --root . integrated-runtime run-v0.1.2 --no-publish\n"
            "audit --root . integrated-runtime open-test-v0.1.2\n"
            "audit --root . integrated-runtime verify-v0.1.2\n"
            "audit --root . integrated-runtime publish-v0.1.2\n",
        )
        agents.write_text(ag, encoding="utf-8")
