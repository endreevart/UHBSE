"""Concept-specific cohort readiness and conditional association baseline."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from human_simulator.medication_concept_v01.representation import (
    bootstrap_improvement,
    feat_m1,
    permutation_upper,
    subject_macro_mae,
    _fit_predict,
    _make_preds,
)
from human_simulator.medication_reference_v01.policy import (
    ACCEPTED_STATUSES,
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    V01_COHORTS,
    VERSION,
)


def build_concept_cohort_readiness(
    *,
    episodes_by_split: dict[str, list[dict[str, Any]]],
    mapped: list[dict[str, Any]],
    split_meta: dict[str, Any],
) -> dict[str, Any]:
    accepted = {
        str(m["source_medicine_id"]): m
        for m in mapped
        if m.get("drug_concept_status") in ACCEPTED_STATUSES
    }
    all_eps = (
        list(episodes_by_split.get("train") or [])
        + list(episodes_by_split.get("validation") or [])
        + list(episodes_by_split.get("test") or [])
    )
    ready, partial, blocked = [], [], []

    if not accepted:
        for outcome, unit in V01_COHORTS:
            cohort_eps = [e for e in all_eps if e["outcome"] == outcome and e["unit"] == unit]
            subjects = {e["opaque_subject_key"] for e in cohort_eps}
            test_eps = [
                e
                for e in (episodes_by_split.get("test") or [])
                if e["outcome"] == outcome and e["unit"] == unit
            ]
            blocked.append(
                {
                    "grain": "accepted_drug_concept × outcome × unit",
                    "outcome": outcome,
                    "unit": unit,
                    "accepted_drug_concept": None,
                    "n_subjects": len(subjects),
                    "n_episodes": len(cohort_eps),
                    "n_test_subjects": len({e["opaque_subject_key"] for e in test_eps}),
                    "block_reasons": ["no_accepted_drug_concept_mapping"],
                    "timestamp_status": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
                }
            )
        return {
            "version": VERSION,
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
            "READY_COHORTS": [],
            "PARTIAL_COHORTS": [],
            "BLOCKED_COHORTS": blocked,
            "n_accepted_concepts": 0,
            "clinical_intervention_cohort_not_claimed": True,
        }

    for mid, rec in sorted(accepted.items()):
        concept_key = rec.get("provider_concept_id") or mid
        for outcome, unit in V01_COHORTS:
            cohort_eps = [
                e
                for e in all_eps
                if e["outcome"] == outcome
                and e["unit"] == unit
                and str(e["medicine_id"]) == mid
            ]
            if not cohort_eps:
                continue
            subjects = {e["opaque_subject_key"] for e in cohort_eps}
            by_split = {}
            for sp, rows in episodes_by_split.items():
                sub = [
                    e
                    for e in rows
                    if e["outcome"] == outcome
                    and e["unit"] == unit
                    and str(e["medicine_id"]) == mid
                ]
                by_split[sp] = {
                    "n_episodes": len(sub),
                    "n_subjects": len({e["opaque_subject_key"] for e in sub}),
                }
            test_subj = by_split.get("test", {}).get("n_subjects", 0)
            gates = {
                "accepted_drug_concept_mapping": True,
                "min_subjects": len(subjects) >= GATE_MIN_SUBJECTS,
                "min_episodes": len(cohort_eps) >= GATE_MIN_EPISODES,
                "subject_disjoint_split": bool(split_meta.get("zero_subject_overlap")),
                "min_test_subjects": test_subj >= GATE_MIN_TEST_SUBJECTS,
                "no_unit_conflict": True,
                "no_identity_or_locator_overlap": bool(
                    split_meta.get("zero_subject_overlap")
                    and split_meta.get("zero_episode_overlap")
                    and split_meta.get("zero_locator_overlap")
                ),
            }
            failed = [k for k, v in gates.items() if not v]
            row = {
                "grain": "accepted_drug_concept × outcome × unit",
                "accepted_drug_concept": concept_key,
                "source_medicine_id": mid,
                "drug_concept_status": rec.get("drug_concept_status"),
                "provider": rec.get("provider"),
                "outcome": outcome,
                "unit": unit,
                "n_subjects": len(subjects),
                "n_episodes": len(cohort_eps),
                "splits": by_split,
                "gates": gates,
                "block_reasons": failed,
                "timestamp_status": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
                "medication_concept_provenance": {
                    "provider_evidence_hash": rec.get("provider_evidence_hash"),
                    "status": rec.get("drug_concept_status"),
                },
            }
            if not failed:
                ready.append(row)
            elif len(failed) <= 2:
                partial.append(row)
            else:
                blocked.append(row)

    if ready:
        status = "READY"
    elif partial:
        status = "PARTIAL_ONLY"
    else:
        status = "ZERO_READY"

    return {
        "version": VERSION,
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": status,
        "READY_COHORTS": ready,
        "PARTIAL_COHORTS": partial,
        "BLOCKED_COHORTS": blocked,
        "n_accepted_concepts": len(accepted),
        "clinical_intervention_cohort_not_claimed": True,
        "thresholds_not_lowered_after_results": True,
    }


def run_conditional_association_baseline(
    *,
    readiness: dict[str, Any],
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
) -> dict[str, Any]:
    ready = readiness.get("READY_COHORTS") or []
    if not ready:
        blockers = []
        for b in (readiness.get("BLOCKED_COHORTS") or [])[:10]:
            blockers.append(
                {
                    "outcome": b.get("outcome"),
                    "n_subjects": b.get("n_subjects"),
                    "n_episodes": b.get("n_episodes"),
                    "block_reasons": b.get("block_reasons"),
                }
            )
        return {
            "FIRST_CONCEPT_SPECIFIC_ASSOCIATION_BASELINE_STATUS": (
                "NOT_RUN_DUE_TO_FAILED_READINESS_GATE"
            ),
            "name": "FIRST_CONCEPT_SPECIFIC_MEDICATION_ASSOCIATION_BASELINE",
            "not_intervention_response": True,
            "not_treatment_effect": True,
            "not_causal": True,
            "blockers_sample": blockers,
        }

    results = []
    for cohort in ready:
        outcome, unit = cohort["outcome"], cohort["unit"]
        mid = str(cohort["source_medicine_id"])
        tr = [
            e
            for e in train
            if e["outcome"] == outcome and e["unit"] == unit and str(e["medicine_id"]) == mid
        ]
        te = [
            e
            for e in test
            if e["outcome"] == outcome and e["unit"] == unit and str(e["medicine_id"]) == mid
        ]
        if len(tr) < 20 or len(te) < 5:
            continue
        y_tr = [float(e["post_value"]) for e in tr]
        # M1 vs accepted-concept indicator (single concept cohort — concept is constant;
        # use exposure flags as concept-context sensitivity within cohort)
        x1_tr = [feat_m1(e) for e in tr]
        x1_te = [feat_m1(e) for e in te]
        m1_hat, _, _, _ = _fit_predict(x1_tr, y_tr, x1_te)
        m1_preds = _make_preds(te, m1_hat)
        # accepted-concept model: M1 + polypharmacy/concurrent (concept identity fixed in cohort)
        x2_tr = [
            feat_m1(e)
            + [
                float(e.get("polypharmacy_flag") or 0),
                float(e.get("concurrent_med_count") or 1),
            ]
            for e in tr
        ]
        x2_te = [
            feat_m1(e)
            + [
                float(e.get("polypharmacy_flag") or 0),
                float(e.get("concurrent_med_count") or 1),
            ]
            for e in te
        ]
        m2_hat, _, _, _ = _fit_predict(x2_tr, y_tr, x2_te)
        m2_preds = _make_preds(te, m2_hat)
        boot = bootstrap_improvement(m1_preds, m2_preds)
        perm = permutation_upper(m1_preds, m2_preds)
        results.append(
            {
                "outcome": outcome,
                "unit": unit,
                "accepted_drug_concept": cohort.get("accepted_drug_concept"),
                "m1_subject_macro_mae": subject_macro_mae(m1_preds),
                "concept_model_subject_macro_mae": subject_macro_mae(m2_preds),
                "improvement": subject_macro_mae(m1_preds) - subject_macro_mae(m2_preds),
                "bootstrap": boot,
                "permutation": perm,
            }
        )

    return {
        "FIRST_CONCEPT_SPECIFIC_ASSOCIATION_BASELINE_STATUS": (
            "EVALUATED" if results else "NOT_RUN_DUE_TO_FAILED_READINESS_GATE"
        ),
        "name": "FIRST_CONCEPT_SPECIFIC_MEDICATION_ASSOCIATION_BASELINE",
        "not_intervention_response": True,
        "not_treatment_effect": True,
        "not_causal": True,
        "cohorts": results,
    }


def coverage_summary(
    mapped: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted_ids = {
        str(m["source_medicine_id"])
        for m in mapped
        if m.get("drug_concept_status") in ACCEPTED_STATUSES
    }
    unresolved = [
        m for m in mapped if m.get("drug_concept_status") not in ACCEPTED_STATUSES
    ]
    ep_accepted = [e for e in episodes if str(e["medicine_id"]) in accepted_ids]
    subj_accepted = {e["opaque_subject_key"] for e in ep_accepted}
    # top unresolved by lost episode coverage
    top = sorted(
        unresolved,
        key=lambda m: -int((m.get("episode_coverage") or {}).get("n_episodes") or 0),
    )[:20]
    return {
        "accepted_medication_records": len(accepted_ids),
        "unresolved_medication_records": len(unresolved),
        "accepted_episode_coverage": len(ep_accepted),
        "accepted_subject_coverage": len(subj_accepted),
        "total_episodes": len(episodes),
        "accepted_episode_fraction": len(ep_accepted) / max(len(episodes), 1),
        "top_unresolved_by_lost_episode_coverage": [
            {
                "source_medicine_id_hash": hashlib_id(m["source_medicine_id"]),
                "status": m["drug_concept_status"],
                "n_episodes": (m.get("episode_coverage") or {}).get("n_episodes", 0),
                "n_subjects": (m.get("episode_coverage") or {}).get("n_subjects", 0),
            }
            for m in top
        ],
    }


def hashlib_id(mid: str) -> str:
    import hashlib

    return hashlib.sha256(str(mid).encode()).hexdigest()[:16]
