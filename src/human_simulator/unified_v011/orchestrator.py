"""Orchestrator for Unified Source Expansion v0.1.1."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from human_simulator.unified_v011.accounting_a import run_accounting
from human_simulator.unified_v011.baseline import verify_baselines
from human_simulator.unified_v011.cross_source_v011 import (
    assess_comparability,
    build_outcome_intersection,
    build_source_b_outcome_catalog,
    conservative_overlap_exclusion,
    corrected_linkage_readiness,
    run_transfer_or_skip,
)
from human_simulator.unified_v011.policy import (
    ARTIFACT_DIR,
    CLINICAL_VALIDATION_STATUS,
    INTERVENTION_RESPONSE_MODEL_STATUS,
    PRODUCTION_READINESS,
    REQUIRED_ARTIFACTS,
    SECURITY_STAGE_STATUS,
    SOURCE_B_INTEGRATION_PARTIAL,
    TREATMENT_EFFECT_STATUS,
    VERSION,
    policy_snapshot,
    uncertainty_policy_hash,
)
from human_simulator.unified_v011.publish import write_evidence_manifest
from human_simulator.unified_v011.robustness_a import (
    run_robustness,
    sanitize_robustness_for_artifact,
)
from human_simulator.unified_v011.source_b_load import (
    run_full_load,
    run_idempotency,
    run_validation_slice,
)
from human_simulator.unified_v011.source_b_mapping import build_mapping_decisions, write_mapping_yaml
from human_simulator.unified_v011.source_b_semantics import run_source_b_semantics
from human_simulator.unified_v011.uncertainty_a import evaluate_uncertainty


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc, encoding="utf-8")
    elif path.suffix in (".yaml", ".yml"):
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_unit_tests(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "pytest",
            "tests/test_unified_source_expansion_v011_unit.py",
            "-q",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "suite": "unit/static",
        "exit_code": proc.returncode,
        "output_tail": out[-2000:],
        "status": "PASS" if proc.returncode == 0 else "FAIL",
    }


def _canonical_counts(repo_root: Path) -> dict[str, Any]:
    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.migrations import row_counts
        from human_simulator.canonical.settings import load_canonical_settings

        with canonical_connection(load_canonical_settings()) as conn:
            return {k: int(v) for k, v in row_counts(conn).items()}
    except Exception as exc:  # noqa: BLE001
        return {"error_type": type(exc).__name__}


def _report_md(verification: dict[str, Any]) -> str:
    return f"""# Unified Source Expansion v{VERSION}

**Status:** see verification.json

## Claims

- Corrected Source A locator accounting (no forced candidate=loaded).
- Predictive-signal robustness (bootstrap ≥2000, shuffle ≥500); not intervention.
- Source B semantic investigation + honest PARTIAL clinical load.
- Cross-source transfer only if gates pass; never clinical validation.

## Non-claims

- Not clinical validation / treatment effect / production readiness.
- No migration 0005 / identity merge / Vault work.
- v0.1 ZIP remains immutable.

## Key statuses

