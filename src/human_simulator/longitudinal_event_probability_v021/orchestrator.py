"""Orchestrator — Longitudinal Event Probability Foundation v0.2.1."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v021.baseline import verify_baseline
from human_simulator.longitudinal_event_probability_v021.defect_reproduction import (
    reproduce_v02_defects,
)
from human_simulator.longitudinal_event_probability_v021.engine import run_engine_shadow
from human_simulator.longitudinal_event_probability_v021.estimators import payload_identity_sha256
from human_simulator.longitudinal_event_probability_v021.event_identity import build_event_identity
from human_simulator.longitudinal_event_probability_v021.landmarks import build_landmark_datasets
from human_simulator.longitudinal_event_probability_v021.observation_window import (
    build_observation_windows,
)
from human_simulator.longitudinal_event_probability_v021.ood import build_ood
from human_simulator.longitudinal_event_probability_v021.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.longitudinal_event_probability_v021.regimes import correct_regimes
from human_simulator.longitudinal_event_probability_v021.registry import build_registry
from human_simulator.longitudinal_event_probability_v021.survival import train_and_evaluate_endpoint
from human_simulator.unified_individual_state_v0111.privacy_scan import scan_public

ENDPOINT_FILES = {
    "TIME_TO_NEXT_LAB_PANEL": "landmark_lab_panel.parquet",
    "TIME_TO_NEXT_ENCOUNTER": "landmark_encounter.parquet",
    "TIME_TO_NEXT_RECORDED_EVENT": "landmark_recorded_event_diagnostic.parquet",
}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def _write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )


def _public_model_result(res: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in res.items() if k != "model"}
    if res.get("model"):
        m = res["model"]
        out["model_public"] = {
            "type": m.get("type"),
            "feature_order": m.get("feature_order"),
            "time_bins_days": m.get("time_bins_days"),
            "l2_selected_on_model_selection_fold": m.get("l2_selected_on_model_selection_fold"),
            "model_identity_sha256": m.get("model_identity_sha256"),
            "cell_id_sha256": m.get("cell_id_sha256"),
            "file_sha256": m.get("file_sha256"),
            "frozen_file": m.get("frozen_file"),
            "supported_horizons_validation": m.get("supported_horizons_validation"),
            "seed": m.get("seed"),
        }
    return out


def _reload_check(root: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = True
    details = []
    for res in results:
        fname = res.get("frozen_file")
        if not fname:
            continue
        path = root / MODELS_DIR / fname
        loaded = json.loads(path.read_text(encoding="utf-8"))
        ident = payload_identity_sha256(loaded)
        equal = ident == res.get("model_identity_sha256")
        feat_eq = loaded.get("feature_order") == (res.get("model") or {}).get("feature_order")
        if res.get("model"):
            w_eq = loaded.get("weights") == res["model"].get("weights")
            s_eq = loaded.get("scaler_mean") == res["model"].get("scaler_mean")
            c_eq = loaded.get("calibrators") == res["model"].get("calibrators")
        else:
            w_eq = s_eq = c_eq = False
        row = {
            "file": fname,
            "identity_equal": equal,
            "feature_order_equal": feat_eq,
            "weights_equal": w_eq,
            "scaler_equal": s_eq,
            "calibration_equal": c_eq,
        }
        details.append(row)
        if not all([equal, feat_eq, w_eq, s_eq, c_eq]):
            ok = False
    return {
        "ok": ok,
        "SURVIVAL_MODEL_RELOAD_STATUS": "PASS" if ok else "FAIL",
        "n": len(details),
        "details_public": [
            {k: v for k, v in d.items() if k != "weights"} for d in details
        ],
    }


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    art.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(json.dumps({"phase": "baseline"}), flush=True)
    baseline = verify_baseline(root)
    _write_json(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    print(json.dumps({"phase": "v02_defect_reproduction"}), flush=True)
    defects = reproduce_v02_defects(root)
    _write_json(art / "v02-defect-reproduction.json", defects["defects"])
    _write_json(art / "v02-probability-acceptance-audit.json", defects["acceptance_audit"])
    _write_json(art / "v02-engine-routing-defect-reproduction.json", defects["engine"])
    _write_json(art / "v02-survival-estimator-audit.json", defects["estimators"])
    _write_json(art / "v02-foundation-acceptance-matrix.json", defects["matrix"])
    _write_json(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "observation_windows"}), flush=True)
    windows = build_observation_windows(root)
    _write_json(art / "administrative-observation-windows.json", windows)

    print(json.dumps({"phase": "event_identity"}), flush=True)
    identity = build_event_identity(root)
    _write_json(art / "observation-event-identity.json", identity)

    print(json.dumps({"phase": "landmarks"}), flush=True)
    landmarks = build_landmark_datasets(root, windows, identity)
    _write_json(art / "landmark-datasets.json", landmarks)
    if not landmarks.get("ok"):
        return {"ok": False, "error": "LANDMARK_FAIL", "landmarks": landmarks}

    primary = identity["primary_endpoint"]
    results: list[dict[str, Any]] = []
    print(json.dumps({"phase": "survival_models"}), flush=True)
    for endpoint in ("TIME_TO_NEXT_LAB_PANEL", "TIME_TO_NEXT_ENCOUNTER"):
        for ss, label in (("magerya_api", "A"), ("kgz_raw", "B")):
            print(json.dumps({"phase": "obs_tte", "endpoint": endpoint, "source": label}), flush=True)
            results.append(
                train_and_evaluate_endpoint(
                    root,
                    parquet_name=ENDPOINT_FILES[endpoint],
                    endpoint_name=endpoint,
                    source_system=ss,
                )
            )
    results.append(
        {
            "status": "NOT_RUN",
            "endpoint": "TIME_TO_NEXT_RECORDED_EVENT",
            "source_system": None,
            "outcome_key": None,
            "reason": "DIAGNOSTIC_HETEROGENEOUS_DOCUMENT_ROWS_NOT_FOR_ENGINE",
            "cells": [],
        }
    )

    thr_path = root / "private/longitudinal-event-probability-v021/landmarks/excursion-thresholds-train-only.json"
    selected = []
    if thr_path.is_file():
        thr = json.loads(thr_path.read_text(encoding="utf-8"))
        for _ss, keys in (thr.get("selected_outcomes_by_source") or {}).items():
            selected.extend(keys)
        for note in thr.get("selection_notes") or []:
            results.append(
                {
                    "status": "NOT_RUN",
                    "endpoint": "TIME_TO_FIRST_SOURCE_SPECIFIC_OUTCOME_EXCURSION",
                    "source_system": None,
                    "outcome_key": note.get("outcome_key"),
                    "reason": note.get("reason"),
                    "cells": [],
                }
            )
    for outcome in selected:
        ss = "magerya_api" if outcome.startswith("A::") else "kgz_raw"
        print(json.dumps({"phase": "exc_tte", "outcome": outcome[:48]}), flush=True)
        results.append(
            train_and_evaluate_endpoint(
                root,
                parquet_name="landmark_outcome_excursion.parquet",
                endpoint_name="TIME_TO_FIRST_SOURCE_SPECIFIC_OUTCOME_EXCURSION",
                source_system=ss,
                outcome_key=outcome,
            )
        )

    _write_json(art / "survival-evaluation.json", {"results": [_public_model_result(r) for r in results]})

    print(json.dumps({"phase": "registry"}), flush=True)
    registry = build_registry(root, results, primary_endpoint=primary)
    public_reg = json.loads(json.dumps(registry))
    for c in (public_reg.get("cells") or {}).values():
        c.pop("calibrator", None)
    _write_json(art / "accepted-probability-registry-public.json", public_reg)

    reload = _reload_check(root, results)
    _write_json(art / "survival-model-reload.json", reload)

    print(json.dumps({"phase": "regimes"}), flush=True)
    regimes = correct_regimes(root)
    _write_json(art / "regime-methodology-correction.json", regimes)

    print(json.dumps({"phase": "ood"}), flush=True)
    ood_file = ENDPOINT_FILES[primary]
    ood = build_ood(root, ood_file)
    _write_json(art / "applicability-ood.json", ood)

    print(json.dumps({"phase": "engine_shadow"}), flush=True)
    shadow = run_engine_shadow(root)
    _write_json(art / "engine-survival-shadow.json", shadow)

    priv = scan_public(art)
    _write_json(art / "public-privacy-scan.json", priv)

    any_km = any(r.get("KAPLAN_MEIER_BASELINE_STATUS") == "BUILT" for r in results)
    any_haz = any(r.get("DISCRETE_TIME_HAZARD_MODEL_STATUS") == "TRAINED" for r in results)
    freeze_ok = registry["frozen_model_count"] == registry["trained_model_count"] and registry[
        "unexplained"
    ] == 0
    tech_prob = registry["global_status"]
    if tech_prob == "ACCEPTED":
        tech_label = "TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED"
    elif tech_prob == "PARTIAL_ACCEPTED":
        tech_label = "PARTIAL_ACCEPTED"
    else:
        tech_label = "EVALUATED_NOT_ACCEPTED"

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V02_DEFECT_REPRODUCTION_STATUS": defects["defects"].get("V02_DEFECT_REPRODUCTION_STATUS"),
        "V02_PROBABILITY_ACCEPTANCE_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "OBSERVATION_EVENT_IDENTITY_STATUS": identity.get("OBSERVATION_EVENT_IDENTITY_STATUS"),
        "OBSERVATION_MICROINTERVAL_AUDIT_STATUS": identity.get(
            "OBSERVATION_MICROINTERVAL_AUDIT_STATUS"
        ),
        "ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS": windows.get(
            "ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS"
        ),
        "CENSORING_CONTRACT_STATUS": landmarks.get("CENSORING_CONTRACT_STATUS"),
        "OUTCOME_EXCURSION_TIMESTAMP_LINEAGE_STATUS": landmarks.get(
            "OUTCOME_EXCURSION_TIMESTAMP_LINEAGE_STATUS"
        ),
        "TARGET_EVENT_REUSE_ACCOUNTING_STATUS": landmarks.get(
            "TARGET_EVENT_REUSE_ACCOUNTING_STATUS"
        ),
        "KAPLAN_MEIER_BASELINE_STATUS": "BUILT" if any_km else "NOT_RUN",
        "IPCW_BRIER_STATUS": "graf_ipcw_brier_divide_by_n",
        "SURVIVAL_CALIBRATION_METHOD_STATUS": "ipcw_weighted_logit_slope",
        "DISCRETE_TIME_HAZARD_MODEL_STATUS": "TRAINED" if any_haz else "NOT_RUN",
        "CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS": registry.get(
            "CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS"
        ),
        "ACCEPTED_PROBABILITY_CELL_COUNT": registry.get("ACCEPTED_PROBABILITY_CELL_COUNT"),
        "SOURCE_A_ACCEPTED_PROBABILITY_CELL_COUNT": registry.get(
            "SOURCE_A_ACCEPTED_PROBABILITY_CELL_COUNT"
        ),
        "SOURCE_B_ACCEPTED_PROBABILITY_CELL_COUNT": registry.get(
            "SOURCE_B_ACCEPTED_PROBABILITY_CELL_COUNT"
        ),
        "TECHNICAL_PROBABILITY_FOUNDATION_STATUS": tech_label,
        "SURVIVAL_MODEL_FREEZE_STATUS": "FROZEN" if freeze_ok and registry["frozen_model_count"] else "FAIL",
        "SURVIVAL_MODEL_RELOAD_STATUS": reload.get("SURVIVAL_MODEL_RELOAD_STATUS"),
        "REGIME_NUMERICAL_STABILITY_STATUS": regimes.get("REGIME_NUMERICAL_STABILITY_STATUS"),
        "REGIME_CONFOUNDING_STATUS": regimes.get("REGIME_CONFOUNDING_STATUS"),
        "REGIME_FOUNDATION_ACCEPTANCE_STATUS": regimes.get(
            "REGIME_FOUNDATION_ACCEPTANCE_STATUS"
        ),
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": ood.get(
            "SOURCE_STRATIFIED_APPLICABILITY_STATUS"
        ),
        "APPLICABILITY_FOUNDATION_STATUS": ood.get("APPLICABILITY_FOUNDATION_STATUS"),
        "ENGINE_MODEL_ROUTING_STATUS": shadow.get("ENGINE_MODEL_ROUTING_STATUS"),
        "ENGINE_SUPPORTED_HORIZON_STATUS": shadow.get("ENGINE_SUPPORTED_HORIZON_STATUS"),
        "ENGINE_APPLICABILITY_INTEGRATION_STATUS": shadow.get(
            "ENGINE_APPLICABILITY_INTEGRATION_STATUS"
        ),
        "ENGINE_SURVIVAL_INFERENCE_STATUS": shadow.get("ENGINE_SURVIVAL_INFERENCE_STATUS"),
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": shadow.get(
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"
        ),
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED_NO_ACCEPTED_LABEL_ONTOLOGY",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
        "SAFETY_BOUNDARY_CLASSIFIER_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "PUBLIC_DATA_MINIMIZATION_STATUS": priv.get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PENDING",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "primary_endpoint": primary,
        "TECHNICAL_PASS": False,
    }
    engine_ok = status["ENGINE_SURVIVAL_INFERENCE_STATUS"] in {
        "TECHNICAL_SHADOW_PASS",
        "TECHNICAL_SHADOW_ROUTING_PASS_NO_ACCEPTED_CELL",
    }
    technical = (
        status["BASELINE_VERIFICATION_STATUS"] == "PASS"
        and status["V02_DEFECT_REPRODUCTION_STATUS"] == "PASS"
        and status["V02_PROBABILITY_ACCEPTANCE_CLAIM_STATUS"] == "CORRECTION_REQUIRED"
        and status["ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS"] == "BUILT"
        and status["OBSERVATION_EVENT_IDENTITY_STATUS"] == "BUILT"
        and landmarks.get("OBSERVATION_PROCESS_LANDMARK_DATASET_STATUS") == "BUILT"
        and landmarks.get("LANDMARK_TEMPORAL_LEAKAGE_STATUS") == "PASS"
        and status["KAPLAN_MEIER_BASELINE_STATUS"] == "BUILT"
        and status["DISCRETE_TIME_HAZARD_MODEL_STATUS"] == "TRAINED"
        and status["SURVIVAL_MODEL_FREEZE_STATUS"] == "FROZEN"
        and status["SURVIVAL_MODEL_RELOAD_STATUS"] == "PASS"
        and status["CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS"] == "BUILT"
        and engine_ok
        and status["ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"]
        == "PASS_NO_FUTURE_HORIZON_READ"
        and status["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
        and status["SCIENTIFIC_CROSS_SOURCE_PASS"] is False
        and (
            status["TECHNICAL_PROBABILITY_FOUNDATION_STATUS"]
            != "TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED"
            or registry.get("coverage_gate", {}).get("passed") is True
        )
    )
    status["TECHNICAL_PASS"] = technical
    _write_json(art / "status-contract.json", status)

    report = f"""# Unified Longitudinal Event Probability Foundation v{VERSION}

