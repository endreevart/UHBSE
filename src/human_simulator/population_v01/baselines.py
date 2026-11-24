"""Multi-outcome baseline experiments (Source A only; no B tuning)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from human_simulator.population_v01.policy import (
    BOOTSTRAP_ITERS,
    L2,
    SEED,
    SHUFFLE_PERMS,
    SOURCE_A,
    VERSION,
)
from human_simulator.scientific.dataset import build_consecutive_pairs, fetch_measurement_series
from human_simulator.scientific.models import FirstLearnedBaseline
from human_simulator.scientific.splits import assign_pairs_to_splits, build_subject_split
from human_simulator.scientific_v02.evaluate import evaluate_a_only
from human_simulator.scientific_v02.train import train_ridge_v02


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def run_outcome_baseline(
    conn: Any,
    outcome: dict[str, Any],
    *,
    seed: int = SEED,
) -> dict[str, Any]:
    """Train persistence/trend/Ridge for one shortlisted outcome; A-only."""
    label = outcome["source_code"]
    unit = outcome["dominant_unit"]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT o.subject_id::text
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND oc.raw_code = %s
              AND COALESCE(oc.raw_unit, '') = %s
              AND oc.numeric_value IS NOT NULL
              AND COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) IS NOT NULL
            GROUP BY o.subject_id
            HAVING COUNT(*) >= 2
            """,
            (SOURCE_A, label, unit),
        )
        subjects = sorted(r[0] for r in cur.fetchall())

    if len(subjects) < 10:
        return {
            "candidate_id": outcome.get("candidate_id"),
            "source_code": label,
            "status": "INSUFFICIENT_SUBJECTS",
            "n_subjects": len(subjects),
        }

    split = build_subject_split(subjects, seed=seed)
    all_keys = (
        set(split["sets"]["train"])
        | set(split["sets"]["validation"])
        | set(split["sets"]["test"])
    )
    series = fetch_measurement_series(
        conn, raw_code=label, dominant_unit=unit, subject_keys=all_keys
    )
    # Defense: A only
    with conn.cursor() as cur:
        keys = list({r["opaque_subject_key"] for r in series})
        if keys:
            cur.execute(
                """
                SELECT subject_id::text FROM canonical_evidence.subject
                WHERE subject_id::text = ANY(%s) AND source_system_id = %s
                """,
                (keys, SOURCE_A),
            )
            a_ok = {r[0] for r in cur.fetchall()}
        else:
            a_ok = set()
    series = [r for r in series if r["opaque_subject_key"] in a_ok]

    pairs, meta = build_consecutive_pairs(
        series,
        outcome={
            "source_measurement_label": label,
            "dominant_unit": unit,
            "candidate_id": outcome.get("candidate_id"),
        },
        config={"seed": seed, "version": VERSION},
    )
    assigned = assign_pairs_to_splits(pairs, split)
    train = assigned["buckets"]["train"]
    val = assigned["buckets"]["validation"]
    test = assigned["buckets"]["test"]

    if len(train) < 50 or len(test) < 20:
        return {
            "candidate_id": outcome.get("candidate_id"),
            "source_code": label,
            "dominant_unit": unit,
            "status": "INSUFFICIENT_PAIRS",
            "n_train": len(train),
            "n_validation": len(val),
            "n_test": len(test),
            "pair_meta": meta,
        }

    # Temporarily reduce shuffle/bootstrap cost via monkeypatch of evaluate constants
    # by calling evaluate then annotating; for multi-outcome we patch module attrs.
    import human_simulator.scientific_v02.evaluate as ev

    old_b, old_s = ev.BOOTSTRAP_ITERS, ev.SHUFFLE_PERMS
    ev.BOOTSTRAP_ITERS = BOOTSTRAP_ITERS
    ev.SHUFFLE_PERMS = SHUFFLE_PERMS
    try:
        trained = train_ridge_v02(
            train,
            val,
            split_hash=str(split.get("split_hash") or _hash(split["sets"])),
            train_pair_manifest_hash=_hash([p.get("pair_id") for p in train]),
            pair_construction_hash=_hash(meta),
            dataset_schema_hash=_hash({"label": label, "unit": unit}),
        )
        model: FirstLearnedBaseline = trained["model"]
        eval_doc = evaluate_a_only(model, train=train, val=val, test=test, seed=seed)
    finally:
        ev.BOOTSTRAP_ITERS = old_b
        ev.SHUFFLE_PERMS = old_s

    eval_doc.pop("_runtime_test_preds_ridge", None)
    eval_doc.pop("_runtime_test_preds_persistence", None)

    shuffle = eval_doc.get("shuffle_control") or {}
    p_val = shuffle.get("permutation_p_value")
    if p_val == 0.0:
        raise RuntimeError("permutation_p_value literal 0.0 forbidden")

    freeze_ok = bool(
        eval_doc.get("source_a_retrospective_backtest_status") == "PASS"
        and len(test) >= 20
        and len(train) >= 50
    )

    return {
        "candidate_id": outcome.get("candidate_id"),
        "source_code": label,
        "dominant_unit": unit,
        "status": "TRAINED" if freeze_ok else "PARTIAL",
        "frozen_technical_model": freeze_ok,
        "clinical_validity_implied": False,
        "n_subjects_split": {
            "train": len(split["sets"]["train"]),
            "validation": len(split["sets"]["validation"]),
            "test": len(split["sets"]["test"]),
        },
        "n_pairs": {"train": len(train), "validation": len(val), "test": len(test)},
        "training_report": trained.get("training_report"),
        "evaluation": eval_doc,
        "tail_risk_status": (
            "COMPUTED"
            if (eval_doc.get("test_metrics") or {}).get("ridge")
            else "NOT_COMPUTED"
        ),
        "uncertainty_status": (
            "COMPUTED" if eval_doc.get("bootstrap") else "NOT_COMPUTED"
        ),
        "source_b_tuned": False,
        "subject_disjoint_splits": True,
        "train_only_preprocessing": True,
        "no_test_for_selection": True,
        "_runtime_model": model,
        "_runtime_train": train,
    }


def run_multi_outcome_baselines(
    conn: Any, shortlist: dict[str, Any]
) -> dict[str, Any]:
    results = []
    models: dict[str, Any] = {}
    trains: dict[str, list[dict[str, Any]]] = {}
    for outcome in shortlist.get("shortlist") or []:
        row = run_outcome_baseline(conn, outcome)
        model = row.pop("_runtime_model", None)
        train = row.pop("_runtime_train", None)
        if model is not None and outcome.get("candidate_id"):
            models[str(outcome["candidate_id"])] = model
            trains[str(outcome["candidate_id"])] = train or []
        results.append(row)
    n_ok = sum(1 for r in results if r.get("status") == "TRAINED")
    return {
        "version": VERSION,
        "multi_outcome_baseline_status": (
            "PASS" if n_ok >= 3 else ("PARTIAL" if n_ok else "FAIL")
        ),
        "n_outcomes_attempted": len(results),
        "n_outcomes_trained": n_ok,
        "target_range": "3-10",
        "outcomes": results,
        "aggregated_medical_score_forbidden": True,
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "_runtime_models": models,
        "_runtime_trains": trains,
    }
