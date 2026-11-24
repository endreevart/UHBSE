"""Orchestrator — Medication Provider Snapshot Integration v0.1.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.models import load_episodes, split_episodes
from human_simulator.medication_concept_v01.cohort_readiness import (
    episode_coverage_by_medicine,
)
from human_simulator.medication_reference_v011.baseline_verify import verify_prior_baseline
from human_simulator.medication_reference_v011.cohorts import (
    build_concept_cohort_readiness,
    coverage_summary,
    run_conditional_association_baseline,
)
from human_simulator.medication_reference_v011.diagnostics import build_private_diagnostics
from human_simulator.medication_reference_v011.esklp_ingest import (
    expected_snapshot_path,
    ingest_esklp_snapshot,
)
from human_simulator.medication_reference_v011.mapping import run_esklp_mapping
from human_simulator.medication_reference_v011.policy import (
    ARTIFACT_DIR,
    CARRIED_FROM_V01,
    EPISODE_JSONL,
    EXPECTED_MEDICINE_IDS,
    RUNTIME_DIR,
    SECURITY_STAGE_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.medication_reference_v011.review import (
    latest_decisions_by_medicine,
    review_export,
    verify_decision_log,
)
from human_simulator.medication_reference_v011.review_pack import build_review_pack
from human_simulator.medication_reference_v011.rxnorm import RxNormClient
from human_simulator.medication_reference_v011.shadow_sensitivity import (
    run_invocab_and_oov_shadow,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8")


def run_full(root: Path, *, no_publish: bool = True, allow_network: bool = False) -> dict[str, Any]:
    """Run v0.1.1 pipeline.

    Hard stops:
    - missing ESKLP snapshot → PROVIDER_INPUT_REQUIRED (no review ZIP)
    - only candidates/ambiguous (no EXACT) and no human accepts → DOMAIN_REVIEW_DECISION_REQUIRED
    """
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    # Ensure expected snapshot directory exists for operator drop-in
    expected_snapshot_path(root).parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = verify_prior_baseline(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "baseline_fail", "baseline": baseline}

    # Corrected network accounting fixture (no 487× network storm)
    rx = RxNormClient(root, allow_network=allow_network)
    # Optional single probe only — never map 487 via network in this release path
    probe = rx.probe_network() if allow_network else "DISABLED"
    network_report = {
        "version": VERSION,
        "probe": probe,
        "accounting": rx.stats.as_dict(),
        "policy": "ESKLP_OFFLINE_PRIMARY_NO_487x2_NETWORK_FALLBACK",
        "v01_defect": {
            "label": "LOGICAL_REQUEST_FAILURES_AFTER_SINGLE_FAILED_PROBE",
            "prior_misleading_counters": {"network_errors": 974, "network_fetches": 0},
        },
    }
    _write(art / "network-accounting.json", network_report)

    esklp = ingest_esklp_snapshot(root)
    # Sanitized provider report (no raw rows)
    provider_report = {
        "version": VERSION,
        "ESKLP": {
            k: v
            for k, v in esklp.items()
            if k not in {"index", "manifest"}
        },
        "ESKLP_manifest_sanitized": esklp.get("manifest"),
        "RxNorm": {
            "retrieval_status": "NOT_USED_AS_PRIMARY_IN_V011",
            "probe": probe,
            "accounting": rx.stats.as_dict(),
            "patient_level_data_sent": False,
        },
        "DailyMed": {"retrieval_status": "DEFERRED"},
        "openFDA": {"retrieval_status": "DEFERRED"},
    }
    if esklp.get("PROVIDER_INPUT_REQUIRED"):
        provider_report["DRUG_REFERENCE_ACQUISITION_STATUS"] = "PROVIDER_INPUT_REQUIRED"
    elif esklp.get("ok"):
        provider_report["DRUG_REFERENCE_ACQUISITION_STATUS"] = "ESKLP_INDEXED"
    else:
        provider_report["DRUG_REFERENCE_ACQUISITION_STATUS"] = esklp.get(
            "ESKLP_PROVIDER_STATUS", "FAILED"
        )
    _write(art / "provider-acquisition-report.json", provider_report)

    if esklp.get("PROVIDER_INPUT_REQUIRED") or not esklp.get("ok"):
        status = {
            "version": VERSION,
            "generated_at": _now(),
            "BASELINE_VERIFICATION_STATUS": "PASS",
            "PIPELINE_STATUS": "PROVIDER_INPUT_REQUIRED",
            "DRUG_REFERENCE_ACQUISITION_STATUS": "PROVIDER_INPUT_REQUIRED",
            "DRUG_CONCEPT_MAPPING_STATUS": "NOT_RUN",
            "DRUG_CONCEPT_ACCEPTED_COUNT": 0,
            "DRUG_CONCEPT_UNRESOLVED_COUNT": EXPECTED_MEDICINE_IDS,
            "DOMAIN_REVIEW_WORKBENCH_STATUS": "AVAILABLE_AFTER_PROVIDER_INPUT",
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS": CARRIED_FROM_V01[
                "FIRST_INTERVENTION_COHORT_READINESS_STATUS"
            ],
            "M2ID_ONEHOT_MODEL_FREEZE_STATUS": CARRIED_FROM_V01[
                "M2ID_ONEHOT_MODEL_FREEZE_STATUS"
            ],
            "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": CARRIED_FROM_V01[
                "M2ID_ONEHOT_ENGINE_SHADOW_STATUS"
            ],
            "PUBLICATION_STATUS": "NOT_PUBLISHED_PROVIDER_INPUT_REQUIRED",
            "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
            "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
            "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
            "QSP_STATUS": "NOT_STARTED",
            "PKPD_STATUS": "NOT_STARTED",
            "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
            "PRODUCTION_READINESS": "NOT_CLAIMED",
            "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
            "expected_esklp_snapshot": str(expected_snapshot_path(root).relative_to(root)),
            "carried_from_v01": dict(CARRIED_FROM_V01),
            "policy": policy_snapshot(),
            "duration_seconds": round(time.time() - t0, 3),
        }
        _write(art / "status-contract.json", status)
        # Still run local in-vocab/OOV shadow (uses frozen v0.1 models; no retrain)
        shadow = run_invocab_and_oov_shadow(root)
        _write(art / "m2id-onehot-invocab-oov-shadow.json", shadow)
        status["M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS"] = shadow.get(
            "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS"
        )
        status["M2ID_ONEHOT_OOV_SHADOW_STATUS"] = shadow.get(
            "M2ID_ONEHOT_OOV_SHADOW_STATUS"
        )
        _write(art / "status-contract.json", status)
        return {
            "ok": False,
            "PIPELINE_STATUS": "PROVIDER_INPUT_REQUIRED",
            "expected_esklp_snapshot": status["expected_esklp_snapshot"],
            "statuses": status,
            "publication": "REFUSED",
        }

    # Episodes + coverage
    ep_path = root / EPISODE_JSONL
    episodes = load_episodes(ep_path)
    split = split_episodes(episodes)
    episodes_by_split = split["episodes_by_split"]
    coverage = episode_coverage_by_medicine(episodes, episodes_by_split)

    human = latest_decisions_by_medicine(root)
    mapped = run_esklp_mapping(
        root,
        index=esklp["index"],
        snapshot_hash=esklp["snapshot_sha256"],
        coverage=coverage,
        human_decisions=human,
    )
    _write(art / "medication-reference-accounting.json", mapped["accounting"])
    _write(art / "medication-reference-mapping-sanitized.json", {"rows": mapped["sanitized"]})

    pack = build_review_pack(root, mapped["mappings"])
    _write(art / "domain-review-pack-manifest.json", {k: v for k, v in pack.items()})

    diag = build_private_diagnostics(
        root,
        esklp=esklp,
        coverage=coverage,
        mappings=mapped["mappings"],
    )
    _write(
        art / "diagnostic-summary-public.json",
        {
            "private_diagnostics_dir": diag.get("private_diagnostics_dir"),
            "archive_stats": diag.get("archive"),
            "source_aggregates": diag.get("source_aggregates"),
            "search_step_public": diag.get("search_step_public"),
            "mapping_summary": diag.get("mapping_summary"),
            "full_medication_strings_in_public": False,
        },
    )

    accepted = mapped["accounting"]["DRUG_CONCEPT_ACCEPTED_COUNT"]
    by_status = mapped["accounting"]["by_status"]
    n_exact = int(by_status.get("EXACT_PROVIDER_MATCH") or 0)
    n_human = int(by_status.get("HUMAN_ACCEPTED") or 0)
    n_supported = int(by_status.get("SUPPORTED_TRANSFORM") or 0)
    n_cand = int(by_status.get("CANDIDATE") or 0)
    n_amb = int(by_status.get("AMBIGUOUS") or 0)
    n_conflict = int(by_status.get("CONFLICT") or 0)
    reviewable = n_exact + n_cand + n_amb + n_conflict
    # Note: EXACT_PROVIDER_MATCH is already counted in accepted
    with_candidates = int(mapped["accounting"].get("source_records_with_ge1_candidate") or 0)

    review_log = review_export(root)
    log_verify = verify_decision_log(root)
    _write(
        art / "domain-review-workbench.json",
        {
            **review_log,
            "verify_log": log_verify,
            "DOMAIN_REVIEW_WORKBENCH_STATUS": "AVAILABLE",
            "human_review_forbidden_without_candidate": True,
        },
    )

    shadow = run_invocab_and_oov_shadow(root)
    _write(art / "m2id-onehot-invocab-oov-shadow.json", shadow)

    # Decision gate — never DOMAIN_REVIEW with zero candidates
    if accepted == 0 and with_candidates == 0:
        status = {
            "version": VERSION,
            "generated_at": _now(),
            "BASELINE_VERIFICATION_STATUS": "PASS",
            "PIPELINE_STATUS": "NO_PROVIDER_COVERAGE_ESTABLISHED",
            "DRUG_REFERENCE_ACQUISITION_STATUS": (
                "ESKLP_INDEXED"
                if int(esklp.get("n_unique_searchable_terms") or 0) > 0
                else "INDEX_EMPTY_NO_SEARCHABLE_TERMS"
            ),
            "DRUG_CONCEPT_MAPPING_STATUS": "NO_PROVIDER_COVERAGE_ESTABLISHED",
            "DRUG_CONCEPT_ACCEPTED_COUNT": 0,
            "DRUG_CONCEPT_UNRESOLVED_COUNT": EXPECTED_MEDICINE_IDS,
            "by_status": by_status,
            "n_exact_provider_match": n_exact,
            "source_records_with_ge1_candidate": with_candidates,
            "DOMAIN_REVIEW_WORKBENCH_STATUS": "BLOCKED_NO_CANDIDATES",
            "private_diagnostics_dir": diag.get("private_diagnostics_dir"),
            "provider_index_stats": esklp.get("stats"),
            "top20_episode_coverage": mapped["accounting"].get("top20_episode_coverage"),
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
            "M2ID_ONEHOT_MODEL_FREEZE_STATUS": CARRIED_FROM_V01[
                "M2ID_ONEHOT_MODEL_FREEZE_STATUS"
            ],
            "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": CARRIED_FROM_V01[
                "M2ID_ONEHOT_ENGINE_SHADOW_STATUS"
            ],
            "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS": shadow.get(
                "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS"
            ),
            "M2ID_ONEHOT_OOV_SHADOW_STATUS": shadow.get("M2ID_ONEHOT_OOV_SHADOW_STATUS"),
            "PUBLICATION_STATUS": "NOT_PUBLISHED",
            "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
            "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
            "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
            "QSP_STATUS": "NOT_STARTED",
            "PKPD_STATUS": "NOT_STARTED",
            "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
            "PRODUCTION_READINESS": "NOT_CLAIMED",
            "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
            "policy": policy_snapshot(),
            "duration_seconds": round(time.time() - t0, 3),
            "zero_candidate_cause_hint": diag.get("search_step_public"),
        }
        _write(art / "status-contract.json", status)
        return {
            "ok": False,
            "PIPELINE_STATUS": "NO_PROVIDER_COVERAGE_ESTABLISHED",
            "private_diagnostics_dir": diag.get("private_diagnostics_dir"),
            "accounting": mapped["accounting"],
            "provider_stats": esklp.get("stats"),
            "statuses": status,
            "publication": "REFUSED",
        }

    if accepted == 0 and with_candidates > 0:
        status = {
            "version": VERSION,
            "generated_at": _now(),
            "BASELINE_VERIFICATION_STATUS": "PASS",
            "PIPELINE_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
            "DRUG_REFERENCE_ACQUISITION_STATUS": "ESKLP_INDEXED",
            "DRUG_CONCEPT_MAPPING_STATUS": "CANDIDATES_PENDING_REVIEW",
            "DRUG_CONCEPT_ACCEPTED_COUNT": 0,
            "DRUG_CONCEPT_UNRESOLVED_COUNT": EXPECTED_MEDICINE_IDS,
            "by_status": by_status,
            "n_exact_provider_match": n_exact,
            "n_human_accepted": n_human,
            "n_supported_transform": n_supported,
            "n_candidate": n_cand,
            "n_ambiguous": n_amb,
            "n_conflict": n_conflict,
            "source_records_with_ge1_candidate": with_candidates,
            "candidate_episode_coverage": mapped["accounting"].get(
                "candidate_episode_coverage"
            ),
            "DOMAIN_REVIEW_WORKBENCH_STATUS": "AVAILABLE",
            "private_review_pack": pack.get("private_review_pack_dir"),
            "private_diagnostics_dir": diag.get("private_diagnostics_dir"),
            "top20_episode_coverage": mapped["accounting"].get("top20_episode_coverage"),
            "top20_with_ge1_candidate": mapped["accounting"].get("top20_with_ge1_candidate"),
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
            "M2ID_ONEHOT_MODEL_FREEZE_STATUS": CARRIED_FROM_V01[
                "M2ID_ONEHOT_MODEL_FREEZE_STATUS"
            ],
            "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": CARRIED_FROM_V01[
                "M2ID_ONEHOT_ENGINE_SHADOW_STATUS"
            ],
            "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS": shadow.get(
                "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS"
            ),
            "M2ID_ONEHOT_OOV_SHADOW_STATUS": shadow.get("M2ID_ONEHOT_OOV_SHADOW_STATUS"),
            "PUBLICATION_STATUS": "NOT_PUBLISHED_DOMAIN_REVIEW_REQUIRED",
            "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
            "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
            "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
            "QSP_STATUS": "NOT_STARTED",
            "PKPD_STATUS": "NOT_STARTED",
            "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
            "PRODUCTION_READINESS": "NOT_CLAIMED",
            "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
            "policy": policy_snapshot(),
            "duration_seconds": round(time.time() - t0, 3),
            "readiness_hint": {
                "note": (
                    "Accept evidence-backed concepts from the private review pack "
                    "(start with top-20). Engineering READY requires accepted "
                    "concept × outcome × unit gates."
                ),
                "top20_episode_coverage": mapped["accounting"].get("top20_episode_coverage"),
                "min_accepts_for_first_ready_cohort_estimate": ">=1 accepted concept covering a V01 outcome cohort that meets GATE_MIN_*",
                "commands": [
                    "audit --root . medication-reference review list --top 20",
                    "audit --root . medication-reference review show <medicine_id>",
                    (
                        "audit --root . medication-reference review accept <medicine_id> "
                        "--candidate <id> --provider ESKLP --reviewer <id> --reason <text>"
                    ),
                    "audit --root . medication-reference review verify-log",
                    "audit --root . medication-reference run-v0.1.1 --no-publish",
                ],
            },
        }
        _write(art / "status-contract.json", status)
        return {
            "ok": False,
            "PIPELINE_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
            "private_review_pack": pack.get("private_review_pack_dir"),
            "private_diagnostics_dir": diag.get("private_diagnostics_dir"),
            "accounting": mapped["accounting"],
            "statuses": status,
            "publication": "REFUSED",
        }

    # Continue with readiness when accepted > 0 (EXACT or HUMAN)
    cov = coverage_summary(mapped["mappings"], total_episodes=len(episodes))
    _write(art / "accepted-coverage-summary.json", cov)

    readiness = build_concept_cohort_readiness(
        episodes_by_split=episodes_by_split,
        mapped=mapped["mappings"],
        split_meta={k: v for k, v in split.items() if k != "episodes_by_split"},
    )
    _write(art / "intervention-cohort-readiness.json", readiness)

    assoc = run_conditional_association_baseline(
        readiness=readiness,
        episodes_by_split=episodes_by_split,
        mapped=mapped["mappings"],
    )
    _write(art / "first-concept-specific-association-baseline.json", assoc)

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "PIPELINE_STATUS": "ACCEPTED_MAPPINGS_PRESENT",
        "DRUG_REFERENCE_ACQUISITION_STATUS": "ESKLP_INDEXED",
        "DRUG_CONCEPT_MAPPING_STATUS": "ACCEPTED_PRESENT",
        "DRUG_CONCEPT_ACCEPTED_COUNT": accepted,
        "DRUG_CONCEPT_UNRESOLVED_COUNT": EXPECTED_MEDICINE_IDS - accepted,
        "by_status": by_status,
        "source_records_with_ge1_candidate": with_candidates,
        "DOMAIN_REVIEW_WORKBENCH_STATUS": "AVAILABLE",
        "private_review_pack": pack.get("private_review_pack_dir"),
        "private_diagnostics_dir": diag.get("private_diagnostics_dir"),
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": readiness.get(
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS"
        ),
        "M2ID_ONEHOT_MODEL_FREEZE_STATUS": CARRIED_FROM_V01[
            "M2ID_ONEHOT_MODEL_FREEZE_STATUS"
        ],
        "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": CARRIED_FROM_V01[
            "M2ID_ONEHOT_ENGINE_SHADOW_STATUS"
        ],
        "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS": shadow.get(
            "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS"
        ),
        "M2ID_ONEHOT_OOV_SHADOW_STATUS": shadow.get("M2ID_ONEHOT_OOV_SHADOW_STATUS"),
        "FIRST_CONCEPT_SPECIFIC_ASSOCIATION_BASELINE_STATUS": assoc.get(
            "FIRST_CONCEPT_SPECIFIC_ASSOCIATION_BASELINE_STATUS"
        ),
        "PUBLICATION_STATUS": "ELIGIBLE_IF_OWNER_REQUESTS_OR_ACCEPTED_PRESENT",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "policy": policy_snapshot(),
        "duration_seconds": round(time.time() - t0, 3),
        "no_publish_default": no_publish,
    }
    _write(art / "status-contract.json", status)
    return {
        "ok": True,
        "PIPELINE_STATUS": status["PIPELINE_STATUS"],
        "statuses": status,
        "accounting": mapped["accounting"],
        "readiness": readiness.get("FIRST_INTERVENTION_COHORT_READINESS_STATUS"),
        "publication": "NOT_RUN" if no_publish else "OWNER_MUST_INVOKE_PUBLISH",
    }
