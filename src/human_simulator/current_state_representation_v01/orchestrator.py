"""Orchestrator — Current State Representation + Applicability/OOD v0.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.current_state_representation_v01.baseline_verify import verify_baseline
from human_simulator.current_state_representation_v01.encoder import fit_encoder
from human_simulator.current_state_representation_v01.engine_shadow import run_engine_shadow
from human_simulator.current_state_representation_v01.evaluate import (
    evaluate_masked_reconstruction,
    evaluate_trajectory,
)
from human_simulator.current_state_representation_v01.freeze import freeze_and_prove
from human_simulator.current_state_representation_v01.ood import build_applicability_ood
from human_simulator.current_state_representation_v01.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.current_state_representation_v01.prior_m2_limitations import (
    reproduce_prior_m2_limitations,
)
from human_simulator.current_state_representation_v01.signatures import (
    build_signature_candidates,
)
from human_simulator.current_state_representation_v01.tensor import build_current_state_tensors
from human_simulator.current_state_representation_v01.vocabulary import (
    build_outcome_vocabulary,
)
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
    import hashlib

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

    print(json.dumps({"phase": "baseline_verify"}), flush=True)
    baseline = verify_baseline(root)
    _write_json(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    print(json.dumps({"phase": "prior_m2_limitations"}), flush=True)
    prior_m2 = reproduce_prior_m2_limitations(root)
    _write_json(art / "prior-m2-limitations.json", prior_m2)
    _write_json(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "outcome_vocabulary"}), flush=True)
    vocab = build_outcome_vocabulary(root)
    _write_json(art / "outcome-vocabulary.json", vocab)
    if not vocab.get("ok"):
        return {"ok": False, "error": "VOCAB_FAIL", "vocab": vocab}

    print(json.dumps({"phase": "current_state_tensor"}), flush=True)
    tensor_meta = build_current_state_tensors(root, vocab)
    _write_json(art / "current-state-tensor.json", tensor_meta)
    if not tensor_meta.get("ok"):
        return {"ok": False, "error": "TENSOR_FAIL", "tensor": tensor_meta}

    print(json.dumps({"phase": "fit_encoder"}), flush=True)
    model = fit_encoder(root, vocab)
    _write_json(
        art / "encoder-train-summary.json",
        {
            "model_name": model["model_name"],
            "architecture": model["architecture"],
            "n_outcomes": len(model["outcome_keys"]),
            "n_train_states_used": model["n_train_states_used"],
            "final_train_masked_mse": model["final_train_masked_mse"],
            "train_loss_history": model["train_loss_history"],
            "vocabulary_hash": model["vocabulary_hash"],
        },
    )

    print(json.dumps({"phase": "freeze"}), flush=True)
    freeze = freeze_and_prove(root, model, vocab)
    _write_json(art / "encoder-freeze-proof.json", freeze)
    model = json.loads((root / MODELS_DIR / "frozen-encoder.json").read_text(encoding="utf-8"))

    print(json.dumps({"phase": "masked_reconstruction"}), flush=True)
    recon_val = evaluate_masked_reconstruction(root, model, role="validation")
    recon_test = evaluate_masked_reconstruction(root, model, role="test")
    _write_json(
        art / "masked-state-reconstruction.json",
        {"validation": recon_val, "test": recon_test},
    )

    print(json.dumps({"phase": "trajectory_eval"}), flush=True)
    traj = evaluate_trajectory(root, model, open_test=True)
    # strip huge per-outcome dumps for public? Keep aggregates + compact metrics
    public_traj = {
        k: v
        for k, v in traj.items()
        if k
        not in {
            "validation_trajectory",
            "test_trajectory",
        }
    }
    # keep compact outcome metrics without subject ids
    def _compact(m: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for ok, ev in m.items():
            if not isinstance(ev, dict):
                continue
            out[ok] = {kk: vv for kk, vv in ev.items() if kk != "bootstrap_vs_active"}
            if "bootstrap_vs_active" in ev:
                out[ok]["bootstrap_vs_active"] = {
                    kk: vv
                    for kk, vv in (ev.get("bootstrap_vs_active") or {}).items()
                    if kk != "per_draw"
                }
        return out

    public_traj["validation_trajectory_compact"] = _compact(traj.get("validation_trajectory") or {})
    public_traj["test_trajectory_compact"] = _compact(traj.get("test_trajectory") or {})
    _write_json(art / "trajectory-evaluation.json", public_traj)

    print(json.dumps({"phase": "applicability_ood"}), flush=True)
    ood = build_applicability_ood(root, model)
    _write_json(art / "applicability-ood.json", ood)
    # copy reference aggregate (no row latents)
    ood_ref = json.loads(
        (root / MODELS_DIR / "applicability-ood-reference.json").read_text(encoding="utf-8")
    )
    ood_ref_pub = {
        k: v
        for k, v in ood_ref.items()
        if k != "latent_centroid"
    }
    ood_ref_pub["latent_centroid_dim"] = len(ood_ref.get("latent_centroid") or [])
    ood_ref_pub["latent_centroid_l2"] = sum(
        x * x for x in (ood_ref.get("latent_centroid") or [])
    ) ** 0.5
    _write_json(art / "applicability-ood-reference-public.json", ood_ref_pub)

    print(json.dumps({"phase": "signatures"}), flush=True)
    sigs = build_signature_candidates(root, model)
    _write_json(art / "state-signature-candidates.json", sigs)

    print(json.dumps({"phase": "engine_shadow"}), flush=True)
    shadow = run_engine_shadow(root)
    _write_json(art / "engine-current-state-shadow.json", shadow)

    priv = scan_public(art)
    _write_json(art / "public-privacy-scan.json", priv)

    a_status = "EVALUATED" if (public_traj.get("validation_summary_a") or {}).get("n_outcomes", 0) else "NOT_RUN"
    b_status = "EVALUATED" if (public_traj.get("validation_summary_b") or {}).get("n_outcomes", 0) else "NOT_RUN"

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "PRIOR_M2_IMPLEMENTATION_STATUS": prior_m2.get("PRIOR_M2_IMPLEMENTATION_STATUS"),
        "PRIOR_M2_FEATURE_CONTRACT_STATUS": prior_m2.get("PRIOR_M2_FEATURE_CONTRACT_STATUS"),
        "PRIOR_M2_COMPARATOR_STATUS": prior_m2.get("PRIOR_M2_COMPARATOR_STATUS"),
        "PRIOR_M2_FOUNDATION_ACCEPTANCE_STATUS": prior_m2.get(
            "PRIOR_M2_FOUNDATION_ACCEPTANCE_STATUS"
        ),
        "SOURCE_SPECIFIC_OUTCOME_VOCABULARY_STATUS": vocab.get(
            "SOURCE_SPECIFIC_OUTCOME_VOCABULARY_STATUS"
        ),
        "CURRENT_STATE_TENSOR_STATUS": tensor_meta.get("CURRENT_STATE_TENSOR_STATUS"),
        "CURRENT_STATE_FEATURE_CONTRACT_STATUS": tensor_meta.get(
            "CURRENT_STATE_FEATURE_CONTRACT_STATUS"
        ),
        "CURRENT_STATE_TEMPORAL_LEAKAGE_STATUS": tensor_meta.get(
            "CURRENT_STATE_TEMPORAL_LEAKAGE_STATUS"
        ),
        "CURRENT_STATE_MISSINGNESS_CONTRACT_STATUS": tensor_meta.get(
            "CURRENT_STATE_MISSINGNESS_CONTRACT_STATUS"
        ),
        "CURRENT_STATE_REPRESENTATION_STATUS": freeze.get("CURRENT_STATE_REPRESENTATION_STATUS"),
        "MASKED_STATE_RECONSTRUCTION_STATUS": "EVALUATED"
        if recon_val.get("ok")
        else "NOT_RUN",
        "SOURCE_A_STATE_REPRESENTATION_STATUS": a_status,
        "SOURCE_B_STATE_REPRESENTATION_STATUS": b_status,
        "SOURCE_AWARE_TRAJECTORY_HEAD_STATUS": traj.get("SOURCE_AWARE_TRAJECTORY_HEAD_STATUS"),
        "INCREMENTAL_STATE_REPRESENTATION_SIGNAL_STATUS": traj.get(
            "INCREMENTAL_STATE_REPRESENTATION_SIGNAL_STATUS"
        ),
        "APPLICABILITY_REFERENCE_STATUS": ood.get("APPLICABILITY_REFERENCE_STATUS"),
        "APPLICABILITY_OOD_DETECTOR_STATUS": ood.get("APPLICABILITY_OOD_DETECTOR_STATUS"),
        "CLINICAL_OOD_VALIDATION_STATUS": "NOT_STARTED",
        "BIO_SIGNATURE_STATUS": "CANDIDATE_ONLY",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED_NO_ACCEPTED_LABEL_ONTOLOGY",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
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
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "ENGINE_CURRENT_STATE_REPRESENTATION_SHADOW_STATUS": shadow.get(
            "ENGINE_CURRENT_STATE_REPRESENTATION_SHADOW_STATUS"
        ),
        "PUBLIC_DATA_MINIMIZATION_STATUS": priv.get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "TECHNICAL_PASS": False,
    }

    technical = (
        status["BASELINE_VERIFICATION_STATUS"] == "PASS"
        and status["PRIOR_M2_FEATURE_CONTRACT_STATUS"] == "NOT_ACCEPTED_MIXED_OUTCOME_CHANNEL"
        and status["PRIOR_M2_FOUNDATION_ACCEPTANCE_STATUS"] == "NOT_ACCEPTED"
        and status["SOURCE_SPECIFIC_OUTCOME_VOCABULARY_STATUS"] == "PASS"
        and status["CURRENT_STATE_TENSOR_STATUS"] == "BUILT"
        and status["CURRENT_STATE_FEATURE_CONTRACT_STATUS"] == "PASS"
        and status["CURRENT_STATE_TEMPORAL_LEAKAGE_STATUS"] == "PASS"
        and status["CURRENT_STATE_MISSINGNESS_CONTRACT_STATUS"] == "PASS"
        and status["CURRENT_STATE_REPRESENTATION_STATUS"] == "FROZEN"
        and status["MASKED_STATE_RECONSTRUCTION_STATUS"] == "EVALUATED"
        and status["SOURCE_AWARE_TRAJECTORY_HEAD_STATUS"] == "EVALUATED"
        and status["APPLICABILITY_REFERENCE_STATUS"] == "BUILT"
        and status["APPLICABILITY_OOD_DETECTOR_STATUS"] == "TECHNICAL_EVALUATED"
        and status["ENGINE_CURRENT_STATE_REPRESENTATION_SHADOW_STATUS"]
        == "TECHNICAL_SHADOW_PASS"
        and status["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
        and status["SCIENTIFIC_CROSS_SOURCE_PASS"] is False
    )
    status["TECHNICAL_PASS"] = technical
    _write_json(art / "status-contract.json", status)

    report = f"""# First Unified A+B Current State Representation and Applicability/OOD Foundation v{VERSION}

