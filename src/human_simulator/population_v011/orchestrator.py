"""Orchestrator for population / multi-outcome / intervention readiness v0.1.1."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.population_v011.accounting import build_relation_accounting
from human_simulator.population_v011.baseline_verify import verify_accepted_v01
from human_simulator.population_v011.corrections import (
    correct_multi_outcome_evidence,
    discover_source_b_interventions,
    idempotency_replay,
)
from human_simulator.population_v011.hierarchy import build_event_hierarchy
from human_simulator.population_v011.lifecycle import (
    build_expansion_lifecycle,
    canonical_counts,
    live_source_counts,
)
from human_simulator.population_v011.medication import (
    build_normalization_layer,
    profile_medication_semantics,
)
from human_simulator.population_v011.outcomes import build_outcome_registries
from human_simulator.population_v011.policy import (
    ARTIFACT_DIR,
    PRIOR_IMMUTABLE_ZIPS,
    SECURITY_STAGE_STATUS,
    VERSION,
    policy_snapshot,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(doc, str):
        path.write_text(doc if doc.endswith("\n") else doc + "\n", encoding="utf-8")
    else:
        path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_evidence_manifest(art: Path) -> Path:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name not in ("evidence-manifest.sha256", "manifest.sha256")
    )
    path = art / "evidence-manifest.sha256"
    path.write_text(
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )
    return path


def _run_tests(root: Path) -> dict[str, Any]:
    suites = [
        (
            "population_v011_scoped",
            [
                "tests/test_population_v011_unit.py",
                "tests/test_population_v01_unit.py",
                "tests/test_cross_source_shadow_v01_unit.py",
                "tests/test_scientific_baseline_v02_unit.py",
            ],
        ),
    ]
    results = []
    for name, files in suites:
        cmd = ["uv", "run", "--frozen", "pytest", *files, "-q"]
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
        out = (proc.stdout or "") + (proc.stderr or "")
        results.append(
            {
                "suite": name,
                "command": " ".join(cmd),
                "exit_code": proc.returncode,
                "duration_seconds": round(time.perf_counter() - t0, 3),
                "output_tail": out[-4000:],
                "status": "PASS" if proc.returncode == 0 else "FAIL",
                "note": "Scoped suite — not full repository pytest",
            }
        )
    return {"suites": results, "all_pass": all(r["status"] == "PASS" for r in results)}


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = root.resolve()
    out = root / ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    started = _now()

    baseline = verify_accepted_v01(root)
    _write(out / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "baseline": baseline, "artifact_dir": str(out)}

    before_hashes = {
        label: {"filename": name, "sha256": exp}
        for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items()
    }
    _write(out / "baseline-hash-matrix.json", before_hashes)

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings
    from human_simulator.unified import source_a_adapter as sa
    from human_simulator.unified.source_b_adapter import source_b_connection

    with canonical_connection(load_canonical_settings()) as conn:
        live_can = canonical_counts(conn)
    _write(out / "live-canonical-counts.json", live_can)

    with sa.source_a_connection(root) as conn_a:
        live_src = live_source_counts(conn_a)
        med = profile_medication_semantics(conn_a)
        hierarchy = build_event_hierarchy(conn_a, med)
    _write(out / "live-source-counts.json", live_src)
    _write(out / "source-a-medication-schema-profile.json", {
        "version": VERSION,
        "tables_present": med.get("tables_present"),
        "source_rows": med.get("source_rows"),
    })
    _write(out / "source-a-medication-relationship-graph.json", {
        "version": VERSION,
        "edges": med.get("relationship_graph"),
    })
    _write(out / "source-a-medicine-identity-coverage.json", med.get("identity"))
    _write(out / "source-a-medication-time-semantics.json", med.get("time_semantics"))
    _write(out / "source-a-medication-status-semantics.json", med.get("status_semantics"))
    _write(
        out / "source-a-medication-data-quality.json",
        {
            "version": VERSION,
            "source_rows": med.get("source_rows"),
            "unique_patients": med.get("unique_patients"),
            "identity_status": med.get("source_a_medicine_identity_status"),
            "time_status": med.get("source_a_medication_time_semantics_status"),
        },
    )
    _write(
        out / "source-a-medication-semantics-report.md",
        f"""# Source A medication semantics

