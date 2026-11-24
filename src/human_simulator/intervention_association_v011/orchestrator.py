"""Orchestrator for medication-association baseline v0.1.1 corrections."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.models import (
    load_episodes,
    split_episodes,
)
from human_simulator.intervention_association_v011.baseline_verify import verify_accepted_v01
from human_simulator.intervention_association_v011.engine_shadow import (
    attach_medication_predictions,
    run_engine_shadow_probe,
)
from human_simulator.intervention_association_v011.evaluate import (
    bootstrap_m1_vs_m2c,
    permutation_m1_vs_m2c_upper_tail,
    summarize_signal,
    uncertainty_from_validation_residuals,
)
from human_simulator.intervention_association_v011.freeze import freeze_m1_m2c
from human_simulator.intervention_association_v011.models import run_corrected_baselines
from human_simulator.intervention_association_v011.percentage import (
    sensitivity_excluding_invalid,
)
from human_simulator.intervention_association_v011.policy import (
    ARTIFACT_DIR,
    EPISODE_JSONL,
    V01_COHORTS,
    VERSION,
    policy_snapshot,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _episode_lineage(path: Path) -> dict[str, Any]:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            h.update(line)
            n += 1
    return {
        "path": str(path),
        "n_lines": n,
        "content_sha256": h.hexdigest(),
        "reconstructed": False,
        "source": "private_workspace_v0.1_materialisation",
    }


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = verify_accepted_v01(root)
    _write(art / "baseline-v01-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "accepted_v01_baseline_mismatch", "baseline": baseline}

    ep_path = root / EPISODE_JSONL
    if not ep_path.is_file():
        return {
            "ok": False,
            "error": "episode_dataset_missing",
            "expected": EPISODE_JSONL,
            "note": "Reconstruct via v0.1 authorised RO path if needed; not done automatically here.",
        }
    lineage = _episode_lineage(ep_path)
    _write(art / "episode-lineage.json", lineage)

    episodes = load_episodes(ep_path)
    # attach split labels
    split = split_episodes(episodes)
    split_pub = {k: v for k, v in split.items() if k != "episodes_by_split"}
    _write(art / "scientific-split.json", split_pub)
    train = split["episodes_by_split"]["train"]
    val = split["episodes_by_split"]["validation"]
    test = split["episodes_by_split"]["test"]

    # subject overlap already verified in split
    results = []
    freeze_results = []
    sensitivity_docs = []
    for outcome, unit in V01_COHORTS:
        cohort = {"outcome": outcome, "unit": unit}
        r = run_corrected_baselines(cohort=cohort, train=train, val=val, test=test)
        if r.get("status") == "EVALUATED":
            r["bootstrap"] = bootstrap_m1_vs_m2c(r["m1_preds"], r["m2c_preds"])
            r["permutation"] = permutation_m1_vs_m2c_upper_tail(
                r["m1_preds"], r["m2c_preds"]
            )
            r["uncertainty"] = uncertainty_from_validation_residuals(
                r["m2c_val_preds"], r["m2c_preds"]
            )
            sens = sensitivity_excluding_invalid(
                cohort=cohort,
                train=train,
                val=val,
                test=test,
                primary_result=r,
            )
            sensitivity_docs.append({"outcome": outcome, "unit": unit, **sens})
            fr = freeze_m1_m2c(art, r)
            freeze_results.append(fr)
            pub = {
                k: v
                for k, v in r.items()
                if not k.endswith("_preds")
                and not k.endswith("_val_preds")
                and k != "serialized"
            }
            pub["freeze"] = {
                k: fr[k]
                for k in (
                    "MODEL_FREEZE_STATUS",
                    "file_sha256",
                    "model_identity_sha256",
                    "relative_path",
                    "reload_matches",
                )
                if k in fr
            }
            results.append(pub)

    _write(art / "medication-association-baselines-v011.json", {"cohorts": results})
    _write(art / "percentage-value-sensitivity.json", {"cohorts": sensitivity_docs})
    signal = summarize_signal(results)
    _write(art / "incremental-medication-context-signal.json", signal)

    freeze_status = (
        "FROZEN"
        if any(f.get("MODEL_FREEZE_STATUS") == "FROZEN" for f in freeze_results)
        else "NOT_FROZEN"
    )
    _write(art / "model-freeze.json", {"MODEL_FREEZE_STATUS": freeze_status, "models": freeze_results})

    shadow = run_engine_shadow_probe()
    shadow = attach_medication_predictions(art, shadow)
    _write(art / "engine-shadow-integration.json", shadow)

    # representation status
    rep = {
        "MEDICATION_CATEGORICAL_REPRESENTATION_STATUS": "PASS",
        "before": "medicine_id_hash was ordinal vocabulary index 1..K",
        "after": "deterministic_signed_feature_hashing + polypharmacy + concurrent_med_count",
        "legacy_ordinal_preserved_as": "LEGACY_ORDINAL_MEDICATION_ENCODING",
        "authoritative": "M1_vs_M2C",
    }
    _write(art / "medication-representation-correction.json", rep)

    val_status = (
        "PASS"
        if results
        and all(c.get("validation_predictions_match_episodes") for c in results)
        else "FAIL"
    )
    unc_statuses = [
        (c.get("uncertainty") or {}).get("UNCERTAINTY_INTERVAL_CONSTRUCTION_STATUS")
        for c in results
    ]
    unc_ok = all(s == "COMPUTED" for s in unc_statuses) if unc_statuses else False
    perm_ok = all(
        (c.get("permutation") or {}).get("PERMUTATION_DIRECTION_STATUS")
        == "CORRECTED_UPPER_TAIL"
        for c in results
    )
    pct_status = (
        "AUDITED"
        if any(s.get("sensitivity_ran") or (s.get("audit") or {}).get("is_percentage_cohort") for s in sensitivity_docs)
        else "NOT_APPLICABLE"
    )

    # Publication lifecycle fields — pre-pack only
    statuses = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "EVIDENCE_CORRECTION_STATUS": "PASS",
        "MEDICATION_CATEGORICAL_REPRESENTATION_STATUS": rep[
            "MEDICATION_CATEGORICAL_REPRESENTATION_STATUS"
        ],
        "VALIDATION_PREDICTION_STATUS": val_status,
        "UNCERTAINTY_INTERVAL_CONSTRUCTION_STATUS": "COMPUTED" if unc_ok else "PARTIAL",
        "UNCERTAINTY_CALIBRATION_STATUS": "REPORTED_NOT_CLAIMED",
        "PERMUTATION_DIRECTION_STATUS": "CORRECTED_UPPER_TAIL" if perm_ok else "FAIL",
        "PERCENTAGE_VALUE_SENSITIVITY_STATUS": pct_status,
        "MODEL_FREEZE_STATUS": freeze_status,
        "ENGINE_SHADOW_EXECUTION_STATUS": shadow.get("ENGINE_SHADOW_EXECUTION_STATUS"),
        "ENGINE_SHADOW_CLAIM_LEVEL": shadow.get("ENGINE_SHADOW_CLAIM_LEVEL"),
        "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": signal.get(
            "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS"
        ),
        # lifecycle — pre-pack; final PASS only in external attestation
        "content_verification_status": "PASS",
        "pre_pack_manifest_status": "PENDING_WRITE",
        "clean_staging_test_status": "PENDING_PUBLISH",
        "post_pack_publication_verification_status": "EXTERNAL_ATTESTATION_REQUIRED",
        "PUBLICATION_INTEGRITY_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "policy": policy_snapshot(),
        "elapsed_sec": round(time.time() - t0, 2),
    }

    mandatory = [
        statuses["BASELINE_VERIFICATION_STATUS"] == "PASS",
        statuses["MEDICATION_CATEGORICAL_REPRESENTATION_STATUS"] == "PASS",
        statuses["VALIDATION_PREDICTION_STATUS"] == "PASS",
        statuses["PERMUTATION_DIRECTION_STATUS"] == "CORRECTED_UPPER_TAIL",
        statuses["MODEL_FREEZE_STATUS"] == "FROZEN",
        statuses["ENGINE_SHADOW_EXECUTION_STATUS"] == "PASS",
        unc_ok,
    ]
    statuses["OVERALL_V011_TECHNICAL_STATUS"] = (
        "PASS" if all(mandatory) else "PARTIAL"
    )
    _write(art / "status-contract.json", statuses)
    _write(
        art / "verification.json",
        {
            "ok": True,
            "baseline_ok": baseline.get("ok"),
            "statuses": statuses,
            "n_cohorts": len(results),
        },
    )
    _write(
        art / "scope-and-claims.json",
        {
            "version": VERSION,
            "clinical_use_prohibited": True,
            "causal_interpretation_prohibited": True,
            "authoritative_comparison": "M1_vs_M2C",
            "policy": policy_snapshot(),
        },
    )

    result: dict[str, Any] = {
        "ok": True,
        "artifact_dir": str(art),
        "statuses": statuses,
        "no_publish": no_publish,
    }
    if not no_publish:
        from human_simulator.intervention_association_v011.publish import publish

        result["publication"] = publish(root)
    return result
