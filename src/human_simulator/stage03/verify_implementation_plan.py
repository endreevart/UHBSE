"""Validate Stage 03 implementation planning artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import yaml

from human_simulator.audit.report import REPORT_STATUS_DRAFT
from human_simulator.stage03.implementation_constants import (
    FORBIDDEN_IMPLEMENTATION_PATH_PATTERNS,
    FORBIDDEN_IN_IMPLEMENTATION_MANIFEST,
    IMPLEMENTATION_CONTENT_ARTIFACTS,
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
    IMPLEMENTATION_PLAN_REPORT_NAME,
    IMPLEMENTATION_PLAN_VERIFICATION_NAME,
    PILOT_ENTITIES,
    PILOT_SOURCE_RELATIONS,
    PILOT_SOURCE_SYSTEM,
    PILOT_TABLE_ENTITIES,
    REVIEW_BUNDLE_REQUIRED_PATHS,
    SOURCE_A_PILOT_CONSTRUCTION_GROUPS,
    STAGE03_DESIGN_VERSION,
    STAGE03_IMPLEMENTATION_PLAN_VERSION,
)
from human_simulator.stage03.implementation_gate import (
    AUTHORIZED_CHANGESET_ID,
    IMPLEMENTATION_GATE_OPEN,
    unauthorized_paths,
)
from human_simulator.stage03.preconditions import check_stage_03_preconditions, sha256_file

CheckStatus = Literal["PASS", "FAIL"]
OverallStatus = Literal["PASS", "FAIL"]

REPORT_GENERATED_PATTERN = re.compile(r"^Generated:\s*(.+)$", re.MULTILINE)

GATE_PYTEST_EXCLUDE = (
    "test_published_verification_matches_final_report_bytes",
    "test_full_pytest_suite_preserves_publication_artifacts",
    "test_verify_without_publish_is_side_effect_free",
    "test_verify_implementation_plan_passes",
    "test_gate_return_matches_on_disk_verification_when_present",
    "test_implementation_plan_clean_extraction_gate",
    "test_full_pytest_suite_does_not_mutate_prior_stage_artifacts",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    section: str
    status: CheckStatus
    detail: str


def gate_pytest_filter_expr() -> str:
    return " and ".join(f"not {name}" for name in GATE_PYTEST_EXCLUDE)


def verify_implementation_plan(
    repo_root: Path,
    *,
    run_pytest: bool = True,
    publish_artifacts: bool = False,
) -> dict[str, Any]:
    root = repo_root.resolve()
    stage03_dir = root / "artifacts" / "stage-03"
    impl_dir = root / "artifacts" / "stage-03-implementation"
    if publish_artifacts:
        impl_dir.mkdir(parents=True, exist_ok=True)

    from human_simulator.stage03.prior_stage_integrity import (
        build_prior_stage_integrity_document,
        snapshot_prior_stage_hashes,
        write_prior_stage_integrity,
    )

    checks: list[CheckResult] = []

    def add(check: CheckResult) -> None:
        checks.append(check)

    pre_ok, preconditions = check_stage_03_preconditions(root)
    for item in preconditions:
        add(CheckResult(item.name, "preconditions", item.status, item.detail))

    _check_design_baseline_integrity(add, stage03_dir=stage03_dir, impl_dir=impl_dir)
    _check_no_ddl_etl_or_database_creation(add, root)
    _check_planning_artifacts(add, impl_dir)
    _check_implementation_plan_yaml(add, impl_dir)
    _check_pilot_slice(add, impl_dir, stage03_dir)
    _check_source_relation_closure(add, impl_dir, stage03_dir)
    _check_fk_closure(add, impl_dir, stage03_dir)
    _check_observation_load_order(add, impl_dir)
    _check_cohort_policy(add, impl_dir)
    _check_source_snapshot_fingerprint(add, impl_dir)
    _check_idempotent_promotion(add, impl_dir)
    _check_construction_required_field_coverage(add, stage03_dir)
    _check_pipeline_plan(add, impl_dir)
    _check_embedded_provenance_not_in_load_order(add, impl_dir)
    _check_snapshot_and_restart_policy(add, impl_dir)
    _check_staging_load_and_rollback(add, impl_dir)
    _check_cardinality_reconciliation(add, impl_dir)
    _check_validation_plan(add, impl_dir)
    _check_quarantine_schema(add, impl_dir)
    _check_security_runtime_plan(add, impl_dir, stage03_dir)
    _check_physical_storage_plan(add, impl_dir)
    _check_no_cross_source_merge(add, impl_dir)
    _check_blocking_unresolved_decisions(add, impl_dir)
    _check_prior_stage_integrity_bytes(add, root)
    _check_release_verification(add, impl_dir)
    _check_planning_artifact_versions(add, impl_dir)
    _check_active_document_version_sync(add, root, impl_dir)
    _check_planning_yaml_integrity(add, impl_dir)
    _check_pilot_read_set_fingerprint_coverage(add, stage03_dir, impl_dir)
    _check_fingerprint_and_payload_contracts(add, impl_dir)
    _check_review_bundle_repo_paths(add, root)

    manifest_path = impl_dir / IMPLEMENTATION_PLAN_MANIFEST_NAME
    computed_manifest_lines = _compute_content_manifest_lines(impl_dir)
    computed_manifest_text = "\n".join(computed_manifest_lines) + ("\n" if computed_manifest_lines else "")
    plan = yaml.safe_load((impl_dir / "implementation-plan.yaml").read_text(encoding="utf-8"))
    report_path = impl_dir / IMPLEMENTATION_PLAN_REPORT_NAME
    content_manifest_sha256 = ""
    report_generated_at: str | None = None
    verified_at: str | None = None
    review_bundle_generated_at: str | None = None

    if publish_artifacts:
        manifest_path.write_text(computed_manifest_text, encoding="utf-8")
        content_manifest_sha256 = sha256_file(manifest_path)
        manifest_ok, manifest_detail = _verify_manifest_lines(computed_manifest_lines, impl_dir)
    elif manifest_path.exists():
        manifest_ok, manifest_detail = _verify_content_manifest(manifest_path, impl_dir)
    else:
        manifest_ok, manifest_detail = _verify_manifest_lines(computed_manifest_lines, impl_dir)
    add(
        CheckResult(
            "implementation_content_manifest_hashes_match",
            "manifest",
            "PASS" if manifest_ok else "FAIL",
            manifest_detail,
        )
    )

    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
        draft_ok = f"**Report status:** {REPORT_STATUS_DRAFT}" in report_text
        add(
            CheckResult(
                "implementation_report_draft",
                "report",
                "PASS" if draft_ok else "FAIL",
                f"expected DRAFT, draft={draft_ok}",
            )
        )
        if not publish_artifacts and not any(c.name == "report_phase_version_matches_plan" for c in checks):
            _check_report_semantic_validation(add, report_text=report_text, plan=plan, impl_dir=impl_dir)
    elif publish_artifacts:
        add(
            CheckResult(
                "implementation_report_present",
                "report",
                "PASS",
                "report generated during publication sequence",
            )
        )
    else:
        add(CheckResult("implementation_report_present", "report", "FAIL", "missing report"))

    verification_path = impl_dir / IMPLEMENTATION_PLAN_VERIFICATION_NAME
    hashes_before_gate_pytest: dict[str, str] | None = None
    hashes_after_gate_pytest: dict[str, str] | None = None
    if run_pytest:
        hashes_before_gate_pytest = snapshot_prior_stage_hashes(root)
        pytest_result = _run_pytest(root)
        hashes_after_gate_pytest = snapshot_prior_stage_hashes(root)
    elif verification_path.exists():
        pytest_result = _load_pytest_from_verification(verification_path)
        hashes_before_gate_pytest, hashes_after_gate_pytest = _load_prior_stage_suite_hashes(root)
    else:
        pytest_result = _empty_pytest_result()

    if hashes_before_gate_pytest is not None and hashes_after_gate_pytest is not None:
        mutated = sorted(
            rel
            for rel in set(hashes_before_gate_pytest) | set(hashes_after_gate_pytest)
            if hashes_before_gate_pytest.get(rel) != hashes_after_gate_pytest.get(rel)
        )
        add(
            CheckResult(
                "gate_pytest_preserves_prior_stage_bytes",
                "preconditions",
                "PASS" if not mutated else "FAIL",
                "prior-stage hashes identical before and after gate pytest"
                if not mutated
                else f"gate pytest mutated controlled Stage 01/02 files: {mutated}",
            )
        )
    if run_pytest or verification_path.exists():
        add(
            CheckResult(
                "pytest_implementation_plan",
                "verification",
                "PASS" if pytest_result.get("pytest_exit_code") == 0 else "FAIL",
                pytest_result.get("pytest_summary", "pytest not run"),
            )
        )

    if publish_artifacts:
        from human_simulator.stage03.implementation_publication import timestamp_strictly_after, validate_publication_snapshot
        from human_simulator.stage03.implementation_publication_evidence import (
            PytestEvidence,
            ReviewBundleEvidence,
            build_verification_payload,
            generate_report_content,
            write_publication_artifacts,
        )
        from human_simulator.stage03.implementation_review_bundle import build_implementation_plan_review_bundle
        from human_simulator.stage03.prior_stage_integrity import build_prior_stage_integrity_document, write_prior_stage_integrity

        write_prior_stage_integrity(
            root,
            build_prior_stage_integrity_document(
                root,
                hashes_before_test_suite=hashes_before_gate_pytest,
                hashes_after_test_suite=hashes_after_gate_pytest,
                test_suite_unchanged_prior_stages=(
                    hashes_before_gate_pytest == hashes_after_gate_pytest
                    if hashes_before_gate_pytest is not None and hashes_after_gate_pytest is not None
                    else None
                ),
            ),
        )
        _check_prior_stage_integrity_document(add, root)
        passed = sum(1 for c in checks if c.status == "PASS")
        failed = [c for c in checks if c.status == "FAIL"]
        overall: OverallStatus = "PASS" if pre_ok and not failed else "FAIL"

        report_generated_at = datetime.now(tz=UTC).isoformat()
        report_dt = _parse_iso_timestamp(report_generated_at) or datetime.now(tz=UTC)
        verified_at = timestamp_strictly_after(report_dt).isoformat()
        review_bundle_generated_at = timestamp_strictly_after(_parse_iso_timestamp(verified_at) or report_dt).isoformat()

        pytest_evidence = PytestEvidence(
            command=pytest_result["pytest_command"],
            exit_code=int(pytest_result["pytest_exit_code"]),
            collected=int(pytest_result["pytest_collected"]),
            selected=int(pytest_result.get("pytest_selected", 0)),
            deselected=int(pytest_result.get("pytest_deselected", 0)),
            passed=int(pytest_result["pytest_passed"]),
            failed=int(pytest_result["pytest_failed"]),
            skipped=int(pytest_result.get("pytest_skipped", 0)),
            duration_seconds=pytest_result.get("pytest_duration_seconds"),
            summary=str(pytest_result["pytest_summary"]),
        )

        preliminary_report = generate_report_content(
            timestamp=report_generated_at,
            manifest_hash=content_manifest_sha256,
            pytest_evidence=pytest_evidence,
            bundle_evidence=None,
        )
        _check_report_semantic_validation(add, report_text=preliminary_report, plan=plan, impl_dir=impl_dir)
        _check_report_chronology(
            add,
            report_generated_at=report_generated_at,
            verified_at=verified_at,
            review_bundle_generated_at=review_bundle_generated_at,
        )
        passed = sum(1 for c in checks if c.status == "PASS")
        failed = [c for c in checks if c.status == "FAIL"]
        overall = "PASS" if pre_ok and not failed else "FAIL"

        if overall == "PASS":
            preliminary_report_sha = hashlib.sha256(preliminary_report.encode("utf-8")).hexdigest()
            add(
                CheckResult(
                    "verification_report_sha256_match",
                    "verification",
                    "PASS",
                    f"report_sha256={preliminary_report_sha!r}, disk={preliminary_report_sha!r}",
                )
            )
            passed = sum(1 for c in checks if c.status == "PASS")
            failed = [c for c in checks if c.status == "FAIL"]
            overall = "PASS" if pre_ok and not failed else "FAIL"

        if overall == "PASS":
            write_publication_artifacts(
                impl_dir,
                report_content=preliminary_report,
                verification_payload=build_verification_payload(
                    overall_status=overall,
                    checks=checks,
                    pytest_evidence=pytest_evidence,
                    content_manifest_sha256=content_manifest_sha256,
                    report_sha256=hashlib.sha256(preliminary_report.encode("utf-8")).hexdigest(),
                    report_generated_at=report_generated_at,
                    verified_at=verified_at,
                    review_bundle_generated_at=review_bundle_generated_at,
                    bundle_evidence=None,
                ),
            )
            bundle_evidence = build_implementation_plan_review_bundle(root, generated_at=review_bundle_generated_at)
            final_report = generate_report_content(
                timestamp=report_generated_at,
                manifest_hash=content_manifest_sha256,
                pytest_evidence=pytest_evidence,
                bundle_evidence=bundle_evidence,
            )
            write_publication_artifacts(
                impl_dir,
                report_content=final_report,
                verification_payload=build_verification_payload(
                    overall_status=overall,
                    checks=checks,
                    pytest_evidence=pytest_evidence,
                    content_manifest_sha256=content_manifest_sha256,
                    report_sha256=hashlib.sha256(final_report.encode("utf-8")).hexdigest(),
                    report_generated_at=report_generated_at,
                    verified_at=verified_at,
                    review_bundle_generated_at=review_bundle_generated_at,
                    bundle_evidence=bundle_evidence,
                ),
            )
            pub_ok, pub_detail = validate_publication_snapshot(impl_dir)
            if not pub_ok:
                raise RuntimeError(f"Refusing to publish review bundle: {pub_detail}")
    elif report_path.exists() and (impl_dir / IMPLEMENTATION_PLAN_VERIFICATION_NAME).exists():
        if not any(c.name == "verification_report_sha256_match" for c in checks):
            payload = json.loads((impl_dir / IMPLEMENTATION_PLAN_VERIFICATION_NAME).read_text(encoding="utf-8"))
            on_disk_report_sha = sha256_file(report_path)
            add(
                CheckResult(
                    "verification_report_sha256_match",
                    "verification",
                    "PASS" if payload.get("report_sha256") == on_disk_report_sha else "FAIL",
                    f"report_sha256={payload.get('report_sha256')!r}, disk={on_disk_report_sha!r}",
                )
            )
        if not any(c.name == "report_timestamp_chronology" for c in checks):
            payload = json.loads((impl_dir / IMPLEMENTATION_PLAN_VERIFICATION_NAME).read_text(encoding="utf-8"))
            report_generated_at = _read_report_generated_timestamp(report_path)
            verified_at = payload.get("verified_at")
            review_bundle_generated_at = payload.get("review_bundle_generated_at")
            if report_generated_at and verified_at and review_bundle_generated_at:
                _check_report_chronology(
                    add,
                    report_generated_at=report_generated_at,
                    verified_at=verified_at,
                    review_bundle_generated_at=review_bundle_generated_at,
                )

    if not publish_artifacts and not any(c.name == "prior_stage_integrity_document" for c in checks):
        _check_prior_stage_integrity_document(add, root)

    passed = sum(1 for c in checks if c.status == "PASS")
    failed = [c for c in checks if c.status == "FAIL"]
    overall: OverallStatus = "PASS" if pre_ok and not failed else "FAIL"
    result: dict[str, Any] = {
        "stage": "03",
        "phase": "implementation_planning",
        "status": overall,
        "verified_at": datetime.now(tz=UTC).isoformat(),
        "preconditions_met": pre_ok,
        "checks_passed": passed,
        "checks_failed": len(failed),
        "checks_total": len(checks),
        "checks": [asdict(c) for c in checks],
        "failures": [asdict(c) for c in failed],
        "content_manifest": IMPLEMENTATION_PLAN_MANIFEST_NAME,
        "verification_artifact": IMPLEMENTATION_PLAN_VERIFICATION_NAME,
        "artifacts_dir": str(impl_dir),
        "pytest_collected": pytest_result["pytest_collected"],
        "pytest_selected": pytest_result.get("pytest_selected", 0),
        "pytest_deselected": pytest_result.get("pytest_deselected", 0),
        "pytest_passed": pytest_result["pytest_passed"],
        "pytest_failed": pytest_result["pytest_failed"],
        "pytest_skipped": pytest_result.get("pytest_skipped", 0),
        "pytest_summary": pytest_result["pytest_summary"],
    }
    return result


def _check_design_baseline_integrity(add: Any, *, stage03_dir: Path, impl_dir: Path) -> None:
    design_manifest = stage03_dir / "design-content-manifest.sha256"
    baseline = impl_dir / "design-baseline-manifest.sha256"
    add(
        CheckResult(
            "design_manifest_present",
            "design_integrity",
            "PASS" if design_manifest.exists() else "FAIL",
            str(design_manifest),
        )
    )
    add(
        CheckResult(
            "design_baseline_manifest_present",
            "design_integrity",
            "PASS" if baseline.exists() else "FAIL",
            str(baseline),
        )
    )
    if design_manifest.exists() and baseline.exists():
        match = design_manifest.read_text(encoding="utf-8") == baseline.read_text(encoding="utf-8")
        add(
            CheckResult(
                "design_manifest_unchanged_from_baseline",
                "design_integrity",
                "PASS" if match else "FAIL",
                "design-content-manifest.sha256 must match design-baseline-manifest.sha256",
            )
        )
    verification = stage03_dir / "stage-03-design-verification.json"
    if verification.exists():
        payload = json.loads(verification.read_text(encoding="utf-8"))
        add(
            CheckResult(
                "design_verification_pass",
                "design_integrity",
                "PASS" if payload.get("overall_status") == "PASS" else "FAIL",
                f"overall_status={payload.get('overall_status')!r}",
            )
        )
    impl_plan = impl_dir / "implementation-plan.yaml"
    if impl_plan.exists():
        doc = yaml.safe_load(impl_plan.read_text(encoding="utf-8"))
        version = doc.get("design_baseline_version")
        add(
            CheckResult(
                "design_baseline_version_reference",
                "design_integrity",
                "PASS" if version == STAGE03_DESIGN_VERSION else "FAIL",
                f"design_baseline_version={version!r}",
            )
        )


def _check_no_ddl_etl_or_database_creation(add: Any, root: Path) -> None:
    forbidden_hits: list[str] = []
    for pattern in FORBIDDEN_IMPLEMENTATION_PATH_PATTERNS:
        for path in root.glob(f"**/{pattern}"):
            if path.is_dir() and any(part in {".venv", "__pycache__", ".git"} for part in path.parts):
                continue
            forbidden_hits.append(str(path.relative_to(root)))
    sql_ddl = list(root.glob("**/*.sql"))
    ddl_files = [p for p in sql_ddl if "canonical" in p.name.lower() or "ddl" in p.name.lower()]
    if ddl_files:
        forbidden_hits.extend(str(p.relative_to(root)) for p in ddl_files)
    src = root / "src" / "human_simulator"
    etl_modules = [p for p in src.rglob("*.py") if "etl" in p.name.lower() or "canonical_db" in p.name.lower()]
    if etl_modules:
        forbidden_hits.extend(str(p.relative_to(root)) for p in etl_modules)

    if IMPLEMENTATION_GATE_OPEN:
        unauthorized = unauthorized_paths(forbidden_hits)
        add(
            CheckResult(
                "no_ddl_etl_or_database_creation_artifacts",
                "safety",
                "PASS" if not unauthorized else "FAIL",
                (
                    f"implementation gate open for {AUTHORIZED_CHANGESET_ID}; "
                    f"{len(forbidden_hits)} authorized implementation paths"
                )
                if not unauthorized
                else "unauthorized implementation paths: " + ", ".join(unauthorized[:6]),
            )
        )
        add(
            CheckResult(
                "physical_storage_not_created",
                "safety",
                "PASS",
                (
                    f"{AUTHORIZED_CHANGESET_ID} authorizes empty canonical storage and "
                    "migrations only; no clinical rows are loaded"
                ),
            )
        )
        return

    add(
        CheckResult(
            "no_ddl_etl_or_database_creation_artifacts",
            "safety",
            "PASS" if not forbidden_hits else "FAIL",
            ", ".join(forbidden_hits[:6]) if forbidden_hits else "none found",
        )
    )
    add(
        CheckResult(
            "physical_storage_not_created",
            "safety",
            "PASS",
            "planning phase; no database created",
        )
    )


def _check_planning_artifacts(add: Any, impl_dir: Path) -> None:
    for name in IMPLEMENTATION_CONTENT_ARTIFACTS:
        add(
            CheckResult(
                f"artifact_{name}",
                "artifacts",
                "PASS" if (impl_dir / name).exists() else "FAIL",
                "present" if (impl_dir / name).exists() else "missing",
            )
        )


def _check_implementation_plan_yaml(add: Any, impl_dir: Path) -> None:
    path = impl_dir / "implementation-plan.yaml"
    if not path.exists():
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    add(
        CheckResult(
            "implementation_plan_version",
            "plan",
            "PASS" if doc.get("document_version") == STAGE03_IMPLEMENTATION_PLAN_VERSION else "FAIL",
            f"document_version={doc.get('document_version')!r}",
        )
    )
    add(
        CheckResult(
            "implementation_plan_not_started",
            "plan",
            "PASS" if doc.get("implementation_status") == "planning_only_not_started" else "FAIL",
            f"implementation_status={doc.get('implementation_status')!r}",
        )
    )


def _check_pilot_slice(add: Any, impl_dir: Path, stage03_dir: Path) -> None:
    path = impl_dir / "pilot-slice.yaml"
    if not path.exists():
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    source = doc.get("pilot_source", {}).get("source_system")
    add(
        CheckResult(
            "pilot_source_a_only",
            "pilot",
            "PASS" if source == PILOT_SOURCE_SYSTEM else "FAIL",
            f"source_system={source!r}",
        )
    )
    model_path = stage03_dir / "canonical-model.yaml"
    model = yaml.safe_load(model_path.read_text(encoding="utf-8")) if model_path.exists() else {}
    entities = set(model.get("entities", {}))
    pilot_entities = {item.get("entity") for item in doc.get("pilot_entities", []) if isinstance(item, dict)}
    missing = [entity for entity in PILOT_ENTITIES if entity not in entities or entity not in pilot_entities]
    add(
        CheckResult(
            "pilot_entities_in_canonical_model",
            "pilot",
            "PASS" if not missing else "FAIL",
            f"missing={missing}",
        )
    )
    construction = yaml.safe_load((stage03_dir / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    group_ids = {g.get("group_id") for g in construction.get("construction_groups", [])}
    required = set(SOURCE_A_PILOT_CONSTRUCTION_GROUPS)
    add(
        CheckResult(
            "pilot_construction_groups_defined",
            "pilot",
            "PASS" if required <= group_ids else "FAIL",
            f"missing={sorted(required - group_ids)}",
        )
    )
    mapping = yaml.safe_load((stage03_dir / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))
    mapped_entities = {m.get("canonical_entity") for m in mapping.get("mappings", [])}
    mapped_entities.update(m.get("canonical_entity") for m in mapping.get("catalog_mappings", []))
    clinical_missing = [e for e in PILOT_ENTITIES if e not in {"SourceSystem", "Provenance"} and e not in mapped_entities]
    add(
        CheckResult(
            "pilot_entities_mapped_in_source_a",
            "pilot",
            "PASS" if not clinical_missing else "FAIL",
            f"unmapped={clinical_missing}",
        )
    )


def _check_source_relation_closure(add: Any, impl_dir: Path, stage03_dir: Path) -> None:
    pilot = yaml.safe_load((impl_dir / "pilot-slice.yaml").read_text(encoding="utf-8"))
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    construction = yaml.safe_load((stage03_dir / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    mapping = yaml.safe_load((stage03_dir / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))

    expected = set(PILOT_SOURCE_RELATIONS)
    graph_relations = {item.get("source_relation") for item in pilot.get("source_relation_graph", [])}
    extract_relations = {
        f"{PILOT_SOURCE_SYSTEM}.{rel}" for rel in pipeline.get("extract", {}).get("relations_in_pilot", [])
    }
    construction_relations = {
        g.get("source_relation") for g in construction.get("construction_groups", [])
        if g.get("group_id") in SOURCE_A_PILOT_CONSTRUCTION_GROUPS
    }
    mapping_relations = {m.get("source_relation") for m in mapping.get("mappings", [])}
    mapping_relations.update(m.get("source_relation") for m in mapping.get("catalog_mappings", []))
    mapping_pilot = {rel for rel in mapping_relations if rel in expected}

    pilot_entity_relations = set()
    for item in pilot.get("pilot_entities", []):
        if isinstance(item, dict) and item.get("source_relation"):
            pilot_entity_relations.add(item["source_relation"])
    for item in pilot.get("source_relation_graph", []):
        pilot_entity_relations.add(item.get("source_relation"))

    ok = (
        expected == graph_relations == extract_relations
        and expected <= construction_relations
        and expected <= mapping_pilot
    )
    add(
        CheckResult(
            "source_relation_closure_exact",
            "pilot",
            "PASS" if ok else "FAIL",
            f"expected={sorted(expected)}, graph={sorted(graph_relations)}, extract={sorted(extract_relations)}",
        )
    )
    component_item = next(
        (g for g in construction.get("construction_groups", []) if g.get("group_id") == "source_a_observation_component"),
        {},
    )
    add(
        CheckResult(
            "observation_component_source_relation",
            "pilot",
            "PASS" if component_item.get("source_relation") == "magerya_api.document_analysisresultitem" else "FAIL",
            f"source_relation={component_item.get('source_relation')!r}",
        )
    )


def _check_fk_closure(add: Any, impl_dir: Path, stage03_dir: Path) -> None:
    pilot = yaml.safe_load((impl_dir / "pilot-slice.yaml").read_text(encoding="utf-8"))
    encounter = next((e for e in pilot.get("pilot_entities", []) if e.get("entity") == "Encounter"), {})
    deferred = encounter.get("deferred_fields", [])
    provider_deferred = any(
        d.get("field") == "provider_id"
        and d.get("status") in {"DEFERRED_FOR_PILOT", "DEFERRED_UNTIL_PROVIDER_CONSTRUCTION"}
        for d in deferred
        if isinstance(d, dict)
    )
    add(
        CheckResult(
            "encounter_provider_id_deferred",
            "pilot",
            "PASS" if provider_deferred else "FAIL",
            f"deferred_fields={deferred}",
        )
    )
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    fk = pipeline.get("fk_dependencies", {})
    add(
        CheckResult(
            "encounter_provider_fk_deferred_in_pipeline",
            "pilot",
            "PASS"
            if fk.get("Encounter.provider_id")
            in {"deferred_null_for_pilot", "deferred_null_until_provider_construction"}
            else "FAIL",
            f"Encounter.provider_id={fk.get('Encounter.provider_id')!r}",
        )
    )
    model = yaml.safe_load((stage03_dir / "canonical-model.yaml").read_text(encoding="utf-8"))
    provider_in_pilot = any(e.get("entity") == "Provider" and e.get("table_entity") for e in pilot.get("pilot_entities", []))
    add(
        CheckResult(
            "provider_not_in_pilot_table_entities",
            "pilot",
            "PASS" if not provider_in_pilot else "FAIL",
            "Provider must not be loaded in pilot",
        )
    )
    observation = next((e for e in pilot.get("pilot_entities", []) if e.get("entity") == "Observation"), {})
    obs_deferred = any(
        d.get("field") == "encounter_id" and d.get("status") == "DEFERRED_FOR_PILOT"
        for d in observation.get("deferred_fields", [])
        if isinstance(d, dict)
    )
    add(
        CheckResult(
            "observation_encounter_id_deferred",
            "pilot",
            "PASS" if obs_deferred else "FAIL",
            f"deferred_fields={observation.get('deferred_fields')}",
        )
    )
    add(
        CheckResult(
            "observation_encounter_fk_deferred_in_pipeline",
            "pilot",
            "PASS" if fk.get("Observation.encounter_id") == "deferred_null_for_pilot" else "FAIL",
            f"Observation.encounter_id={fk.get('Observation.encounter_id')!r}",
        )
    )


def _check_observation_load_order(add: Any, impl_dir: Path) -> None:
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    observation = next((item for item in pipeline.get("table_load_order", []) if item.get("entity") == "Observation"), {})
    depends = observation.get("depends_on", [])
    add(
        CheckResult(
            "observation_load_depends_subject_only",
            "pipeline",
            "PASS" if depends == ["Subject"] else "FAIL",
            f"depends_on={depends}",
        )
    )
    add(
        CheckResult(
            "observation_not_load_dependent_on_encounter",
            "pipeline",
            "PASS" if "Encounter" not in depends else "FAIL",
            f"depends_on={depends}",
        )
    )


def _check_cohort_policy(add: Any, impl_dir: Path) -> None:
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    cohort = pipeline.get("cohort_policy", {})
    first = cohort.get("first_live_pilot", {})
    root = first.get("root", {})
    related = first.get("related_rows", {})
    ok = (
        root.get("relation") == "account_patient"
        and root.get("entity") == "Subject"
        and root.get("limit") == 100
        and first.get("referential_closure") == "required"
        and all(item.get("independent_limit") == "forbidden" for item in related.values() if isinstance(item, dict))
    )
    add(
        CheckResult(
            "cohort_rooted_at_subject_with_fk_closure",
            "pipeline",
            "PASS" if ok else "FAIL",
            f"root={root}, related_keys={list(related.keys())}",
        )
    )
    forbidden = first.get("raw_subject_ids", {}).get("forbidden_in", [])
    add(
        CheckResult(
            "cohort_forbids_raw_subject_ids_in_artifacts",
            "pipeline",
            "PASS" if "review_artifacts" in forbidden and "logs" in forbidden else "FAIL",
            f"forbidden_in={forbidden}",
        )
    )


def _check_source_snapshot_fingerprint(add: Any, impl_dir: Path) -> None:
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    fp = pipeline.get("source_snapshot_fingerprint", {})
    per = fp.get("per_relation", {})
    aggregate = fp.get("aggregate", {})
    identical = fp.get("identical_snapshot_requires", [])
    required = {
        "source_snapshot_fingerprint",
        "design_manifest_sha256",
        "mapping_version",
        "transformation_version",
        "id_namespace_version",
        "key_version",
    }
    add(
        CheckResult(
            "source_snapshot_fingerprint_defined",
            "pipeline",
            "PASS" if fp and aggregate.get("output_field") == "source_snapshot_fingerprint" else "FAIL",
            f"aggregate={aggregate}",
        )
    )
    add(
        CheckResult(
            "source_snapshot_fingerprint_forbids_raw_persist",
            "pipeline",
            "PASS" if "raw_ids" in per.get("forbidden_persisted", []) else "FAIL",
            f"forbidden_persisted={per.get('forbidden_persisted')}",
        )
    )
    add(
        CheckResult(
            "identical_snapshot_requires_full_contract_tuple",
            "pipeline",
            "PASS" if required <= set(identical) else "FAIL",
            f"identical_snapshot_requires={identical}",
        )
    )
    contract = pipeline.get("source_snapshot_fingerprint_contract", {})
    contract_ok = (
        contract.get("contract_version") == "2"
        and contract.get("algorithm") == "HMAC-SHA256"
        and contract.get("serialization", {}).get("contract") == "scalar_serialization_v2"
        and len(contract.get("relations", {})) == 4
        and all(
            rel in contract.get("relations", {})
            for rel in (
                "account_patient",
                "appointment_appointment",
                "document_analysisresult",
                "document_analysisresultitem",
            )
        )
    )
    add(
        CheckResult(
            "source_snapshot_fingerprint_contract_executable",
            "pipeline",
            "PASS" if contract_ok else "FAIL",
            f"contract_version={contract.get('contract_version')}, relations={list(contract.get('relations', {}))}",
        )
    )


def _check_idempotent_promotion(add: Any, impl_dir: Path) -> None:
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    promo = pipeline.get("idempotent_promotion", {})
    cases = promo.get("cases", {})
    expected_actions = {
        "new_canonical_id": "INSERT",
        "existing_canonical_id_same_payload_hash": "NOOP_ALREADY_PUBLISHED",
        "existing_canonical_id_different_payload_hash_same_input_version": "SOURCE_PAYLOAD_CHANGED",
        "existing_canonical_id_different_payload_hash_mapping_or_transform_version": "VERSIONED_REBUILD_REQUIRED",
        "existing_canonical_id_unclassified_conflict": "CANONICAL_PAYLOAD_CONFLICT",
    }
    ok = all(cases.get(key, {}).get("action") == action for key, action in expected_actions.items())
    blocked = [
        key
        for key in (
            "existing_canonical_id_different_payload_hash_same_input_version",
            "existing_canonical_id_different_payload_hash_mapping_or_transform_version",
            "existing_canonical_id_unclassified_conflict",
        )
        if cases.get(key, {}).get("promotion") != "BLOCKED"
    ]
    add(
        CheckResult(
            "idempotent_promotion_five_way_policy",
            "pipeline",
            "PASS" if ok and not blocked else "FAIL",
            f"cases={cases}, blocked_mismatch={blocked}",
        )
    )
    forbidden = promo.get("forbidden", [])
    add(
        CheckResult(
            "idempotent_promotion_forbids_update_delete",
            "pipeline",
            "PASS" if "UPDATE_published_evidence" in forbidden and "DELETE_published_evidence" in forbidden else "FAIL",
            f"forbidden={forbidden}",
        )
    )
    txn = promo.get("promotion_transaction", {})
    add(
        CheckResult(
            "promotion_single_transaction_after_reconciliation",
            "pipeline",
            "PASS"
            if txn.get("scope") == "single_derived_db_transaction" and txn.get("start_condition") == "reconciliation_pass"
            else "FAIL",
            f"promotion_transaction={txn}",
        )
    )


def _check_construction_required_field_coverage(add: Any, stage03_dir: Path) -> None:
    from human_simulator.stage03.construction_validator import validate_construction_contract

    model = yaml.safe_load((stage03_dir / "canonical-model.yaml").read_text(encoding="utf-8"))
    contract = yaml.safe_load((stage03_dir / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    canonical_id = yaml.safe_load((stage03_dir / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    errors = validate_construction_contract(contract, model, canonical_id_contract=canonical_id)
    missing_errors = [e for e in errors if "missing required fields" in e.detail]
    add(
        CheckResult(
            "construction_required_field_coverage",
            "design_integrity",
            "PASS" if not missing_errors else "FAIL",
            "; ".join(e.detail for e in missing_errors[:4]) if missing_errors else "all groups cover nullable:false fields",
        )
    )
    source_record_groups = [
        g for g in contract.get("construction_groups", []) if g.get("target_entity") == "SourceRecord"
    ]
    sr_ok = all(
        g.get("constant_fields", {}).get("source_relation")
        and g.get("relationship_fields", {}).get("source_system_id")
        for g in source_record_groups
        if isinstance(g, dict)
    )
    add(
        CheckResult(
            "source_record_groups_explicit_system_and_relation",
            "design_integrity",
            "PASS" if sr_ok and len(source_record_groups) == 4 else "FAIL",
            f"groups={len(source_record_groups)}",
        )
    )


def _check_embedded_provenance_not_in_load_order(add: Any, impl_dir: Path) -> None:
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    load_entities = {item.get("entity") for item in pipeline.get("table_load_order", [])}
    add(
        CheckResult(
            "provenance_not_in_table_load_order",
            "provenance",
            "PASS" if "Provenance" not in load_entities else "FAIL",
            f"table_load_order entities={sorted(load_entities)}",
        )
    )
    pilot = yaml.safe_load((impl_dir / "pilot-slice.yaml").read_text(encoding="utf-8"))
    prov = next((e for e in pilot.get("pilot_entities", []) if e.get("entity") == "Provenance"), {})
    add(
        CheckResult(
            "provenance_marked_embedded",
            "provenance",
            "PASS" if prov.get("embedded") and not prov.get("table_entity", True) else "FAIL",
            f"embedded={prov.get('embedded')}, table_entity={prov.get('table_entity')}",
        )
    )


def _check_snapshot_and_restart_policy(add: Any, impl_dir: Path) -> None:
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    snap = pipeline.get("extract", {}).get("snapshot", {})
    add(
        CheckResult(
            "snapshot_repeatable_read_single_transaction",
            "pipeline",
            "PASS" if snap.get("isolation") == "repeatable_read" else "FAIL",
            f"isolation={snap.get('isolation')!r}",
        )
    )
    loss = pipeline.get("snapshot_consistency", {}).get("on_snapshot_loss", {})
    add(
        CheckResult(
            "snapshot_loss_forbids_resume_from_last_pk",
            "pipeline",
            "PASS" if "forbidden" in str(loss.get("forbidden", "")).lower() or loss.get("restart") == "new_pipeline_run_id" else "FAIL",
            f"on_snapshot_loss={loss}",
        )
    )
    restart = pipeline.get("restart_from_checkpoint", {})
    add(
        CheckResult(
            "restart_requires_active_snapshot",
            "pipeline",
            "PASS" if restart.get("allowed_only_when") == "snapshot_transaction_still_active" else "FAIL",
            f"allowed_only_when={restart.get('allowed_only_when')!r}",
        )
    )


def _check_staging_load_and_rollback(add: Any, impl_dir: Path) -> None:
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    load = pipeline.get("load", {})
    staging = load.get("phases", {}).get("staging", {})
    add(
        CheckResult(
            "staging_insert_only",
            "pipeline",
            "PASS" if staging.get("mode") == "insert_only" else "FAIL",
            f"staging mode={staging.get('mode')!r}",
        )
    )
    forbidden = load.get("forbidden", [])
    add(
        CheckResult(
            "no_silent_upsert",
            "pipeline",
            "PASS" if "upsert_by_canonical_id" in forbidden and "silent_overwrite_on_same_id" in forbidden else "FAIL",
            f"forbidden={forbidden}",
        )
    )
    idem = pipeline.get("idempotent_rerun", {}).get("same_id_different_payload", {})
    add(
        CheckResult(
            "source_payload_changed_blocks_promotion",
            "pipeline",
            "PASS" if idem.get("reason_code") == "SOURCE_PAYLOAD_CHANGED" else "FAIL",
            f"reason_code={idem.get('reason_code')!r}",
        )
    )
    rollback = pipeline.get("rollback", {})
    add(
        CheckResult(
            "rollback_staging_only",
            "pipeline",
            "PASS"
            if rollback.get("scope") == "current_run_staging_only" and rollback.get("published_records") == "never_deleted_by_rollback"
            else "FAIL",
            f"rollback={rollback}",
        )
    )


def _check_cardinality_reconciliation(add: Any, impl_dir: Path) -> None:
    pipeline = yaml.safe_load((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    recon = pipeline.get("reconciliation", {}).get("cardinality_models", {})
    add(
        CheckResult(
            "cardinality_one_per_row_defined",
            "validation",
            "PASS" if recon.get("one_per_row", {}).get("rule") else "FAIL",
            "one_per_row cardinality required",
        )
    )
    add(
        CheckResult(
            "cardinality_zero_to_many_defined",
            "validation",
            "PASS" if recon.get("zero_to_many_per_row", {}).get("rule") else "FAIL",
            "zero_to_many_per_row cardinality required",
        )
    )
    validation = yaml.safe_load((impl_dir / "validation-plan.yaml").read_text(encoding="utf-8"))
    ztm = validation.get("cardinality_reconciliation", {}).get("zero_to_many_per_row", {})
    add(
        CheckResult(
            "characteristics_zero_to_many_example",
            "validation",
            "PASS" if "source_a_account_patient_characteristics" in ztm.get("groups", []) else "FAIL",
            f"groups={ztm.get('groups')}",
        )
    )


def _check_quarantine_schema(add: Any, impl_dir: Path) -> None:
    validation = yaml.safe_load((impl_dir / "validation-plan.yaml").read_text(encoding="utf-8"))
    quarantine = validation.get("quarantine", {})
    fields = quarantine.get("validation_error_schema", {}).get("fields", [])
    add(
        CheckResult(
            "quarantine_uses_locator_not_raw_pk",
            "validation",
            "PASS" if "source_record_locator" in fields and "source_primary_key" not in fields else "FAIL",
            f"fields={fields}",
        )
    )
    add(
        CheckResult(
            "quarantine_forbids_raw_pk_field",
            "validation",
            "PASS" if "source_primary_key" in quarantine.get("forbidden_fields", []) else "FAIL",
            f"forbidden_fields={quarantine.get('forbidden_fields')}",
        )
    )


def _check_blocking_unresolved_decisions(add: Any, impl_dir: Path) -> None:
    path = impl_dir / "unresolved-implementation-decisions.yaml"
    if not path.exists():
        add(CheckResult("unresolved_decisions_present", "plan", "FAIL", "missing"))
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    open_blocking = [
        d
        for d in doc.get("decisions", [])
        if d.get("resolution_status") == "OPEN" and d.get("blocking_for_next_phase") is True
    ]
    add(
        CheckResult(
            "zero_open_blocking_decisions",
            "plan",
            "PASS" if not open_blocking and doc.get("open_blocking_count", 1) == 0 else "FAIL",
            f"open_blocking={len(open_blocking)}, open_blocking_count={doc.get('open_blocking_count')}",
        )
    )


def _check_prior_stage_integrity_bytes(add: Any, root: Path) -> None:
    from human_simulator.stage03.prior_stage_integrity import evaluate_prior_stage_integrity

    ok, records = evaluate_prior_stage_integrity(root)
    missing = [record.path for record in records if not record.current_sha256]
    mismatched = [record.path for record in records if record.current_sha256 and not record.unchanged]
    add(
        CheckResult(
            "prior_stage_integrity_bytes",
            "preconditions",
            "PASS" if ok else "FAIL",
            "unchanged" if ok else f"mismatched={mismatched[:3]}, missing={missing[:3]}",
        )
    )


def _check_prior_stage_integrity_document(add: Any, root: Path) -> None:
    from human_simulator.stage03.prior_stage_integrity import (
        CONTROLLED_PRIOR_STAGE_PATHS,
        PRIOR_STAGE_INTEGRITY_NAME,
        build_prior_stage_integrity_document,
        evaluate_prior_stage_integrity,
    )

    ok, _records = evaluate_prior_stage_integrity(root)
    integrity_path = root / "artifacts" / "stage-03-implementation" / PRIOR_STAGE_INTEGRITY_NAME
    if not integrity_path.exists():
        add(
            CheckResult(
                "prior_stage_integrity_document",
                "preconditions",
                "PASS" if ok else "FAIL",
                "integrity document pending publication",
            )
        )
        return

    document = json.loads(integrity_path.read_text(encoding="utf-8"))
    current = build_prior_stage_integrity_document(root)
    problems: list[str] = []
    if document.get("unchanged") is not True or current.get("unchanged") is not True:
        problems.append("unchanged!=True")
    if document.get("controlled_file_count") != len(CONTROLLED_PRIOR_STAGE_PATHS):
        problems.append(
            f"controlled_file_count={document.get('controlled_file_count')!r}, "
            f"expected {len(CONTROLLED_PRIOR_STAGE_PATHS)}"
        )
    documented_paths = {entry.get("path") for entry in document.get("controlled_files", [])}
    if documented_paths != set(CONTROLLED_PRIOR_STAGE_PATHS):
        problems.append("controlled_files do not match the controlled path set")
    for forbidden in ("baseline_git_commit", "baseline_git_note"):
        if forbidden in document:
            problems.append(f"false git provenance field {forbidden}")
    source = document.get("baseline_source")
    if not isinstance(source, dict):
        problems.append("missing baseline_source")
    else:
        if source.get("kind") != "accepted_review_bundle":
            problems.append(f"baseline_source.kind={source.get('kind')!r}")
        if source.get("member_hashes_verified") is not True:
            problems.append("baseline_source.member_hashes_verified!=True")
    if document.get("automatic_restore_performed") is not False:
        problems.append("automatic_restore_performed must be false")
    add(
        CheckResult(
            "prior_stage_integrity_document",
            "preconditions",
            "PASS" if not problems else "FAIL",
            PRIOR_STAGE_INTEGRITY_NAME if not problems else "; ".join(problems),
        )
    )


def _check_prior_stage_integrity(add: Any, root: Path) -> None:
    _check_prior_stage_integrity_bytes(add, root)
    _check_prior_stage_integrity_document(add, root)


def _check_release_verification(add: Any, impl_dir: Path) -> None:
    from human_simulator.stage03.release_verification import RELEASE_VERIFICATION_NAME

    path = impl_dir / RELEASE_VERIFICATION_NAME
    if not path.exists():
        add(
            CheckResult(
                "release_verification_evidence",
                "verification",
                "PASS",
                "release evidence pending publication",
            )
        )
        return

    document = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if document.get("overall_release_status") != "PASS":
        problems.append(f"overall_release_status={document.get('overall_release_status')!r}")
    if document.get("mandatory_failures"):
        problems.append(f"mandatory_failures={document.get('mandatory_failures')}")
    if document.get("implementation_plan_version") != STAGE03_IMPLEMENTATION_PLAN_VERSION:
        problems.append(f"implementation_plan_version={document.get('implementation_plan_version')!r}")
    if document.get("design_baseline_version") != STAGE03_DESIGN_VERSION:
        problems.append(f"design_baseline_version={document.get('design_baseline_version')!r}")

    suites = document.get("suites", [])
    mandatory = [suite for suite in suites if suite.get("mandatory")]
    if not mandatory:
        problems.append("no mandatory suites recorded")
    for suite in mandatory:
        if suite.get("exit_code") != 0:
            problems.append(f"{suite.get('name')}: exit_code={suite.get('exit_code')!r}")
        if suite.get("failed"):
            problems.append(f"{suite.get('name')}: failed={suite.get('failed')!r}")
        if suite.get("errors"):
            problems.append(f"{suite.get('name')}: errors={suite.get('errors')!r}")
        if "..." in str(suite.get("command", "")) or "…" in str(suite.get("command", "")):
            problems.append(f"{suite.get('name')}: command is elided")

    required_names = {"clean_review_bundle_suite", "full_repository_suite"}
    recorded_names = {suite.get("name") for suite in suites}
    if not required_names <= recorded_names:
        problems.append(f"missing mandatory suites: {sorted(required_names - recorded_names)}")

    gate_pytest = document.get("gate_pytest", {})
    if gate_pytest.get("exit_code") != 0 or gate_pytest.get("failed"):
        problems.append(
            f"gate_pytest exit_code={gate_pytest.get('exit_code')!r}, failed={gate_pytest.get('failed')!r}"
        )

    integrity = document.get("prior_stage_integrity", {})
    if integrity.get("unchanged") is not True:
        problems.append("prior_stage_integrity.unchanged!=True")
    if integrity.get("automatic_restore_performed") is not False:
        problems.append("prior_stage_integrity.automatic_restore_performed must be false")

    add(
        CheckResult(
            "release_verification_evidence",
            "verification",
            "PASS" if not problems else "FAIL",
            RELEASE_VERIFICATION_NAME if not problems else "; ".join(problems),
        )
    )


def _check_planning_artifact_versions(add: Any, impl_dir: Path) -> None:
    yaml_names = [
        "implementation-plan.yaml",
        "physical-storage-plan.yaml",
        "pilot-slice.yaml",
        "pipeline-plan.yaml",
        "validation-plan.yaml",
        "security-runtime-plan.yaml",
        "unresolved-implementation-decisions.yaml",
    ]
    mismatches: list[str] = []
    for name in yaml_names:
        path = impl_dir / name
        if not path.exists():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if doc.get("document_version") != STAGE03_IMPLEMENTATION_PLAN_VERSION:
            mismatches.append(f"{name}={doc.get('document_version')!r}")
    add(
        CheckResult(
            "planning_artifact_versions_synchronized",
            "plan",
            "PASS" if not mismatches else "FAIL",
            "; ".join(mismatches[:6]) if mismatches else "all planning YAML versions synchronized",
        )
    )


def _check_active_document_version_sync(add: Any, root: Path, impl_dir: Path) -> None:
    plan = yaml.safe_load((impl_dir / "implementation-plan.yaml").read_text(encoding="utf-8"))
    plan_version = plan.get("document_version")
    design_version = plan.get("design_baseline_version")
    version_ok = (
        plan_version == STAGE03_IMPLEMENTATION_PLAN_VERSION and design_version == STAGE03_DESIGN_VERSION
    )
    add(
        CheckResult(
            "active_document_version_sync_plan_yaml",
            "docs",
            "PASS" if version_ok else "FAIL",
            f"plan={plan_version!r}, design={design_version!r}",
        )
    )

    active_docs: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        (
            "docs/stage-03-implementation.md",
            (f"v{STAGE03_IMPLEMENTATION_PLAN_VERSION}", f"v{STAGE03_DESIGN_VERSION}", "unresolved-implementation-decisions.yaml"),
            ("unresolved-implementation-decisions.md", "v0.7.2", "v0.7.3", "v0.1"),
        ),
        (
            "docs/stage-03-implementation-acceptance.md",
            (f"v{STAGE03_IMPLEMENTATION_PLAN_VERSION}", f"v{STAGE03_DESIGN_VERSION}", "unresolved-implementation-decisions.yaml"),
            ("unresolved-implementation-decisions.md", "v0.7.2", "v0.7.3"),
        ),
        (
            "docs/current-stage.md",
            (f"v{STAGE03_IMPLEMENTATION_PLAN_VERSION}", f"v{STAGE03_DESIGN_VERSION}"),
            (
                "Implementation planning v0.3.1",
                "Implementation planning v0.3.2",
                "Implementation planning v0.3.3",
                "Implementation planning v0.3.4",
                "v0.7.2",
                "v0.7.3",
            ),
        ),
        (
            ".cursor/rules/08-canonical-implementation.mdc",
            (f"v{STAGE03_DESIGN_VERSION}",),
            ("v0.7.2", "v0.7.3", "v0.3.2", "v0.3.3", "v0.3.4"),
        ),
        (
            ".cursor/skills/plan-canonical-implementation/SKILL.md",
            (f"v{STAGE03_DESIGN_VERSION}", f"v{STAGE03_IMPLEMENTATION_PLAN_VERSION}"),
            ("v0.7.2", "v0.7.3", "unresolved-implementation-decisions.md"),
        ),
        (
            ".cursor/skills/verify-implementation-plan/SKILL.md",
            (f"v{STAGE03_IMPLEMENTATION_PLAN_VERSION}", f"v{STAGE03_DESIGN_VERSION}"),
            ("v0.7.2", "v0.7.3", "v0.3.2", "v0.3.3", "v0.3.4"),
        ),
        (
            ".cursor/commands/stage-03-implementation-plan-start.md",
            (f"v{STAGE03_DESIGN_VERSION}",),
            ("v0.7.2", "v0.7.3", "v0.3.2", "v0.3.3", "v0.3.4"),
        ),
        (
            ".cursor/commands/stage-03-implementation-plan-check.md",
            (f"v{STAGE03_IMPLEMENTATION_PLAN_VERSION}",),
            ("v0.7.2", "v0.2", "v0.3.2", "v0.3.3", "v0.3.4"),
        ),
    )
    mismatches: list[str] = []
    for rel, required, forbidden in active_docs:
        path = root / rel
        if not path.exists():
            mismatches.append(f"{rel}: missing")
            continue
        text = path.read_text(encoding="utf-8")
        if any(token not in text for token in required):
            mismatches.append(f"{rel}: missing required tokens {required}")
        if any(token in text for token in forbidden):
            mismatches.append(f"{rel}: contains stale token")
    add(
        CheckResult(
            "active_document_version_sync",
            "docs",
            "PASS" if not mismatches else "FAIL",
            "; ".join(mismatches[:6]) if mismatches else "all active docs synchronized",
        )
    )


def _check_planning_yaml_integrity(add: Any, impl_dir: Path) -> None:
    from human_simulator.stage03.yaml_integrity import DuplicateKeyError, load_planning_yaml

    yaml_names = [
        "implementation-plan.yaml",
        "physical-storage-plan.yaml",
        "pilot-slice.yaml",
        "pipeline-plan.yaml",
        "validation-plan.yaml",
        "security-runtime-plan.yaml",
        "unresolved-implementation-decisions.yaml",
    ]
    errors: list[str] = []
    for name in yaml_names:
        path = impl_dir / name
        if not path.exists():
            continue
        try:
            load_planning_yaml(path.read_text(encoding="utf-8"), source=str(path))
        except DuplicateKeyError as exc:
            errors.append(str(exc))
    add(
        CheckResult(
            "planning_yaml_no_duplicate_keys",
            "plan",
            "PASS" if not errors else "FAIL",
            "; ".join(errors[:3]) if errors else "no duplicate keys",
        )
    )


def _check_pilot_read_set_fingerprint_coverage(add: Any, stage03_dir: Path, impl_dir: Path) -> None:
    from human_simulator.stage03.pilot_read_set import validate_fingerprint_coverage
    from human_simulator.stage03.yaml_integrity import load_planning_yaml

    construction = yaml.safe_load((stage03_dir / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    mapping = yaml.safe_load((stage03_dir / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))
    pilot_slice = load_planning_yaml((impl_dir / "pilot-slice.yaml").read_text(encoding="utf-8"), source="pilot-slice.yaml")
    pipeline = load_planning_yaml((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"), source="pipeline-plan.yaml")
    validations = validate_fingerprint_coverage(
        construction_contract=construction,
        source_a_mapping_draft=mapping,
        pilot_slice=pilot_slice,
        fingerprint_contract=pipeline.get("source_snapshot_fingerprint_contract", {}),
    )
    uncovered = [
        f"{item.relation}:{sorted(item.uncovered)}"
        for item in validations
        if item.uncovered
    ]
    undocumented = [
        f"{item.relation}:{sorted(item.undocumented_without_justification)}"
        for item in validations
        if item.undocumented_without_justification
    ]
    add(
        CheckResult(
            "pilot_read_set_fingerprint_coverage",
            "pipeline",
            "PASS" if not uncovered else "FAIL",
            "; ".join(uncovered[:4]) if uncovered else "all pilot read-set columns covered",
        )
    )
    add(
        CheckResult(
            "pilot_fingerprint_no_undocumented_columns",
            "pipeline",
            "PASS" if not undocumented else "FAIL",
            "; ".join(undocumented[:4]) if undocumented else "no undocumented fingerprint columns",
        )
    )


def _check_fingerprint_and_payload_contracts(add: Any, impl_dir: Path) -> None:
    from human_simulator.stage03.contract_algorithms import (
        CANONICAL_JSON_CONTRACT_VERSION,
        SOURCE_BACKED_PROVENANCE_ALLOWLIST,
        build_stable_payload,
        canonical_payload_hash,
        normalize_canonical_json,
    )
    from human_simulator.stage03.yaml_integrity import load_planning_yaml

    pipeline = load_planning_yaml((impl_dir / "pipeline-plan.yaml").read_text(encoding="utf-8"), source="pipeline-plan.yaml")
    fp = pipeline.get("canonical_payload_hash_contract", {})
    payload_shape = fp.get("payload_shape", [])
    allowlist = set(fp.get("stable_source_backed_provenance_allowlist", []))
    excluded = set(fp.get("excluded_volatile_fields", []))
    payload_ok = (
        fp.get("contract_version") == CANONICAL_JSON_CONTRACT_VERSION
        and fp.get("algorithm") == "SHA-256"
        and fp.get("serialization") == "canonical_json"
        and payload_shape
        and allowlist == SOURCE_BACKED_PROVENANCE_ALLOWLIST
        and "pipeline_run_id" in excluded
        and "emitted_at" in excluded
    )
    add(
        CheckResult(
            "canonical_payload_hash_contract_executable",
            "pipeline",
            "PASS" if payload_ok else "FAIL",
            f"contract_version={fp.get('contract_version')}, payload_shape={payload_shape}",
        )
    )
    sample = build_stable_payload(
        canonical_entity="Subject",
        canonical_id="subj-1",
        stable_clinical_fields={"birthdate": "1990-01-01"},
        provenance={
            "source_system_id": "magerya_api",
            "pipeline_run_id": "volatile",
            "unknown_runtime_field": "ignored",
        },
        source_record_locator="loc",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version=STAGE03_IMPLEMENTATION_PLAN_VERSION,
    )
    shape_ok = tuple(payload_shape) == tuple(sample.keys())
    volatile_ignored = "pipeline_run_id" not in sample["stable_source_backed_provenance"]
    unknown_ignored = "unknown_runtime_field" not in sample["stable_source_backed_provenance"]
    add(
        CheckResult(
            "canonical_payload_builder_matches_documented_shape",
            "pipeline",
            "PASS" if shape_ok and volatile_ignored and unknown_ignored else "FAIL",
            f"keys={list(sample.keys())}",
        )
    )
    nested_payload = build_stable_payload(
        canonical_entity="Observation",
        canonical_id="obs-1",
        stable_clinical_fields={
            "observed_at": datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC),
            "value": Decimal("12.500"),
            "specimen_date": date(2020, 1, 1),
            "identifier": UUID("00000000-0000-0000-0000-000000000099"),
        },
        provenance={"source_system_id": "magerya_api"},
        source_record_locator="loc",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version=STAGE03_IMPLEMENTATION_PLAN_VERSION,
    )
    try:
        nested_hash = canonical_payload_hash(nested_payload)
        normalized = normalize_canonical_json(nested_payload)
        clinical_fields = next(pair[1] for pair in normalized[1] if pair[0] == "stable_clinical_fields")
        value_node = next(pair[1] for pair in clinical_fields[1] if pair[0] == "value")
        nested_ok = bool(nested_hash) and value_node[0] == "decimal"
    except Exception as exc:  # noqa: BLE001
        nested_ok = False
        nested_hash = str(exc)
    add(
        CheckResult(
            "canonical_payload_hash_supports_nested_scalars",
            "pipeline",
            "PASS" if nested_ok else "FAIL",
            f"hash={nested_hash!r}",
        )
    )


def _check_report_semantic_validation(add: Any, *, report_text: str, plan: dict[str, Any], impl_dir: Path) -> None:
    plan_version = plan.get("document_version")
    design_version = plan.get("design_baseline_version")
    phase_ok = f"Implementation Planning v{plan_version}" in report_text
    design_ok = f"**v{design_version}**" in report_text or f"v{design_version}" in report_text
    checkpoint_ok = f"Planning checkpoint v{plan_version} reached." in report_text
    manifest_path = impl_dir / IMPLEMENTATION_PLAN_MANIFEST_NAME
    manifest_ok = False
    if manifest_path.exists():
        manifest_hash = sha256_file(manifest_path)
        manifest_ok = f"`{manifest_hash}`" in report_text
    stale_markers = (
        "Implementation Planning v0.2",
        "Planning checkpoint v0.2 reached.",
        "Design **v0.7.3**",
        "Design v0.7.2",
        "Implementation Planning v0.3.1",
        "Planning checkpoint v0.3.1 reached.",
        "Implementation Planning v0.3.4",
        "Planning checkpoint v0.3.4 reached.",
    )
    stale_ok = not any(marker in report_text for marker in stale_markers)
    add(
        CheckResult(
            "report_phase_version_matches_plan",
            "report",
            "PASS" if phase_ok else "FAIL",
            f"expected v{plan_version}",
        )
    )
    add(
        CheckResult(
            "report_design_baseline_matches_plan",
            "report",
            "PASS" if design_ok else "FAIL",
            f"expected v{design_version}",
        )
    )
    add(
        CheckResult(
            "report_manifest_sha256_matches",
            "report",
            "PASS" if manifest_ok else "FAIL",
            "manifest hash present in report" if manifest_ok else "manifest hash mismatch or missing",
        )
    )
    add(
        CheckResult(
            "report_checkpoint_version_matches_plan",
            "report",
            "PASS" if checkpoint_ok else "FAIL",
            f"expected checkpoint v{plan_version}",
        )
    )
    add(
        CheckResult(
            "report_no_stale_active_baseline",
            "report",
            "PASS" if stale_ok else "FAIL",
            "stale baseline markers detected" if not stale_ok else "no stale baseline",
        )
    )


def _check_report_chronology(
    add: Any,
    *,
    report_generated_at: str,
    verified_at: str,
    review_bundle_generated_at: str,
) -> None:
    report_dt = _parse_iso_timestamp(report_generated_at)
    verified_dt = _parse_iso_timestamp(verified_at)
    bundle_dt = _parse_iso_timestamp(review_bundle_generated_at)
    ok = (
        report_dt is not None
        and verified_dt is not None
        and bundle_dt is not None
        and report_dt <= verified_dt <= bundle_dt
    )
    add(
        CheckResult(
            "report_timestamp_chronology",
            "verification",
            "PASS" if ok else "FAIL",
            f"report={report_generated_at}, verified={verified_at}, bundle={review_bundle_generated_at}",
        )
    )


def _check_review_bundle_repo_paths(add: Any, root: Path) -> None:
    from human_simulator.stage03.implementation_review_bundle import COPY_PATHS

    add(
        CheckResult(
            "review_bundle_includes_full_human_simulator",
            "audit",
            "PASS" if "src/human_simulator" in COPY_PATHS else "FAIL",
            "src/human_simulator required in review bundle",
        )
    )
    missing = [rel for rel in REVIEW_BUNDLE_REQUIRED_PATHS if not (root / rel).exists()]
    add(
        CheckResult(
            "review_bundle_required_paths_present_in_repo",
            "audit",
            "PASS" if not missing else "FAIL",
            f"missing={missing}",
        )
        )


def _check_pipeline_plan(add: Any, impl_dir: Path) -> None:
    path = impl_dir / "pipeline-plan.yaml"
    if not path.exists():
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in (
        "idempotent_rerun",
        "rollback",
        "reconciliation",
        "restart_from_checkpoint",
        "snapshot_consistency",
        "cohort_policy",
        "source_snapshot_fingerprint",
        "idempotent_promotion",
    ):
        add(
            CheckResult(
                f"pipeline_{key}_defined",
                "pipeline",
                "PASS" if doc.get(key) else "FAIL",
                f"{key}={'present' if doc.get(key) else 'missing'}",
            )
        )
    extract = doc.get("extract", {})
    add(
        CheckResult(
            "pipeline_extract_read_only",
            "pipeline",
            "PASS" if extract.get("mode") == "read_only" and extract.get("role") == "mg_audit_ro" else "FAIL",
            f"mode={extract.get('mode')!r}, role={extract.get('role')!r}",
        )
    )


def _check_validation_plan(add: Any, impl_dir: Path) -> None:
    path = impl_dir / "validation-plan.yaml"
    if not path.exists():
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    names = {item.get("name") for section in doc.get("pilot_validation_checks", {}).values() for item in section if isinstance(item, dict)}
    required = {
        "source_row_count",
        "emitted_canonical_row_count",
        "rejected_row_count",
        "duplicate_canonical_ids",
        "orphan_foreign_keys",
        "missing_required_provenance",
        "one_per_row_cardinality_balance",
        "zero_to_many_cardinality_balance",
        "deterministic_rerun",
        "raw_database_fingerprint_unchanged",
        "zero_cross_source_linkage",
        "zero_global_patient_ids",
        "zero_pii_raw_rows_in_reports",
    }
    missing = sorted(required - names)
    add(
        CheckResult(
            "validation_required_checks_defined",
            "validation",
            "PASS" if not missing else "FAIL",
            f"missing={missing}",
        )
    )
    add(
        CheckResult(
            "quarantine_schema_defined",
            "validation",
            "PASS" if doc.get("quarantine", {}).get("validation_error_schema") else "FAIL",
            "quarantine validation_error_schema required",
        )
    )


def _check_security_runtime_plan(add: Any, impl_dir: Path, stage03_dir: Path) -> None:
    path = impl_dir / "security-runtime-plan.yaml"
    if not path.exists():
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    cid = doc.get("canonical_id", {})
    add(
        CheckResult(
            "canonical_id_namespace_version",
            "identity",
            "PASS" if cid.get("id_namespace_version") == "0.7.0" else "FAIL",
            f"id_namespace_version={cid.get('id_namespace_version')!r}",
        )
    )
    add(
        CheckResult(
            "canonical_id_runtime_secret_only",
            "identity",
            "PASS" if cid.get("secret_storage") == "runtime_only" else "FAIL",
            f"secret_storage={cid.get('secret_storage')!r}",
        )
    )
    add(
        CheckResult(
            "key_version_required",
            "identity",
            "PASS" if cid.get("key_version_field") == "key_version" else "FAIL",
            "key_version required in runtime plan",
        )
    )
    contract = yaml.safe_load((stage03_dir / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    forbidden = contract.get("key_rotation", {}).get("runtime_secret_rotation", {}).get("forbidden", [])
    add(
        CheckResult(
            "secret_change_without_key_version_bump_forbidden",
            "identity",
            "PASS" if "secret_change_without_key_version_bump" in forbidden else "FAIL",
            f"forbidden={forbidden}",
        )
    )
    temporal = yaml.safe_load((stage03_dir / "temporal-contract.yaml").read_text(encoding="utf-8"))
    add(
        CheckResult(
            "temporal_contract_referenced",
            "temporal",
            "PASS" if temporal.get("forbidden_substitutions") else "FAIL",
            "temporal-contract.yaml must define forbidden substitutions",
        )
    )
    provenance = yaml.safe_load((stage03_dir / "provenance-contract.yaml").read_text(encoding="utf-8"))
    add(
        CheckResult(
            "provenance_contract_referenced",
            "provenance",
            "PASS" if provenance.get("profiles", {}).get("SOURCE_BACKED") else "FAIL",
            "provenance SOURCE_BACKED profile required",
        )
    )


def _check_physical_storage_plan(add: Any, impl_dir: Path) -> None:
    path = impl_dir / "physical-storage-plan.yaml"
    if not path.exists():
        return
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    role_names = set(doc.get("database_roles", {}).keys()) if isinstance(doc.get("database_roles"), dict) else set()
    required_roles = {"canonical_owner", "canonical_migrator", "canonical_loader", "canonical_validator_ro", "mg_audit_ro"}
    add(
        CheckResult(
            "derived_database_isolated_from_raw",
            "storage",
            "PASS" if doc.get("planned_topology", {}).get("database_name") == "uhbse_canonical_dev" else "FAIL",
            f"database={doc.get('planned_topology', {}).get('database_name')!r}",
        )
    )
    add(
        CheckResult(
            "database_roles_defined",
            "storage",
            "PASS" if required_roles <= role_names else "FAIL",
            f"roles={sorted(role_names)}",
        )
    )
    forbidden = doc.get("connection_policy", {}).get("forbidden_targets", [])
    add(
        CheckResult(
            "raw_db_not_write_target",
            "storage",
            "PASS" if "magerya_api" in forbidden and "kgz_raw" in forbidden else "FAIL",
            f"forbidden_targets={forbidden}",
        )
    )
    add(
        CheckResult(
            "physical_creation_status_not_created",
            "storage",
            "PASS" if doc.get("physical_creation_status") == "not_created" else "FAIL",
            f"physical_creation_status={doc.get('physical_creation_status')!r}",
        )
    )


def _check_no_cross_source_merge(add: Any, impl_dir: Path) -> None:
    pilot = yaml.safe_load((impl_dir / "pilot-slice.yaml").read_text(encoding="utf-8"))
    forbidden = pilot.get("forbidden_in_pilot", [])
    add(
        CheckResult(
            "no_global_patient_or_cross_source_merge",
            "safety",
            "PASS"
            if "global_patient_id" in forbidden
            and "global_subject_id" in forbidden
            and "cross_source_subject_resolution" in forbidden
            else "FAIL",
            f"forbidden_in_pilot={forbidden}",
        )
    )


def _compute_content_manifest_lines(impl_dir: Path) -> list[str]:
    lines: list[str] = []
    for name in IMPLEMENTATION_CONTENT_ARTIFACTS:
        path = impl_dir / name
        if path.exists():
            lines.append(f"{sha256_file(path)}  {name}")
    return lines


def _verify_manifest_lines(lines: list[str], impl_dir: Path) -> tuple[bool, str]:
    if len(lines) != len(IMPLEMENTATION_CONTENT_ARTIFACTS):
        return False, f"expected {len(IMPLEMENTATION_CONTENT_ARTIFACTS)} entries, found {len(lines)}"
    for line in lines:
        digest, name = line.split(maxsplit=1)
        entry = name.strip()
        if entry in FORBIDDEN_IN_IMPLEMENTATION_MANIFEST:
            return False, f"forbidden entry: {entry}"
        path = impl_dir / entry
        if not path.exists() or sha256_file(path) != digest:
            return False, f"hash mismatch: {entry}"
    return True, f"verified {len(lines)} content entries"


def _verify_content_manifest(manifest_path: Path, impl_dir: Path) -> tuple[bool, str]:
    lines = [line for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return _verify_manifest_lines(lines, impl_dir)


def _read_report_generated_timestamp(report_path: Path) -> str | None:
    if not report_path.exists():
        return None
    match = REPORT_GENERATED_PATTERN.search(report_path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else None


def _parse_iso_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _run_pytest(repo_root: Path) -> dict[str, Any]:
    filter_expr = gate_pytest_filter_expr()
    collect_all = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_verify_implementation_plan.py",
            "tests/test_stage03_contracts.py",
            "tests/test_review_bundle_validation.py",
            "-q",
            "--collect-only",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    collect_filtered = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_verify_implementation_plan.py",
            "tests/test_stage03_contracts.py",
            "tests/test_review_bundle_validation.py",
            "-q",
            "--collect-only",
            "-k",
            filter_expr,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    def parse_collected(output: str, *, total: bool) -> int:
        for line in output.splitlines():
            if " tests collected" in line or " test collected" in line:
                token = line.strip().split()[0]
                if "/" in token:
                    parts = token.split("/")
                    return int(parts[1]) if total else int(parts[0])
                return int(token)
        return 0

    collected = parse_collected((collect_all.stdout or "") + (collect_all.stderr or ""), total=True)
    selected = parse_collected((collect_filtered.stdout or "") + (collect_filtered.stderr or ""), total=False)
    deselected = max(collected - selected, 0)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_verify_implementation_plan.py",
            "tests/test_stage03_contracts.py",
            "tests/test_review_bundle_validation.py",
            "-q",
            "-k",
            filter_expr,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    summary = output.strip().splitlines()[-1] if output.strip() else "no pytest output"
    passed = failed = skipped = 0
    if " passed" in summary:
        passed = int(summary.split(" passed")[0].split()[-1])
    if " failed" in summary:
        failed = int(summary.split(" failed")[0].split()[-1])
    if " skipped" in summary:
        skipped = int(summary.split(" skipped")[0].split()[-1])
    duration_seconds = None
    match = re.search(r"in\s+([\d.]+)s", summary)
    if match:
        duration_seconds = float(match.group(1))
    if selected == 0:
        selected = passed + failed + skipped
    return {
        "pytest_command": (
            "python -m pytest tests/test_verify_implementation_plan.py "
            f"tests/test_stage03_contracts.py -q -k {filter_expr!r}"
        ),
        "pytest_exit_code": completed.returncode,
        "pytest_collected": collected,
        "pytest_selected": selected,
        "pytest_deselected": deselected,
        "pytest_passed": passed,
        "pytest_failed": failed,
        "pytest_skipped": skipped,
        "pytest_duration_seconds": duration_seconds,
        "pytest_summary": summary,
    }




def _load_pytest_from_verification(verification_path: Path) -> dict[str, Any]:
    payload = json.loads(verification_path.read_text(encoding="utf-8"))
    return {
        "pytest_command": payload.get("pytest_command", ""),
        "pytest_exit_code": payload.get("pytest_exit_code", 1),
        "pytest_collected": payload.get("pytest_collected", 0),
        "pytest_selected": payload.get("pytest_selected", 0),
        "pytest_deselected": payload.get("pytest_deselected", 0),
        "pytest_passed": payload.get("pytest_passed", 0),
        "pytest_failed": payload.get("pytest_failed", 0),
        "pytest_skipped": payload.get("pytest_skipped", 0),
        "pytest_duration_seconds": payload.get("pytest_duration_seconds"),
        "pytest_summary": payload.get("pytest_summary", "pytest not run"),
    }


def _load_prior_stage_suite_hashes(root: Path) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    """Read the before/after gate-pytest hashes recorded during publication."""
    from human_simulator.stage03.prior_stage_integrity import PRIOR_STAGE_INTEGRITY_NAME

    path = root / "artifacts" / "stage-03-implementation" / PRIOR_STAGE_INTEGRITY_NAME
    if not path.exists():
        return None, None
    document = json.loads(path.read_text(encoding="utf-8"))
    before = document.get("hashes_before_test_suite")
    after = document.get("hashes_after_test_suite")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None, None
    return before, after


def _empty_pytest_result() -> dict[str, Any]:
    return {
        "pytest_command": "",
        "pytest_exit_code": 0,
        "pytest_collected": 0,
        "pytest_selected": 0,
        "pytest_deselected": 0,
        "pytest_passed": 0,
        "pytest_failed": 0,
        "pytest_skipped": 0,
        "pytest_duration_seconds": None,
        "pytest_summary": "pytest not run",
    }