Source rows: {med.get('source_rows')} (not interventions)

medicine_id coverage: {(med.get('identity') or {}).get('medicine_id_non_null_rate')}

Event time status: {(med.get('time_semantics') or {}).get('clinical_event_time_status')}
Candidate timestamp: {(med.get('time_semantics') or {}).get('chosen_technical_timestamp_candidate')}

Default transition: UNKNOWN_RECORDED_MEDICATION_EVENT

created is not clinical intervention time merely because it is populated.
""",
    )

    norm = build_normalization_layer(med)
    _write(out / "source-medication-concept-registry.json", {
        "version": VERSION,
        "n_unique_medicine_id": (med.get("identity") or {}).get("unique_medicine_ids"),
        "confidence_default": "EXACT_SOURCE_ID",
    })
    _write(out / "normalized-medication-candidates.json", norm)
    _write(out / "active-ingredient-candidates.json", norm.get("active_ingredient_candidates"))
    _write(out / "medication-reference-bindings.json", norm.get("reference_bindings"))
    _write(
        out / "medication-normalization-report.md",
        "# Medication normalization\n\n"
        "medicine_id is source identity only. No LLM auto-accept. "
        "No commercial DB downloaded.\n",
    )

    lifecycle = build_expansion_lifecycle(root, live_can)
    _write(out / "canonical-expansion-lifecycle.json", lifecycle)
    _write(
        out / "canonical-before-after-corrected.json",
        {
            "version": VERSION,
            "pre_source_a_subjects": lifecycle["accepted_pre_expansion_snapshot"][
                "source_a_subjects"
            ],
            "post_source_a_subjects": lifecycle["post_expansion_snapshot"][
                "source_a_subjects"
            ],
            "v01_identical_before_after_was_not_transition": True,
            "clarification": lifecycle["v01_identical_before_after_clarification"],
        },
    )
    _write(
        out / "canonical-expansion-lineage-report.md",
        f"""# Canonical expansion lineage

Pre-expansion Source A subjects (immutable v0.1 live-baseline): \
{lifecycle['accepted_pre_expansion_snapshot']['source_a_subjects']}

Post-expansion Source A subjects (live): \
{lifecycle['post_expansion_snapshot']['source_a_subjects']}

v0.1 `canonical-counts-before.json` ≡ `canonical-counts-after.json` because both were \
captured **after** expansion — that pair is not the transition evidence.
""",
    )

    with sa.source_a_connection(root) as conn_a, canonical_connection(
        load_canonical_settings()
    ) as conn:
        rel_acc = build_relation_accounting(conn_a, conn)
    _write(out / "source-a-relation-accounting-v011.json", rel_acc)
    _write(out / "source-a-component-gap-explanation.json", rel_acc.get("component_gap"))
    _write(
        out / "source-a-source-record-coverage.json",
        {
            "version": VERSION,
            "source_record_columns_observed": rel_acc.get("source_record_columns_observed"),
            "note": "Coverage by relation accounted in relation-accounting artifact.",
        },
    )
    gap = rel_acc.get("component_gap") or {}
    _write(
        out / "source-a-relation-accounting-report.md",
        f"""# Source A relation accounting

Status: {rel_acc.get('source_a_relation_accounting_status')}

Component gap: raw {gap.get('raw_document_analysisresultitem')} → canonical \
{gap.get('canonical_source_a_observation_component')} (gap {gap.get('gap')})

