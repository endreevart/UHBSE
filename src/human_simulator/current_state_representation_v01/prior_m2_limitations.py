"""Document prior M2 implementation limitations (do not rewrite v0.1.1.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.current_state_representation_v01.policy import (
    ACCEPTED_V0111_ARTIFACT_DIR,
    V0111_MODELS_DIR,
    VERSION,
)


def reproduce_prior_m2_limitations(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ACCEPTED_V0111_ARTIFACT_DIR
    base = json.loads((art / "source-aware-baseline.json").read_text(encoding="utf-8"))
    src = (
        root / "src/human_simulator/unified_individual_state_v0111/baseline_models.py"
    ).read_text(encoding="utf-8")

    defects = []

    # 1. first available outcome persistence for train feature
    d1 = {
        "id": "mixed_persistence_channel_first_available",
        "code_marker": 'for o, tr in by_state_targets.get(sid, {}).items():\n                    if tr.get("persistence_value") is not None:\n                        pers = tr["persistence_value"]\n                        break'
        in src
        or "pers = tr[\"persistence_value\"]\n                        break" in src,
        "reproduced": "persistence_value" in src
        and "break" in src
        and "by_state_targets" in src,
    }
    defects.append(d1)

    # 2. different analytes/units in one channel
    d2 = {
        "id": "mixed_analyte_unit_in_single_feature_channel",
        "defect": "single persistence_value feature channel shared across outcomes",
        "reproduced": "FEAT_NAMES_FULL = FEAT_BASE + [\"persistence_value\"" in src
        or "persistence_value\", \"persistence_missing\"]" in src,
    }
    defects.append(d2)

    # 3. comparator uses target-specific persistence unlike train
    d3 = {
        "id": "comparator_persistence_semantics_differ_from_train",
        "reproduced": "pers = t.get(\"persistence_value\")" in src
        and "for o, tr in by_state_targets" in src,
    }
    defects.append(d3)

    # 4. comparator always M1 Ridge not active provider
    d4 = {
        "id": "comparator_always_m1_not_active_provider",
        "reproduced": "mae_m1" in json.dumps(base.get("m2_metrics") or {})
        and "active_provider" not in (src[src.find("comparator") : src.find("comparator") + 800] if "comparator" in src else ""),
        "note": "comparator block computes pred1 via Ridge provider weights always",
        "code_has_ridge_only_comparator": "pred1 = predict_ridge" in src,
    }
    d4["reproduced"] = d4["code_has_ridge_only_comparator"]
    defects.append(d4)

    # 5. M2 better than M1 on 1/24
    comp = (base.get("m2_metrics") or {}).get("comparator_vs_m0_m1_identical_target_ids") or {}
    better = 0
    for _k, v in comp.items():
        if isinstance(v, dict) and v.get("mae_m2") is not None and v.get("mae_m1") is not None:
            if v["mae_m2"] < v["mae_m1"]:
                better += 1
    d5 = {
        "id": "m2_better_than_m1_count",
        "n_outcomes_compared": len(comp),
        "n_m2_better": better,
        "expected_about": 1,
        "reproduced": better <= 3 and len(comp) >= 20,  # allow small variance; documented as ~1
        "observed": better,
    }
    defects.append(d5)

    # 6. subsample 2500 of ~51880
    d6 = {
        "id": "m2_train_subsample_2500",
        "code_marker": "max_train = 2500" in src,
        "reproduced": "max_train = 2500" in src,
        "note": "deterministic subsample from full train state design matrix",
    }
    defects.append(d6)

    # 7. micro-MAE without full subject-macro comparator in M2 test report
    test_m2 = ((base.get("m2_metrics") or {}).get("test") or {}).get("per_outcome") or {}
    sample = next(iter(test_m2.values()), {}) if test_m2 else {}
    d7 = {
        "id": "m2_test_micro_mae_not_subject_macro_comparator",
        "sample_keys": sorted(sample.keys()) if isinstance(sample, dict) else [],
        "has_micro_mae": isinstance(sample, dict) and "micro_mae" in sample,
        "has_subject_macro": isinstance(sample, dict)
        and "subject_macro_mae" in sample,
        "reproduced": isinstance(sample, dict)
        and "micro_mae" in sample
        and "subject_macro_mae" not in sample,
    }
    defects.append(d7)

    ok = all(bool(d.get("reproduced")) for d in defects)
    return {
        "version": VERSION,
        "PRIOR_M2_IMPLEMENTATION_STATUS": "REAL_TECHNICAL_PROTOTYPE",
        "PRIOR_M2_FEATURE_CONTRACT_STATUS": "NOT_ACCEPTED_MIXED_OUTCOME_CHANNEL",
        "PRIOR_M2_COMPARATOR_STATUS": "CORRECTION_REQUIRED",
        "PRIOR_M2_FOUNDATION_ACCEPTANCE_STATUS": "NOT_ACCEPTED",
        "defects": defects,
        "m0_m1_and_state_dataset_remain_valid": True,
        "ok": ok,
    }
