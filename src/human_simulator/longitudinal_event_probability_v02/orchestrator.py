"""Orchestrator — Longitudinal Event Probability Foundation v0.2."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v02.baseline_verify import verify_baseline
from human_simulator.longitudinal_event_probability_v02.defect_reproduction import (
    reproduce_v01_defects,
)
from human_simulator.longitudinal_event_probability_v02.engine_shadow import run_engine_shadow
from human_simulator.longitudinal_event_probability_v02.landmarks import build_landmark_datasets
from human_simulator.longitudinal_event_probability_v02.observation_window import (
    build_observation_windows,
)
from human_simulator.longitudinal_event_probability_v02.ood import build_ood
from human_simulator.longitudinal_event_probability_v02.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.longitudinal_event_probability_v02.regimes import correct_regimes
from human_simulator.longitudinal_event_probability_v02.survival import (
    train_and_evaluate_endpoint,
)
from human_simulator.unified_individual_state_v0111.privacy_scan import scan_public


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
    import hashlib

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
    """Strip weights from public artifacts; keep hashes and metrics."""
    out = {k: v for k, v in res.items() if k != "model"}
    if res.get("model"):
        m = res["model"]
        out["model_public"] = {
            "type": m.get("type"),
            "feature_order": m.get("feature_order"),
            "time_bins_days": m.get("time_bins_days"),
            "l2_selected_on_validation": m.get("l2_selected_on_validation"),
            "model_identity_sha256": m.get("model_identity_sha256"),
            "seed": m.get("seed"),
        }
    return out


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

    print(json.dumps({"phase": "v01_defect_reproduction"}), flush=True)
    defects = reproduce_v01_defects(root)
    _write_json(art / "v01-survival-defect-reproduction.json", defects["survival"])
    _write_json(art / "v01-engine-leakage-reproduction.json", defects["engine"])
    _write_json(art / "v01-regime-methodology-defects.json", defects["regime"])
    _write_json(art / "v01-accepted-foundation-matrix.json", defects["matrix"])
    _write_json(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "observation_windows"}), flush=True)
    windows = build_observation_windows(root)
    _write_json(art / "administrative-observation-windows.json", windows)

    print(json.dumps({"phase": "landmarks"}), flush=True)
    landmarks = build_landmark_datasets(root, windows)
    _write_json(art / "landmark-datasets.json", landmarks)
    if not landmarks.get("ok"):
        return {"ok": False, "error": "LANDMARK_FAIL", "landmarks": landmarks}

    print(json.dumps({"phase": "survival_models"}), flush=True)
    frozen: dict[str, Any] = {}
    results = []

    for ss, label in (("magerya_api", "A"), ("kgz_raw", "B")):
        print(json.dumps({"phase": "obs_tte", "source": label}), flush=True)
        res = train_and_evaluate_endpoint(
            root,
            parquet_name="landmark_observation_process.parquet",
            endpoint_name="TIME_TO_NEXT_RECORDED_EVENT",
            source_system=ss,
        )
        results.append(res)
        if res.get("model"):
            key = f"obs_{label}"
            m = dict(res["model"])
            m["endpoint"] = "TIME_TO_NEXT_RECORDED_EVENT"
            m["source_system"] = ss
            frozen[key] = m
            (root / MODELS_DIR / f"frozen-{key}.json").write_text(
                json.dumps(m, separators=(",", ":")) + "\n", encoding="utf-8"
            )

    # Excursion: first few outcomes from thresholds file
    thr_path = (
        root
        / "private/longitudinal-event-probability-v02/landmarks/excursion-thresholds-train-only.json"
    )
    thr = json.loads(thr_path.read_text(encoding="utf-8"))
    for outcome in (thr.get("selected_outcomes") or [])[:4]:
        ss = "magerya_api" if outcome.startswith("A::") else "kgz_raw"
        print(json.dumps({"phase": "exc_tte", "outcome": outcome[:40]}), flush=True)
        res = train_and_evaluate_endpoint(
            root,
            parquet_name="landmark_outcome_excursion.parquet",
            endpoint_name="TIME_TO_FIRST_SOURCE_SPECIFIC_OUTCOME_EXCURSION",
            source_system=ss,
            outcome_key=outcome,
        )
        results.append(res)
        if res.get("model"):
            key = f"exc_{hash(outcome) & 0xffffffff:08x}"
            m = dict(res["model"])
            m["endpoint"] = "TIME_TO_FIRST_SOURCE_SPECIFIC_OUTCOME_EXCURSION"
            m["outcome_key"] = outcome
            m["source_system"] = ss
            frozen[key] = m

    _write_json(
        art / "survival-evaluation.json",
        {"results": [_public_model_result(r) for r in results]},
    )
    (root / MODELS_DIR / "frozen-models-index.json").write_text(
        json.dumps(
            {
                k: {
                    "model_identity_sha256": v.get("model_identity_sha256"),
                    "endpoint": v.get("endpoint"),
                    "outcome_key": v.get("outcome_key"),
                    "source_system": v.get("source_system"),
                    "feature_order": v.get("feature_order"),
                }
                for k, v in frozen.items()
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Aggregate statuses
    any_km = any(r.get("KAPLAN_MEIER_BASELINE_STATUS") == "BUILT" for r in results)
    any_haz = any(r.get("DISCRETE_TIME_HAZARD_MODEL_STATUS") == "TRAINED" for r in results)
    obs_results = [r for r in results if r.get("endpoint") == "TIME_TO_NEXT_RECORDED_EVENT"]
    exc_results = [
        r
        for r in results
        if r.get("endpoint") == "TIME_TO_FIRST_SOURCE_SPECIFIC_OUTCOME_EXCURSION"
    ]
    accepted = [
        r for r in results if r.get("foundation_status") == "TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED"
    ]
    tech_prob = (
        "TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED"
        if accepted
        else (
            "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_OR_CALIBRATED_SIGNAL"
            if any(r.get("status") == "EVALUATED" for r in results)
            else "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
        )
    )

    print(json.dumps({"phase": "regimes"}), flush=True)
    regimes = correct_regimes(root)
    _write_json(art / "regime-methodology-correction.json", regimes)

    print(json.dumps({"phase": "ood"}), flush=True)
    ood = build_ood(root)
    _write_json(art / "applicability-ood.json", ood)

    print(json.dumps({"phase": "engine_shadow"}), flush=True)
    shadow = run_engine_shadow(root, frozen)
    _write_json(art / "engine-survival-shadow.json", shadow)

    priv = scan_public(art)
    _write_json(art / "public-privacy-scan.json", priv)

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V01_SURVIVAL_DEFECT_REPRODUCTION_STATUS": defects["survival"].get(
            "V01_SURVIVAL_DEFECT_REPRODUCTION_STATUS"
        ),
        "V01_ENGINE_FUTURE_LEAKAGE_STATUS": defects["engine"].get(
            "V01_ENGINE_FUTURE_LEAKAGE_STATUS"
        ),
        "V01_REGIME_METHODOLOGY_STATUS": defects["regime"].get(
            "V01_REGIME_METHODOLOGY_STATUS"
        ),
        "PRIOR_TRANSITION_DATASET_FOUNDATION_STATUS": defects["matrix"].get(
            "PRIOR_TRANSITION_DATASET_FOUNDATION_STATUS"
        ),
        "PRIOR_TTE_DATASET_FOUNDATION_STATUS": defects["matrix"].get(
            "PRIOR_TTE_DATASET_FOUNDATION_STATUS"
        ),
        "PRIOR_TTE_MODEL_FOUNDATION_STATUS": defects["matrix"].get(
            "PRIOR_TTE_MODEL_FOUNDATION_STATUS"
        ),
        "ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS": windows.get(
            "ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS"
        ),
        "CENSORING_CONTRACT_STATUS": landmarks.get("CENSORING_CONTRACT_STATUS"),
        "OBSERVATION_PROCESS_LANDMARK_DATASET_STATUS": landmarks.get(
            "OBSERVATION_PROCESS_LANDMARK_DATASET_STATUS"
        ),
        "OUTCOME_EXCURSION_LANDMARK_DATASET_STATUS": landmarks.get(
            "OUTCOME_EXCURSION_LANDMARK_DATASET_STATUS"
        ),
        "LANDMARK_TEMPORAL_LEAKAGE_STATUS": landmarks.get(
            "LANDMARK_TEMPORAL_LEAKAGE_STATUS"
        ),
        "KAPLAN_MEIER_BASELINE_STATUS": "BUILT" if any_km else "NOT_RUN",
        "DISCRETE_TIME_HAZARD_MODEL_STATUS": "TRAINED" if any_haz else "NOT_RUN",
        "SURVIVAL_MODEL_FREEZE_STATUS": "FROZEN" if frozen else "NOT_RUN",
        "SURVIVAL_CALIBRATION_STATUS": "EVALUATED",
        "OBSERVATION_PROCESS_PROBABILITY_STATUS": (
            "EVALUATED"
            if any(r.get("status") == "EVALUATED" for r in obs_results)
            else "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
        ),
        "OUTCOME_EXCURSION_PROBABILITY_STATUS": (
            "EVALUATED"
            if any(r.get("status") == "EVALUATED" for r in exc_results)
            else "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
        ),
        "TECHNICAL_PROBABILITY_FOUNDATION_STATUS": tech_prob,
        "REGIME_NUMERICAL_STABILITY_STATUS": regimes.get(
            "REGIME_NUMERICAL_STABILITY_STATUS"
        ),
        "REGIME_CONFOUNDING_STATUS": regimes.get("REGIME_CONFOUNDING_STATUS"),
        "REGIME_FOUNDATION_ACCEPTANCE_STATUS": regimes.get(
            "REGIME_FOUNDATION_ACCEPTANCE_STATUS"
        ),
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": ood.get(
            "SOURCE_STRATIFIED_APPLICABILITY_STATUS"
        ),
        "APPLICABILITY_FOUNDATION_STATUS": ood.get("APPLICABILITY_FOUNDATION_STATUS"),
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
        "PUBLICATION_INTEGRITY_STATUS": "PENDING",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "TECHNICAL_PASS": False,
    }

    technical = (
        status["BASELINE_VERIFICATION_STATUS"] == "PASS"
        and status["V01_ENGINE_FUTURE_LEAKAGE_STATUS"]
        == "CONFIRMED_FUTURE_HORIZON_LEAKAGE"
        and status["PRIOR_TTE_MODEL_FOUNDATION_STATUS"]
        == "NOT_ACCEPTED_NOT_PROBABILISTIC"
        and status["ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS"] == "BUILT"
        and status["OBSERVATION_PROCESS_LANDMARK_DATASET_STATUS"] == "BUILT"
        and status["OUTCOME_EXCURSION_LANDMARK_DATASET_STATUS"] == "BUILT"
        and status["LANDMARK_TEMPORAL_LEAKAGE_STATUS"] == "PASS"
        and status["KAPLAN_MEIER_BASELINE_STATUS"] == "BUILT"
        and status["DISCRETE_TIME_HAZARD_MODEL_STATUS"] == "TRAINED"
        and status["SURVIVAL_MODEL_FREEZE_STATUS"] == "FROZEN"
        and status["ENGINE_SURVIVAL_INFERENCE_STATUS"] == "TECHNICAL_SHADOW_PASS"
        and status["ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"]
        == "PASS_NO_FUTURE_HORIZON_READ"
        and status["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
        and status["SCIENTIFIC_CROSS_SOURCE_PASS"] is False
    )
    status["TECHNICAL_PASS"] = technical
    _write_json(art / "status-contract.json", status)

    report = f"""# Unified Longitudinal Event Probability Foundation v{VERSION}

