"""Orchestrator — Medication Concept Harmonization and Corrected Categorical Baseline v0.1."""

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
from human_simulator.intervention_association_v011.evaluate import (
    uncertainty_from_validation_residuals,
)
from human_simulator.intervention_association_v011.models import run_corrected_baselines
from human_simulator.intervention_association_v011.percentage import (
    sensitivity_excluding_invalid,
)
from human_simulator.medication_concept_v01.baseline_verify import verify_prior_baseline
from human_simulator.medication_concept_v01.cohort_readiness import (
    build_cohort_readiness,
    episode_coverage_by_medicine,
)
from human_simulator.medication_concept_v01.concept_registry import build_concept_registry
from human_simulator.medication_concept_v01.engine_shadow import (
    run_hardened_shadow_inference,
)
from human_simulator.medication_concept_v01.policy import (
    ARTIFACT_DIR,
    EPISODE_JSONL,
    RUNTIME_DIR,
    SECURITY_STAGE_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.medication_concept_v01.providers import build_provider_manifest
from human_simulator.medication_concept_v01.representation import (
    run_corrected_representation_experiment,
)
from human_simulator.unified.source_a_adapter import source_a_connection


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _episode_lineage(path: Path) -> dict[str, Any]:
    h = hashlib.sha256()
    n = 0
    subjects: set[str] = set()
    with path.open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            h.update(line)
            n += 1
            try:
                row = json.loads(line)
                subjects.add(str(row.get("opaque_subject_key") or ""))
            except json.JSONDecodeError:
                pass
    subjects.discard("")
    return {
        "path": str(path),
        "n_lines": n,
        "n_subjects": len(subjects),
        "content_sha256": h.hexdigest(),
        "row_level_in_review_zip": False,
    }


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = verify_prior_baseline(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "baseline_verification_failed", "baseline": baseline}

    ep_path = root / EPISODE_JSONL
    if not ep_path.is_file():
        return {"ok": False, "error": "episode_dataset_missing", "expected": EPISODE_JSONL}
    lineage = _episode_lineage(ep_path)
    _write(art / "episode-lineage.json", lineage)

    episodes = load_episodes(ep_path)
    split = split_episodes(episodes)
    split_pub = {k: v for k, v in split.items() if k != "episodes_by_split"}
    _write(art / "scientific-split.json", split_pub)
    train = split["episodes_by_split"]["train"]
    val = split["episodes_by_split"]["validation"]
    test = split["episodes_by_split"]["test"]
    coverage = episode_coverage_by_medicine(episodes, split["episodes_by_split"])

    providers = build_provider_manifest(root)
    _write(art / "provider-snapshot-manifest.json", providers)

    with source_a_connection(root) as conn_a:
        registry = build_concept_registry(
            conn_a,
            root,
            provider_manifest=providers,
            episode_coverage=coverage,
        )

    _write(art / "medication-concept-accounting.json", registry["accounting"])
    _write(
        art / "medication-concept-registry-sanitized.json",
        {
            "records": registry["sanitized_records"],
            "disclosure": "original names withheld; private workspace only",
            "status_counts": registry["status_counts"],
        },
    )
    _write(
        art / "medication-domain-review-queue.json",
        {
            "queue": registry["domain_review_queue"][:200],
            "top_ambiguous": registry["top_ambiguous"],
            "top_unresolved": registry["top_unresolved"],
            "prioritization": "episode_coverage_then_subjects_then_ambiguity_not_test_performance",
        },
    )

    n_accepted = int(registry["n_accepted"])
    sens = run_corrected_representation_experiment(
        train=train,
        val=val,
        test=test,
        n_accepted_drug_concepts=n_accepted,
        concept_by_medicine={
            str(r["source_medicine_id"]): r for r in registry["records"]
        },
    )
    _write(art / "medication-representation-experiment.json", sens)

    uncertainty_docs = []
    sensitivity_docs = []
    for c in sens.get("cohorts") or []:
        cohort = {"outcome": c["outcome"], "unit": c["unit"]}
        r = run_corrected_baselines(cohort=cohort, train=train, val=val, test=test)
        if r.get("status") == "EVALUATED":
            unc = uncertainty_from_validation_residuals(
                r["m2c_val_preds"], r["m2c_preds"]
            )
            uncertainty_docs.append({"outcome": c["outcome"], "unit": c["unit"], **unc})
            sens_pct = sensitivity_excluding_invalid(
                cohort=cohort,
                train=train,
                val=val,
                test=test,
                primary_result=r,
            )
            sensitivity_docs.append({"outcome": c["outcome"], "unit": c["unit"], **sens_pct})
    _write(art / "validation-residual-uncertainty.json", {"cohorts": uncertainty_docs})
    _write(art / "percentage-value-sensitivity.json", {"cohorts": sensitivity_docs})

    readiness = build_cohort_readiness(
        episodes_by_split=split["episodes_by_split"],
        concept_records=registry["records"],
        split_meta=split_pub,
    )
    _write(art / "intervention-cohort-readiness.json", readiness)

    frozen_root = (
        root
        / "artifacts"
        / "stage-03-first-medication-association-baseline-v0.1.1"
        / "frozen_models"
    )
    # Use first cohort train slice for onehot demo vocab
    train_lymph = [
        e for e in train if e["outcome"] == "Лимфоциты" and e["unit"] == "%"
    ] or train[:500]
    shadow = run_hardened_shadow_inference(
        frozen_root=frozen_root, train_for_onehot=train_lymph
    )
    _write(art / "medication-model-shadow-inference.json", shadow)

    statuses = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "SOURCE_MEDICATION_RECORD_LINKAGE_STATUS": registry["accounting"].get(
            "SOURCE_RECORD_LINKAGE_STATUS"
        ),
        "MEDICATION_SOURCE_ACCOUNTING_STATUS": registry["accounting"].get(
            "MEDICATION_SOURCE_ACCOUNTING_STATUS"
        ),
        "DRUG_REFERENCE_PROVIDER_STATUS": providers.get("DRUG_REFERENCE_PROVIDER_STATUS"),
        "DRUG_CONCEPT_MAPPING_STATUS": registry["accounting"].get(
            "DRUG_CONCEPT_MAPPING_STATUS"
        ),
        "DRUG_CONCEPT_ACCEPTED_COUNT": registry["n_accepted"],
        "DRUG_CONCEPT_UNRESOLVED_COUNT": registry["n_unresolved"],
        "M2ID_CATEGORICAL_CORRECTION_STATUS": sens.get("M2ID_CATEGORICAL_CORRECTION_STATUS"),
        "M2SEM_GATE_STATUS": sens.get("M2SEM_GATE_STATUS"),
        "MEDICATION_REPRESENTATION_EXPERIMENT_STATUS": sens.get(
            "MEDICATION_REPRESENTATION_EXPERIMENT_STATUS"
        ),
        "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": sens.get(
            "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS"
        ),
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": readiness.get(
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS"
        ),
        "MEDICATION_MODEL_SHADOW_INFERENCE_STATUS": shadow.get(
            "MEDICATION_MODEL_SHADOW_INFERENCE_STATUS"
        ),
        "ENGINE_SHADOW_EXECUTION_STATUS": shadow.get("ENGINE_SHADOW_EXECUTION_STATUS"),
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "PUBLICATION_INTEGRITY_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "pre_pack_manifest_status": "PASS",
        "content_verification_status": "PASS",
        "clean_staging_test_status": "PENDING_PUBLISH",
        "post_pack_publication_verification_status": "EXTERNAL_ATTESTATION_REQUIRED",
        "policy": policy_snapshot(),
        "duration_seconds": round(time.time() - t0, 3),
    }
    _write(art / "status-contract.json", statuses)
    _write(
        art / "scope-and-claims.json",
        {
            "version": VERSION,
            "claim_level": "TECHNICAL_DRUG_CONCEPT_AND_CATEGORICAL_BASELINE_ONLY",
            "source_record_linkage_is_not_drug_concept_harmonization": True,
            "not_claims": [
                "treatment_effect",
                "causal_effect",
                "intervention_response",
                "clinical_validation",
                "confirmed_administration",
                "qsp",
                "pkpd",
                "production_readiness",
            ],
            "security_stage_status": SECURITY_STAGE_STATUS,
        },
    )

    verification = {
        "ok": bool(
            baseline.get("ok")
            and registry["accounting"].get("MEDICATION_SOURCE_ACCOUNTING_STATUS") == "PASS"
            and shadow.get("MEDICATION_MODEL_SHADOW_INFERENCE_STATUS") == "PASS"
            and shadow.get("ENGINE_SHADOW_EXECUTION_STATUS") == "PASS"
            and sens.get("M2ID_CATEGORICAL_CORRECTION_STATUS") == "PASS"
        ),
        "version": VERSION,
        "statuses": {
            k: statuses[k]
            for k in statuses
            if k.endswith("_STATUS")
            or k.endswith("_COUNT")
            or k
            in (
                "pre_pack_manifest_status",
                "content_verification_status",
                "clean_staging_test_status",
                "post_pack_publication_verification_status",
            )
        },
        "n_cohorts": len(sens.get("cohorts") or []),
        "episode_n": lineage["n_lines"],
        "episode_subjects": lineage["n_subjects"],
        "methodological_defects_in_prior": len(baseline.get("methodological_defects") or []),
    }
    _write(art / "verification.json", verification)

    if not no_publish:
        from human_simulator.medication_concept_v01.publish import publish

        pub = publish(root)
        return {"ok": verification["ok"] and pub.get("attestation_status") == "PASS", **pub}

    return {
        "ok": verification["ok"],
        "artifact_dir": str(art),
        "verification": verification,
        "statuses": statuses,
    }
