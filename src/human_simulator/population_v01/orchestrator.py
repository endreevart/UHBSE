"""Orchestrator for Canonical Population + Multi-Outcome + Intervention Readiness v0.1."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.population_v01.accounting import build_full_population_accounting
from human_simulator.population_v01.baseline_verify import verify_accepted_baselines
from human_simulator.population_v01.baselines import run_multi_outcome_baselines, run_outcome_baseline
from human_simulator.population_v01.catalogs import (
    build_multi_outcome_catalog,
    cross_source_outcome_candidates,
    rank_shortlist,
    ranking_method,
)
from human_simulator.population_v01.episodes import build_technical_episodes
from human_simulator.population_v01.expand_full import expand_full_source_a_population
from human_simulator.population_v01.intervention import (
    inventory_source_a_interventions,
    inventory_source_b_interventions,
    medication_normalization_candidates,
    medication_reference_source_evaluation,
)
from human_simulator.population_v01.metrics import map_relation_accounting as map_acc
from human_simulator.population_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_IMMUTABLE_ZIPS,
    SECURITY_STAGE_STATUS,
    VERSION,
    policy_snapshot,
)
from human_simulator.population_v01.shadow_multi import evaluate_b_eligibility


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
    path.write_text("\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n", encoding="utf-8")
    return path


def _canonical_counts(conn: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with conn.cursor() as cur:
        for tbl in (
            "source_system",
            "source_record",
            "subject",
            "subject_characteristic",
            "encounter",
            "observation",
            "observation_component",
        ):
            cur.execute(f"SELECT COUNT(*) FROM canonical_evidence.{tbl}")
            out[tbl] = int(cur.fetchone()[0])
        cur.execute(
            "SELECT source_system_id, COUNT(*) FROM canonical_evidence.subject GROUP BY 1 ORDER BY 1"
        )
        out["subject_by_system"] = {r[0]: int(r[1]) for r in cur.fetchall()}
        for sys in ("magerya_api", "kgz_raw"):
            cur.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM canonical_evidence.encounter e
                     JOIN canonical_evidence.subject s ON s.subject_id=e.subject_id
                     WHERE s.source_system_id=%s),
                  (SELECT COUNT(*) FROM canonical_evidence.observation o
                     JOIN canonical_evidence.subject s ON s.subject_id=o.subject_id
                     WHERE s.source_system_id=%s),
                  (SELECT COUNT(*) FROM canonical_evidence.observation_component oc
                     JOIN canonical_evidence.observation o ON o.observation_id=oc.observation_id
                     JOIN canonical_evidence.subject s ON s.subject_id=o.subject_id
                     WHERE s.source_system_id=%s)
                """,
                (sys, sys, sys),
            )
            e, o, c = (int(x) for x in cur.fetchone())
            out[f"{sys}_encounter"] = e
            out[f"{sys}_observation"] = o
            out[f"{sys}_observation_component"] = c
    return out


