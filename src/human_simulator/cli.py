"""CLI entry points for Stage 01 audit."""

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


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    log = get_logger("audit.cli")

    parser = argparse.ArgumentParser(prog="audit", description="UHBSE Stage 01 database audit")
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

    args = parser.parse_args(argv)
    settings = AuditSettings.from_repo(args.root)

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