**Report status: FINAL**

## Phase 0 — v0.2 defect reproduction

- V02_DEFECT_REPRODUCTION_STATUS: `{status['V02_DEFECT_REPRODUCTION_STATUS']}`
- V02_PROBABILITY_ACCEPTANCE_CLAIM_STATUS: `CORRECTION_REQUIRED`
- v0.2 global ACCEPTED claim is not transferred.

## Endpoints / identity

- Primary endpoint (pre-test, not model performance): `{primary}`
- OBSERVATION_EVENT_IDENTITY_STATUS: `{status['OBSERVATION_EVENT_IDENTITY_STATUS']}`
- OBSERVATION_MICROINTERVAL_AUDIT_STATUS: `{status['OBSERVATION_MICROINTERVAL_AUDIT_STATUS']}`
- Administrative windows are source-specific; global max is an administrative bound, not continuous observation.

## Survival / cells

- KM: `{status['KAPLAN_MEIER_BASELINE_STATUS']}`
- IPCW Brier: `{status['IPCW_BRIER_STATUS']}`
- Calibration: `{status['SURVIVAL_CALIBRATION_METHOD_STATUS']}`
- Discrete-time hazard: `{status['DISCRETE_TIME_HAZARD_MODEL_STATUS']}`
- Accepted cells: {status['ACCEPTED_PROBABILITY_CELL_COUNT']} (A={status['SOURCE_A_ACCEPTED_PROBABILITY_CELL_COUNT']}, B={status['SOURCE_B_ACCEPTED_PROBABILITY_CELL_COUNT']})
- TECHNICAL_PROBABILITY_FOUNDATION_STATUS: `{status['TECHNICAL_PROBABILITY_FOUNDATION_STATUS']}`