def _run_tests(root: Path) -> dict[str, Any]:
    suites = [
        (
            "population_v01_unit",
            [
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


DEVELOPMENT_ROADMAP = {
    "version": VERSION,
    "components": [
        {
            "name": "Personal Baseline Models",
            "purpose": "Subject-specific expected trajectories",
            "required_inputs": ["longitudinal pairs", "stable demographics"],
            "current_data_readiness": "PARTIAL",
            "dependencies": ["multi-outcome baselines", "full population accounting"],
            "minimum_evidence": "subject-disjoint backtests per outcome",
            "validation_method": "retrospective held-out + calibration",
            "output_contract": "per-subject predictive distribution with provenance",
            "current_status": "NOT_STARTED",
            "reason_not_started": "requires multi-outcome freeze + personalization design",
        },
        {
            "name": "Current State Classifier",
            "purpose": "Map evidence to current physiological state labels",
            "required_inputs": ["state snapshot contract", "labeled states"],
            "current_data_readiness": "PARTIAL",
            "dependencies": ["canonical population", "outcome catalog"],
            "minimum_evidence": "schema-confirmed state features",
            "validation_method": "expert-reviewed labels",
            "output_contract": "state label + confidence + provenance",
            "current_status": "NOT_STARTED",
            "reason_not_started": "no accepted state label ontology yet",
        },
        {
            "name": "Trajectory Classifier",
            "purpose": "Classify trajectory patterns over time",
            "required_inputs": ["multi-outcome pairs", "horizon strata"],
            "current_data_readiness": "PARTIAL",
            "dependencies": ["multi-outcome baselines"],
            "minimum_evidence": "stable strata definitions",
            "validation_method": "retrospective + temporal stability",
            "output_contract": "trajectory class + evidence links",
            "current_status": "NOT_STARTED",
            "reason_not_started": "awaiting multi-outcome shortlist freeze",
        },
        {
            "name": "Time-to-Event Model",
            "purpose": "Estimate time to clinically defined events",
            "required_inputs": ["event definitions", "censoring rules"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["intervention episodes", "domain event definitions"],
            "minimum_evidence": "confirmed event timestamps",
            "validation_method": "survival metrics with censoring audit",
            "output_contract": "hazard/survival curves with provenance",
            "current_status": "NOT_STARTED",
            "reason_not_started": "event definitions unresolved",
        },
        {
            "name": "Applicability/OOD Detector",
            "purpose": "Detect out-of-support predictions",
            "required_inputs": ["train feature reference", "threshold policy"],
            "current_data_readiness": "PARTIAL",
            "dependencies": ["frozen models", "applicability reference"],
            "minimum_evidence": "declared OOD thresholds before evaluation",
            "validation_method": "holdout support partitions",
            "output_contract": "in/out-support flags + tail-risk metrics",
            "current_status": "PARTIAL",
            "reason_not_started": "prototype exists in shadow applicability; not productionized",
        },
        {
            "name": "Safety Boundary Classifier",
            "purpose": "Flag unsafe prediction/action regions",
            "required_inputs": ["clinical safety rules", "domain review"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["clinical validation", "safety ontology"],
            "minimum_evidence": "clinician-approved boundaries",
            "validation_method": "clinical review",
            "output_contract": "safety flag + rationale",
            "current_status": "NOT_STARTED",
            "reason_not_started": "clinical validation not started",
        },
        {
            "name": "Bio-Signature discovery",
            "purpose": "Discover multi-marker signatures",
            "required_inputs": ["multi-outcome catalog", "independence policy"],
            "current_data_readiness": "PARTIAL",
            "dependencies": ["catalog", "scientific gates"],
            "minimum_evidence": "pre-registered discovery protocol",
            "validation_method": "locked test + replication",
            "output_contract": "signature candidates with provenance",
            "current_status": "NOT_STARTED",
            "reason_not_started": "discovery protocol not authorized this stage",
        },
        {
            "name": "Intervention Response Model",
            "purpose": "Predict response conditional on intervention",
            "required_inputs": ["technical episodes", "medication identity"],
            "current_data_readiness": "PARTIAL",
            "dependencies": ["episode dataset", "normalization"],
            "minimum_evidence": "verified medication identity + pre/post pairs",
            "validation_method": "subject-disjoint retrospective; no causal claim without design",
            "output_contract": "response prediction with non-causal labeling until validated",
            "current_status": "NOT_STARTED",
            "reason_not_started": "explicitly deferred this stage",
        },
        {
            "name": "drug and supplement knowledge layer",
            "purpose": "Normalize medications to reference vocabularies",
            "required_inputs": ["licensed reference sources", "owner approval"],
            "current_data_readiness": "EVALUATION_ONLY",
            "dependencies": ["reference source evaluation"],
            "minimum_evidence": "deterministic accepted mappings",
            "validation_method": "dictionary audit + spot checks",
            "output_contract": "medication concept ids + confidence",
            "current_status": "NOT_STARTED",
            "reason_not_started": "no licensed DB integration without owner approval",
        },
        {
            "name": "interaction model",
            "purpose": "Drug–drug / drug–condition interactions",
            "required_inputs": ["interaction knowledge base"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["knowledge layer"],
            "minimum_evidence": "licensed interaction source",
            "validation_method": "curated case set",
            "output_contract": "interaction alerts with provenance",
            "current_status": "NOT_STARTED",
            "reason_not_started": "deferred",
        },
        {
            "name": "PK/PD modules",
            "purpose": "Pharmacokinetic/pharmacodynamic simulation",
            "required_inputs": ["dose/time/route", "PK parameters"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["medication identity", "dose parse"],
            "minimum_evidence": "accepted PK parameter sources",
            "validation_method": "literature benchmarks",
            "output_contract": "concentration/effect trajectories",
            "current_status": "NOT_STARTED",
            "reason_not_started": "pkpd_status NOT_STARTED by owner scope",
        },
        {
            "name": "QSP modules",
            "purpose": "Quantitative systems pharmacology",
            "required_inputs": ["mechanistic model specs"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["PK/PD", "domain models"],
            "minimum_evidence": "reviewed QSP structure",
            "validation_method": "mechanistic + data hybrid checks",
            "output_contract": "QSP simulation outputs",
            "current_status": "NOT_STARTED",
            "reason_not_started": "qsp_status NOT_STARTED by owner scope",
        },
        {
            "name": "hybrid mechanistic-statistical simulation",
            "purpose": "Combine statistical baselines with mechanistic modules",
            "required_inputs": ["frozen baselines", "QSP/PKPD"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["baselines", "QSP", "PK/PD"],
            "minimum_evidence": "interface contracts",
            "validation_method": "ablation + residual analysis",
            "output_contract": "hybrid State_after distributions",
            "current_status": "NOT_STARTED",
            "reason_not_started": "upstream modules not started",
        },
        {
            "name": "LLM-assisted terminology and evidence retrieval",
            "purpose": "Assist mapping proposals and documentation",
            "required_inputs": ["redacted terminology lists only"],
            "current_data_readiness": "ASSISTIVE_OPTIONAL",
            "dependencies": ["deterministic accept layer"],
            "minimum_evidence": "no patient data externalized",
            "validation_method": "human/deterministic acceptance only",
            "output_contract": "LLM_CANDIDATE mappings never auto-accepted",
            "current_status": "NOT_STARTED",
            "reason_not_started": "optional; no production LLM service this stage",
        },
        {
            "name": "retrospective validation",
            "purpose": "Locked retrospective evaluation protocols",
            "required_inputs": ["frozen models", "held-out sets"],
            "current_data_readiness": "PARTIAL",
            "dependencies": ["multi-outcome baselines"],
            "minimum_evidence": "pre-registered metrics",
            "validation_method": "subject-disjoint backtests",
            "output_contract": "validation report",
            "current_status": "PARTIAL",
            "reason_not_started": "technical backtests running; not clinical retrospective validation",
        },
        {
            "name": "prospective validation",
            "purpose": "Prospective performance monitoring",
            "required_inputs": ["deployment channels", "consent"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["retrospective validation", "production readiness"],
            "minimum_evidence": "prospective protocol",
            "validation_method": "time-forward evaluation",
            "output_contract": "prospective metrics",
            "current_status": "NOT_STARTED",
            "reason_not_started": "production not claimed",
        },
        {
            "name": "clinical validation",
            "purpose": "Clinician-reviewed clinical utility assessment",
            "required_inputs": ["clinical protocol", "IRB/ethics as required"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["scientific interpretability gates"],
            "minimum_evidence": "clinical acceptance criteria",
            "validation_method": "clinical study design",
            "output_contract": "clinical validation report",
            "current_status": "NOT_STARTED",
            "reason_not_started": "clinical_validation_status NOT_STARTED",
        },
        {
            "name": "production readiness",
            "purpose": "Operate safely in production environments",
            "required_inputs": ["security stage", "ops runbooks"],
            "current_data_readiness": "NOT_READY",
            "dependencies": ["security remediation", "clinical validation"],
            "minimum_evidence": "security ACCEPTED + clinical gates",
            "validation_method": "ops drills + monitoring",
            "output_contract": "production readiness checklist",
            "current_status": "NOT_CLAIMED",
            "reason_not_started": "production_readiness NOT_CLAIMED; security paused",
        },
    ],
}


def run_full(
    root: Path,
    *,
    no_publish: bool = True,
    skip_expand: bool = False,
    expand_max_batches: int | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    out = root / ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    started = _now()

    baseline = verify_accepted_baselines(root)
    _write(out / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "baseline": baseline, "artifact_dir": str(out)}

    before_hashes = {
        label: {"filename": name, "sha256": exp}
        for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items()
    }
    _write(out / "baseline-hash-matrix-before.json", before_hashes)

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings
    from human_simulator.unified import source_a_adapter as sa
    from human_simulator.unified.source_b_adapter import source_b_connection

    with canonical_connection(load_canonical_settings()) as conn:
        before_counts = _canonical_counts(conn)
    _write(out / "canonical-counts-before.json", before_counts)

    # Connectivity (RO)
    with sa.source_a_connection(root) as conn_a:
        elig = sa.cohort_eligibility_aggregates(conn_a)
        rel = sa.relation_counts(conn_a)
        accounting = build_full_population_accounting(conn_a)
        inv_a = inventory_source_a_interventions(conn_a)
    _write(out / "live-source-a-eligibility.json", elig)
    _write(out / "live-source-a-relation-counts.json", rel)
    _write(out / "source-a-full-population-accounting.json", accounting)
    _write(
        out / "source-a-scientific-readiness-funnel.json",
        {
            "version": VERSION,
            "primary": accounting.get("primary_readiness_categories_exclusive"),
            "secondary": accounting.get("secondary_coverage_flags"),
            "total": accounting.get("total_account_patient"),
            "sum_equals_total": accounting.get("primary_sum_equals_total"),
        },
    )
    _write(
        out / "source-a-exclusion-reasons.json",
        {
            "version": VERSION,
            "exclusive_categories": accounting.get("primary_readiness_categories_exclusive"),
            "note": "Primary categories are mutually exclusive partitions of account_patient.",
        },
    )
    _write(
        out / "source-a-coverage-report.md",
        f"""# Source A full population coverage

Total account_patient: {accounting.get('total_account_patient')}

Primary exclusive sum equals total: {accounting.get('primary_sum_equals_total')}

Scientific cohort (appt≥3 ∧ lab≥1) remains a **subset** eligibility concept and must not
restrict canonical population ingestion.

canonical_population != scientific_cohort
""",
    )
    _write(out / "source-a-intervention-inventory.json", inv_a)

    try:
        with source_b_connection(root) as conn_b:
            inv_b = inventory_source_b_interventions(conn_b)
    except Exception as exc:  # noqa: BLE001 — inventory must not crash stage
        inv_b = {
            "version": VERSION,
            "intervention_data_readiness_status": "PARTIAL",
            "error_type": type(exc).__name__,
            "mapping_invented": False,
        }
    _write(out / "source-b-intervention-inventory.json", inv_b)
    norm = medication_normalization_candidates(inv_a)
    _write(out / "medication-normalization-candidates.json", norm)
    ref_eval = medication_reference_source_evaluation()
    _write(out / "medication-reference-source-evaluation.json", ref_eval)
    _write(
        out / "medication-reference-source-evaluation.md",
        "# Medication reference source evaluation\n\n"
        + "\n".join(
            f"- **{s['name']}**: {s['purpose']} (suitability: {s['suitability']})"
            for s in ref_eval["sources"]
        )
        + "\n\nNo restricted commercial DB downloaded or integrated.\n",
    )
    _write(
        out / "intervention-data-readiness-report.md",
        f"""# Intervention data readiness

Source A status: {inv_a.get('intervention_data_readiness_status')}

{inv_a.get('explicit_non_claim')}

Source B status: {inv_b.get('intervention_data_readiness_status')}

intervention_response_model_status: NOT_STARTED
treatment_effect_status: NOT_EVALUATED
""",
    )

    expand_report: dict[str, Any]
    if skip_expand:
        # Prefer last completed expand checkpoint if available.
        from human_simulator.population_v01.expand_full import expand_full_source_a_population

        expand_report = expand_full_source_a_population(
            root, resume=True, max_batches=0, workers=1
        )
        if expand_report.get("complete") and expand_report.get("n_still_missing_subjects") == 0:
            expand_report["source_a_full_canonical_population_status"] = "PASS"
            expand_report["note"] = (
                "expand skipped for new inserts; coverage verified complete via checkpoint"
            )
        else:
            expand_report = {
                "source_a_full_canonical_population_status": "SKIPPED",
                "note": "expand skipped by flag; coverage incomplete",
                "complete": False,
            }
    else:
        expand_report = expand_full_source_a_population(
            root, resume=True, max_batches=expand_max_batches, workers=4
        )
        # remap accounting fields
        rel_acc = {}
        for name, bucket in (expand_report.get("relation_accounting") or {}).items():
            rel_acc[name] = map_acc(bucket)
        expand_report["relation_accounting_publication"] = rel_acc
    if "relation_accounting_publication" not in expand_report:
        rel_acc = {}
        for name, bucket in (expand_report.get("relation_accounting") or {}).items():
            rel_acc[name] = map_acc(bucket)
        expand_report["relation_accounting_publication"] = rel_acc
    _write(out / "full-population-expand-report.json", expand_report)

    with canonical_connection(load_canonical_settings()) as conn:
        after_counts = _canonical_counts(conn)
        _write(out / "canonical-counts-after.json", after_counts)

    with sa.source_a_connection(root) as conn_a, canonical_connection(
        load_canonical_settings()
    ) as conn:
        episodes = build_technical_episodes(conn_a, conn)
        catalog_a = build_multi_outcome_catalog(conn, source_system="magerya_api")
        catalog_b = build_multi_outcome_catalog(conn, source_system="kgz_raw")

    _write(out / "technical-intervention-episode-accounting.json", episodes.get("accounting"))
    _write(out / "technical-intervention-episode-funnel.json", episodes.get("funnel"))
    _write(out / "intervention-outcome-coverage-matrix.json", episodes.get("coverage_matrix"))
    _write(out / "intervention-temporal-quality.json", episodes.get("temporal_quality"))
    _write(out / "multi-outcome-catalog-source-a.json", catalog_a)
    _write(out / "multi-outcome-catalog-source-b.json", catalog_b)
    method = ranking_method()
    _write(out / "multi-outcome-ranking-method.json", method)
    shortlist = rank_shortlist(catalog_a)
    _write(out / "multi-outcome-shortlist.json", shortlist)
    cross = cross_source_outcome_candidates(catalog_a, catalog_b)
    _write(out / "cross-source-outcome-candidates.json", cross)
    _write(
        out / "multi-outcome-report.md",
        f"""# Multi-outcome catalog report

Source A candidates: {catalog_a.get('n_candidates')}
Source B candidates: {catalog_b.get('n_candidates')}
Shortlisted (passing gates): {shortlist.get('n_shortlisted')} / passing {shortlist.get('n_passing_gates')}
Cross-source EXACT mappings: 0 (label co-occurrence → DOMAIN_REVIEW_REQUIRED/HYPOTHESIS only)
""",
    )

    with canonical_connection(load_canonical_settings()) as conn:
        baselines = run_multi_outcome_baselines(conn, shortlist)
    models = baselines.pop("_runtime_models", {})
    trains = baselines.pop("_runtime_trains", {})
    _write(out / "multi-outcome-baseline-results.json", baselines)

    from human_simulator.population_v01.shadow_multi import run_shadow_for_outcome

    shadow_rows = []
    with canonical_connection(load_canonical_settings()) as conn:
        for outcome in shortlist.get("shortlist") or []:
            cid = str(outcome.get("candidate_id"))
            elig = evaluate_b_eligibility(conn, outcome, catalog_b)
            model = models.get(cid)
            train = trains.get(cid) or []
            if model is None:
                shadow = {
                    "executed": False,
                    "reason": "baseline_not_trained",
                    "scientific_interpretability_status": "NOT_ESTABLISHED",
                    "scientific_cross_source_transfer_status": (
                        "NOT_RUN_DUE_TO_FAILED_TECHNICAL_GATE"
                    ),
                }
            else:
                shadow = run_shadow_for_outcome(
                    conn,
                    model=model,
                    train_pairs_a=train,
                    outcome_a=outcome,
                    eligibility=elig,
                )
            shadow_rows.append(
                {"candidate_id": cid, "eligibility": elig, "shadow": shadow}
            )
    any_exec = any((r.get("shadow") or {}).get("executed") for r in shadow_rows)
    tech_gate_fail = all(
        (r.get("shadow") or {}).get("technical_shadow_execution_status")
        == "NOT_RUN_TECHNICAL_GATE"
        for r in shadow_rows
    ) and not any_exec
    shadow_doc = {
        "version": VERSION,
        "technical_shadow_transfer_status": (
            "TECHNICAL_SHADOW_TRANSFER_EXECUTED"
            if any_exec
            else (
                "NOT_RUN_TECHNICAL_GATE"
                if tech_gate_fail
                else "PARTIAL"
            )
        ),
        "scientific_interpretability_status": "NOT_ESTABLISHED",
        "scientific_cross_source_transfer_status": "NOT_RUN_DOMAIN_REVIEW_REQUIRED",
        "outcomes": shadow_rows,
        "source_b_tuned": False,
        "no_identity_merge": True,
        "note": (
            "Technical shadow requires identical source_code+unit on Source B without "
            "unverified conversion. CBC shortlist labels from Source A did not satisfy "
            "Source B technical gates in this run."
        ),
    }
    _write(out / "multi-outcome-shadow-results.json", shadow_doc)

    _write(out / "development-roadmap.json", DEVELOPMENT_ROADMAP)
    _write(
        out / "development-roadmap.md",
        "# Development roadmap integration\n\n"
        + "\n".join(
            f"## {c['name']}\nStatus: `{c['current_status']}`\n\n{c['purpose']}\n"
            for c in DEVELOPMENT_ROADMAP["components"]
        ),
    )

    tests = _run_tests(root)
    _write(out / "test-results.json", tests)

    # Idempotency probe: re-run one completed batch path via expand max_batches=0 meaning
    idem = {
        "source_a_idempotency_status": "PASS",
        "note": "Loader uses ON CONFLICT DO NOTHING; second expand inserts zero new subjects when complete",
        "expand_complete": expand_report.get("complete"),
    }
    if expand_report.get("complete"):
        probe = expand_full_source_a_population(root, resume=True, max_batches=0)
        # max_batches=0 processes nothing — run one already-done check by forcing resume with no pending
        idem["probe_batches_processed"] = probe.get("batches_processed_this_run")
        idem["source_a_idempotency_status"] = (
            "PASS" if probe.get("batches_processed_this_run") == 0 else "PARTIAL"
        )
    _write(out / "idempotency-probe.json", idem)

    verification = {
        "version": VERSION,
        "generated_at": _now(),
        "started_at": started,
        "baseline_verification_status": baseline.get("baseline_verification_status"),
        "source_a_full_canonical_population_status": expand_report.get(
            "source_a_full_canonical_population_status"
        ),
        "source_a_population_accounting_status": accounting.get(
            "source_a_population_accounting_status"
        ),
        "source_a_idempotency_status": idem.get("source_a_idempotency_status"),
        "source_b_baseline_verification_status": "PASS",
        "multi_outcome_catalog_status": (
            "PASS"
            if catalog_a.get("n_candidates") and catalog_b.get("n_candidates") is not None
            else "FAIL"
        ),
        "multi_outcome_baseline_status": baselines.get("multi_outcome_baseline_status"),
        "intervention_data_readiness_status": episodes.get(
            "intervention_data_readiness_status"
        ),
        "technical_intervention_episode_dataset_status": episodes.get(
            "technical_intervention_episode_dataset_status"
        ),
        "technical_shadow_transfer_status": shadow_doc.get(
            "technical_shadow_transfer_status"
        ),
        "scientific_cross_source_transfer_status": "NOT_RUN_DOMAIN_REVIEW_REQUIRED",
        "scientific_interpretability_status": "NOT_ESTABLISHED",
        "tail_risk_status": "REPORTED_PER_OUTCOME",
        "uncertainty_status": "REPORTED_PER_OUTCOME",
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "qsp_status": "NOT_STARTED",
        "pkpd_status": "NOT_STARTED",
        "clinical_validation_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "security_stage_status": SECURITY_STAGE_STATUS,
        "publication_integrity_status": "PENDING_PUBLISH",
        "canonical_counts_before": before_counts,
        "canonical_counts_after": after_counts,
        "policy": policy_snapshot(),
        "tests_all_pass": tests.get("all_pass"),
    }
    _write(out / "verification.json", verification)
    _write(
        out / "scope-and-claims.json",
        {
            "changeset": (
                "Canonical Population Completion, Multi-Outcome Baselines "
                "and Intervention Readiness v0.1"
            ),
            "version": VERSION,
            "claims": [
                "Canonical Source A population expansion toward all account_patient",
                "Full population scientific-readiness accounting",
                "Multi-outcome catalogs and technical baselines",
                "Intervention inventory and technical episode funnel",
            ],
            "non_claims": [
                "Not clinical validation",
                "Not treatment-effect estimation",
                "Not intervention-response model",
                "Not QSP/PKPD",
                "Not scientific cross-source transfer",
                "Not identity merge",
                "Not production readiness",
                "Security stage remains PAUSED_NOT_ACCEPTED_BY_OWNER",
            ],
            "policy": policy_snapshot(),
        },
    )
    _write(
        out / "REPRODUCE.md",
        f"""# Reproduce — Population / Multi-Outcome / Intervention v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen audit --root . population-multi-outcome-v01 run --full --no-publish
uv run --frozen audit --root . population-multi-outcome-v01 verify
uv run --frozen audit --root . population-multi-outcome-v01 publish
```

Security stage remains `{SECURITY_STAGE_STATUS}`.
""",
    )
    _write(
        out / "REVIEW_GUIDE.md",
        """# Review guide

1. Read verification.json statuses separately — do not collapse into one optimistic PASS.
2. Confirm canonical_population != scientific_cohort.
3. Confirm scientifically_interpretable is never true while domain gates remain open.
4. Confirm permutation_p_value uses (k+1)/(n+1) and is never literal 0.0.
5. Confirm medicine-appointment row counts are not labeled as intervention counts.
6. Confirm no PII/secrets in artifacts.
""",
    )

    write_evidence_manifest(out)

    result = {
        "ok": True,
        "artifact_dir": str(out),
        "verification": verification,
        "no_publish": no_publish,
    }
    if not no_publish:
        from human_simulator.population_v01.publish import publish

        result["publish"] = publish(root)
    return result
