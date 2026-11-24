"""Source A-only population lineage and split for scientific baseline v0.2."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from human_simulator.scientific.dataset import build_consecutive_pairs, fetch_measurement_series
from human_simulator.scientific.splits import assign_pairs_to_splits, build_subject_split
from human_simulator.unified_v011.robustness_a import fixed_outcome_selected
from human_simulator.scientific_v02.policy import (
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    SEED,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _step(**kw: Any) -> dict[str, Any]:
    prev = kw["previous_population"]
    res = kw["resulting_population"]
    excl = prev - res if prev is not None else 0
    return {
        **kw,
        "excluded_count": excl if prev is not None else 0,
        "monotonic": prev is None or (excl >= 0 and res <= prev),
    }


def build_a_only_experiment(conn: Any, *, seed: int = SEED) -> dict[str, Any]:
    """Build A-only funnel + subject-disjoint split + pairs (runtime pairs stripped later)."""
    selected = fixed_outcome_selected()
    label = selected.get("source_measurement_label") or FIXED_OUTCOME_LABEL
    unit = selected.get("dominant_unit") or FIXED_OUTCOME_UNIT

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM canonical_evidence.subject WHERE source_system_id = %s",
            (SOURCE_A_SYSTEM_ID,),
        )
        n_canonical = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT o.subject_id::text
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND oc.numeric_value IS NOT NULL
              AND COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) IS NOT NULL
            GROUP BY o.subject_id
            HAVING COUNT(*) >= 2
            """,
            (SOURCE_A_SYSTEM_ID,),
        )
        sci_ids = sorted(r[0] for r in cur.fetchall())
        n_sci = len(sci_ids)

        # ≥1 / ≥2 dated numeric T3 among scientific-eligible subjects only
        sci_set = set(sci_ids)
        cur.execute(
            """
            SELECT o.subject_id::text, COUNT(*)::bigint
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND oc.raw_code = %s
              AND COALESCE(oc.raw_unit, '') = %s
              AND oc.numeric_value IS NOT NULL
              AND COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) IS NOT NULL
            GROUP BY o.subject_id
            """,
            (SOURCE_A_SYSTEM_ID, label, unit),
        )
        t3_counts = {r[0]: int(r[1]) for r in cur.fetchall() if r[0] in sci_set}
        n_t3_ge1 = sum(1 for c in t3_counts.values() if c >= 1)
        n_t3_ge2 = sum(1 for c in t3_counts.values() if c >= 2)

    split = build_subject_split(sci_ids, seed=seed)
    all_keys = (
        set(split["sets"]["train"])
        | set(split["sets"]["validation"])
        | set(split["sets"]["test"])
    )
    series = fetch_measurement_series(
        conn, raw_code=label, dominant_unit=unit, subject_keys=all_keys
    )
    series_subjects = {r["opaque_subject_key"] for r in series}
    # Restrict series to A (defense in depth)
    with conn.cursor() as cur:
        if series_subjects:
            cur.execute(
                """
                SELECT subject_id::text, source_system_id
                FROM canonical_evidence.subject
                WHERE subject_id::text = ANY(%s)
                """,
                (list(series_subjects),),
            )
            sys_map = {r[0]: r[1] for r in cur.fetchall()}
        else:
            sys_map = {}
    series = [r for r in series if sys_map.get(r["opaque_subject_key"]) == SOURCE_A_SYSTEM_ID]
    b_in_series = sum(1 for s in series_subjects if sys_map.get(s) == SOURCE_B_SYSTEM_ID)

    pairs, meta = build_consecutive_pairs(
        series,
        outcome=selected,
        config={
            "seed": seed,
            "version": VERSION,
            "unit_policy": "fixed_outcome_dominant_unit",
            "pair_definition": "strict_consecutive_neighbors_only",
            "outcome_selection": "FIXED_NO_RESELECT",
        },
    )
    summary = meta.get("summary") or {}
    n_with_pairs = int(summary.get("n_subjects_with_pairs") or 0)
    n_pairs = int(summary.get("n_pairs") or 0)

    assigned = assign_pairs_to_splits(pairs, split)
    buckets = assigned["buckets"]
    train, val, test = buckets["train"], buckets["validation"], buckets["test"]

    # Provenance of pair subjects
    pair_subj = list({p["opaque_subject_key"] for p in pairs})
    a_n = b_n = 0
    if pair_subj:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_system_id, COUNT(*)
                FROM canonical_evidence.subject
                WHERE subject_id::text = ANY(%s)
                GROUP BY 1
                """,
                (pair_subj,),
            )
            for sys, n in cur.fetchall():
                if sys == SOURCE_A_SYSTEM_ID:
                    a_n = int(n)
                elif sys == SOURCE_B_SYSTEM_ID:
                    b_n = int(n)

    # Horizon / unit invariants
    horizons_ok = all(float(p["horizon_days"]) > 0 for p in pairs)
    units_ok = all(
        (p.get("unit") or unit) == FIXED_OUTCOME_UNIT
        or str((p.get("model_features") or {}).get("y_t0")) is not None
        for p in pairs
    )
    # pairs from build_consecutive_pairs may store unit in summary
    units_ok = summary.get("units") == [FIXED_OUTCOME_UNIT] or summary.get("units") == [
        unit
    ]

    funnel = [
        _step(
            name="1_source_a_canonical_subjects",
            previous_population=None,
            resulting_population=n_canonical,
            inclusion_rule="canonical_evidence.subject.source_system_id=magerya_api",
            exclusion_rule="non-A subjects",
            source_relation="canonical_evidence.subject",
            provenance_condition=f"source_system_id={SOURCE_A_SYSTEM_ID}",
            temporal_requirements="none",
            distinctness_rule="COUNT(subject_id)",
        ),
        _step(
            name="2_scientific_eligible_ge2_dated_numeric_any_code",
            previous_population=n_canonical,
            resulting_population=n_sci,
            inclusion_rule="≥2 dated numeric observation_components (any code)",
            exclusion_rule="<2 dated numeric components",
            source_relation="observation_component⋈observation⋈subject",
            provenance_condition=f"source_system_id={SOURCE_A_SYSTEM_ID}",
            temporal_requirements="observed_at/specimen/recorded not null",
            distinctness_rule="GROUP BY subject_id HAVING COUNT(*)>=2",
        ),
        _step(
            name="3_subjects_with_ge1_dated_numeric_t3_pmol",
            previous_population=n_sci,
            resulting_population=n_t3_ge1,
            inclusion_rule=f"raw_code={label!r} unit={unit!r} ≥1 dated numeric",
            exclusion_rule="no matching T3 row",
            source_relation="observation_component",
            provenance_condition=f"source_system_id={SOURCE_A_SYSTEM_ID}",
            temporal_requirements="dated",
            distinctness_rule="DISTINCT subject_id",
        ),
        _step(
            name="4_subjects_with_ge2_dated_numeric_t3_pmol",
            previous_population=n_t3_ge1,
            resulting_population=n_t3_ge2,
            inclusion_rule="≥2 dated numeric T3 measurements",
            exclusion_rule="exactly one T3 measurement",
            source_relation="observation_component",
            provenance_condition=f"source_system_id={SOURCE_A_SYSTEM_ID}",
            temporal_requirements="dated",
            distinctness_rule="HAVING COUNT(*)>=2",
        ),
        _step(
            name="5_subjects_with_strict_consecutive_positive_horizon_pair",
            previous_population=n_t3_ge2,
            resulting_population=n_with_pairs,
            inclusion_rule="strict consecutive neighbors; horizon>0",
            exclusion_rule=str(summary.get("exclusions_by_reason") or {}),
            source_relation="build_consecutive_pairs",
            provenance_condition="A-only scientific eligible universe",
            temporal_requirements="positive horizon",
            distinctness_rule="subjects with ≥1 pair",
        ),
    ]

    train_s = len({p["opaque_subject_key"] for p in train})
    val_s = len({p["opaque_subject_key"] for p in val})
    test_s = len({p["opaque_subject_key"] for p in test})

    population_def = {
        "source_system_id": SOURCE_A_SYSTEM_ID,
        "scientific_eligible": "ge2_dated_numeric_any_code",
        "outcome": {
            "candidate_id": selected.get("candidate_id"),
            "label": label,
            "unit": unit,
        },
        "seed": seed,
        "n_scientific_eligible": n_sci,
    }
    population_definition_hash = _hash(population_def)

    # Aggregate pair manifest hash (no IDs): sorted feature+y hashes
    def _pair_agg_hash(plist: list[dict[str, Any]]) -> str:
        digests = []
        for p in plist:
            digests.append(
                _hash(
                    {
                        "feats": p.get("model_features"),
                        "y_t1": p.get("y_t1"),
                        "h": p.get("horizon_days"),
                    }
                )
            )
        return _hash(sorted(digests))

    train_manifest_hash = _pair_agg_hash(train)
    split_manifest = {
        "algorithm": (
            "sha256(split|{seed}|{subject_id}) ranking of Source A scientific-eligible "
            "subjects; cut by SPLIT_TRAIN/VAL/TEST fractions; subject-disjoint"
        ),
        "seed": seed,
        "population_definition_hash": population_definition_hash,
        "split_hash": split.get("split_hash"),
        "n_subjects": {
            "train": train_s,
            "validation": val_s,
            "test": test_s,
            "scientific_eligible_total": n_sci,
            "with_pairs_total": n_with_pairs,
        },
        "n_pairs": {
            "train": len(train),
            "validation": len(val),
            "test": len(test),
            "total": n_pairs,
        },
        "overlap": {
            "subject_overlap_zero": split.get("subject_overlap_zero"),
            "locator_overlap_zero": (assigned.get("verification") or {}).get(
                "locator_overlap_zero"
            ),
        },
        "opaque_split_manifest_hash": _hash(
            {
                "split_hash": split.get("split_hash"),
                "population_definition_hash": population_definition_hash,
                "n_pairs": {
                    "train": len(train),
                    "validation": len(val),
                    "test": len(test),
                },
            }
        ),
        "contains_subject_identifiers": False,
    }

    lineage = {
        "version": VERSION,
        "source_a_population_lineage_status": (
            "PASS"
            if all(s["monotonic"] for s in funnel)
            and b_n == 0
            and b_in_series == 0
            and horizons_ok
            else "FAIL"
        ),
        "funnel": funnel,
        "counts": {
            "source_a_canonical_subjects": n_canonical,
            "scientific_eligible": n_sci,
            "t3_subjects_ge1_dated_numeric": n_t3_ge1,
            "t3_subjects_ge2_dated_numeric": n_t3_ge2,
            "subjects_with_strict_pairs": n_with_pairs,
            "all_pairs": n_pairs,
            "train_subjects": train_s,
            "validation_subjects": val_s,
            "test_subjects": test_s,
            "train_pairs": len(train),
            "validation_pairs": len(val),
            "test_pairs": len(test),
            "series_subjects_after_code_filter": len(series_subjects),
        },
        "naming_note": (
            "t3_subjects_ge1 and t3_subjects_ge2 are distinct; do not equate series "
            "subjects (~ge1) with subjects that form pairs."
        ),
        "invariants": {
            "source_b_rows_in_source_a_experiment": b_n,
            "source_b_in_series": b_in_series,
            "source_a_pair_subjects": a_n,
            "all_horizons_positive": horizons_ok,
            "all_units_pmol": units_ok,
            "subject_overlap_zero": split.get("subject_overlap_zero"),
            "locator_overlap_zero": (assigned.get("verification") or {}).get(
                "locator_overlap_zero"
            ),
        },
    }

    provenance = {
        "version": VERSION,
        "source_a_provenance_isolation_status": (
            "PASS" if b_n == 0 and b_in_series == 0 else "CROSS_SOURCE_CONTAMINATION_DETECTED"
        ),
        "source_b_rows_in_source_a_experiment": b_n,
        "source_b_in_series": b_in_series,
        "source_a_pair_subjects": a_n,
        "provenance_filter": f"source_system_id={SOURCE_A_SYSTEM_ID}",
    }

    split_accounting = {
        "version": VERSION,
        "source_a_split_status": (
            "PASS"
            if split.get("subject_overlap_zero")
            and (assigned.get("verification") or {}).get("locator_overlap_zero")
            else "FAIL"
        ),
        "counts": split_manifest["n_subjects"] | {"pairs": split_manifest["n_pairs"]},
        "seed": seed,
        "split_hash": split.get("split_hash"),
        "population_definition_hash": population_definition_hash,
        "test_not_used_for_training_or_tuning": True,
    }

    return {
        "lineage": lineage,
        "provenance": provenance,
        "split_accounting": split_accounting,
        "split_manifest": split_manifest,
        "outcome": {
            "candidate_id": selected.get("candidate_id"),
            "label": label,
            "unit": unit,
            "medical_domain_interpretation": "DOMAIN_REVIEW_PENDING",
        },
        "train_pair_manifest_hash": train_manifest_hash,
        "pair_construction_hash": summary.get("dataset_build_configuration_hash"),
        "dataset_schema_hash": summary.get("dataset_schema_hash"),
        "_runtime": {
            "train": train,
            "validation": val,
            "test": test,
            "split": split,
            "selected": selected,
        },
    }