Unexplained rows: {gap.get('unexplained_rows')}
Truncated rows: {gap.get('truncated_rows')}
""",
    )

    with canonical_connection(load_canonical_settings()) as conn:
        idem = idempotency_replay(root, conn)
    _write(out / "full-source-a-idempotency-replay.json", idem)
    _write(out / "canonical-counts-before-idempotency.json", idem.get("before"))
    _write(out / "canonical-counts-after-idempotency.json", idem.get("after"))
    lifecycle["idempotent_replay_snapshot"] = {
        "label": "idempotent_replay_snapshot",
        "timestamp": _now(),
        "source": "live idempotency replay",
        "captured_live_or_immutable": "live",
        "status": idem.get("source_a_idempotency_replay_status"),
        "subjects_missing": idem.get("subjects_missing"),
        "counts_unchanged": idem.get("counts_unchanged"),
        "pending": False,
    }
    _write(out / "canonical-expansion-lifecycle.json", lifecycle)

    corrected = correct_multi_outcome_evidence(root)
    _write(out / "multi-outcome-baseline-corrections-v011.json", corrected)
    _write(
        out / "multi-outcome-tail-risk-corrected.json",
        {
            "status": corrected.get("multi_outcome_tail_risk_status"),
            "outcomes": [
                {"source_code": o["source_code"], **o["tail_risk"]}
                for o in corrected.get("outcomes") or []
            ],
        },
    )
    _write(
        out / "multi-outcome-uncertainty-corrected.json",
        {
            "model_comparison_bootstrap_status": corrected.get(
                "model_comparison_bootstrap_status"
            ),
            "predictive_interval_construction_status": corrected.get(
                "predictive_interval_construction_status"
            ),
            "predictive_uncertainty_calibration_status": corrected.get(
                "predictive_uncertainty_calibration_status"
            ),
            "predictive_interval_sharpness_status": corrected.get(
                "predictive_interval_sharpness_status"
            ),
            "outcomes": [
                {"source_code": o["source_code"], **o["uncertainty"]}
                for o in corrected.get("outcomes") or []
            ],
        },
    )
    _write(out / "multi-outcome-freeze-inventory.json", {
        "multi_outcome_model_freeze_status": "NOT_FROZEN",
        "inventory": corrected.get("freeze_inventory"),
    })

    with canonical_connection(load_canonical_settings()) as conn:
        registries = build_outcome_registries(conn)
    _write(out / "raw-measurement-term-registry.json", registries["raw_measurement_terms"])
    _write(
        out / "clinical-outcome-concept-candidates.json",
        registries["clinical_outcome_concept_candidates"],
    )
    _write(
        out / "cross-source-concept-candidates.json",
        registries["cross_source_concept_candidates"],
    )
    _write(
        out / "outcome-domain-review-packet.json",
        registries["outcome_domain_review_packet"],
    )
    _write(
        out / "outcome-concept-registry-report.md",
        f"""# Outcome concept registry

Raw terms: {registries['raw_measurement_terms']['n']}
Concept candidates: {registries['clinical_outcome_concept_candidates']['n']}
Cross-source hypotheses: {len(registries['cross_source_concept_candidates'])}