**Report status: DRAFT**

## Baseline

- Immutable input: individual-state baseline v0.1.1.1
- `BASELINE_VERIFICATION_STATUS={status['BASELINE_VERIFICATION_STATUS']}`

## Prior M2 (not accepted foundation)

- `PRIOR_M2_FEATURE_CONTRACT_STATUS={status['PRIOR_M2_FEATURE_CONTRACT_STATUS']}`
- `PRIOR_M2_FOUNDATION_ACCEPTANCE_STATUS={status['PRIOR_M2_FOUNDATION_ACCEPTANCE_STATUS']}`

## Vocabulary / Tensor / Encoder

- Outcomes selected (train thresholds): {vocab.get('funnel', {}).get('selected')}
- A/B selected: {vocab.get('funnel', {}).get('selected_a')} / {vocab.get('funnel', {}).get('selected_b')}
- Tensor: `{status['CURRENT_STATE_TENSOR_STATUS']}` n={tensor_meta.get('n_tensors')}
- Model: `UnifiedSourceAwareStateEncoderV01` — `{status['CURRENT_STATE_REPRESENTATION_STATUS']}`

## Evaluation

- Masked reconstruction: `{status['MASKED_STATE_RECONSTRUCTION_STATUS']}`
- Trajectory heads: `{status['SOURCE_AWARE_TRAJECTORY_HEAD_STATUS']}`
- Incremental signal: `{status['INCREMENTAL_STATE_REPRESENTATION_SIGNAL_STATUS']}`

## Applicability / OOD (technical only)

- Reference: `{status['APPLICABILITY_REFERENCE_STATUS']}`
- Detector: `{status['APPLICABILITY_OOD_DETECTOR_STATUS']}`
- Clinical OOD validation: NOT_STARTED
- Not a clinical safety detector.

## Non-claims

- Current State Classifier: NOT_STARTED_NO_ACCEPTED_LABEL_ONTOLOGY
- Medication residual / intervention / TE / QSP / PKPD: NOT_STARTED / NOT_EVALUATED
- SCIENTIFIC_CROSS_SOURCE_PASS=false
- SECURITY_STAGE_STATUS=PAUSED_NOT_ACCEPTED_BY_OWNER

## Engine shadow

`{status['ENGINE_CURRENT_STATE_REPRESENTATION_SHADOW_STATUS']}`

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
        from human_simulator.current_state_representation_v01.publish import publish

        result["publish"] = publish(root)
    return result
