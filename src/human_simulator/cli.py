"""CLI entry points for Stage 01 audit and Stage 02 restore infrastructure."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from human_simulator.audit.postgres_profile import (
    ProfilePostgresError,
    UnsafeConfigurationError,
    profile_postgres_source,
)
from human_simulator.config.policy import ProfilingPolicy
from human_simulator.audit.connection import connection_check
from human_simulator.audit.discover import discover_schema
from human_simulator.audit.report import generate_report, write_draft_stage_01_report
from human_simulator.audit.structure import profile_structure
from human_simulator.audit.verify import verify_stage
from human_simulator.config.settings import AuditSettings
from human_simulator.db.session import create_audit_engine
from human_simulator.logging_config import configure_logging, get_logger
from human_simulator.stage02.profile_second_source import profile_second_source
from human_simulator.stage02.preflight import run_preflight, write_preflight_artifacts
from human_simulator.stage02.restore import RestoreError, restore_second_source, write_restore_report
from human_simulator.stage02.settings import KgzRestoreSettings


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    log = get_logger("audit.cli")

    parser = argparse.ArgumentParser(prog="audit", description="UHBSE database audit and Stage 02 restore")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("connection-check", help="Check database connectivity")
    sub.add_parser("discover-schema", help="Discover schema metadata")
    sub.add_parser("profile-structure", help="Profile null rates and structure")
    sub.add_parser("profile-source", help="Profile one PostgreSQL clinic source")
    sub.add_parser("profile-aggregates", help="Build aggregate summaries")
    sub.add_parser("classify-entities", help="Find candidate clinical entities from schema profile")
    sub.add_parser("draft-report", help="Write stage-01-report.md with DRAFT status")
    sub.add_parser("generate-report", help="Write Stage 01 artifacts and report")
    sub.add_parser("verify-stage", help="Verify Stage 01 deliverables")
    sub.add_parser("restore-preflight", help="Preflight checks for kgz dump restore (no restore)")
    restore_parser = sub.add_parser(
        "restore-second-source",
        help="Restore kgz dump into kgz_raw (requires --confirm)",
    )
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicit confirmation required to run restore",
    )
    sub.add_parser(
        "profile-second-source",
        help="Profile source B (kgz) via read-only kgz_audit_ro",
    )

    sub.add_parser(
        "profile-source-a",
        help="Profile Source A (magerya_api) via read-only mg_audit_ro and verify Stage 01",
    )

    sub.add_parser(
        "compare-source-audits",
        help="Compare Stage 01 source A artifacts with Stage 02 source B artifacts",
    )

    sub.add_parser(
        "assess-source-relationship",
        help="Assess system relationship and aggregate identity linkage between sources A and B",
    )

    sub.add_parser(
        "verify-stage-02",
        help="Verify Stage 02 deliverables and promote report to FINAL on PASS",
    )

    design_check_parser = sub.add_parser(
        "stage-03-check",
        help="Verify Stage 03 design preconditions and artifacts (DRAFT report only)",
    )
    design_check_parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Read-only verification; writes no artifacts (reviewer mode)",
    )

    plan_check_parser = sub.add_parser(
        "stage-03-implementation-plan-check",
        help="Verify Stage 03 implementation planning artifacts (DRAFT report only)",
    )
    plan_check_parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Read-only verification; writes no artifacts (reviewer mode)",
    )

    changeset_check_parser = sub.add_parser(
        "changeset-01-check",
        help="Verify Stage 03 Implementation Changeset 01 (canonical storage foundation)",
    )
    changeset_check_parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Read-only verification; writes no artifacts (reviewer mode)",
    )

    sub.add_parser(
        "changeset-01-baseline",
        help="Read-only baseline precondition check for Changeset 01 (writes nothing)",
    )

    maintenance_parser = sub.add_parser(
        "stage-02-maintenance-01",
        help="Diagnose the relationship manifest drift and prepare a candidate repair (applies nothing)",
    )
    maintenance_parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Run the diagnosis without building the review bundle",
    )

    maintenance_apply_parser = sub.add_parser(
        "stage-02-maintenance-01-apply",
        help="Apply the authorised relationship-manifest repair from the maintenance candidate",
    )
    maintenance_apply_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to perform the manifest replacement",
    )
    maintenance_apply_parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Apply without building the promotion review bundle",
    )

    changeset_publish_parser = sub.add_parser(
        "changeset-01-publish",
        help="Run all Changeset 01 gates and suites, then publish the review bundle once",
    )
    changeset_publish_parser.add_argument(
        "--skip-migration-suite",
        action="store_true",
        help="Omit the live migration suite when no canonical endpoint is configured",
    )

    sub.add_parser(
        "stage-02-pre-live-load-gate",
        help=(
            "Evaluate stage02_relationship_integrity_pre_live_load; read-only, never repairs"
        ),
    )

    migrate_parser = sub.add_parser(
        "canonical-migrate",
        help="Apply forward-only canonical migrations to the isolated derived database",
    )
    migrate_parser.add_argument(
        "--database",
        default=None,
        help="Override the target database name (used by the disposable migration suite)",
    )
    migrate_parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Apply and verify without writing changeset artifacts",
    )

    capture_parser = sub.add_parser(
        "canonical-capture-baseline",
        help=(
            "Rebuild the pinned schema definition baseline on a throwaway database "
            "created from the accepted migrations, then drop it"
        ),
    )
    capture_parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Capture and report without writing the baseline artifact",
    )

    restore_baseline_parser = sub.add_parser(
        "restore-prior-stage-baseline",
        help="Restore accepted Stage 01/02 bytes from the accepted review bundle (requires --confirm)",
    )
    restore_baseline_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicit confirmation required; verifiers and tests must never call this",
    )

    frozen_parser = sub.add_parser(
        "frozen-evidence-check",
        help="Read-only integrity check of every frozen Stage 01/02, Design, Plan and migration input",
    )
    frozen_parser.set_defaults(command="frozen-evidence-check")

    recover_evidence_parser = sub.add_parser(
        "recover-design-evidence",
        help=(
            "Recover the accepted Design report and verification bytes from an accepted "
            "release archive (requires --confirm)"
        ),
    )
    recover_evidence_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicit confirmation required; verifiers, suites and the publisher never call this",
    )

    irr = sub.add_parser("integrated-runtime", help="Integrated Research Runtime Foundation")
    irr_sub = irr.add_subparsers(dest="irr_command", required=True)
    irr_run = irr_sub.add_parser("run-v0.1.6", help="Run Integrated Research Runtime v0.1.6")
    irr_run.add_argument("--no-publish", action="store_true", default=True)
    irr_sub.add_parser("open-test-v0.1.6", help="Consume frozen upstream held-out without recomputing gates")
    irr_sub.add_parser("verify-v0.1.6", help="Print v0.1.6 verification.json")
    irr_sub.add_parser("publish-v0.1.6", help="Publish the immutable v0.1.6 review ZIP")
    irr_run15 = irr_sub.add_parser("run-v0.1.5", help="Run Integrated Research Runtime v0.1.5")
    irr_run15.add_argument("--no-publish", action="store_true", default=True)
    irr_sub.add_parser("open-test-v0.1.5", help="Consume frozen upstream held-out without recomputing gates")
    irr_sub.add_parser("verify-v0.1.5", help="Print v0.1.5 verification.json")
    irr_sub.add_parser("publish-v0.1.5", help="Publish the immutable v0.1.5 review ZIP")

    irr05 = sub.add_parser(
        "intervention-readiness",
        help="Stage 05 Gate 0 — Intervention Response Readiness and Exposure Semantics",
    )
    irr05_sub = irr05.add_subparsers(dest="irr05_command", required=True)
    irr05_run = irr05_sub.add_parser(
        "run-v0.1",
        help="Run the v0.1.1 corrected readiness audit (frozen v0.1 code stays in its review ZIP)",
    )
    irr05_run.add_argument("--no-publish", action="store_true", default=True)
    irr05_sub.add_parser("verify-v0.1", help="Print the frozen v0.1 verification.json")
    irr05_sub.add_parser("publish-v0.1", help="Refuse to overwrite the published v0.1 review ZIP")
    irr05_run11 = irr05_sub.add_parser("run-v0.1.1", help="Run the v0.1.1 corrected readiness audit")
    irr05_run11.add_argument("--no-publish", action="store_true", default=True)
    irr05_sub.add_parser("verify-v0.1.1", help="Print v0.1.1 verification.json")
    irr05_sub.add_parser("publish-v0.1.1", help="Publish the immutable v0.1.1 review ZIP")

    args = parser.parse_args(argv)
    if args.command == "intervention-readiness":
        cmd = str(args.irr05_command or "")
        if cmd in {"run-v0.1", "run-v0.1.1", "verify-v0.1.1", "publish-v0.1.1"}:
            from human_simulator.intervention_response_readiness_v011.cli import (
                dispatch_intervention_readiness_v011,
            )

            return dispatch_intervention_readiness_v011(args.root, cmd, args)
        from human_simulator.intervention_response_readiness_v01.cli import (
            dispatch_intervention_readiness_v01,
        )

        return dispatch_intervention_readiness_v01(args.root, cmd, args)
    if args.command == "integrated-runtime":
        cmd = str(args.irr_command or "")
        if cmd.endswith("v0.1.6"):
            from human_simulator.integrated_research_runtime_v016.cli import dispatch_integrated_runtime_v016

            return dispatch_integrated_runtime_v016(args.root, cmd, args)
        from human_simulator.integrated_research_runtime_v015.cli import dispatch_integrated_runtime_v015

        return dispatch_integrated_runtime_v015(args.root, args.irr_command, args)

    settings = AuditSettings.from_repo(args.root)

    if args.command == "restore-preflight":
        kgz = KgzRestoreSettings.from_repo(args.root)
        result = run_preflight(kgz)
        artifacts_dir = args.root / kgz.artifacts_dir
        json_path, md_path = write_preflight_artifacts(result, artifacts_dir)
        log.info(
            "restore_preflight_complete",
            status=result.status,
            json=str(json_path),
            markdown=str(md_path),
        )
        print(
            json.dumps(
                {
                    "status": result.status,
                    "target_database": result.target_database,
                    "artifacts": [str(json_path), str(md_path)],
                },
                indent=2,
            )
        )
        return 0 if result.status != "FAIL" else 1

    if args.command == "restore-second-source":
        kgz = KgzRestoreSettings.from_repo(args.root)
        if not args.confirm:
            log.error("restore_confirmation_required")
            print(
                json.dumps(
                    {
                        "error": "Restore requires explicit confirmation: audit restore-second-source --confirm",
                    },
                    indent=2,
                )
            )
            return 1
        try:
            report, preflight = restore_second_source(kgz, confirm=True)
        except RestoreError as exc:
            log.error("restore_failed", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        report_path, md_path = write_restore_report(report, args.root / kgz.artifacts_dir)
        print(
            json.dumps(
                {
                    "restore_performed": report.restore_performed,
                    "preflight_status": preflight.status,
                    "pg_restore_exit_code": report.pg_restore_exit_code,
                    "report": str(report_path),
                    "report_markdown": str(md_path),
                    "auditor_connection": report.auditor_connection or kgz.audit_redacted_url,
                    "message": report.message,
                },
                indent=2,
            )
        )
        return 0 if report.pg_restore_exit_code == 0 else 1

    if args.command == "profile-second-source":
        try:
            result = profile_second_source(args.root)
        except Exception as exc:
            log.error("profile_second_source_failed", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "profile-source-a":
        from human_simulator.stage01.profile_source_a import profile_source_a

        try:
            result = profile_source_a(args.root)
        except Exception as exc:
            log.error("profile_source_a_failed", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("verify_status") == "PASS" else 1

    if args.command == "compare-source-audits":
        from human_simulator.stage02.compare_source_audits import (
            CompareSourceAuditsError,
            compare_source_audits,
        )

        try:
            result = compare_source_audits(args.root)
        except CompareSourceAuditsError as exc:
            log.error("compare_source_audits_failed", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "PASS" else 1

    if args.command == "assess-source-relationship":
        from human_simulator.stage02.assess_source_relationship import (
            AssessSourceRelationshipError,
            assess_source_relationship,
        )

        try:
            result = assess_source_relationship(args.root)
        except AssessSourceRelationshipError as exc:
            log.error("assess_source_relationship_failed", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        except ValueError as exc:
            log.error("assess_source_relationship_config", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "PASS" else 1

    if args.command == "verify-stage-02":
        from human_simulator.stage02.verify_stage_02 import verify_stage_02

        result = verify_stage_02(args.root, run_tests=True)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "PASS" else 1

    if args.command == "stage-03-check":
        from human_simulator.stage03.verify_stage_03_design import verify_stage_03_design

        if args.no_publish:
            result = verify_stage_03_design(args.root, run_pytest=False, publish_artifacts=False)
        else:
            result = verify_stage_03_design(args.root)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "PASS" else 1

    if args.command == "stage-03-implementation-plan-check":
        from human_simulator.stage03.verify_implementation_plan import verify_implementation_plan

        result = verify_implementation_plan(
            args.root,
            run_pytest=not args.no_publish,
            publish_artifacts=not args.no_publish,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "PASS" else 1

    if args.command == "changeset-01-check":
        from human_simulator.stage03.verify_changeset_01 import verify_changeset_01

        result = verify_changeset_01(args.root, publish_artifacts=not args.no_publish)
        print(json.dumps(result, indent=2))
        return 0 if result.get("overall_status") == "PASS" else 1

    if args.command == "changeset-01-baseline":
        from human_simulator.stage03.changeset_01_baseline import evaluate_baseline

        result = evaluate_baseline(args.root)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "PASS" else 1

    if args.command == "stage-02-maintenance-01":
        from human_simulator.stage02_maintenance.publish_maintenance_01 import (
            MaintenancePublicationBlocked,
            publish_maintenance_01,
            stage_02_fingerprint,
        )
        from human_simulator.stage02_maintenance.run_maintenance_01 import run_maintenance_01

        before = stage_02_fingerprint(args.root)
        result = run_maintenance_01(args.root)
        after = stage_02_fingerprint(args.root)
        result["working_stage_02_sha256_before"] = before
        result["working_stage_02_sha256_after"] = after
        if before != after:
            log.error("stage_02_maintenance_mutated_stage_02")
            print(json.dumps({"error": "artifacts/stage-02/ was modified", **result}, indent=2))
            return 1

        if not args.no_publish:
            try:
                result["publication"] = publish_maintenance_01(
                    args.root, expected_stage_02=before
                )
            except MaintenancePublicationBlocked as exc:
                log.error("stage_02_maintenance_publication_blocked", reason=str(exc))
                print(json.dumps({"error": str(exc), **result}, indent=2))
                return 1

        print(json.dumps(result, indent=2))
        return 0

    if args.command == "stage-02-maintenance-01-apply":
        from human_simulator.stage02.relationship_manifest import MANIFEST_NAME
        from human_simulator.stage02_maintenance.apply_maintenance_01 import (
            MaintenanceApplyBlocked,
            apply_maintenance_01,
            finalize_applied_repair,
        )
        from human_simulator.stage02_maintenance.constants import (
            EXPECTED_MANIFEST_SHA_AFTER,
            STAGE_02_DIR,
        )
        from human_simulator.stage02_maintenance.drift_diagnosis import sha256_file
        from human_simulator.stage02_maintenance.publish_promotion import (
            PromotionPublicationBlocked,
            publish_promotion,
        )

        if not args.confirm:
            log.error("stage_02_maintenance_apply_refused")
            print(
                json.dumps(
                    {
                        "error": (
                            "refusing to apply without explicit confirmation: "
                            "audit --root . stage-02-maintenance-01-apply --confirm"
                        )
                    },
                    indent=2,
                )
            )
            return 1

        root = args.root.resolve()
        manifest_sha = sha256_file(root / STAGE_02_DIR / MANIFEST_NAME)
        if manifest_sha == EXPECTED_MANIFEST_SHA_AFTER:
            try:
                result = finalize_applied_repair(root)
            except MaintenanceApplyBlocked as exc:
                log.error("stage_02_maintenance_apply_blocked", reason=str(exc))
                print(json.dumps({"error": str(exc)}, indent=2))
                return 1
        else:
            try:
                result = apply_maintenance_01(root, confirm=args.confirm)
            except MaintenanceApplyBlocked as exc:
                log.error("stage_02_maintenance_apply_blocked", reason=str(exc))
                print(json.dumps({"error": str(exc)}, indent=2))
                return 1

        if not args.no_publish and result.get("status") == "PASS":
            try:
                result["publication"] = publish_promotion(root)
            except PromotionPublicationBlocked as exc:
                log.error("stage_02_maintenance_promotion_blocked", reason=str(exc))
                print(json.dumps({"error": str(exc), **result}, indent=2))
                return 1

        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "PASS" else 1

    if args.command == "changeset-01-publish":
        from human_simulator.stage03.publish_changeset_01 import (
            ChangesetPublicationBlocked,
            publish_changeset_01,
        )

        try:
            result = publish_changeset_01(
                args.root, run_migration_suite=not args.skip_migration_suite
            )
        except ChangesetPublicationBlocked as exc:
            log.error("changeset_01_publication_blocked", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "stage-02-pre-live-load-gate":
        from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate

        document = evaluate_pre_live_load_gate(args.root).document()
        print(json.dumps(document, indent=2))
        return 0 if document.get("status") == "PASS" else 1

    if args.command == "canonical-migrate":
        from human_simulator.stage03.canonical_migration_run import run_canonical_migration

        result = run_canonical_migration(
            args.root,
            database_override=args.database,
            publish_artifacts=not args.no_publish,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "PASS" else 1

    if args.command == "canonical-capture-baseline":
        from human_simulator.stage03.canonical_migration_run import (
            capture_schema_definition_baseline,
        )

        result = capture_schema_definition_baseline(args.root, publish=not args.no_publish)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "frozen-evidence-check":
        from human_simulator.stage03.frozen_evidence import evaluate_frozen_evidence

        document = evaluate_frozen_evidence(args.root)
        print(json.dumps(document, indent=2))
        return 0 if document["status"] == "PASS" else 1

    if args.command == "recover-design-evidence":
        from human_simulator.stage03.frozen_evidence import (
            FrozenEvidenceDrift,
            evaluate_frozen_evidence,
            recover_design_evidence,
        )

        if not args.confirm:
            log.error("recover_design_evidence_confirmation_required")
            print(
                json.dumps(
                    {
                        "error": "Recovering Design evidence requires explicit confirmation: "
                        "audit recover-design-evidence --confirm",
                    },
                    indent=2,
                )
            )
            return 1
        try:
            recovered = recover_design_evidence(args.root, confirm=True)
        except FrozenEvidenceDrift as exc:
            log.error("recover_design_evidence_failed", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        document = evaluate_frozen_evidence(args.root)
        recovered["frozen_evidence_status"] = document["status"]
        print(json.dumps(recovered, indent=2))
        return 0 if document["status"] == "PASS" else 1

    if args.command == "restore-prior-stage-baseline":
        from human_simulator.stage03.prior_stage_integrity import (
            evaluate_prior_stage_integrity,
            restore_prior_stage_baseline,
        )

        if not args.confirm:
            log.error("restore_prior_stage_baseline_confirmation_required")
            print(
                json.dumps(
                    {
                        "error": "Restoring the prior-stage baseline requires explicit "
                        "confirmation: audit restore-prior-stage-baseline --confirm",
                    },
                    indent=2,
                )
            )
            return 1
        try:
            restored = restore_prior_stage_baseline(args.root, confirm=True)
        except (FileNotFoundError, ValueError) as exc:
            log.error("restore_prior_stage_baseline_failed", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        ok, _records = evaluate_prior_stage_integrity(args.root)
        log.info("restore_prior_stage_baseline_complete", restored=len(restored), matches_accepted=ok)
        print(json.dumps({"restored_files": restored, "matches_accepted_hashes": ok}, indent=2))
        return 0 if ok else 1

    if args.command == "verify-stage":
        from human_simulator.audit.verify import verify_stage_01

        artifacts_dir = args.root / settings.artifacts_dir
        result = verify_stage_01(args.root, artifacts_dir=artifacts_dir, run_tests=True)
        print(json.dumps(result, indent=2))
        if result["status"] == "PASS":
            return 0
        if result["status"] == "PARTIAL":
            return 2
        return 1

    if args.command == "classify-entities":
        from human_simulator.classify.entities import ClassifyEntitiesError, classify_from_artifacts

        artifacts_dir = args.root / settings.artifacts_dir
        try:
            result = classify_from_artifacts(args.root, artifacts_dir)
        except ClassifyEntitiesError as exc:
            log.error("classify_entities_failed", reason=str(exc))
            print(json.dumps({"error": str(exc)}, indent=2))
            return 1
        candidate_count = sum(len(items) for items in result["entity_types"].values())
        print(
            json.dumps(
                {
                    "candidates": candidate_count,
                    "unknown_relations": len(result["unknown_relations"]),
                    "artifacts": [
                        str(artifacts_dir / "entity-candidates.yaml"),
                        str(artifacts_dir / "relation-graph.md"),
                        str(artifacts_dir / "unknown-semantics.md"),
                    ],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "draft-report":
        artifacts_dir = args.root / settings.artifacts_dir
        path = write_draft_stage_01_report(artifacts_dir)
        log.info("draft_report_written", path=str(path))
        print(json.dumps({"report": str(path), "status": "DRAFT"}, indent=2))
        return 0

    engine = create_audit_engine(settings)

    try:
        if args.command == "connection-check":
            result = connection_check(settings, engine)
            print(json.dumps(result, indent=2))
            return 0 if result["reachable"] else 1

        if args.command == "discover-schema":
            result = discover_schema(engine)
            print(json.dumps({"table_count": result["table_count"]}, indent=2))
            return 0

        if args.command == "profile-structure":
            schema = discover_schema(engine)
            result = profile_structure(engine, schema)
            print(json.dumps({"tables_profiled": len(result["tables"])}, indent=2))
            return 0

        if args.command == "profile-source":
            if engine.dialect.name != "postgresql":
                raise ProfilePostgresError("profile-source requires PostgreSQL")
            policy = ProfilingPolicy.from_repo(args.root)
            try:
                result = profile_postgres_source(settings, engine, policy)
            except UnsafeConfigurationError as exc:
                log.error("unsafe_configuration", reason=str(exc))
                print(json.dumps({"error": str(exc)}, indent=2))
                return 1
            print(
                json.dumps(
                    {
                        "relations": result["relation_count"],
                        "columns": result["column_count"],
                        "artifact": str(args.root / policy.artifacts_dir / "schema-profile.json"),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "profile-aggregates":
            from human_simulator.audit.aggregates import profile_aggregates

            schema = discover_schema(engine)
            structure = profile_structure(engine, schema)
            result = profile_aggregates(engine, structure)
            print(json.dumps({"column_count": result["column_count"]}, indent=2))
            return 0

        if args.command == "generate-report":
            from human_simulator.audit.aggregates import profile_aggregates

            source_audit = connection_check(settings, engine)
            schema = discover_schema(engine)
            structure = profile_structure(engine, schema)
            aggregates = profile_aggregates(engine, structure)
            artifacts_dir = args.root / settings.artifacts_dir
            path = generate_report(
                artifacts_dir,
                {
                    "source_audit": source_audit,
                    "schema_discovery": schema,
                    "structure_profile": structure,
                    "aggregate_profile": aggregates,
                },
            )
            log.info("report_written", path=str(path))
            print(json.dumps({"report": str(path)}, indent=2))
            return 0

    finally:
        engine.dispose()

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