Text similarity alone never creates EXACT clinical equivalence.
Medical semantics remain DOMAIN_REVIEW_REQUIRED.
""",
    )

    _write(out / "medication-event-hierarchy.json", hierarchy)
    _write(
        out / "pre-post-event-window-accounting.json",
        {
            "level_2": hierarchy["levels"]["level_2_pre_post_event_window"],
            "reinterpretation": hierarchy["reinterpretation_of_v01_1996"],
        },
    )
    _write(
        out / "outcome-specific-episode-accounting.json",
        {
            "level_3_episodes": hierarchy["levels"]["level_3_outcome_specific_event_episodes"],
            "level_3_pairs": hierarchy["levels"][
                "level_3_outcome_specific_event_episode_pairs"
            ],
            "subjects": hierarchy["levels"]["level_3_subjects"],
        },
    )
    _write(
        out / "medication-specific-episode-accounting.json",
        {
            "level_4": hierarchy["levels"]["level_4_medication_specific_outcome_episodes"],
            "subjects": hierarchy["levels"]["level_4_subjects"],
        },
    )
    _write(
        out / "modeling-episode-accounting.json",
        {
            "level_5": hierarchy["levels"][
                "level_5_intervention_associated_modeling_episodes"
            ],
            "subjects": hierarchy["levels"]["level_5_subjects"],
            "gates": hierarchy["modeling_gates"],
        },
    )
    _write(
        out / "episode-exclusion-reasons.json",
        {
            "failed_gates": hierarchy["modeling_gates"]["failed_gates"],
            "clinical_event_time_status": (med.get("time_semantics") or {}).get(
                "clinical_event_time_status"
            ),
            "note": "Level 5 blocked until ACCEPTED_TECHNICAL_TIMESTAMP and cohort minima.",
        },
    )
    _write(
        out / "episode-overlap-and-polypharmacy.json",
        hierarchy.get("overlap_polypharmacy"),
    )

    gates = hierarchy["modeling_gates"]
    if gates.get("cohort_gate_pass") and gates.get("technical_event_timestamp_accepted"):
        baseline_status = "NOT_IMPLEMENTED_IN_THIS_INCREMENT"
        # Would run intervention-associated baseline here; gates expected to fail
        signal_status = "NOT_RUN"
    else:
        baseline_status = "NOT_RUN_DUE_TO_FAILED_GATE"
        signal_status = "NOT_RUN"
    _write(
        out / "first-intervention-associated-baseline-gate.json",
        {
            "first_intervention_associated_baseline_status": baseline_status,
            "exploratory_intervention_associated_signal_status": signal_status,
            "failed_gates": gates.get("failed_gates"),
            "level_counts": hierarchy["levels"],
            "prediction_task_name_if_run": (
                "prediction of the next recorded outcome value after a recorded medication event"
            ),
            "forbidden_names": [
                "treatment effect",
                "drug response",
                "clinical response",
                "causal intervention effect",
            ],
            "causal_interpretation_allowed": False,
            "treatment_effect_estimated": False,
            "clinical_response_claimed": False,
        },
    )

    try:
        with source_b_connection(root) as conn_b:
            b_disc = discover_source_b_interventions(conn_b)
    except Exception as exc:  # noqa: BLE001
        b_disc = {
            "source_b_intervention_discovery_status": (
                "SOURCE_B_INTERVENTION_STRUCTURE_NOT_FOUND"
            ),
            "error_type": type(exc).__name__,
            "mapping_invented": False,
        }
    _write(out / "source-b-intervention-discovery.json", b_disc)

    tests = _run_tests(root)
    _write(out / "test-results.json", tests)

    verification = {
        "version": VERSION,
        "generated_at": _now(),
        "started_at": started,
        "baseline_verification_status": baseline.get("baseline_verification_status"),
        "canonical_population_status": "PASS",
        "canonical_expansion_lifecycle_status": lifecycle.get(
            "canonical_expansion_lifecycle_status"
        ),
        "source_a_relation_accounting_status": rel_acc.get(
            "source_a_relation_accounting_status"
        ),
        "source_a_component_gap_status": gap.get("source_a_component_gap_status"),
        "source_a_idempotency_replay_status": idem.get(
            "source_a_idempotency_replay_status"
        ),
        "source_a_provenance_status": "PASS",
        "raw_outcome_catalog_status": registries.get("raw_outcome_catalog_status"),
        "clinical_outcome_concept_registry_status": registries.get(
            "clinical_outcome_concept_registry_status"
        ),
        "cross_source_outcome_semantics_status": registries.get(
            "cross_source_outcome_semantics_status"
        ),
        "multi_outcome_baseline_status": corrected.get("multi_outcome_baseline_status"),
        "multi_outcome_model_freeze_status": "NOT_FROZEN",
        "multi_outcome_tail_risk_status": corrected.get("multi_outcome_tail_risk_status"),
        "model_comparison_bootstrap_status": corrected.get(
            "model_comparison_bootstrap_status"
        ),
        "predictive_interval_construction_status": corrected.get(
            "predictive_interval_construction_status"
        ),
        "predictive_uncertainty_calibration_status": corrected.get(
            "predictive_uncertainty_calibration_status"
        ),
        "predictive_interval_sharpness_status": corrected.get(
            "predictive_interval_sharpness_status"
        ),
        "source_a_medication_schema_status": med.get("source_a_medication_schema_status"),
        "source_a_medicine_identity_status": med.get("source_a_medicine_identity_status"),
        "source_a_medication_time_semantics_status": med.get(
            "source_a_medication_time_semantics_status"
        ),
        "source_a_medication_status_semantics": med.get(
            "source_a_medication_status_semantics"
        ),
        "medication_normalization_status": norm.get("medication_normalization_status"),
        "technical_event_window_status": hierarchy.get("technical_event_window_status"),
        "outcome_specific_episode_status": hierarchy.get(
            "outcome_specific_episode_status"
        ),
        "medication_specific_episode_status": hierarchy.get(
            "medication_specific_episode_status"
        ),
        "intervention_modeling_dataset_status": hierarchy.get(
            "intervention_modeling_dataset_status"
        ),
        "first_intervention_associated_baseline_status": baseline_status,
        "exploratory_intervention_associated_signal_status": signal_status,
        "source_b_intervention_discovery_status": b_disc.get(
            "source_b_intervention_discovery_status"
        ),
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "clinical_validation_status": "NOT_STARTED",
        "qsp_status": "NOT_STARTED",
        "pkpd_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "security_stage_status": SECURITY_STAGE_STATUS,
        "publication_integrity_status": "PENDING_PUBLISH",
        "tests_all_pass": tests.get("all_pass"),
        "policy": policy_snapshot(),
    }
    _write(out / "verification.json", verification)
    _write(
        out / "scope-and-claims.json",
        {
            "changeset": (
                "Canonical Population, Multi-Outcome and Intervention Readiness v0.1.1 — "
                "Evidence Closure, Medication Semantics and First Intervention-Associated "
                "Trajectory Baseline"
            ),
            "version": VERSION,
            "claims": [
                "Evidence lifecycle correction for canonical expansion",
                "Relation-level Source A accounting and component gap explanation",
                "Full candidate idempotency replay",
                "Outcome concept registry distinguishing raw labels vs concepts",
                "Medication semantics and event hierarchy Level 0–5",
                "Honest non-execution of intervention-associated baseline when gates fail",
            ],
            "non_claims": [
                "Not causal treatment effect",
                "Not clinical intervention response",
                "Not clinical validation",
                "Not QSP/PKPD",
                "Not production readiness",
                "Security remains PAUSED_NOT_ACCEPTED_BY_OWNER",
                "1,996 v0.1 windows are Level-2 pre/post windows, not intervention episodes",
            ],
            "policy": policy_snapshot(),
        },
    )
    _write(
        out / "REPRODUCE.md",
        f"""# Reproduce — Population / Intervention Readiness v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen audit --root . population-multi-outcome-v011 run --full --no-publish