## Engine

- Routing: `{status['ENGINE_MODEL_ROUTING_STATUS']}`
- Supported horizon: `{status['ENGINE_SUPPORTED_HORIZON_STATUS']}`
- OOD integration: `{status['ENGINE_APPLICABILITY_INTEGRATION_STATUS']}`
- Inference: `{status['ENGINE_SURVIVAL_INFERENCE_STATUS']}`
- Future leakage: `{status['ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS']}`

## Non-claims

No medication residual / intervention / TE / Safety Boundary / QSP / PKPD.
SCIENTIFIC_CROSS_SOURCE_PASS=false
PRODUCTION_READINESS=NOT_CLAIMED
SECURITY_STAGE_STATUS=PAUSED_NOT_ACCEPTED_BY_OWNER

## TECHNICAL_PASS

`{status['TECHNICAL_PASS']}`
"""
    _write_md(art / "stage-report.md", report)
    _write_json(
        art / "verification.json",
        {
            "version": VERSION,
            "ok": technical,
            "TECHNICAL_PASS": technical,
            "duration_seconds": round(time.time() - t0, 3),
            "status": status,
        },
    )
    write_manifest(art)
    result = {
        "ok": technical,
        "artifact_dir": str(art),
        "duration_seconds": round(time.time() - t0, 3),
        "status": status,
    }
    if not no_publish and technical:
        from human_simulator.longitudinal_event_probability_v021.publish import publish

        result["publish"] = publish(root)
    return result