**Report status: DRAFT**

## Phase 0

- Prior TTE datasets/models: NOT_ACCEPTED
- Engine future-horizon leakage: CONFIRMED
- Transition dataset: ACCEPTED_TECHNICAL_LONGITUDINAL_INPUT

## Landmarks / models

- Observation windows: `{status['ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS']}`
- Landmark leakage: `{status['LANDMARK_TEMPORAL_LEAKAGE_STATUS']}`
- KM / discrete hazard: `{status['KAPLAN_MEIER_BASELINE_STATUS']}` / `{status['DISCRETE_TIME_HAZARD_MODEL_STATUS']}`
- Technical probability foundation: `{status['TECHNICAL_PROBABILITY_FOUNDATION_STATUS']}`

## Regimes / OOD / Engine

- Regime foundation: `{status['REGIME_FOUNDATION_ACCEPTANCE_STATUS']}`
- Applicability foundation: `{status['APPLICABILITY_FOUNDATION_STATUS']}`
- Engine survival: `{status['ENGINE_SURVIVAL_INFERENCE_STATUS']}`
- Engine leakage: `{status['ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS']}`

## Non-claims

No medication residual / intervention / TE / Safety Boundary / QSP / PKPD.
SCIENTIFIC_CROSS_SOURCE_PASS=false

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
        from human_simulator.longitudinal_event_probability_v02.publish import publish

        result["publish"] = publish(root)
    return result