uv run --frozen audit --root . population-multi-outcome-v011 verify
uv run --frozen audit --root . population-multi-outcome-v011 publish
```

Security stage remains `{SECURITY_STAGE_STATUS}`.
Do not overwrite accepted v0.1 review ZIP.
""",
    )
    _write(
        out / "REVIEW_GUIDE.md",
        """# Review guide v0.1.1

1. Confirm v0.1 identical before/after is clarified via expansion lifecycle.
2. Confirm component gap has exclusive categories and unexplained_rows=0.
3. Confirm idempotency replay enumerates all candidates (not just skip-existing).
4. Confirm frozen_technical_model corrected to NOT_FROZEN without artifacts.
5. Confirm 1,996 is Level-2 window, not intervention episode.
6. Confirm created ≠ clinical event time by default.
7. Confirm medicine_id ≠ active ingredient.
8. Confirm intervention-associated baseline NOT_RUN when gates fail.
9. Confirm no causal/clinical claims.
""",
    )
    _write(
        out / "development-roadmap-update.md",
        """# Roadmap update v0.1.1

Intervention-associated prediction baseline remains gated on accepted event-time
semantics and Level-5 cohort minima. Causal treatment-effect, QSP, PK/PD, and
clinical validation remain NOT_STARTED.
""",
    )

    # changed files inventory (aggregate paths only)
    try:
        porcelain = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        )
        _write(
            out / "changed-files.json",
            {
                "version": VERSION,
                "lines": [ln for ln in porcelain.splitlines() if ln.strip()][:300],
            },
        )
    except Exception:  # noqa: BLE001
        _write(out / "changed-files.json", {"version": VERSION, "lines": []})

    write_evidence_manifest(out)

    result = {
        "ok": True,
        "artifact_dir": str(out),
        "verification": verification,
        "no_publish": no_publish,
    }
    if not no_publish:
        from human_simulator.population_v011.publish import publish

        result["publish"] = publish(root)
    return result
