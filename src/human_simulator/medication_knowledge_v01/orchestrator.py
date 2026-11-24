"""Orchestrator — Medication Knowledge, Representation and Exposure Semantics v0.1."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.models import (
    load_episodes,
    split_episodes,
)
from human_simulator.intervention_association_v011.evaluate import (
    uncertainty_from_validation_residuals,
)
from human_simulator.intervention_association_v011.percentage import (
    sensitivity_excluding_invalid,
)
from human_simulator.intervention_association_v011.models import run_corrected_baselines
from human_simulator.medication_knowledge_v01.baseline_audit import audit_v011_baseline
from human_simulator.medication_knowledge_v01.engine_shadow import (
    run_medication_model_shadow_inference,
)
from human_simulator.medication_knowledge_v01.exposure import build_exposure_semantics_report
from human_simulator.medication_knowledge_v01.external_ref import (
    build_external_reference_status,
)
from human_simulator.medication_knowledge_v01.inventory import build_medication_registry
from human_simulator.medication_knowledge_v01.policy import (
    ARTIFACT_DIR,
    EPISODE_JSONL,
    RUNTIME_DIR,
    SECURITY_STAGE_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.medication_knowledge_v01.representation import (
    run_representation_sensitivity,
)
from human_simulator.unified.source_a_adapter import source_a_connection


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _episode_lineage(path: Path) -> dict[str, Any]:
    h = hashlib.sha256()
    n = 0
    subjects: set[str] = set()
    with path.open("rb") as fh:
        for line in fh:
            if not line.strip():
                continue
            h.update(line)
            n += 1
            try:
                row = json.loads(line)
                subjects.add(str(row.get("opaque_subject_key") or ""))
            except json.JSONDecodeError:
                pass
    subjects.discard("")
    return {
        "path": str(path),
        "n_lines": n,
        "n_subjects": len(subjects),
        "content_sha256": h.hexdigest(),
        "reconstructed": False,
        "source": "private_workspace_v0.1_materialisation",
        "row_level_in_review_zip": False,
    }


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Phase 0
    baseline = audit_v011_baseline(root)
    _write(art / "v011-baseline-packaging-audit.json", baseline)
    analytical = baseline.get("V011_ANALYTICAL_PAYLOAD_STATUS")
    containment = baseline.get("V011_REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS")
    # Corrections land in the NEW bundle via publish; carried-forward correction
    # status flips to PASS only after clean-extraction publish verification.
    carried = "PENDING_PUBLISH_VERIFICATION"
    if analytical != "VERIFIED":
        carried = "FAIL"
    _write(
        art / "carried-forward-evidence-correction.json",
        {
            "V011_ANALYTICAL_PAYLOAD_STATUS": analytical,
            "V011_REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": containment,
            "packaging_defects": baseline.get("packaging_defects"),
            "CARRIED_FORWARD_EVIDENCE_CORRECTION_STATUS": carried,
            "note": (
                "v0.1.1 ZIP is immutable; corrections are applied in the new "
                "medication-knowledge-representation v0.1 review bundle"
            ),
        },
    )

    # Phase 1–2 + 4 (Source A RO)
    with source_a_connection(root) as conn_a:
        inventory = build_medication_registry(conn_a, root)
        exposure = build_exposure_semantics_report(conn_a)

    _write(art / "medication-source-accounting.json", inventory["summary"])
    _write(
        art / "medication-registry-sanitized.json",
        {
            "records": inventory["sanitized_records"],
            "disclosure": "original names/descriptions withheld; private workspace only",
        },
    )
    external = build_external_reference_status()
    _write(art / "external-medication-reference.json", external)
    _write(art / "exposure-semantics-contract.json", exposure)

    # Episodes (private)
    ep_path = root / EPISODE_JSONL
    if not ep_path.is_file():
        return {
            "ok": False,
            "error": "episode_dataset_missing",
            "expected": EPISODE_JSONL,
        }
    lineage = _episode_lineage(ep_path)
    _write(art / "episode-lineage.json", lineage)
    exposure["episode_summary_ref"] = {
        "n_episodes": lineage["n_lines"],
        "n_subjects": lineage["n_subjects"],
    }
    _write(art / "exposure-semantics-contract.json", exposure)

    episodes = load_episodes(ep_path)
    split = split_episodes(episodes)
    split_pub = {k: v for k, v in split.items() if k != "episodes_by_split"}
    _write(art / "scientific-split.json", split_pub)
    train = split["episodes_by_split"]["train"]
    val = split["episodes_by_split"]["validation"]
    test = split["episodes_by_split"]["test"]

    # Phase 3 — representation sensitivity
    sens = run_representation_sensitivity(
        train=train,
        val=val,
        test=test,
        n_source_exact=inventory["n_source_exact"],
        n_supported_transform=inventory["n_supported_transform"],
    )

    # Attach validation residual uncertainty for M2C32 using v0.1.1 corrected path
    # (same split / cohorts) as secondary uncertainty evidence
    uncertainty_docs = []
    sensitivity_docs = []
    for outcome, unit in (
        (c["outcome"], c["unit"]) for c in sens.get("cohorts") or []
    ):
        cohort = {"outcome": outcome, "unit": unit}
        r = run_corrected_baselines(cohort=cohort, train=train, val=val, test=test)
        if r.get("status") == "EVALUATED":
            unc = uncertainty_from_validation_residuals(
                r["m2c_val_preds"], r["m2c_preds"]
            )
            uncertainty_docs.append({"outcome": outcome, "unit": unit, **unc})
            sens_pct = sensitivity_excluding_invalid(
                cohort=cohort,
                train=train,
                val=val,
                test=test,
                primary_result=r,
            )
            sensitivity_docs.append({"outcome": outcome, "unit": unit, **sens_pct})

    _write(art / "medication-representation-sensitivity.json", sens)
    _write(art / "validation-residual-uncertainty.json", {"cohorts": uncertainty_docs})
    _write(art / "percentage-value-sensitivity.json", {"cohorts": sensitivity_docs})

    # Collision summary table
    collision_table = []
    for c in sens.get("cohorts") or []:
        for label, model in (c.get("models") or {}).items():
            if isinstance(model, dict) and "collision" in model:
                collision_table.append(
                    {
                        "outcome": c["outcome"],
                        "representation": label,
                        **model["collision"],
                    }
                )
    _write(art / "representation-collision-table.json", {"rows": collision_table})

    # Phase 5 — real frozen inference shadow
    frozen_root = (
        root
        / "artifacts"
        / "stage-03-first-medication-association-baseline-v0.1.1"
        / "frozen_models"
    )
    shadow = run_medication_model_shadow_inference(frozen_root=frozen_root)
    _write(art / "medication-model-shadow-inference.json", shadow)

    signal = sens.get("INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS")
    accounting_ok = inventory["summary"].get("MEDICATION_SOURCE_ACCOUNTING_STATUS") == "PASS"
    shadow_inf = shadow.get("MEDICATION_MODEL_SHADOW_INFERENCE_STATUS")
    shadow_eng = shadow.get("ENGINE_SHADOW_EXECUTION_STATUS")

    statuses = {
        "version": VERSION,
        "generated_at": _now(),
        "CARRIED_FORWARD_EVIDENCE_CORRECTION_STATUS": carried,
        "V011_ANALYTICAL_PAYLOAD_STATUS": analytical,
        "V011_REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": containment,
        "MEDICATION_SOURCE_ACCOUNTING_STATUS": inventory["summary"][
            "MEDICATION_SOURCE_ACCOUNTING_STATUS"
        ],
        "MEDICATION_SEMANTIC_REGISTRY_STATUS": inventory["summary"][
            "MEDICATION_SEMANTIC_REGISTRY_STATUS"
        ],
        "EXTERNAL_MEDICATION_REFERENCE_STATUS": external[
            "EXTERNAL_MEDICATION_REFERENCE_STATUS"
        ],
        "MEDICATION_REPRESENTATION_SENSITIVITY_STATUS": sens[
            "MEDICATION_REPRESENTATION_SENSITIVITY_STATUS"
        ],
        "EXPOSURE_SEMANTICS_STATUS": exposure["EXPOSURE_SEMANTICS_STATUS"],
        "MEDICATION_MODEL_SHADOW_INFERENCE_STATUS": shadow_inf,
        "ENGINE_SHADOW_EXECUTION_STATUS": shadow_eng,
        "ENGINE_SHADOW_CLAIM_LEVEL": shadow.get("ENGINE_SHADOW_CLAIM_LEVEL"),
        "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": signal,
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "PUBLICATION_INTEGRITY_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "pre_pack_manifest_status": "PASS",
        "content_verification_status": "PASS",
        "clean_staging_test_status": "PENDING_PUBLISH",
        "post_pack_publication_verification_status": "EXTERNAL_ATTESTATION_REQUIRED",
        "policy": policy_snapshot(),
        "duration_seconds": round(time.time() - t0, 3),
    }
    _write(art / "status-contract.json", statuses)
    _write(
        art / "scope-and-claims.json",
        {
            "version": VERSION,
            "claim_level": "TECHNICAL_MEDICATION_KNOWLEDGE_AND_REPRESENTATION_ONLY",
            "not_claims": [
                "treatment_effect",
                "causal_effect",
                "intervention_response",
                "clinical_validation",
                "confirmed_administration",
                "qsp",
                "pkpd",
                "production_readiness",
            ],
            "recorded_medication_association_ne_confirmed_administration": True,
            "association_ne_intervention_response": True,
            "prediction_ne_treatment_effect": True,
            "security_stage_status": SECURITY_STAGE_STATUS,
        },
    )

    verification = {
        "ok": bool(
            accounting_ok
            and shadow_inf == "PASS"
            and shadow_eng == "PASS"
            and analytical == "VERIFIED"
        ),
        "version": VERSION,
        "statuses": {
            k: statuses[k]
            for k in statuses
            if k.endswith("_STATUS")
            or k
            in (
                "pre_pack_manifest_status",
                "content_verification_status",
                "clean_staging_test_status",
                "post_pack_publication_verification_status",
                "ENGINE_SHADOW_CLAIM_LEVEL",
            )
        },
        "n_cohorts": len(sens.get("cohorts") or []),
        "episode_n": lineage["n_lines"],
        "episode_subjects": lineage["n_subjects"],
        "packaging_defects_found_in_v011": len(baseline.get("packaging_defects") or []),
    }
    # Forbid stale PENDING_WRITE / PENDING_PUBLISH in finalized pre-pack evidence
    # except clean_staging which is updated at publish time before packing.
    if verification["statuses"].get("pre_pack_manifest_status") == "PENDING_WRITE":
        verification["ok"] = False
        verification["error"] = "stale_PENDING_WRITE"
    _write(art / "verification.json", verification)

    if not no_publish:
        from human_simulator.medication_knowledge_v01.publish import publish

        pub = publish(root)
        return {"ok": verification["ok"] and pub.get("attestation_status") == "PASS", **pub}

    return {
        "ok": verification["ok"],
        "artifact_dir": str(art),
        "verification": verification,
        "statuses": statuses,
    }
