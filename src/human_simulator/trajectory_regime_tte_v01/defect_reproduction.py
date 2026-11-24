"""Phase 0 — reproduce CSR v0.1 evidence defects; foundation acceptance matrix."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.trajectory_regime_tte_v01.policy import (
    ACCEPTED_CSR_ARTIFACT_DIR,
    VERSION,
)


def reproduce_v01_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ACCEPTED_CSR_ARTIFACT_DIR
    vocab = json.loads((art / "outcome-vocabulary.json").read_text(encoding="utf-8"))
    tens = json.loads((art / "current-state-tensor.json").read_text(encoding="utf-8"))
    enc = json.loads((art / "encoder-train-summary.json").read_text(encoding="utf-8"))
    recon = json.loads(
        (art / "masked-state-reconstruction.json").read_text(encoding="utf-8")
    )
    traj = json.loads((art / "trajectory-evaluation.json").read_text(encoding="utf-8"))
    ood = json.loads((art / "applicability-ood.json").read_text(encoding="utf-8"))
    sigs = json.loads(
        (art / "state-signature-candidates.json").read_text(encoding="utf-8")
    )

    enc_src = (
        root / "src/human_simulator/current_state_representation_v01/encoder.py"
    ).read_text(encoding="utf-8")
    eval_src = (
        root / "src/human_simulator/current_state_representation_v01/evaluate.py"
    ).read_text(encoding="utf-8")
    ood_src = (
        root / "src/human_simulator/current_state_representation_v01/ood.py"
    ).read_text(encoding="utf-8")
    sig_src = (
        root / "src/human_simulator/current_state_representation_v01/signatures.py"
    ).read_text(encoding="utf-8")
    pol_src = (
        root / "src/human_simulator/current_state_representation_v01/policy.py"
    ).read_text(encoding="utf-8")

    fit_body = enc_src[enc_src.find("def fit_encoder") : enc_src.find("def predict_encoder")]
    hist = enc.get("train_loss_history") or []
    loss0 = hist[0]["masked_mse"] if hist else None
    loss_last = hist[-1]["masked_mse"] if hist else None

    test_compact = traj.get("test_trajectory_compact") or {}
    test_better = sum(
        1
        for v in test_compact.values()
        if isinstance(v, dict)
        and v.get("subject_macro_mae_encoder") is not None
        and v["subject_macro_mae_encoder"] < v["subject_macro_mae_active"]
    )

    # M2 loader structure
    m2 = json.loads(
        (
            root / "private/unified-individual-state-v0111/models/frozen-m2.json"
        ).read_text(encoding="utf-8")
    )
    m2_nested = "model" in m2 and "outcome_keys" in (m2.get("model") or {})
    m2_top = "outcome_keys" in m2
    m2_loader_bug = (
        'm2.get("outcome_keys")' in eval_src or "m2.get('outcome_keys')" in eval_src
    ) and m2_nested and not m2_top

    # OOD code vs artifact: published scored 800; current code may say test[:400]
    published_n = ood.get("test_n_scored")
    code_has_400 = "test[:400]" in ood_src
    code_has_800 = "test[:800]" in ood_src
    ood_repro_defect = published_n == 800 and (code_has_400 or not code_has_800)

    # Normalized skill from held-out set scale
    scale_on_heldout = (
        "mu = sum(ys) / len(ys)" in eval_src
        and "scale = math.sqrt(var)" in eval_src
        and "train_only_scale" not in eval_src
    )

    defects = [
        {
            "id": "tensor_308_outcomes_167a_141b",
            "reproduced": vocab["funnel"]["selected"] == 308
            and vocab["funnel"]["selected_a"] == 167
            and vocab["funnel"]["selected_b"] == 141,
            "observed": {
                "selected": vocab["funnel"]["selected"],
                "a": vocab["funnel"]["selected_a"],
                "b": vocab["funnel"]["selected_b"],
            },
        },
        {
            "id": "tensor_rows_73806",
            "reproduced": tens.get("n_tensors") == 73806,
            "observed": tens.get("n_tensors"),
        },
        {
            "id": "vocabulary_train_thresholds_plus_heldout_support",
            "reproduced": vocab.get("selection_on")
            == "train_thresholds_plus_heldout_support",
            "observed": vocab.get("selection_on"),
        },
        {
            "id": "encoder_trained_on_1500_states",
            "reproduced": enc.get("n_train_states_used") == 1500
            and "MAX_TRAIN_STATES = 1500" in pol_src,
            "observed": enc.get("n_train_states_used"),
        },
        {
            "id": "no_corruption_during_training",
            "reproduced": not any(
                x in fit_body for x in ("hide_mask", "corrupt", "corruption_frac")
            ),
            "note": "reconstruction target visible on encoder input during fit",
        },
        {
            "id": "training_loss_does_not_improve",
            "reproduced": loss0 is not None
            and loss_last is not None
            and abs(loss0 - 1.34) < 0.05
            and loss_last > loss0,
            "observed": {"first": loss0, "last": loss_last},
        },
        {
            "id": "masked_recon_worse_than_train_mean",
            "reproduced": all(
                recon[r]["per_source"][s]["subject_macro_mae"]
                > recon[r]["per_source"][s]["baseline_train_mean_mae"]
                for r in ("validation", "test")
                for s in ("A", "B")
            ),
            "observed": {
                r: {
                    s: {
                        "encoder": recon[r]["per_source"][s]["subject_macro_mae"],
                        "baseline": recon[r]["per_source"][s][
                            "baseline_train_mean_mae"
                        ],
                    }
                    for s in ("A", "B")
                }
                for r in ("validation", "test")
            },
        },
        {
            "id": "trajectory_0_of_24_val_1_of_24_test",
            "reproduced": traj.get("n_encoder_better_than_active_validation") == 0
            and test_better == 1
            and len(test_compact) == 24,
            "observed": {
                "val_better": traj.get("n_encoder_better_than_active_validation"),
                "test_better": test_better,
                "n_comparable_test": len(test_compact),
            },
        },
        {
            "id": "normalized_skill_uses_heldout_scale_not_train_only",
            "reproduced": scale_on_heldout,
        },
        {
            "id": "ood_reference_first_300_train_plus_100_val_no_stratification",
            "reproduced": "train[:300]" in ood_src and "val[:100]" in ood_src,
        },
        {
            "id": "ood_code_artifact_test_n_scored_mismatch",
            "reproduced": ood_repro_defect,
            "published_test_n_scored": published_n,
            "current_code_has_test_400": code_has_400,
            "current_code_has_test_800": code_has_800,
            "V01_OOD_CODE_ARTIFACT_REPRODUCIBILITY_STATUS": "FAIL_CODE_ARTIFACT_MISMATCH",
            "note": "Published artifact reports test_n_scored=800; post-publish code uses test[:400]",
        },
        {
            "id": "signatures_400_train_no_stability",
            "reproduced": "train[:400]" in sig_src
            and "stability" not in (sigs.get("BIO_SIGNATURE_STATUS") or "").lower(),
            "observed_n_candidates": len(sigs.get("candidates") or []),
        },
        {
            "id": "prior_m2_loader_reads_outcome_keys_at_wrong_level",
            "reproduced": m2_loader_bug,
            "frozen_m2_structure": {"top_keys": list(m2.keys())[:6], "nested_model": m2_nested},
            "note": "Silent skip of prior M2 technical benchmark when outcome_keys nested under model",
        },
    ]

    all_ok = all(bool(d.get("reproduced")) for d in defects)
    return {
        "version": VERSION,
        "V01_EVIDENCE_DEFECT_REPRODUCTION_STATUS": "PASS" if all_ok else "PARTIAL",
        "V01_OOD_CODE_ARTIFACT_REPRODUCIBILITY_STATUS": "FAIL_CODE_ARTIFACT_MISMATCH",
        "defects": defects,
        "n_reproduced": sum(1 for d in defects if d.get("reproduced")),
        "n_defects": len(defects),
        "ok": all_ok,
    }


def foundation_acceptance_matrix(root: Path, defects: dict[str, Any]) -> dict[str, Any]:
    """Tensor may be technical input; encoder is NOT accepted as foundation."""
    root = Path(root).resolve()
    art = root / ACCEPTED_CSR_ARTIFACT_DIR
    tens = json.loads((art / "current-state-tensor.json").read_text(encoding="utf-8"))
    feature_ok = tens.get("CURRENT_STATE_FEATURE_CONTRACT_STATUS") == "PASS"
    leak_ok = tens.get("CURRENT_STATE_TEMPORAL_LEAKAGE_STATUS") == "PASS"
    miss_ok = tens.get("CURRENT_STATE_MISSINGNESS_CONTRACT_STATUS") == "PASS"
    tensor_built = tens.get("CURRENT_STATE_TENSOR_STATUS") == "BUILT"

    return {
        "version": VERSION,
        "PRIOR_STATE_TENSOR_FOUNDATION_STATUS": (
            "ACCEPTED_TECHNICAL_INPUT"
            if tensor_built and feature_ok and leak_ok and miss_ok
            else "NOT_ACCEPTED"
        ),
        "PRIOR_STATE_ENCODER_FOUNDATION_STATUS": "NOT_ACCEPTED_WEAK_OR_NEGATIVE_EVIDENCE",
        "rationale": {
            "tensor": "source-aware per-outcome channels + train-only scalers + no temporal leakage verified",
            "encoder": "no train-time corruption; loss non-improving; recon worse than train-mean; 0/24 val trajectory wins; FROZEN alone is not foundation",
            "do_not_rewrite_v01_zip": True,
        },
        "defect_reproduction_ok": defects.get("ok"),
        "ok": True,
    }