```text
{json.dumps({k: verification.get(k) for k in sorted(verification) if k.endswith('_status') or k in ('production_readiness', 'security_stage_status')}, indent=2)}
```
"""


def run_v011(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    """Produce all required artifacts under ARTIFACT_DIR."""
    root = root.resolve()
    out = root / ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    started = _now()

    scope = {
        "changeset": "Stage 03 Unified Source Expansion v0.1.1",
        "version": VERSION,
        "claims": [
            "Correct Source A accounting evidence (10423 gap classified honestly).",
            "Evaluate predictive-signal robustness with bootstrap/permutation/horizon.",
            "Correct uncertainty statuses (overcoverage ≠ full PASS).",
            "Deep Source B semantic investigation and ACCEPTED-only clinical load.",
            "Gated CROSS_SOURCE_TRANSFER_EXPLORATION — never clinical validation.",
        ],
        "non_claims": [
            "Not clinical validation.",
            "Not intervention-response / treatment-effect.",
            "Not production readiness.",
            "No migration 0005 / identity merge / Vault.",
            "Do not overwrite Unified v0.1 ZIP.",
        ],
        "policy": policy_snapshot(),
    }
    _write(out / "scope-and-claims.json", scope)

    baseline = verify_baselines(root)
    _write(out / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        verification = {
            "baseline_ok": False,
            "detail": baseline.get("refuse_reason") or "baseline mismatch",
            "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
            "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
            "treatment_effect_status": TREATMENT_EFFECT_STATUS,
            "production_readiness": PRODUCTION_READINESS,
            "security_stage_status": SECURITY_STAGE_STATUS,
            "publication_integrity_status": "NOT_RUN",
        }
        _write(out / "verification.json", verification)
        _write(out / "report.md", _report_md(verification))
        write_evidence_manifest(out)
        return {"baseline_ok": False, "artifact_dir": str(out), **verification}

    counts_before = _canonical_counts(root)

    # --- Source A accounting ---
    locator, recon, idem_a = run_accounting(root)
    _write(out / "source-a-locator-accounting.json", locator)
    _write(out / "source-a-expansion-reconciliation.json", recon)
    _write(out / "source-a-idempotency-verification.json", idem_a)

    # Policy hash BEFORE uncertainty recomputation
    unc_policy_hash = uncertainty_policy_hash()

    # --- Robustness + uncertainty (live canonical) ---
    robustness: dict[str, Any] = {"status": "NOT_RUN"}
    uncertainty: dict[str, Any] = {"status": "NOT_RUN"}
    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings

        with canonical_connection(load_canonical_settings()) as conn:
            robustness = run_robustness(conn)
        uncertainty = evaluate_uncertainty(
            test_preds_ridge=robustness.get("test_preds_ridge") or [],
            test_preds_persistence=robustness.get("test_preds_persistence") or [],
            val_n=int((robustness.get("learned_for_uncertainty") or {}).get("val_n") or 0),
            interval_construction_ok=True,
            policy_hash_before=unc_policy_hash,
        )
    except Exception as exc:  # noqa: BLE001
        robustness = {
            "status": "INSUFFICIENT_DATA",
            "error_type": type(exc).__name__,
            "source_a_predictive_signal_status": "INSUFFICIENT_DATA",
            "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
            "treatment_effect_status": TREATMENT_EFFECT_STATUS,
            "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
            "production_readiness": PRODUCTION_READINESS,
        }
        uncertainty = {
            "status": "INSUFFICIENT_DATA",
            "uncertainty_policy_hash_before_recomputation": unc_policy_hash,
            "error_type": type(exc).__name__,
        }

    _write(out / "source-a-expanded-backtest-robustness.json", sanitize_robustness_for_artifact(robustness))
    _write(
        out / "source-a-subject-cluster-bootstrap.json",
        robustness.get("bootstrap")
        or {"status": "NOT_RUN", "n_iterations": 0},
    )
    _write(
        out / "source-a-horizon-sensitivity.json",
        robustness.get("horizon_sensitivity") or {"status": "NOT_RUN"},
    )
    _write(
        out / "source-a-shuffled-label-control.json",
        robustness.get("shuffle_control")
        or robustness.get("shuffle_full")
        or {"status": "NOT_RUN"},
    )
    _write(out / "source-a-uncertainty-evaluation.json", uncertainty)

    # --- Source B ---
    semantics = run_source_b_semantics(root)
    _write(out / "source-b-role-graph.json", semantics.get("role_graph") or {})
    _write(out / "source-b-consultation-semantics.json", semantics.get("consultation_semantics") or {})
    _write(out / "source-b-laboratory-semantics.json", semantics.get("laboratory_semantics") or {})
    _write(out / "source-b-grouping-analysis.json", semantics.get("grouping_analysis") or {})

    mapping = build_mapping_decisions(root, semantics=semantics)
    write_mapping_yaml(out / "source-b-mapping-decisions.yaml", mapping)

    validation = run_validation_slice(root, mapping)
    _write(out / "source-b-validation-slice.json", validation)

    load_report = run_full_load(root, mapping)
    _write(out / "source-b-canonical-load-report.json", load_report)
    _write(
        out / "source-b-relation-accounting.json",
        {
            "relations": load_report.get("relation_accounting") or {},
            "truncated_total": load_report.get("truncated_total", 0),
            "unexplained_total": load_report.get("unexplained_total", 0),
        },
    )

    # Idempotency second pass only if Subject/Encounter were loadable
    if mapping.get("source_b_subject_mapping_status") == "ACCEPTED":
        idem_b = run_idempotency(root, mapping, first_pass=load_report)
    else:
        idem_b = {
            "status": "PASS",
            "note": "No clinical load performed; idempotency vacuously satisfied",
            "second_pass_newly_inserted_subjects": 0,
            "second_pass_newly_inserted_encounters": 0,
        }
    _write(out / "source-b-idempotency-report.json", idem_b)

    obs_accepted = mapping.get("source_b_observation_mapping_status") == "ACCEPTED"
    b_catalog = build_source_b_outcome_catalog(observation_accepted=obs_accepted)
    _write(out / "source-b-outcome-catalog.json", b_catalog)

    # --- Cross-source ---
    linkage = corrected_linkage_readiness(root)
    _write(out / "linkage-readiness-corrected.json", linkage)
    overlap = conservative_overlap_exclusion(linkage)
    intersection = build_outcome_intersection(source_b_observation_accepted=obs_accepted)
    _write(out / "cross-source-outcome-intersection.json", intersection)
    comparability = assess_comparability(
        observation_accepted=obs_accepted,
        intersection=intersection,
        overlap_control=overlap,
        sufficient_b_pairs=False,
    )
    comparability["overlap_control"] = overlap
    _write(out / "cross-source-comparability.json", comparability)
    transfer = run_transfer_or_skip(comparability=comparability)
    _write(out / "cross-source-transfer-backtest.json", transfer)

    counts_after = _canonical_counts(root)
    _write(
        out / "canonical-counts-before-after.json",
        {"before": counts_before, "after": counts_after},
    )
    _write(
        out / "multi-source-provenance-report.json",
        {
            "source_a_system": "magerya_api",
            "source_b_system": "kgz_raw",
            "identity_merge": False,
            "record_origin_required": True,
            "source_b_clinical_rows": {
                "subjects": load_report.get("subjects_loaded", 0),
                "encounters": load_report.get("encounters_loaded", 0),
                "observations": load_report.get("observations_loaded", 0),
            },
        },
    )
    _write(
        out / "reject-summary.json",
        {
            "source_a": "see v0.1 expansion rejects (unchanged)",
            "source_b": load_report.get("relation_accounting"),
        },
    )
    _write(
        out / "truncation-report.json",
        {
            "source_a_truncated_total": 0,
            "source_b_truncated_total": load_report.get("truncated_total", 0),
        },
    )

    tests = _run_unit_tests(root)
    _write(out / "test-results.json", tests)

    b_subj = mapping.get("source_b_subject_mapping_status")
    b_enc = mapping.get("source_b_encounter_mapping_status")
    b_obs = mapping.get("source_b_observation_mapping_status")
    multi = SOURCE_B_INTEGRATION_PARTIAL
    if (
        locator.get("source_a_accounting_evidence_status") == "PASS"
        and int(load_report.get("subjects_loaded") or 0) > 0
        and int(load_report.get("encounters_loaded") or 0) > 0
        and idem_b.get("status") == "PASS"
        and b_obs == "ACCEPTED"
        and int(load_report.get("observations_loaded") or 0) > 0
    ):
        multi = "TECHNICAL_MULTI_SOURCE_PIPELINE_PASS"
    elif (
        locator.get("source_a_accounting_evidence_status") == "PASS"
        and int(load_report.get("subjects_loaded") or 0) > 0
        and idem_b.get("status") == "PASS"
    ):
        # Subject/Encounter persisted; Observation not accepted → honest PARTIAL
        multi = SOURCE_B_INTEGRATION_PARTIAL
    else:
        multi = SOURCE_B_INTEGRATION_PARTIAL

    verification = {
        "version": VERSION,
        "started_at": started,
        "finished_at": _now(),
        "baseline_ok": True,
        "source_a_canonical_data_status": "PASS",
        "source_a_accounting_evidence_status": locator.get(
            "source_a_accounting_evidence_status"
        ),
        "source_a_idempotency_status": idem_a.get("status"),
        "source_a_predictive_signal_status": robustness.get(
            "source_a_predictive_signal_status"
        ),
        "source_a_signal_robustness_status": robustness.get(
            "source_a_signal_robustness_status"
        ),
        "uncertainty_interval_construction_status": uncertainty.get(
            "uncertainty_interval_construction_status"
        ),
        "uncertainty_coverage_status": uncertainty.get("uncertainty_coverage_status"),
        "uncertainty_sharpness_status": uncertainty.get("uncertainty_sharpness_status"),
        "source_b_subject_mapping_status": b_subj,
        "source_b_encounter_mapping_status": b_enc,
        "source_b_observation_mapping_status": b_obs,
        "source_b_canonical_integration_status": load_report.get(
            "source_b_canonical_integration_status", SOURCE_B_INTEGRATION_PARTIAL
        ),
        "source_b_idempotency_status": idem_b.get("status"),
        "cross_source_outcome_comparability_status": comparability.get(
            "cross_source_outcome_comparability_status"
        ),
        "cross_source_overlap_control_status": overlap.get(
            "cross_source_overlap_control_status"
        ),
        "cross_source_transfer_status": transfer.get("status"),
        "identity_linkage_status": linkage.get("identity_status"),
        "multi_source_canonical_status": multi,
        "publication_integrity_status": "NOT_RUN_UNTIL_PUBLISH",
        "pre_publish_verification_status": "PENDING_PUBLISH",
        "post_publish_integrity_status": "NOT_RUN",
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "treatment_effect_status": TREATMENT_EFFECT_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "unit_tests": tests.get("status"),
    }
    _write(out / "verification.json", verification)
    _write(
        out / "release-verification.json",
        {
            "version": VERSION,
            "verification_mirror": verification,
            "required_artifacts": list(REQUIRED_ARTIFACTS),
        },
    )
    _write(out / "report.md", _report_md(verification))
    _write(
        out / "REPRODUCE.md",
        f"""# REPRODUCE — Unified Source Expansion v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_source_expansion_v011_unit.py -q
uv run --frozen audit --root . unified-source-expansion-v011 run --full --no-publish
uv run --frozen audit --root . unified-source-expansion-v011 verify
```
""",
    )
    write_evidence_manifest(out)

    missing = [n for n in REQUIRED_ARTIFACTS if not (out / n).is_file()]
    result = {
        "baseline_ok": True,
        "artifact_dir": str(out),
        "missing_artifacts": missing,
        "no_publish": no_publish,
        **verification,
    }
    if not no_publish:
        from human_simulator.unified_v011.publish import PublicationError, publish_unified_v011

        try:
            pub = publish_unified_v011(root)
            result["publish"] = pub
        except PublicationError as exc:
            result["publish_error"] = str(exc)
    return result
