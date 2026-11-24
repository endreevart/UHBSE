"""Reproduce methodology / evidence defects from published v0.1.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_individual_state_v0111.policy import (
    ACCEPTED_V011_UIS_ARTIFACT_DIR,
    VERSION,
)


def reproduce_v011_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ACCEPTED_V011_UIS_ARTIFACT_DIR
    defects: list[dict[str, Any]] = []

    split = json.loads((art / "overlap-guarded-split.json").read_text(encoding="utf-8"))
    bal = (split.get("source_balance") or {}).get("magerya_api") or {}
    d1 = {
        "id": "source_a_subject_split_30776_6607_6473",
        "observed": bal,
        "expected": {"train": 30776, "validation": 6607, "test": 6473},
        "reproduced": bal.get("train") == 30776
        and bal.get("validation") == 6607
        and bal.get("test") == 6473,
    }
    defects.append(d1)

    sm = json.loads((art / "individual-state-dataset.json").read_text(encoding="utf-8"))
    fa = (sm.get("funnel") or {}).get("magerya_api") or {}
    d2 = {
        "id": "source_a_primary_target_subjects_8888_151_164",
        "observed": {
            "train": fa.get("train_subjects"),
            "validation": fa.get("validation_subjects"),
            "test": fa.get("test_subjects"),
        },
        "expected": {"train": 8888, "validation": 151, "test": 164},
        "reproduced": fa.get("train_subjects") == 8888
        and fa.get("validation_subjects") == 151
        and fa.get("test_subjects") == 164,
    }
    defects.append(d2)

    # Code defect: role-dependent primary_index before eligibility
    src = (
        root
        / "src/human_simulator/unified_individual_state_v011/state_dataset.py"
    ).read_text(encoding="utf-8")
    d3 = {
        "id": "val_test_pick_primary_index_before_eligibility",
        "defect": (
            "validation/test select one primary_index before checking positive horizon, "
            "same-timestamp collapse, and numeric target presence"
        ),
        "code_marker": 'if role != "train"' in src and "primary_indices[h % len" in src,
        "reproduced": 'if role != "train"' in src and "primary_indices[h % len" in src,
    }
    defects.append(d3)

    base = json.loads((art / "source-aware-baseline.json").read_text(encoding="utf-8"))
    tiny = []
    for ok, m in (base.get("outcome_metrics") or {}).items():
        if not ok.startswith("A::"):
            continue
        n = (m.get("test") or {}).get("n_subjects") or 0
        if 1 <= n <= 9:
            tiny.append({"outcome": ok, "n_test_subjects": n})
    sum_a = base.get("source_a_summary") or {}
    d4 = {
        "id": "tiny_a_test_cohorts_in_wins_losses",
        "n_a_outcomes_with_1_to_9_test_subjects": len(tiny),
        "examples": tiny[:6],
        "wins_losses_include_them": True,
        "aggregate_status": sum_a.get("INCREMENTAL_SIGNAL_STATUS")
        or base.get("SOURCE_A_INCREMENTAL_SIGNAL_STATUS"),
        "reproduced": len(tiny) >= 1,
    }
    defects.append(d4)

    d5 = {
        "id": "m2_status_without_fit",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": base.get("JOINT_MULTI_OUTCOME_MODEL_STATUS"),
        "defect": "status set to TECHNICAL_MASKED_MULTI_OUTPUT_EVALUATED without fit/predict/evaluate",
        "reproduced": base.get("JOINT_MULTI_OUTCOME_MODEL_STATUS")
        == "TECHNICAL_MASKED_MULTI_OUTPUT_EVALUATED",
    }
    defects.append(d5)

    m2m = base.get("m2_metrics") or {}
    d6 = {
        "id": "m2_metrics_lack_real_artifacts",
        "keys": sorted(m2m.keys()),
        "has_predictions": "predictions" in m2m or "test_predictions" in m2m,
        "has_parameters": "parameters" in m2m or "weights" in m2m,
        "has_loss": "loss" in m2m or "train_loss" in m2m,
        "has_per_outcome_metrics": "per_outcome" in m2m or "by_outcome" in m2m,
        "reproduced": not (
            ("predictions" in m2m or "test_predictions" in m2m)
            and ("parameters" in m2m or "weights" in m2m)
            and ("per_outcome" in m2m or "by_outcome" in m2m)
        ),
    }
    defects.append(d6)

    shadow = {}
    sp = art / "engine-unified-state-shadow.json"
    if sp.is_file():
        shadow = json.loads(sp.read_text(encoding="utf-8"))
    eng_src = (
        root / "src/human_simulator/unified_individual_state_v011/engine_shadow.py"
    ).read_text(encoding="utf-8")
    d7 = {
        "id": "engine_shadow_m1_only_single_provider",
        "ENGINE_UNIFIED_STATE_SHADOW_STATUS": shadow.get(
            "ENGINE_UNIFIED_STATE_SHADOW_STATUS"
        ),
        "defect": "shadow runs M1 Ridge for one provider/fixture; does not confirm M2 execution",
        "single_outcome_key": "outcome_key" in eng_src
        and "sorted(providers.keys())[0]" in eng_src,
        "no_m2_path": "m2" not in eng_src.lower()
        or "M2" not in eng_src
        or "frozen-m2" not in eng_src,
        "reproduced": shadow.get("ENGINE_UNIFIED_STATE_SHADOW_STATUS")
        == "TECHNICAL_SHADOW_PASS"
        and "sorted(providers.keys())[0]" in eng_src,
    }
    defects.append(d7)

    ok = all(bool(d.get("reproduced")) for d in defects)
    return {
        "version": VERSION,
        "V011_METHOD_EVIDENCE_DEFECT_REPRODUCTION_STATUS": "PASS" if ok else "FAIL",
        "defects": defects,
        "n_defects": len(defects),
        "ok": ok,
    }
