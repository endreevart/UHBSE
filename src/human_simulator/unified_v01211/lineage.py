"""Source A population lineage funnel + provenance isolation (aggregates only)."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.dataset import build_consecutive_pairs, fetch_measurement_series
from human_simulator.scientific.splits import assign_pairs_to_splits, build_subject_split
from human_simulator.unified_v011.robustness_a import fixed_outcome_selected
from human_simulator.unified_v01211.policy import (
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    SEED,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def _step(
    *,
    name: str,
    previous: int | None,
    resulting: int,
    inclusion: str,
    exclusion: str,
    source_relation: str,
    provenance_condition: str,
    subject_distinctness: str,
) -> dict[str, Any]:
    prev = previous if previous is not None else resulting
    excluded = prev - resulting
    return {
        "name": name,
        "previous_population": prev,
        "resulting_count": resulting,
        "excluded_count": excluded,
        "inclusion_criterion": inclusion,
        "exclusion_criteria": exclusion,
        "source_relation": source_relation,
        "provenance_condition": provenance_condition,
        "subject_distinctness_rule": subject_distinctness,
        "monotonic": excluded >= 0 and resulting <= prev,
    }


def count_subjects(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return int(cur.fetchone()[0])


def fetch_subject_ids(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return sorted(str(r[0]) for r in cur.fetchall())


def build_source_a_population_lineage(conn: Any, *, seed: int = SEED) -> dict[str, Any]:
    """Independent Source A-only funnel with provenance filter source_system=magerya_api."""
    selected = fixed_outcome_selected()
    label = selected.get("source_measurement_label") or FIXED_OUTCOME_LABEL
    unit = selected.get("dominant_unit") or FIXED_OUTCOME_UNIT

    # 1. total Source A subjects (canonical loaded cohort)
    total_a = count_subjects(
        conn,
        "SELECT COUNT(*) FROM canonical_evidence.subject WHERE source_system_id = %s",
        (SOURCE_A_SYSTEM_ID,),
    )
    # Note: in this DB, Subject rows for A are the load-eligible cohort (8262), not 43856.
    # Record both: catalog/raw total if available is out of scope; use canonical Subject.
    load_eligible = total_a  # current canonical Subject A population == load-eligible

    # 3. same as load for this environment (already filtered at load)
    canonical_a = total_a

    # 4. scientific split-eligible: A subjects with ≥2 dated numeric components
    sci_a_ids = fetch_subject_ids(
        conn,
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
    sci_a = len(sci_a_ids)

    # Unscoped (buggy) count — for defect explanation only
    unscoped = count_subjects(
        conn,
        """
        SELECT COUNT(*) FROM (
          SELECT o.subject_id
          FROM canonical_evidence.observation_component oc
          JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
          WHERE oc.numeric_value IS NOT NULL
            AND COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) IS NOT NULL
          GROUP BY o.subject_id
          HAVING COUNT(*) >= 2
        ) t
        """,
    )
    b_ge2 = count_subjects(
        conn,
        """
        SELECT COUNT(*) FROM (
          SELECT o.subject_id
          FROM canonical_evidence.observation_component oc
          JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
          JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
          WHERE s.source_system_id = %s
            AND oc.numeric_value IS NOT NULL
            AND COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) IS NOT NULL
          GROUP BY o.subject_id
          HAVING COUNT(*) >= 2
        ) t
        """,
        (SOURCE_B_SYSTEM_ID,),
    )

    # 5–7 T3 series / pairs under A-only eligible split
    split = build_subject_split(sci_a_ids, seed=seed)
    all_keys = set(split["sets"]["train"]) | set(split["sets"]["validation"]) | set(
        split["sets"]["test"]
    )
    series = fetch_measurement_series(
        conn, raw_code=label, dominant_unit=unit, subject_keys=all_keys
    )
    t3_subjects = len({r["opaque_subject_key"] for r in series})
    pairs, meta = build_consecutive_pairs(series, outcome=selected, config={"seed": seed})
    summary = meta.get("summary") or {}
    subjects_with_pairs = int(summary.get("n_subjects_with_pairs") or 0)
    n_pairs = int(summary.get("n_pairs") or 0)

    # Provenance of pair subjects
    pair_subj = list({p["opaque_subject_key"] for p in pairs})
    a_pairs = b_pairs = 0
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
                    a_pairs = int(n)
                elif sys == SOURCE_B_SYSTEM_ID:
                    b_pairs = int(n)

    assigned = assign_pairs_to_splits(pairs, split)
    buckets = assigned["buckets"]
    train_s = len({p["opaque_subject_key"] for p in buckets["train"]})
    val_s = len({p["opaque_subject_key"] for p in buckets["validation"]})
    test_s = len({p["opaque_subject_key"] for p in buckets["test"]})
    train_p = len(buckets["train"])
    val_p = len(buckets["validation"])
    test_p = len(buckets["test"])

    overlap_subj = (
        len(set(split["sets"]["train"]) & set(split["sets"]["validation"]))
        + len(set(split["sets"]["train"]) & set(split["sets"]["test"]))
        + len(set(split["sets"]["validation"]) & set(split["sets"]["test"]))
    )
    loc_ok = bool((assigned.get("verification") or {}).get("locator_overlap_zero"))

    steps = [
        _step(
            name="1_source_a_total_canonical_subjects",
            previous=None,
            resulting=total_a,
            inclusion="canonical_evidence.subject.source_system_id = magerya_api",
            exclusion="non-A subjects",
            source_relation="canonical_evidence.subject",
            provenance_condition=f"source_system_id={SOURCE_A_SYSTEM_ID}",
            subject_distinctness="COUNT(subject_id)",
        ),
        _step(
            name="2_source_a_load_eligible_appt3_lab1",
            previous=total_a,
            resulting=load_eligible,
            inclusion="In this DB, Subject A rows are the load-eligible cohort",
            exclusion="none within canonical Subject A",
            source_relation="canonical_evidence.subject",
            provenance_condition=f"source_system_id={SOURCE_A_SYSTEM_ID}",
            subject_distinctness="distinct subject_id",
        ),
        _step(
            name="3_canonical_source_a_subjects",
            previous=load_eligible,
            resulting=canonical_a,
            inclusion="same as load-eligible in current canonical",
            exclusion="none",
            source_relation="canonical_evidence.subject",
            provenance_condition=f"source_system_id={SOURCE_A_SYSTEM_ID}",
            subject_distinctness="distinct subject_id",
        ),
        _step(
            name="4_scientific_split_eligible_ge2_dated_numeric",
            previous=canonical_a,
            resulting=sci_a,
            inclusion="≥2 dated numeric observation_components",
            exclusion="subjects with <2 dated numeric components",
            source_relation="observation_component ⋈ observation ⋈ subject",
            provenance_condition=f"subject.source_system_id={SOURCE_A_SYSTEM_ID}",
            subject_distinctness="GROUP BY subject_id HAVING COUNT(*)>=2",
        ),
        _step(
            name="5_subjects_with_accepted_t3_pmol",
            previous=sci_a,
            resulting=t3_subjects,
            inclusion=f"raw_code={label!r} AND raw_unit={unit!r}",
            exclusion="no matching T3 series rows",
            source_relation="observation_component",
            provenance_condition=f"subject in A-only scientific eligible; code/unit fixed",
            subject_distinctness="distinct opaque_subject_key in series",
        ),
        _step(
            name="6_subjects_with_ge2_dated_numeric_t3",
            previous=t3_subjects,
            resulting=t3_subjects,  # series already requires dated numeric
            inclusion="series builder requires clinical timestamp + numeric",
            exclusion="undated rows skipped in series builder",
            source_relation="fetch_measurement_series",
            provenance_condition="A-only",
            subject_distinctness="distinct subject in series",
        ),
        _step(
            name="7_subjects_with_strict_consecutive_pairs",
            previous=t3_subjects,
            resulting=subjects_with_pairs,
            inclusion="strict consecutive neighbors; positive horizon",
            exclusion=str(summary.get("exclusions_by_reason") or {}),
            source_relation="build_consecutive_pairs",
            provenance_condition="A-only",
            subject_distinctness="subjects with ≥1 pair",
        ),
        _step(
            name="8_train_val_test_subjects",
            previous=subjects_with_pairs,
            resulting=train_s + val_s + test_s,
            inclusion="subject-level hash-ranked split on A-only scientific eligible",
            exclusion="eligible subjects without pairs",
            source_relation="build_subject_split + assign_pairs_to_splits",
            provenance_condition="A-only eligible universe",
            subject_distinctness="disjoint train/val/test",
        ),
        _step(
            name="9_train_val_test_pairs",
            previous=n_pairs,
            resulting=train_p + val_p + test_p,
            inclusion="pairs assigned by subject split",
            exclusion="none if all pair subjects in split",
            source_relation="assign_pairs_to_splits",
            provenance_condition="A-only",
            subject_distinctness="pair locators disjoint across splits",
        ),
        _step(
            name="10_test_pairs_uncertainty_recomputation",
            previous=test_p,
            resulting=test_p,
            inclusion="test split pairs used for uncertainty coverage",
            exclusion="none within test",
            source_relation="test bucket",
            provenance_condition="A-only",
            subject_distinctness="test subjects only",
        ),
    ]

    monotonic = all(s["monotonic"] and s["excluded_count"] >= 0 for s in steps)
    # steps 8–9 compare different units (subjects vs pairs) — check 1–7 + 10 carefully
    funnel_subject_steps = steps[:8]
    mono_subjects = all(
        s["monotonic"] and s["excluded_count"] >= 0 for s in funnel_subject_steps
    )

    contamination = b_pairs > 0
    status = (
        "CROSS_SOURCE_CONTAMINATION_DETECTED"
        if contamination
        else ("PASS" if mono_subjects and monotonic and overlap_subj == 0 and loc_ok else "PARTIAL")
    )

    return {
        "version": VERSION,
        "source_a_population_lineage_status": status,
        "provenance_filter": f"source_system_id={SOURCE_A_SYSTEM_ID}",
        "funnel": steps,
        "counts": {
            "source_a_total_canonical_subjects": total_a,
            "source_a_load_eligible": load_eligible,
            "canonical_source_a_subjects": canonical_a,
            "scientific_split_eligible_source_a_only": sci_a,
            "t3_series_subjects": t3_subjects,
            "subjects_with_strict_pairs": subjects_with_pairs,
            "all_t3_pairs": n_pairs,
            "train_subjects": train_s,
            "validation_subjects": val_s,
            "test_subjects": test_s,
            "train_pairs": train_p,
            "validation_pairs": val_p,
            "test_pairs_uncertainty": test_p,
        },
        "defect_41492_explanation": {
            "mislabeled_field_in_v0121": "scientific_eligible_subjects_ge2_dated_numeric",
            "observed_value": unscoped,
            "true_meaning": (
                "unscoped_all_sources_subjects_with_ge2_dated_numeric_components "
                "(fetch_eligible_subjects had no source_system filter)"
            ),
            "source_a_component": sci_a,
            "source_b_component": b_ge2,
            "sum_equals_observed": sci_a + b_ge2 == unscoped,
            "renamed_field": "unscoped_all_sources_ge2_dated_numeric_subjects",
            "must_not_be_used_as_source_a_scientific_eligible": True,
        },
        "invariants": {
            "source_b_pair_subjects": b_pairs,
            "source_a_pair_subjects": a_pairs,
            "source_b_rows_in_source_a_experiment": b_pairs,
            "subject_overlap_train_val_test": overlap_subj,
            "locator_overlap_zero": loc_ok,
            "monotonic_subject_funnel": mono_subjects,
            "negative_exclusion_forbidden": all(s["excluded_count"] >= 0 for s in steps),
        },
        "split_hash": split.get("split_hash"),
        "a_only_funnel_test_pairs": test_p,
        "authoritative_uncertainty_test_pairs": test_p,
        "runtime_train_horizons": [
            float(p["horizon_days"]) for p in buckets["train"] if p.get("horizon_days") is not None
        ],
        "runtime_train_pairs": buckets["train"],  # runtime only — stripped before write
        "_strip_before_write": True,
    }


def build_provenance_isolation(lineage: dict[str, Any]) -> dict[str, Any]:
    inv = lineage.get("invariants") or {}
    b_rows = int(inv.get("source_b_rows_in_source_a_experiment") or 0)
    ok = b_rows == 0 and int(inv.get("subject_overlap_train_val_test") or 0) == 0
    return {
        "version": VERSION,
        "source_a_provenance_isolation_status": "PASS" if ok else "CROSS_SOURCE_CONTAMINATION_DETECTED",
        "source_b_rows_in_source_a_experiment": b_rows,
        "source_a_pair_subjects": inv.get("source_a_pair_subjects"),
        "subject_overlap_train_val_test": inv.get("subject_overlap_train_val_test"),
        "locator_overlap_zero": inv.get("locator_overlap_zero"),
        "note": (
            "Pair locators for T3 raw_code/unit are Source A only. "
            "v0.1.2.1 eligible_gap field incorrectly mixed A+B into scientific_eligible count."
        ),
        "split_universe_note": (
            "v0.1.2.1 run_robustness used unscoped eligible for subject ranking; "
            "that does not insert B rows into T3 series (distinct raw_code), but "
            "this correction rebuilds the funnel with A-only eligible."
        ),
    }


def correct_uncertainty_artifact(
    prior: dict[str, Any],
    lineage: dict[str, Any],
) -> dict[str, Any]:
    """Fix mislabeled eligible field; do not retrain; keep exclusive quantile evidence."""
    out = dict(prior)
    out["version"] = VERSION
    gap = None
    # find nested eligible_gap
    rob = dict(out.get("robustness_sanitized") or {})
    if "eligible_gap" in rob:
        gap = dict(rob["eligible_gap"])
    elif "eligible_gap" in out:
        gap = dict(out["eligible_gap"])

    expl = lineage.get("defect_41492_explanation") or {}
    corrected_gap = {
        "source_a_eligible_subjects_appt3_and_lab1": lineage["counts"]["source_a_load_eligible"],
        "scientific_eligible_subjects_ge2_dated_numeric_SOURCE_A_ONLY": lineage["counts"][
            "scientific_split_eligible_source_a_only"
        ],
        "unscoped_all_sources_ge2_dated_numeric_subjects": expl.get("observed_value"),
        "unscoped_field_must_not_be_used_as_source_a_scientific_eligible": True,
        "difference_source_a_load_minus_source_a_scientific": (
            lineage["counts"]["source_a_load_eligible"]
            - lineage["counts"]["scientific_split_eligible_source_a_only"]
        ),
        "expected_difference_orienting": 265,
        "difference_matches_265": (
            lineage["counts"]["source_a_load_eligible"]
            - lineage["counts"]["scientific_split_eligible_source_a_only"]
        )
        == 265,
        "defect_v0121": {
            "mislabeled_value": expl.get("observed_value"),
            "was_sum_of_a_and_b": True,
            "source_a_component": expl.get("source_a_component"),
            "source_b_component": expl.get("source_b_component"),
        },
        "prior_raw_eligible_gap_preserved_for_audit": gap,
    }
    rob["eligible_gap"] = corrected_gap
    rob.pop("scientific_eligible_subjects_ge2_dated_numeric", None)
    out["robustness_sanitized"] = rob
    out["eligible_gap_corrected"] = corrected_gap
    out["authoritative_uncertainty_test_pairs"] = lineage.get(
        "authoritative_uncertainty_test_pairs"
    )
    out["source_a_uncertainty_evidence_status"] = (
        "PASS"
        if out.get("source_a_uncertainty_recomputation_status") == "PASS"
        and lineage.get("invariants", {}).get("source_b_rows_in_source_a_experiment") == 0
        else "PARTIAL"
    )
    out["refit_performed"] = False
    return out
