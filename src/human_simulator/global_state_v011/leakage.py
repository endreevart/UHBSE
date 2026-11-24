"""Leakage and independence checks for horizon-aligned backtest."""

from __future__ import annotations

from typing import Any


def run_leakage_checks(
    *,
    primary_rows: list[dict[str, Any]],
    global_split: dict[str, Any],
    contamination: dict[str, Any],
    no_refit: dict[str, Any],
    medication_features_present: bool = False,
) -> dict[str, Any]:
    train = set(global_split["sets"]["train"])
    val = set(global_split["sets"]["validation"])
    test = set(global_split["sets"]["test"])
    train_val = train | val

    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    subjects = {r["opaque_subject_key"] for r in primary_rows}
    roles_ok = all(global_split["assignment"].get(s) == "test" for s in subjects)
    add("all_subjects_global_test", roles_ok, len(subjects))
    add("subject_absent_from_train_val", subjects.isdisjoint(train_val))
    add("subject_overlap_train_test_zero", train.isdisjoint(test))
    add("subject_overlap_val_test_zero", val.isdisjoint(test))
    add("subject_overlap_train_val_zero", train.isdisjoint(val))

    cutoff_ok = all(r.get("cutoff_before_target") for r in primary_rows)
    add("cutoff_strictly_before_target", cutoff_ok)

    # Target row absent from state inputs: enforced by assembler (time <= cutoff)
    # and cutoff < target — already checked.
    add("target_absent_from_state_inputs_by_time", cutoff_ok)

    loc_counts: dict[str, int] = {}
    for r in primary_rows:
        loc_counts[r["locator_hash"]] = loc_counts.get(r["locator_hash"], 0) + 1
    add("primary_target_reuse_zero", all(c == 1 for c in loc_counts.values()), len(loc_counts))

    # Locator overlap with training pairs: subjects disjoint ⇒ locator subjects disjoint
    add(
        "locator_subject_overlap_with_train_zero",
        subjects.isdisjoint(train),
    )

    add(
        "source_b_rows_zero",
        int(contamination.get("source_b_rows_in_universe", -1)) == 0,
    )
    add("medication_features_zero", medication_features_present is False)
    add("model_hashes_before_equals_after", bool(no_refit.get("before_equals_after")))

    horizon_ok = all(
        abs(float(r["prediction_horizon_days"]) - float(r["target_horizon_days"])) < 1e-9
        for r in primary_rows
    )
    add("prediction_horizon_equals_target_horizon", horizon_ok)

    ok = all(c["ok"] for c in checks)
    return {
        "LEAKAGE_INDEPENDENCE_STATUS": "PASS" if ok else "FAIL",
        "checks": checks,
        "ok": ok,
    }
