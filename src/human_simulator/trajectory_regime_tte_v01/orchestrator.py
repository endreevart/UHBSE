"""Orchestrator — Trajectory Regime + TTE Foundation v0.1."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.trajectory_regime_tte_v01.baseline_verify import verify_baseline
from human_simulator.trajectory_regime_tte_v01.defect_reproduction import (
    foundation_acceptance_matrix,
    reproduce_v01_defects,
)
from human_simulator.trajectory_regime_tte_v01.denoising_encoder import (
    encoder_identity,
    fit_denoising_encoder,
    save_encoder,
)
from human_simulator.trajectory_regime_tte_v01.engine_shadow import run_engine_shadow
from human_simulator.trajectory_regime_tte_v01.evaluate import (
    apply_foundation_gates,
    evaluate_reconstruction,
    evaluate_trajectory,
)
from human_simulator.trajectory_regime_tte_v01.ood_v02 import build_ood_v02
from human_simulator.trajectory_regime_tte_v01.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.trajectory_regime_tte_v01.regimes import discover_regimes
from human_simulator.trajectory_regime_tte_v01.transitions import build_transitions
from human_simulator.trajectory_regime_tte_v01.tte import build_tte_foundation
from human_simulator.trajectory_regime_tte_v01.vocabulary import build_train_only_vocabulary
from human_simulator.unified_individual_state_v0111.privacy_scan import scan_public


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def _write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    art.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(json.dumps({"phase": "baseline"}), flush=True)
    baseline = verify_baseline(root)
    _write_json(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    print(json.dumps({"phase": "v01_defect_reproduction"}), flush=True)
    defects = reproduce_v01_defects(root)
    _write_json(art / "v01-evidence-defect-reproduction.json", defects)
    matrix = foundation_acceptance_matrix(root, defects)
    _write_json(art / "v01-foundation-acceptance-matrix.json", matrix)
    _write_json(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "train_only_vocabulary"}), flush=True)
    vocab = build_train_only_vocabulary(root)
    _write_json(art / "outcome-vocabulary-train-only.json", {
        k: v for k, v in vocab.items() if k not in {"selected", "excluded_sample"}
    } | {
        "selected_count": len(vocab.get("selected") or []),
        "selected_head": (vocab.get("selected") or [])[:5],
        "excluded_sample": vocab.get("excluded_sample"),
    })
    if not vocab.get("ok"):
        return {"ok": False, "error": "VOCAB_FAIL", "vocab": vocab}

    csr_order = json.loads(
        (
            root
            / "artifacts/stage-03-first-unified-current-state-representation-applicability-ood-v0.1"
            / "outcome-vocabulary.json"
        ).read_text(encoding="utf-8")
    )["vocabulary_order"]

    print(json.dumps({"phase": "denoising_encoder"}), flush=True)
    model = fit_denoising_encoder(root, vocab)
    _write_json(
        art / "denoising-encoder-train-summary.json",
        {
            "model_name": model["model_name"],
            "architecture": model["architecture"],
            "n_outcomes": len(model["outcome_keys"]),
            "n_train_states_used": model["n_train_states_used"],
            "sampling_funnel": model["sampling_funnel"],
            "epoch_end_history": model["epoch_end_history"],
            "DENOISING_MASKED_ENCODER_STATUS": "TRAINED",
        },
    )

    # Freeze
    meta = {
        "train_population_hash": hashlib.sha256(
            json.dumps(sorted(model["outcome_keys"])).encode()
        ).hexdigest(),
        "split_hash": _sha(
            root
            / "artifacts/stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1"
            / "overlap-guarded-split.json"
        )
        if (
            root
            / "artifacts/stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1"
            / "overlap-guarded-split.json"
        ).is_file()
        else "",
        "target_construction_hash": "",
        "vocabulary_hash": vocab["vocabulary_hash"],
    }
    saved = save_encoder(root, model, meta)
    model = json.loads(
        (root / MODELS_DIR / "frozen-denoising-encoder.json").read_text(encoding="utf-8")
    )
    # mutation proofs
    mut = copy.deepcopy(model)
    mut["W_fore"][0][0] += 1e-3
    freeze_proof = {
        "identity": saved["identity"],
        "reload_ok": encoder_identity(model, meta) == saved["identity"],
        "coef_mutation_breaks": encoder_identity(mut, meta) != saved["identity"],
        "DENOISING_MASKED_ENCODER_STATUS": "FROZEN",
    }
    _write_json(art / "denoising-encoder-freeze-proof.json", freeze_proof)

    print(json.dumps({"phase": "evaluate"}), flush=True)
    recon_val = evaluate_reconstruction(root, model, csr_order, role="validation")
    recon_test = evaluate_reconstruction(root, model, csr_order, role="test")
    _write_json(
        art / "masked-denoising-reconstruction.json",
        {"validation": recon_val, "test": recon_test},
    )
    traj = evaluate_trajectory(root, model, csr_order, open_test=True)

    def _compact(m: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for ok, ev in (m or {}).items():
            if not isinstance(ev, dict):
                continue
            out[ok] = {
                kk: vv
                for kk, vv in ev.items()
                if kk != "bootstrap_vs_active"
            }
            if "bootstrap_vs_active" in ev:
                out[ok]["bootstrap_vs_active"] = ev["bootstrap_vs_active"]
        return out

    _write_json(
        art / "trajectory-evaluation.json",
        {
            "n_encoder_better_than_active_validation": traj.get(
                "n_encoder_better_than_active_validation"
            ),
            "normalized_metrics_train_only_scale": True,
            "m2_loader_uses_nested_model": traj.get("m2_loader_uses_nested_model"),
            "validation_compact": _compact(traj.get("validation")),
            "test_compact": _compact(traj.get("test")),
        },
    )
    gates = apply_foundation_gates(recon_val, traj)
    _write_json(art / "corrected-foundation-gates.json", gates)
    foundation_accepted = (
        gates["CORRECTED_STATE_REPRESENTATION_FOUNDATION_STATUS"] == "ACCEPTED"
    )

    print(json.dumps({"phase": "ood_v02"}), flush=True)
    ood = build_ood_v02(root, model, csr_order, foundation_accepted=foundation_accepted)
    _write_json(art / "applicability-ood-v02.json", ood)

    print(json.dumps({"phase": "transitions"}), flush=True)
    trans = build_transitions(root)
    _write_json(art / "transition-dataset.json", trans)

    print(json.dumps({"phase": "regimes"}), flush=True)
    regimes = discover_regimes(root)
    _write_json(art / "trajectory-regime-discovery.json", regimes)

    print(json.dumps({"phase": "tte"}), flush=True)
    tte = build_tte_foundation(root, use_encoder_features=foundation_accepted)
    # strip large nested for public
    tte_pub = {
        k: v
        for k, v in tte.items()
        if k not in {"observation_process_eval", "outcome_excursion_eval"}
    }
    tte_pub["observation_process_eval_summary"] = {
        "status": tte.get("OBSERVATION_PROCESS_TTE_STATUS"),
        "by_source_status": {
            s: ((tte.get("observation_process_eval") or {}).get("by_source") or {})
            .get(s, {})
            .get("status")
            for s in ("A", "B")
        },
    }
    tte_pub["outcome_excursion_eval_summary"] = {
        "status": tte.get("OUTCOME_EXCURSION_TTE_STATUS"),
        "by_source_status": {
            s: ((tte.get("outcome_excursion_eval") or {}).get("by_source") or {})
            .get(s, {})
            .get("status")
            for s in ("A", "B")
        },
    }
    # include compact concordance where available
    for ep_key, src_key in (
        ("observation_process_eval", "observation_process_eval_summary"),
        ("outcome_excursion_eval", "outcome_excursion_eval_summary"),
    ):
        for s in ("A", "B"):
            block = ((tte.get(ep_key) or {}).get("by_source") or {}).get(s) or {}
            if block.get("status") == "EVALUATED":
                tte_pub[src_key][s] = {
                    "validation_concordance": (block.get("validation") or {}).get(
                        "concordance_m1"
                    ),
                    "test_concordance": (block.get("test") or {}).get("concordance_m1"),
                    "encoder_used": block.get("encoder_used_as_foundation"),
                }
    _write_json(art / "tte-foundation.json", tte_pub)

    print(json.dumps({"phase": "engine_shadow"}), flush=True)
    shadow = run_engine_shadow(root, foundation_accepted=foundation_accepted)
    _write_json(art / "engine-trajectory-tte-shadow.json", shadow)

    priv = scan_public(art)
    _write_json(art / "public-privacy-scan.json", priv)

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V01_EVIDENCE_DEFECT_REPRODUCTION_STATUS": defects.get(
            "V01_EVIDENCE_DEFECT_REPRODUCTION_STATUS"
        ),
        "V01_OOD_CODE_ARTIFACT_REPRODUCIBILITY_STATUS": defects.get(
            "V01_OOD_CODE_ARTIFACT_REPRODUCIBILITY_STATUS"
        ),
        "PRIOR_STATE_TENSOR_FOUNDATION_STATUS": matrix.get(
            "PRIOR_STATE_TENSOR_FOUNDATION_STATUS"
        ),
        "PRIOR_STATE_ENCODER_FOUNDATION_STATUS": matrix.get(
            "PRIOR_STATE_ENCODER_FOUNDATION_STATUS"
        ),
        "TRAIN_ONLY_OUTCOME_VOCABULARY_STATUS": vocab.get(
            "TRAIN_ONLY_OUTCOME_VOCABULARY_STATUS"
        ),
        "DENOISING_MASKED_ENCODER_STATUS": freeze_proof.get(
            "DENOISING_MASKED_ENCODER_STATUS"
        ),
        "CORRECTED_STATE_REPRESENTATION_FOUNDATION_STATUS": gates.get(
            "CORRECTED_STATE_REPRESENTATION_FOUNDATION_STATUS"
        ),
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": ood.get(
            "SOURCE_STRATIFIED_APPLICABILITY_STATUS"
        ),
        "TRANSITION_DATASET_STATUS": trans.get("TRANSITION_DATASET_STATUS"),
        "TRANSITION_DATASET_ACCOUNTING_STATUS": trans.get(
            "TRANSITION_DATASET_ACCOUNTING_STATUS"
        ),
        "TRAJECTORY_REGIME_DISCOVERY_STATUS": regimes.get(
            "TRAJECTORY_REGIME_DISCOVERY_STATUS"
        ),
        "TRAJECTORY_REGIME_STABILITY_STATUS": regimes.get(
            "TRAJECTORY_REGIME_STABILITY_STATUS"
        ),
        "TIME_TO_EVENT_DATASET_STATUS": tte.get("TIME_TO_EVENT_DATASET_STATUS"),
        "OBSERVATION_PROCESS_TTE_STATUS": tte.get("OBSERVATION_PROCESS_TTE_STATUS"),
        "OUTCOME_EXCURSION_TTE_STATUS": tte.get("OUTCOME_EXCURSION_TTE_STATUS"),
        "TIME_TO_EVENT_BASELINE_STATUS": tte.get("TIME_TO_EVENT_BASELINE_STATUS"),
        "ENGINE_TRAJECTORY_TTE_SHADOW_STATUS": shadow.get(
            "ENGINE_TRAJECTORY_TTE_SHADOW_STATUS"
        ),
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED_NO_ACCEPTED_LABEL_ONTOLOGY",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
        "SAFETY_BOUNDARY_CLASSIFIER_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "PUBLIC_DATA_MINIMIZATION_STATUS": priv.get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "PUBLICATION_INTEGRITY_STATUS": "PENDING",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "TECHNICAL_PASS": False,
    }

    technical = (
        status["BASELINE_VERIFICATION_STATUS"] == "PASS"
        and status["V01_EVIDENCE_DEFECT_REPRODUCTION_STATUS"] in {"PASS", "PARTIAL"}
        and status["PRIOR_STATE_ENCODER_FOUNDATION_STATUS"]
        == "NOT_ACCEPTED_WEAK_OR_NEGATIVE_EVIDENCE"
        and status["TRAIN_ONLY_OUTCOME_VOCABULARY_STATUS"] == "PASS"
        and status["DENOISING_MASKED_ENCODER_STATUS"] == "FROZEN"
        and status["SOURCE_STRATIFIED_APPLICABILITY_STATUS"] == "TECHNICAL_EVALUATED"
        and status["TRANSITION_DATASET_STATUS"] == "BUILT"
        and status["TRANSITION_DATASET_ACCOUNTING_STATUS"] == "PASS"
        and status["TIME_TO_EVENT_DATASET_STATUS"] == "BUILT"
        and status["ENGINE_TRAJECTORY_TTE_SHADOW_STATUS"] == "TECHNICAL_SHADOW_PASS"
        and status["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
        and status["SCIENTIFIC_CROSS_SOURCE_PASS"] is False
        and defects.get("n_reproduced", 0) >= 12
    )
    status["TECHNICAL_PASS"] = technical
    _write_json(art / "status-contract.json", status)

    report = f"""# Unified Trajectory Regime Discovery and Time-to-Event Foundation v{VERSION}

