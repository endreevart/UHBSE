"""Orchestrate assess-source-relationship for Stage 02."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from human_simulator.stage01.settings import MgAuditSettings
from human_simulator.stage02.artifact_safety import validate_relationship_artifacts
from human_simulator.stage02.identity_linkage import assess_identity_linkage, render_identity_linkage_markdown
from human_simulator.stage02.linkage_settings import LinkageSettings
from human_simulator.stage02.relationship_gates import AssessSourceRelationshipError, run_relationship_gates
from human_simulator.stage02.relationship_manifest import (
    RELATIONSHIP_MANIFEST_ARTIFACTS,
    verify_relationship_manifest,
    write_relationship_manifest,
)
from human_simulator.stage02.settings import KgzRestoreSettings
from human_simulator.stage02.source_relationship import (
    assess_structural_relationship,
    finalize_relationship_verdict,
    render_source_relationship_markdown,
)
from human_simulator.stage02.subject_root_analysis import (
    analyze_subject_roots,
    render_subject_root_markdown,
)

FINGERPRINT_RELATIONS: tuple[tuple[str, str], ...] = (
    ("magerya_api", "account_patient"),
    ("public", "consultations"),
    ("public", "users"),
    ("public", "persons"),
)


def assess_source_relationship(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    stage01_dir = root / "artifacts" / "stage-01"
    stage02_dir = root / "artifacts" / "stage-02"
    stage02_dir.mkdir(parents=True, exist_ok=True)

    gate_context = run_relationship_gates(root)
    query_log: list[dict[str, str]] = []

    mg = MgAuditSettings.from_repo(root)
    kgz = KgzRestoreSettings.from_repo(root)
    linkage = LinkageSettings.from_repo(root)
    hmac_key = linkage.require_key()

    mg_engine = create_engine(mg.audit_sqlalchemy_url)
    kgz_engine = create_engine(kgz.audit_sqlalchemy_url)

    try:
        fingerprint_before = _capture_fingerprints(mg_engine, kgz_engine, query_log)

        subject_root = analyze_subject_roots(
            mg_engine,
            kgz_engine,
            profile_a_path=stage01_dir / "schema-profile.json",
            profile_b_path=stage02_dir / "schema-profile-kgz.json",
        )
        query_log.append({"operation": "subject_root_analysis", "status": "completed"})

        structural = assess_structural_relationship(root)

        source_b_verdict = subject_root["source_b"]["overall_verdict"]
        resolution = subject_root["source_b"].get("patient_id_resolution")
        identity = assess_identity_linkage(
            mg_engine,
            kgz_engine,
            hmac_key=hmac_key,
            source_b_subject_verdict=source_b_verdict,
            source_b_resolution=resolution,
        )
        query_log.append({"operation": "identity_linkage_assessment", "status": "completed"})

        identity_verdict_code = identity.get("identity_verdict", {}).get("verdict", "NOT_ASSESSED")
        structural["source_relationship_verdict"] = finalize_relationship_verdict(
            structural,
            identity_verdict=identity_verdict_code,
            subject_root_a=subject_root["source_a"]["verdict"],
            subject_root_b=source_b_verdict,
        )

        fingerprint_after = _capture_fingerprints(mg_engine, kgz_engine, query_log)
        db_unchanged = fingerprint_before == fingerprint_after

        _write_artifacts(
            stage02_dir,
            subject_root=subject_root,
            structural=structural,
            identity=identity,
            query_log=query_log,
        )
        manifest_hashes = write_relationship_manifest(stage02_dir)
        manifest_ok, manifest_detail = verify_relationship_manifest(stage02_dir)
        safety_findings = validate_relationship_artifacts(stage02_dir)

        verification = _build_verification_report(
            gate_context.gates,
            manifest_ok=manifest_ok,
            manifest_detail=manifest_detail,
            safety_findings=safety_findings,
            db_unchanged=db_unchanged,
            subject_root=subject_root,
            identity=identity,
            structural=structural,
        )
        (stage02_dir / "relationship-verification-report.json").write_text(
            json.dumps(verification, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        write_relationship_manifest(stage02_dir)

        return {
            "status": verification["status"],
            "subject_root_a_verdict": subject_root["source_a"]["verdict"],
            "subject_root_b_verdict": source_b_verdict,
            "identity_verdict": identity_verdict_code,
            "source_relationship_verdict": structural["source_relationship_verdict"]["verdict"],
            "manifest": manifest_hashes,
            "artifacts": [str(stage02_dir / name) for name in RELATIONSHIP_MANIFEST_ARTIFACTS],
        }
    finally:
        mg_engine.dispose()
        kgz_engine.dispose()


def _write_artifacts(
    stage02_dir: Path,
    *,
    subject_root: dict[str, Any],
    structural: dict[str, Any],
    identity: dict[str, Any],
    query_log: list[dict[str, str]],
) -> None:
    writes: tuple[tuple[str, dict[str, Any] | list[Any], str | None], ...] = (
        ("subject-root-analysis.json", subject_root, None),
        ("subject-root-analysis.md", {}, "subject_root_md"),
        ("source-relationship-assessment.json", structural, None),
        ("source-relationship-assessment.md", {}, "structural_md"),
        ("identity-linkage-assessment.json", identity, None),
        ("identity-linkage-assessment.md", {}, "identity_md"),
        ("relationship-query-log.json", {"operations": query_log}, None),
    )
    for filename, payload, kind in writes:
        path = stage02_dir / filename
        if kind == "subject_root_md":
            path.write_text(render_subject_root_markdown(subject_root), encoding="utf-8")
        elif kind == "structural_md":
            path.write_text(render_source_relationship_markdown(structural), encoding="utf-8")
        elif kind == "identity_md":
            path.write_text(render_identity_linkage_markdown(identity), encoding="utf-8")
        else:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _capture_fingerprints(
    mg_engine: Engine,
    kgz_engine: Engine,
    query_log: list[dict[str, str]],
) -> dict[str, int]:
    fingerprints: dict[str, int] = {}
    for schema, relation in FINGERPRINT_RELATIONS:
        engine = mg_engine if schema == "magerya_api" else kgz_engine
        key = f"{schema}.{relation}"
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{relation}")).scalar_one()
        fingerprints[key] = int(count)
        query_log.append({"operation": "fingerprint_count", "relation": key, "status": "read_only"})
    return fingerprints


def _build_verification_report(
    gates: list[Any],
    *,
    manifest_ok: bool,
    manifest_detail: str,
    safety_findings: list[dict[str, str]],
    db_unchanged: bool,
    subject_root: dict[str, Any],
    identity: dict[str, Any],
    structural: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, str]] = [
        {"name": gate.name, "status": gate.status, "detail": gate.detail} for gate in gates
    ]
    checks.append(
        {
            "name": "relationship_manifest",
            "status": "PASS" if manifest_ok else "FAIL",
            "detail": manifest_detail,
        }
    )
    checks.append(
        {
            "name": "raw_databases_unchanged",
            "status": "PASS" if db_unchanged else "FAIL",
            "detail": "row-count fingerprints identical before/after assessment",
        }
    )
    checks.append(
        {
            "name": "artifact_safety",
            "status": "PASS" if not safety_findings else "FAIL",
            "detail": "no PII/HMAC leaks" if not safety_findings else str(safety_findings[:3]),
        }
    )
    identity_verdict = identity.get("identity_verdict", {}).get("verdict", "NOT_ASSESSED")
    checks.append(
        {
            "name": "no_linkage_proven",
            "status": "PASS" if identity_verdict != "LINKAGE_PROVEN" else "FAIL",
            "detail": f"identity_verdict={identity_verdict}",
        }
    )
    checks.append(
        {
            "name": "subject_root_verdicts_present",
            "status": "PASS",
            "detail": (
                f"source_a={subject_root['source_a']['verdict']}, "
                f"source_b={subject_root['source_b']['overall_verdict']}"
            ),
        }
    )
    checks.append(
        {
            "name": "source_relationship_verdict_present",
            "status": "PASS",
            "detail": structural["source_relationship_verdict"]["verdict"],
        }
    )

    checks.extend(_interpretation_checks(identity, structural))

    failed = [check for check in checks if check["status"] != "PASS"]
    population_estimate = identity.get("overlap_aggregates", {}).get("population_overlap_estimate", {})
    return {
        "verified_at": datetime.now(tz=UTC).isoformat(),
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "summary": {
            "subject_root_a_verdict": subject_root["source_a"]["verdict"],
            "subject_root_b_verdict": subject_root["source_b"]["overall_verdict"],
            "identity_verdict": identity_verdict,
            "source_relationship_verdict": structural["source_relationship_verdict"]["verdict"],
            "population_overlap_estimate_status": population_estimate.get("status"),
        },
        "unresolved_questions": structural["source_relationship_verdict"].get("unresolved_questions", []),
    }


def _interpretation_checks(identity: dict[str, Any], structural: dict[str, Any]) -> list[dict[str, str]]:
    overlap = identity.get("overlap_aggregates", {})
    population = overlap.get("population_overlap_estimate", {})
    supporting = structural.get("source_relationship_verdict", {}).get("supporting_evidence", [])
    supporting_text = " ".join(supporting)

    checks = [
        {
            "name": "population_overlap_not_extrapolated",
            "status": "PASS"
            if population.get("status") == "NOT_ESTIMABLE"
            and "estimated_overlap_percentage" not in overlap
            else "FAIL",
            "detail": population.get("reason", "population_overlap_estimate missing"),
        },
        {
            "name": "infrastructure_excluded_from_application_similarity",
            "status": "PASS"
            if "shared_relation_name_count" not in structural.get("structural_similarity", {})
            else "FAIL",
            "detail": "application vs infrastructure relation counts are separated",
        },
        {
            "name": "identifier_matches_not_labeled_subject_matches",
            "status": "PASS"
            if "matched_unique_phone_identifiers" in overlap
            and "matches_by_phone" not in overlap
            else "FAIL",
            "detail": "overlap uses identifier-level naming",
        },
        {
            "name": "subjects_without_any_strong_identifier_per_source",
            "status": "PASS"
            if all(
                key in overlap
                for key in (
                    "source_a_subjects_without_any_strong_identifier",
                    "source_b_subjects_without_any_strong_identifier",
                )
            )
            and "unevaluable_due_to_missing_identifiers" not in overlap
            else "FAIL",
            "detail": "missing strong identifiers reported separately per source",
        },
        {
            "name": "conflict_definition_present",
            "status": "PASS" if identity.get("conflict_definition") else "FAIL",
            "detail": "conflict_definition block present in identity assessment",
        },
        {
            "name": "supporting_evidence_no_population_extrapolation",
            "status": "PASS"
            if "estimated" not in supporting_text.lower()
            and "%" not in supporting_text
            and "39 shared relation names" not in supporting_text
            else "FAIL",
            "detail": "supporting evidence avoids population percentage extrapolation",
        },
        {
            "name": "hmac_key_metadata",
            "status": "PASS"
            if identity.get("hmac_key_present_in_runtime") is True
            and identity.get("hmac_key_persisted_in_artifacts") is False
            and identity.get("hmac_key_source") == "local_env"
            and "hmac_key_stored" not in identity
            else "FAIL",
            "detail": "HMAC key metadata uses runtime-only fields",
        },
    ]
    return checks


__all__ = ["AssessSourceRelationshipError", "assess_source_relationship"]
