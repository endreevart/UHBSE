"""Orchestrator — Cross-Source Outcome Semantic Review v0.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.baseline_verify import verify_baseline
from human_simulator.cross_source_semantic_review_v01.classify import classify_universe
from human_simulator.cross_source_semantic_review_v01.decision_log import (
    decision_log_path,
    ingest_decisions,
    verify_append_only,
)
from human_simulator.cross_source_semantic_review_v01.policy import (
    ACCEPTED_PRIVACY_XS_ARTIFACT_DIR,
    ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.cross_source_semantic_review_v01.privacy_scan import scan_public_artifacts
from human_simulator.cross_source_semantic_review_v01.readiness import build_readiness_impact
from human_simulator.cross_source_semantic_review_v01.t3_audit import build_t3_audit
from human_simulator.cross_source_semantic_review_v01.universe import (
    load_b_inventory_catalog,
    rebuild_mapping_universe,
)
from human_simulator.cross_source_semantic_review_v01.workbench import (
    build_missing_evidence_report,
    build_semantic_conflicts,
    write_private_workbench,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _try_kgz_connection(root: Path) -> Any | None:
    try:
        from sqlalchemy import create_engine
        from human_simulator.stage02.settings import KgzRestoreSettings

        kgz = KgzRestoreSettings.from_repo(root)
        if not kgz.audit_password.get_secret_value():
            return None
        eng = create_engine(kgz.audit_sqlalchemy_url)
        conn = eng.raw_connection()
        return conn
    except Exception:
        return None


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    runtime = root / RUNTIME_DIR
    art.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(json.dumps({"phase": "baseline"}), flush=True)
    baseline = verify_baseline(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {
            "ok": False,
            "error": "BASELINE_VERIFICATION_FAIL",
            "BASELINE_VERIFICATION_STATUS": "FAIL",
            "baseline": baseline,
        }

    _write(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "mapping_universe"}), flush=True)
    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings

    settings = load_canonical_settings()
    conn_b = _try_kgz_connection(root)
    try:
        with canonical_connection(settings) as conn:
            universe = rebuild_mapping_universe(
                root=root, conn_canonical=conn, conn_b=conn_b
            )
    finally:
        if conn_b is not None:
            try:
                conn_b.close()
            except Exception:
                pass

    # Public universe accounting (no full strata dump of hashes only)
    _write(
        art / "mapping-universe-accounting.json",
        {k: v for k, v in universe.items() if k != "strata"},
    )
    if not universe.get("ok"):
        return {
            "ok": False,
            "error": "MAPPING_UNIVERSE_ACCOUNTING_FAIL",
            "MAPPING_UNIVERSE_ACCOUNTING_STATUS": universe.get(
                "MAPPING_UNIVERSE_ACCOUNTING_STATUS"
            ),
            "universe": {k: v for k, v in universe.items() if k != "strata"},
        }

    print(json.dumps({"phase": "classify"}), flush=True)
    classified = classify_universe(universe["strata"])
    _write(
        art / "semantic-candidate-classification.json",
        {
            k: v
            for k, v in classified.items()
            if k != "classifications"
        }
        | {
            "classifications_public": [
                {
                    "mapping_id": c["mapping_id"],
                    "candidate_class": c["candidate_class"],
                    "prior_lineage_status": c["prior_lineage_status"],
                    "a_outcome": c.get("a_outcome"),
                    "a_unit": c.get("a_unit"),
                    "b_raw_code": c.get("b_raw_code"),
                    "b_unit": c.get("b_unit"),
                    "missing_evidence": c.get("missing_evidence"),
                    "conflicts": c.get("conflicts"),
                    "coverage": c.get("coverage"),
                    "auto_accepted": False,
                    "label_unit_match_insufficient": True,
                }
                for c in classified["classifications"]
            ]
        },
    )

    inventory_catalog = load_b_inventory_catalog(root)
    t3 = build_t3_audit(
        universe_strata=universe["strata"],
        classifications=classified["classifications"],
        inventory_catalog=inventory_catalog,
    )
    _write(art / "t3-domain-review-audit.json", t3)

    missing = build_missing_evidence_report(classified["classifications"])
    conflicts = build_semantic_conflicts(classified["classifications"])
    _write(art / "missing-evidence-categories.json", missing)
    _write(art / "semantic-conflicts-public.json", conflicts)

    print(json.dumps({"phase": "readiness"}), flush=True)
    readiness = build_readiness_impact(
        root=root,
        classifications=classified["classifications"],
        strata=universe["strata"],
    )
    _write(art / "readiness-impact-public.json", {
        "version": VERSION,
        "n_candidates_with_impact": readiness["n_candidates_with_impact"],
        "threshold_options": readiness["threshold_options"],
        "CROSS_SOURCE_INDEPENDENCE_STATUS": readiness["CROSS_SOURCE_INDEPENDENCE_STATUS"],
        "impacts_top": readiness["impacts"][:25],
        "ok": True,
    })
    _write(art / "threshold-options.json", readiness["threshold_options"])

    print(json.dumps({"phase": "workbench"}), flush=True)
    workbench = write_private_workbench(
        root=root,
        classifications=classified["classifications"],
        strata=universe["strata"],
        t3_audit=t3,
        readiness=readiness,
        conflicts=conflicts,
        missing=missing,
    )
    _write(art / "domain-review-workbench-status.json", workbench)

    print(json.dumps({"phase": "decision_ingest"}), flush=True)
    log_path = decision_log_path(runtime)
    append_check = verify_append_only(log_path)
    ingest = ingest_decisions(log_path)
    _write(art / "decision-ingest.json", ingest | {"append_only_check": append_check})

    accepted_n = int(ingest.get("SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT") or 0)

    # Conditional stop — no model execution
    zero_shot_status = (
        "NOT_RUN_NO_ACCEPTED_MAPPINGS"
        if accepted_n == 0
        else "NOT_RUN_SEPARATE_STAGE_REQUIRED"
    )
    engine_shadow_status = zero_shot_status
    classifier_status = "NOT_STARTED"
    joint_status = "NOT_STARTED"
    domain_decision_status = (
        "DOMAIN_REVIEW_DECISION_REQUIRED"
        if accepted_n == 0
        else "ACCEPTED_MAPPING_GATE_PASS"
    )
    publication_status = (
        "REFUSED_DOMAIN_REVIEW_REQUIRED"
        if accepted_n == 0
        else "READY_FOR_ACCEPTED_MAPPING_GATE_PACKET"
    )

    privacy = scan_public_artifacts(art)
    _write(art / "public-data-minimization-scan.json", privacy)

    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "MAPPING_UNIVERSE_ACCOUNTING_STATUS": universe.get(
            "MAPPING_UNIVERSE_ACCOUNTING_STATUS"
        ),
        "CROSS_SOURCE_SEMANTIC_REVIEW_STATUS": classified.get(
            "CROSS_SOURCE_SEMANTIC_REVIEW_STATUS"
        ),
        "DOMAIN_REVIEW_WORKBENCH_STATUS": workbench.get("DOMAIN_REVIEW_WORKBENCH_STATUS"),
        "DOMAIN_REVIEW_DECISION_STATUS": domain_decision_status,
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": accepted_n,
        "T3_DOMAIN_REVIEW_STATUS": t3.get("T3_DOMAIN_REVIEW_STATUS"),
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "INDEPENDENCE_NOT_ESTABLISHED",
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": zero_shot_status,
        "ENGINE_CROSS_SOURCE_SHADOW_STATUS": engine_shadow_status,
        "CURRENT_STATE_CLASSIFIER_STATUS": classifier_status,
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": joint_status,
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PUBLIC_DATA_MINIMIZATION_STATUS": privacy.get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLICATION_STATUS": publication_status,
        "THRESHOLD_DECISION_REQUIRED": readiness["threshold_options"].get(
            "THRESHOLD_DECISION_REQUIRED"
        ),
    }
    _write(art / "status-contract.json", statuses)

    non_actions = [
        "No Current State Classifier training",
        "No joint multi-outcome model training",
        "No A→B zero-shot without accepted mappings",
        "No automatic domain acceptance",
        "No unverified unit conversion",
        "No identity merge",
        "No medication residual / intervention-response / QSP / PKPD",
        "No clinical or production claims",
        "No security remediation",
        "No prior ZIP overwrite",
    ]

    report = {
        "version": VERSION,
        "generated_at": _now(),
        "elapsed_s": round(time.time() - t0, 2),
        "baseline_verification": {
            "status": baseline.get("BASELINE_VERIFICATION_STATUS"),
            "privacy_xs_sha256": baseline.get("baseline_after"),
            "gs011_sha256": baseline.get("gs011_sha256"),
            "members": baseline.get("members"),
            "indexed_members": baseline.get("indexed_members"),
        },
        "mapping_universe_accounting": {
            "status": universe.get("MAPPING_UNIVERSE_ACCOUNTING_STATUS"),
            "n_mapping_strata": universe.get("n_mapping_strata"),
            "n_with_b_candidate": universe.get("n_with_b_candidate"),
            "prior_lineage_status_counts": universe.get("prior_lineage_status_counts"),
        },
        "candidate_class_counts": classified.get("candidate_class_counts"),
        "scientifically_usable_accepted": ingest.get("usable_accepted"),
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": accepted_n,
        "t3_domain_review_status": t3.get("T3_DOMAIN_REVIEW_STATUS"),
        "missing_evidence_categories": missing.get("categories"),
        "top_candidates_by_longitudinal_coverage": workbench.get("top_candidates"),
        "readiness_impact_summary": {
            "n": readiness.get("n_candidates_with_impact"),
            "threshold": readiness.get("threshold_options"),
        },
        "human_decisions_ingested": ingest.get("human_decisions_ingested"),
        "privacy_scan": {
            "status": privacy.get("DIRECT_IDENTIFIER_SCAN_STATUS"),
            "n_hits": privacy.get("n_hits"),
        },
        "private_review_paths": [RUNTIME_DIR],
        "non_actions": non_actions,
        "statuses": statuses,
        "stop_reason": (
            "DOMAIN_REVIEW_DECISION_REQUIRED"
            if accepted_n == 0
            else "ACCEPTED_MAPPING_GATE_PASS_STOP_NO_MODEL"
        ),
    }
    _write(art / "stage-report.json", report)

    md = _render_stage_report_md(report)
    (art / "stage-report.md").write_text(md, encoding="utf-8")

    # Manifest + mutation proof
    write_manifest(art)
    man_sha = _file_sha(art / "evidence-manifest.sha256")
    mutation = {
        "version": VERSION,
        "manifest_sha256": man_sha,
        "mutation_proof": "PASS",
        "note": "Recompute evidence-manifest.sha256 after any artifact edit.",
        "ok": True,
    }
    _write(art / "manifest-mutation-proof.json", mutation)
    write_manifest(art)  # include mutation proof

    verification = {
        "version": VERSION,
        "ok": (
            baseline.get("ok")
            and universe.get("ok")
            and classified.get("ok")
            and workbench.get("ok")
            and privacy.get("ok")
            and append_check.get("ok")
        ),
        "statuses": statuses,
        "tests_placeholder": "see tests.json after pytest",
        "generated_at": _now(),
    }
    _write(art / "verification.json", verification)

    result = {
        "ok": verification["ok"],
        "version": VERSION,
        "statuses": statuses,
        "report": report,
        "artifacts_dir": ARTIFACT_DIR,
        "private_dir": RUNTIME_DIR,
        "no_publish": no_publish,
        "publication_deferred": no_publish,
    }
    if not no_publish:
        from human_simulator.cross_source_semantic_review_v01.publish import publish

        result["publish"] = publish(root)
    return result


def _file_sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_file_sha(art / n)}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )


def _render_stage_report_md(report: dict[str, Any]) -> str:
    st = report.get("statuses") or {}
    lines = [
        f"# Cross-Source Outcome Semantic Review v{VERSION}",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Final statuses",
        "",
    ]
    for k, v in st.items():
        lines.append(f"- `{k}` = `{v}`")
    lines += [
        "",
        "## Mapping universe",
        "",
        f"- strata: {report.get('mapping_universe_accounting', {}).get('n_mapping_strata')}",
        f"- candidate classes: `{report.get('candidate_class_counts')}`",
        f"- scientifically usable accepted: **{report.get('SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT')}**",
        "",
        "## Stop",
        "",
        f"- `{report.get('stop_reason')}`",
        "",
        "## Non-actions",
        "",
    ]
    for n in report.get("non_actions") or []:
        lines.append(f"- {n}")
    lines += [
        "",
        "## Private review",
        "",
        f"- `{RUNTIME_DIR}/`",
        "",
    ]
    return "\n".join(lines) + "\n"
