"""Orchestrator — LEP v0.2.1.1 freeze-then-open-test lifecycle."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v0211.baseline import verify_baseline
from human_simulator.longitudinal_event_probability_v0211.defect_reproduction import (
    reproduce_v021_defects,
)
from human_simulator.longitudinal_event_probability_v0211.engine import run_engine_shadow
from human_simulator.longitudinal_event_probability_v0211.estimators import payload_identity_sha256
from human_simulator.longitudinal_event_probability_v0211.event_identity import build_event_identity
from human_simulator.longitudinal_event_probability_v0211.freeze import (
    freeze_status,
    mark_test_opened,
    verify_pretest_freeze,
    write_pretest_freeze,
)
from human_simulator.longitudinal_event_probability_v0211.landmarks import build_landmark_datasets
from human_simulator.longitudinal_event_probability_v0211.observation_window import (
    build_observation_windows,
)
from human_simulator.longitudinal_event_probability_v0211.ood import fit_ood_pretest, score_test_ood
from human_simulator.longitudinal_event_probability_v0211.policy import (
    ARTIFACT_DIR,
    EXCURSION_ENDPOINT,
    MODELS_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.longitudinal_event_probability_v0211.regimes import correct_regimes
from human_simulator.longitudinal_event_probability_v0211.registry import build_registry
from human_simulator.longitudinal_event_probability_v0211.survival import (
    evaluate_test_frozen,
    train_and_freeze_endpoint,
)
from human_simulator.unified_individual_state_v0111.privacy_scan import scan_public

ENDPOINT_FILES = {
    "TIME_TO_NEXT_LAB_PANEL": "landmark_lab_panel.parquet",
    "TIME_TO_NEXT_ENCOUNTER": "landmark_encounter.parquet",
    "TIME_TO_NEXT_RECORDED_EVENT": "landmark_recorded_event_diagnostic.parquet",
}
RESULTS_CACHE = "pre-test-endpoint-results.json"


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
    out = {k: v for k, v in res.items() if k not in {"model", "test_held_rows"}}
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
        "MODEL_PAYLOAD_IDENTITY_STATUS": "PASS" if ok else "FAIL",
        "n": len(details),
        "details_public": [{k: v for k, v in d.items() if k != "weights"} for d in details],
    }


def _train_all(root: Path, identity: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for endpoint in ("TIME_TO_NEXT_LAB_PANEL", "TIME_TO_NEXT_ENCOUNTER"):
        for ss, label in (("magerya_api", "A"), ("kgz_raw", "B")):
            print(json.dumps({"phase": "obs_tte", "endpoint": endpoint, "source": label}), flush=True)
            results.append(
                train_and_freeze_endpoint(
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
    thr_path = (
        root
        / "private/longitudinal-event-probability-v0211/landmarks/excursion-thresholds-train-only.json"
    )
    selected = []
    if thr_path.is_file():
        thr = json.loads(thr_path.read_text(encoding="utf-8"))
        for _ss, keys in (thr.get("selected_outcomes_by_source") or {}).items():
            selected.extend(keys)
        for note in thr.get("selection_notes") or []:
            results.append(
                {
                    "status": "NOT_RUN",
                    "endpoint": EXCURSION_ENDPOINT,
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
            train_and_freeze_endpoint(
                root,
                parquet_name="landmark_outcome_excursion.parquet",
                endpoint_name=EXCURSION_ENDPOINT,
                source_system=ss,
                outcome_key=outcome,
            )
        )
    _ = identity
    return results


def _persist_results_cache(root: Path, results: list[dict[str, Any]]) -> None:
    serializable = []
    for r in results:
        serializable.append(_public_model_result(r))
    (root / MODELS_DIR / RESULTS_CACHE).write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _load_frozen_results(root: Path) -> list[dict[str, Any]]:
    path = root / MODELS_DIR / RESULTS_CACHE
    cached = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for rec in cached:
        rec = dict(rec)
        fname = rec.get("frozen_file")
        if fname:
            model_path = root / MODELS_DIR / fname
            rec["model"] = json.loads(model_path.read_text(encoding="utf-8"))
        out.append(rec)
    return out


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    """Train + freeze. Does not open test. Publication requires open-test afterwards."""
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

    print(json.dumps({"phase": "v021_defect_reproduction"}), flush=True)
    defects = reproduce_v021_defects(root)
    _write_json(art / "v021-defect-reproduction.json", defects["defects"])
    _write_json(art / "v021-cell-acceptance-correction.json", defects["cell_acceptance_correction"])
    _write_json(art / "v021-foundation-acceptance-matrix.json", defects["matrix"])
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
    print(json.dumps({"phase": "survival_models_freeze"}), flush=True)
    results = _train_all(root, identity)
    _write_json(art / "survival-evaluation.json", {"results": [_public_model_result(r) for r in results], "test_opened": False})

    print(json.dumps({"phase": "ood_pretest"}), flush=True)
    ood = fit_ood_pretest(root, ENDPOINT_FILES[primary])
    _write_json(art / "applicability-ood.json", ood)

    print(json.dumps({"phase": "regimes_carry"}), flush=True)
    regimes = correct_regimes(root)
    _write_json(art / "regime-methodology-correction.json", regimes)

    reload = _reload_check(root, results)
    _write_json(art / "survival-model-reload.json", reload)

    print(json.dumps({"phase": "pretest_registry"}), flush=True)
    registry = build_registry(
        root,
        results,
        primary_endpoint=primary,
        ood_integrity="FROZEN" if ood.get("ok") else "FAIL",
        freeze_ok=False,
    )
    public_reg = json.loads(json.dumps(registry))
    for c in (public_reg.get("cells") or {}).values():
        c.pop("calibrator", None)
    _write_json(art / "accepted-probability-registry-public.json", public_reg)
    _persist_results_cache(root, results)
    freeze = write_pretest_freeze(
        root,
        registry=registry,
        results_public=[_public_model_result(r) for r in results],
        extra_files=[RESULTS_CACHE],
    )
    _write_json(art / "pre-test-freeze.json", freeze)

    priv = scan_public(art)
    _write_json(art / "public-privacy-scan.json", priv)

    any_km = any(r.get("KAPLAN_MEIER_BASELINE_STATUS") == "BUILT" for r in results)
    any_haz = any(r.get("DISCRETE_TIME_HAZARD_MODEL_STATUS") == "TRAINED" for r in results)
    freeze_ok = freeze.get("ok") and reload.get("ok")
    status = {
        "version": VERSION,
        "generated_at": _now(),
        "phase": "PRE_TEST_FREEZE",
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V021_DEFECT_REPRODUCTION_STATUS": defects["defects"].get("V021_DEFECT_REPRODUCTION_STATUS"),
        "OUTCOME_EXCURSION_RISK_SET_STATUS": landmarks.get("OUTCOME_EXCURSION_LANDMARK_DATASET_STATUS"),
        "OUTCOME_EXCURSION_ASCERTAINMENT_STATUS": (
            "PUBLISHED" if landmarks.get("no_post_t0_ascertainment_opportunity") else "NOT_RUN"
        ),
        "HORIZON_IDENTIFIABILITY_STATUS": "DECLARED",
        "IPCW_POSITIVITY_STATUS": "DECLARED",
        "CALIBRATOR_FIT_STATUS": "FITTED_PRE_TEST",
        "CALIBRATION_EVALUATION_STATUS": "INDEPENDENT_EVAL_PRE_TEST",
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "TEST_ACCESS_LIFECYCLE_STATUS": "FROZEN_CLOSED",
        "MODEL_PAYLOAD_IDENTITY_STATUS": reload.get("MODEL_PAYLOAD_IDENTITY_STATUS"),
        "OOD_ARTIFACT_INTEGRITY_STATUS": ood.get("OOD_ARTIFACT_INTEGRITY_STATUS"),
        "CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS": registry.get("CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS"),
        "VALIDATION_ACCEPTED_CELL_COUNT": registry.get("VALIDATION_ACCEPTED_CELL_COUNT"),
        "HELDOUT_TEST_CONFIRMED_CELL_COUNT": 0,
        "ENGINE_ELIGIBLE_CELL_COUNT": 0,
        "TECHNICAL_PROBABILITY_FOUNDATION_STATUS": "PENDING_OPEN_TEST",
        "ENGINE_MODEL_ROUTING_STATUS": "PENDING_OPEN_TEST",
        "ENGINE_SURVIVAL_INFERENCE_STATUS": "PENDING_OPEN_TEST",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PENDING_OPEN_TEST",
        "KAPLAN_MEIER_BASELINE_STATUS": "BUILT" if any_km else "NOT_RUN",
        "DISCRETE_TIME_HAZARD_MODEL_STATUS": "TRAINED" if any_haz else "NOT_RUN",
        "SURVIVAL_MODEL_RELOAD_STATUS": reload.get("SURVIVAL_MODEL_RELOAD_STATUS"),
        "REGIME_FOUNDATION_ACCEPTANCE_STATUS": "NOT_ACCEPTED_RETROSPECTIVE_ONLY",
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
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
        "open_test_required": True,
    }
    _write_json(art / "status-contract.json", status)
    _write_md(
        art / "stage-report.md",
        f"""# Unified Longitudinal Event Probability Foundation v{VERSION}