**Report status: DRAFT**

## Phase 0 — CSR v0.1 audit

- `PRIOR_STATE_TENSOR_FOUNDATION_STATUS={status['PRIOR_STATE_TENSOR_FOUNDATION_STATUS']}`
- `PRIOR_STATE_ENCODER_FOUNDATION_STATUS={status['PRIOR_STATE_ENCODER_FOUNDATION_STATUS']}`
- OOD code/artifact: `{status['V01_OOD_CODE_ARTIFACT_REPRODUCIBILITY_STATUS']}`

## Corrected representation

- Denoising encoder: `{status['DENOISING_MASKED_ENCODER_STATUS']}`
- Foundation gates: `{status['CORRECTED_STATE_REPRESENTATION_FOUNDATION_STATUS']}`

## Transitions / regimes / TTE

- Transitions: `{status['TRANSITION_DATASET_STATUS']}` n={trans.get('n_transitions')}
- Regimes: `{status['TRAJECTORY_REGIME_DISCOVERY_STATUS']}`
- Observation-process TTE: `{status['OBSERVATION_PROCESS_TTE_STATUS']}`
- Outcome excursion TTE: `{status['OUTCOME_EXCURSION_TTE_STATUS']}`

## Non-claims

Classifier / Safety Boundary / medication residual / intervention / TE / QSP / PKPD: NOT_STARTED
SCIENTIFIC_CROSS_SOURCE_PASS=false
SECURITY_STAGE_STATUS=PAUSED_NOT_ACCEPTED_BY_OWNER

## TECHNICAL_PASS

`{status['TECHNICAL_PASS']}`
"""
    _write_md(art / "stage-report.md", report)
    _write_json(
        art / "verification.json",
        {
            "version": VERSION,
            "ok": technical,
            "TECHNICAL_PASS": technical,
            "duration_seconds": round(time.time() - t0, 3),
            "status": status,
        },
    )
    write_manifest(art)

    result = {
        "ok": technical,
        "artifact_dir": str(art),
        "duration_seconds": round(time.time() - t0, 3),
        "status": status,
    }
    if not no_publish and technical:
        from human_simulator.trajectory_regime_tte_v01.publish import publish

        result["publish"] = publish(root)
    return result
