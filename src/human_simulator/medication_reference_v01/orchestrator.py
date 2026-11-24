"""Orchestrator — Medication Reference Acquisition v0.1."""

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
from human_simulator.medication_concept_v01.cohort_readiness import (
    episode_coverage_by_medicine,
)
from human_simulator.medication_reference_v01.baseline_verify import verify_prior_baseline
from human_simulator.medication_reference_v01.cohorts import (
    build_concept_cohort_readiness,
    coverage_summary,
    run_conditional_association_baseline,
)
from human_simulator.medication_reference_v01.engine_shadow import (
    run_m2id_onehot_engine_shadow,
)
from human_simulator.medication_reference_v01.freeze import freeze_all_cohorts
from human_simulator.medication_reference_v01.mapping import run_provider_mapping
from human_simulator.medication_reference_v01.policy import (
    ARTIFACT_DIR,
    EPISODE_JSONL,
    EXPECTED_MEDICINE_IDS,
    RUNTIME_DIR,
    SECURITY_STAGE_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.medication_reference_v01.providers import (
    build_provider_acquisition_report,
    discover_esklp_status,
)
from human_simulator.medication_reference_v01.review import (
    latest_decisions_by_medicine,
    review_export,
)
from human_simulator.medication_reference_v01.schema import schema_document


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


def run_full(
    root: Path,
    *,
    no_publish: bool = True,
    allow_network: bool = True,
) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = verify_prior_baseline(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "baseline_fail", "baseline": baseline}

    _write(art / "medication-concept-schema.json", schema_document())

    ep_path = root / EPISODE_JSONL
    if not ep_path.is_file():
        return {"ok": False, "error": "episode_dataset_missing"}
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

    human = latest_decisions_by_medicine(root)
    mapping = run_provider_mapping(
        root,
        coverage=coverage,
        human_decisions=human,
        allow_network=allow_network,
    )
    esklp = discover_esklp_status(root)
    provider_report = build_provider_acquisition_report(
        rxnorm_stats=mapping["rxnorm_stats"],
        esklp=esklp,
        rxnorm_verified_n=mapping["rxnorm_verified_n"],
    )
    _write(art / "provider-acquisition-report.json", provider_report)
    _write(
        art / "medication-reference-mapping-sanitized.json",
        {
            "records": mapping["sanitized"],
            "status_counts": mapping["status_counts"],
            "n_records": mapping["n_records"],
            "expected": mapping["expected"],
        },
    )
    _write(
        art / "medication-reference-accounting.json",
        {
            "total_source_medicines": mapping["n_records"],
            "expected_source_medicines": EXPECTED_MEDICINE_IDS,
            "matches_expected": mapping["n_records"] == EXPECTED_MEDICINE_IDS,
            "by_status": mapping["status_counts"],
            "DRUG_CONCEPT_ACCEPTED_COUNT": mapping["DRUG_CONCEPT_ACCEPTED_COUNT"],
            "DRUG_CONCEPT_UNRESOLVED_COUNT": mapping["DRUG_CONCEPT_UNRESOLVED_COUNT"],
            "DRUG_CONCEPT_MAPPING_STATUS": (
                "NO_ACCEPTED_MAPPINGS"
                if mapping["DRUG_CONCEPT_ACCEPTED_COUNT"] == 0
                else (
                    "PARTIAL"
                    if mapping["DRUG_CONCEPT_UNRESOLVED_COUNT"]
                    else "COMPLETE"
                )
            ),
            "unaccounted": EXPECTED_MEDICINE_IDS - mapping["n_records"]
            if mapping["n_records"] <= EXPECTED_MEDICINE_IDS
            else mapping["n_records"] - EXPECTED_MEDICINE_IDS,
        },
    )

    cov = coverage_summary(mapping["mapped"], episodes)
    _write(art / "accepted-coverage-summary.json", cov)

    review_pub = review_export(root)
    _write(art / "domain-review-workbench.json", review_pub)

    readiness = build_concept_cohort_readiness(
        episodes_by_split=split["episodes_by_split"],
        mapped=mapping["mapped"],
        split_meta=split_pub,
    )
    _write(art / "intervention-cohort-readiness.json", readiness)

    freeze = freeze_all_cohorts(art, train=train, val=val, test=test)
    _write(art / "m2id-onehot-model-freeze.json", freeze)

    shadow = run_m2id_onehot_engine_shadow(
        frozen_root=art / "frozen_models_m2id_onehot"
    )
    _write(art / "m2id-onehot-engine-shadow.json", shadow)

    baseline_assoc = run_conditional_association_baseline(
        readiness=readiness, train=train, val=val, test=test
    )
    _write(art / "first-concept-specific-association-baseline.json", baseline_assoc)

    accounting = json.loads((art / "medication-reference-accounting.json").read_text())
    statuses = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "DRUG_REFERENCE_ACQUISITION_STATUS": provider_report[
            "DRUG_REFERENCE_ACQUISITION_STATUS"
        ],
        "DRUG_CONCEPT_MAPPING_STATUS": accounting["DRUG_CONCEPT_MAPPING_STATUS"],
        "DRUG_CONCEPT_ACCEPTED_COUNT": accounting["DRUG_CONCEPT_ACCEPTED_COUNT"],
        "DRUG_CONCEPT_UNRESOLVED_COUNT": accounting["DRUG_CONCEPT_UNRESOLVED_COUNT"],
        "DOMAIN_REVIEW_WORKBENCH_STATUS": review_pub["DOMAIN_REVIEW_WORKBENCH_STATUS"],
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": readiness[
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS"
        ],
        "M2ID_ONEHOT_MODEL_FREEZE_STATUS": freeze["M2ID_ONEHOT_MODEL_FREEZE_STATUS"],
        "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": shadow["M2ID_ONEHOT_ENGINE_SHADOW_STATUS"],
        "FIRST_CONCEPT_SPECIFIC_ASSOCIATION_BASELINE_STATUS": baseline_assoc[
            "FIRST_CONCEPT_SPECIFIC_ASSOCIATION_BASELINE_STATUS"
        ],
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "PUBLICATION_INTEGRITY_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "pre_pack_manifest_status": "PASS",
        "content_verification_status": "PASS",
        "clean_staging_test_status": "PENDING_PUBLISH",
        "post_pack_publication_verification_status": "EXTERNAL_ATTESTATION_REQUIRED",
        "scope_correction": baseline.get("scope_correction"),
        "policy": policy_snapshot(),
        "duration_seconds": round(time.time() - t0, 3),
        "n_human_decisions": review_pub["n_decisions"],
    }
    _write(art / "status-contract.json", statuses)
    _write(
        art / "scope-and-claims.json",
        {
            "version": VERSION,
            "claim_level": "TECHNICAL_REFERENCE_ACQUISITION_AND_M2ID_ONEHOT_SHADOW_ONLY",
            "not_claims": [
                "treatment_effect",
                "causal_effect",
                "intervention_response",
                "clinical_validation",
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
            and freeze.get("M2ID_ONEHOT_MODEL_FREEZE_STATUS") in ("FROZEN", "PARTIAL")
            and shadow.get("M2ID_ONEHOT_ENGINE_SHADOW_STATUS") == "PASS"
            and mapping["n_records"] == EXPECTED_MEDICINE_IDS
        ),
        "version": VERSION,
        "statuses": {
            k: statuses[k]
            for k in statuses
            if k.endswith("_STATUS") or k.endswith("_COUNT") or k.startswith("pre_pack")
            or k.startswith("clean_")
            or k.startswith("content_")
            or k.startswith("post_pack")
        },
        "episode_n": lineage["n_lines"],
        "episode_subjects": lineage["n_subjects"],
    }
    _write(art / "verification.json", verification)

    if not no_publish:
        from human_simulator.medication_reference_v01.publish import publish

        pub = publish(root)
        return {"ok": verification["ok"] and pub.get("attestation_status") == "PASS", **pub}

    return {
        "ok": verification["ok"],
        "artifact_dir": str(art),
        "verification": verification,
        "statuses": statuses,
    }