**Report status: DRAFT**

Pre-test freeze complete. Test is not opened. Run `open-test-v0.2.1.1` then `publish-v0.2.1.1`.

PRE_TEST_PHYSICAL_FREEZE_STATUS=`{status['PRE_TEST_PHYSICAL_FREEZE_STATUS']}`
""",
    )
    _write_json(
        art / "verification.json",
        {
            "version": VERSION,
            "ok": False,
            "reason": "OPEN_TEST_REQUIRED",
            "TECHNICAL_PASS": False,
            "duration_seconds": round(time.time() - t0, 3),
            "status": status,
            "freeze_ok": freeze_ok,
        },
    )
    write_manifest(art)
    _ = no_publish
    return {
        "ok": True,
        "frozen": True,
        "test_opened": False,
        "artifact_dir": str(art),
        "duration_seconds": round(time.time() - t0, 3),
        "status": status,
    }


def _parquet_for(endpoint: str) -> str:
    if endpoint == EXCURSION_ENDPOINT:
        return "landmark_outcome_excursion.parquet"
    return ENDPOINT_FILES.get(endpoint) or "landmark_lab_panel.parquet"


def open_test(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    t0 = time.time()
    freeze = verify_pretest_freeze(root)
    _write_json(art / "pre-test-freeze-verify.json", freeze)
    if not freeze.get("ok"):
        return {"ok": False, "error": "FREEZE_VERIFY_FAIL", "freeze": freeze}
    mark_test_opened(root)

    identity = json.loads((art / "observation-event-identity.json").read_text(encoding="utf-8"))
    landmarks = json.loads((art / "landmark-datasets.json").read_text(encoding="utf-8"))
    primary = identity["primary_endpoint"]
    results = _load_frozen_results(root)
    print(json.dumps({"phase": "open_test"}), flush=True)
    opened = []
    for rec in results:
        if rec.get("frozen_file"):
            rec = evaluate_test_frozen(root, rec, parquet_name=_parquet_for(rec["endpoint"]))
        opened.append(rec)
    _write_json(
        art / "survival-evaluation.json",
        {"results": [_public_model_result(r) for r in opened], "test_opened": True},
    )

    ood = score_test_ood(root, ENDPOINT_FILES[primary])
    _write_json(art / "applicability-ood.json", ood)
    ood_integrity = "PASS" if ood.get("ok") is not False else "FAIL"
    if ood.get("error"):
        ood_integrity = "FAIL"

    reload = json.loads((art / "survival-model-reload.json").read_text(encoding="utf-8"))
    registry = build_registry(
        root,
        opened,
        primary_endpoint=primary,
        ood_integrity="PASS" if ood_integrity == "PASS" else "FAIL",
        freeze_ok=True,
    )
    public_reg = json.loads(json.dumps(registry))
    for c in (public_reg.get("cells") or {}).values():
        c.pop("calibrator", None)
    _write_json(art / "accepted-probability-registry-public.json", public_reg)

    print(json.dumps({"phase": "engine_shadow"}), flush=True)
    shadow = run_engine_shadow(root)
    _write_json(art / "engine-survival-shadow.json", shadow)

    priv = scan_public(art)
    _write_json(art / "public-privacy-scan.json", priv)

    any_km = any(r.get("KAPLAN_MEIER_BASELINE_STATUS") == "BUILT" for r in opened)
    any_haz = any(r.get("DISCRETE_TIME_HAZARD_MODEL_STATUS") == "TRAINED" for r in opened)
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

    baseline = json.loads((art / "baseline-verification.json").read_text(encoding="utf-8"))
    defects = json.loads((art / "v021-defect-reproduction.json").read_text(encoding="utf-8"))
    windows = json.loads((art / "administrative-observation-windows.json").read_text(encoding="utf-8"))
    regimes = json.loads((art / "regime-methodology-correction.json").read_text(encoding="utf-8"))
    ood_art = json.loads((art / "applicability-ood.json").read_text(encoding="utf-8"))

    ident_cells = [
        c.get("horizon_identifiability_status")
        for c in (registry.get("cells") or {}).values()
        if c.get("horizon_days") is not None
    ]
    ipcw_cells = [
        ((c.get("validation_gates") or {}).get("ipcw_effective_n"))
        for c in (registry.get("cells") or {}).values()
        if c.get("horizon_days") is not None
    ]
    horizon_status = (
        "PASS"
        if any(s == "PASS" for s in ident_cells)
        or any(
            s == "NOT_ACCEPTED_ADMINISTRATIVE_BOUNDARY_NON_IDENTIFIABLE" for s in ident_cells
        )
        else "FAIL"
    )
    if all(
        s in {None, "NOT_RUN"} or str(s).startswith("NOT_RUN")
        for s in ident_cells
    ) and ident_cells:
        horizon_status = "DECLARED"

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "phase": "OPEN_TEST",
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V021_DEFECT_REPRODUCTION_STATUS": defects.get("V021_DEFECT_REPRODUCTION_STATUS"),
        "OUTCOME_EXCURSION_RISK_SET_STATUS": landmarks.get(
            "OUTCOME_EXCURSION_LANDMARK_DATASET_STATUS"
        ),
        "OUTCOME_EXCURSION_ASCERTAINMENT_STATUS": (
            "PUBLISHED" if landmarks.get("no_post_t0_ascertainment_opportunity") else "NOT_RUN"
        ),
        "HORIZON_IDENTIFIABILITY_STATUS": horizon_status,
        "IPCW_POSITIVITY_STATUS": "PUBLISHED",
        "CALIBRATOR_FIT_STATUS": "FITTED_PRE_TEST",
        "CALIBRATION_EVALUATION_STATUS": "INDEPENDENT_EVAL",
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": freeze.get("PRE_TEST_PHYSICAL_FREEZE_STATUS"),
        "TEST_ACCESS_LIFECYCLE_STATUS": "OPENED",
        "MODEL_PAYLOAD_IDENTITY_STATUS": reload.get("MODEL_PAYLOAD_IDENTITY_STATUS"),
        "OOD_ARTIFACT_INTEGRITY_STATUS": shadow.get("OOD_ARTIFACT_INTEGRITY_STATUS")
        or ood_art.get("OOD_ARTIFACT_INTEGRITY_STATUS"),
        "CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS": registry.get(
            "CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS"
        ),
        "VALIDATION_ACCEPTED_CELL_COUNT": registry.get("VALIDATION_ACCEPTED_CELL_COUNT"),
        "HELDOUT_TEST_CONFIRMED_CELL_COUNT": registry.get("HELDOUT_TEST_CONFIRMED_CELL_COUNT"),
        "ENGINE_ELIGIBLE_CELL_COUNT": registry.get("ENGINE_ELIGIBLE_CELL_COUNT"),
        "TECHNICAL_PROBABILITY_FOUNDATION_STATUS": tech_label,
        "SURVIVAL_MODEL_FREEZE_STATUS": "FROZEN" if freeze_ok and registry["frozen_model_count"] else "FAIL",
        "SURVIVAL_MODEL_RELOAD_STATUS": reload.get("SURVIVAL_MODEL_RELOAD_STATUS"),
        "REGIME_NUMERICAL_STABILITY_STATUS": regimes.get("REGIME_NUMERICAL_STABILITY_STATUS"),
        "REGIME_CONFOUNDING_STATUS": regimes.get("REGIME_CONFOUNDING_STATUS"),
        "REGIME_FOUNDATION_ACCEPTANCE_STATUS": "NOT_ACCEPTED_RETROSPECTIVE_ONLY",
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": ood_art.get(
            "SOURCE_STRATIFIED_APPLICABILITY_STATUS"
        ),
        "APPLICABILITY_FOUNDATION_STATUS": ood_art.get("APPLICABILITY_FOUNDATION_STATUS"),
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
        "ipcw_effective_n_published": any(v is not None for v in ipcw_cells),
    }
    engine_ok = status["ENGINE_SURVIVAL_INFERENCE_STATUS"] in {
        "TECHNICAL_SHADOW_PASS",
        "TECHNICAL_SHADOW_ROUTING_PASS_NO_ACCEPTED_CELL",
    }
    technical = (
        status["BASELINE_VERIFICATION_STATUS"] == "PASS"
        and status["V021_DEFECT_REPRODUCTION_STATUS"] == "PASS"
        and status["PRE_TEST_PHYSICAL_FREEZE_STATUS"] in {"FROZEN", "VERIFIED"}
        and status["TEST_ACCESS_LIFECYCLE_STATUS"] == "OPENED"
        and windows.get("ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS") == "BUILT"
        and identity.get("OBSERVATION_EVENT_IDENTITY_STATUS") == "BUILT"
        and landmarks.get("OBSERVATION_PROCESS_LANDMARK_DATASET_STATUS") == "BUILT"
        and landmarks.get("LANDMARK_TEMPORAL_LEAKAGE_STATUS") == "PASS"
        and any_km
        and any_haz
        and status["SURVIVAL_MODEL_FREEZE_STATUS"] == "FROZEN"
        and status["SURVIVAL_MODEL_RELOAD_STATUS"] == "PASS"
        and status["CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS"] == "BUILT"
        and engine_ok
        and status["ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"]
        == "PASS_NO_FUTURE_HORIZON_READ"
        and status["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
        and status["SCIENTIFIC_CROSS_SOURCE_PASS"] is False
        and status["STATE_ENCODER_STATUS"] == "NOT_ACCEPTED"
        and status["REGIME_FOUNDATION_ACCEPTANCE_STATUS"] == "NOT_ACCEPTED_RETROSPECTIVE_ONLY"
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

## Phase 0 — v0.2.1 defect reproduction

- V021_DEFECT_REPRODUCTION_STATUS: `{status['V021_DEFECT_REPRODUCTION_STATUS']}`
- v0.2.1 accepted-cell count of 9 is not transferred.

## Risk-set / excursion

- Endpoint: `{EXCURSION_ENDPOINT}`
- Recorded laboratory excursion, not latent biology.
- OUTCOME_EXCURSION_RISK_SET_STATUS: `{status['OUTCOME_EXCURSION_RISK_SET_STATUS']}`
- OUTCOME_EXCURSION_ASCERTAINMENT_STATUS: `{status['OUTCOME_EXCURSION_ASCERTAINMENT_STATUS']}`

## Horizon / calibration / freeze

- HORIZON_IDENTIFIABILITY_STATUS: `{status['HORIZON_IDENTIFIABILITY_STATUS']}`
- IPCW_POSITIVITY_STATUS: `{status['IPCW_POSITIVITY_STATUS']}`
- CALIBRATION_EVALUATION_STATUS: `{status['CALIBRATION_EVALUATION_STATUS']}`
- PRE_TEST_PHYSICAL_FREEZE_STATUS: `{status['PRE_TEST_PHYSICAL_FREEZE_STATUS']}`
- TEST_ACCESS_LIFECYCLE_STATUS: `{status['TEST_ACCESS_LIFECYCLE_STATUS']}`

## Cells (recalculated)

- VALIDATION_ACCEPTED_CELL_COUNT: {status['VALIDATION_ACCEPTED_CELL_COUNT']}
- HELDOUT_TEST_CONFIRMED_CELL_COUNT: {status['HELDOUT_TEST_CONFIRMED_CELL_COUNT']}
- ENGINE_ELIGIBLE_CELL_COUNT: {status['ENGINE_ELIGIBLE_CELL_COUNT']}
- TECHNICAL_PROBABILITY_FOUNDATION_STATUS: `{status['TECHNICAL_PROBABILITY_FOUNDATION_STATUS']}`

## Engine

- Routing: `{status['ENGINE_MODEL_ROUTING_STATUS']}`
- Inference: `{status['ENGINE_SURVIVAL_INFERENCE_STATUS']}`
- Future leakage: `{status['ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS']}`
- OOD integrity: `{status['OOD_ARTIFACT_INTEGRITY_STATUS']}`

## Non-claims

STATE_ENCODER_STATUS=NOT_ACCEPTED
REGIME_FOUNDATION_ACCEPTANCE_STATUS=NOT_ACCEPTED_RETROSPECTIVE_ONLY
SCIENTIFIC_CROSS_SOURCE_PASS=false
DOMAIN_ACCEPTED_MAPPING_COUNT=0
CLINICAL_VALIDATION_STATUS=NOT_STARTED
PRODUCTION_READINESS=NOT_CLAIMED
SECURITY_STAGE_STATUS=PAUSED_NOT_ACCEPTED_BY_OWNER
MEDICATION_RESIDUAL_MODEL_STATUS=NOT_STARTED

Next stage is First Source-Aware Medication Residual Foundation v0.1. Zero accepted probability cells do not block that transition.

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
    return {
        "ok": technical,
        "artifact_dir": str(art),
        "duration_seconds": round(time.time() - t0, 3),
        "status": status,
        "freeze": freeze_status(root),
    }
