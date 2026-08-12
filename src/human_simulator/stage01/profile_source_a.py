"""Profile Source A (magerya_api) via read-only mg_audit_ro."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.audit.connection import connection_check
from human_simulator.audit.postgres_profile import profile_postgres_source
from human_simulator.audit.report import write_draft_stage_01_report
from human_simulator.audit.verify import verify_stage_01
from human_simulator.classify.entities import classify_clinical_entities
from human_simulator.config.policy import ProfilingPolicy
from human_simulator.config.settings import AuditSettings
from human_simulator.db.session import create_audit_engine
from human_simulator.stage01.create_audit_role import create_mg_audit_role
from human_simulator.stage01.manifest import verify_manifest, write_manifest
from human_simulator.stage01.settings import MAGERYA_APPLICATION_SCHEMAS, MG_AUDIT_USER, MgAuditSettings
from human_simulator.stage02.schema_fingerprint import compare_source_a_fingerprint


def _audit_settings_for_profiling(mg: MgAuditSettings) -> AuditSettings:
    password = mg.audit_password.get_secret_value()
    if not password:
        raise RuntimeError("MG_AUDIT_PASSWORD missing; run create_mg_audit_role first")
    return AuditSettings(
        pg_host=mg.pg_host,
        pg_port=mg.pg_port,
        pg_database=mg.pg_database,
        pg_user=mg.audit_user,
        pg_password=mg.audit_password,
        repo_root=mg.repo_root,
        artifacts_dir=mg.artifacts_dir,
    )


def profile_source_a(repo_root: Path) -> dict[str, Any]:
    mg = MgAuditSettings.from_repo(repo_root)
    if mg.audit_user != MG_AUDIT_USER:
        raise RuntimeError(f"profiling must use audit user {MG_AUDIT_USER!r}, got {mg.audit_user!r}")

    role_info = create_mg_audit_role(mg)
    mg = MgAuditSettings.from_repo(repo_root)
    settings = _audit_settings_for_profiling(mg)
    policy = replace(ProfilingPolicy.from_repo(repo_root), artifacts_dir=Path("artifacts/stage-01"))
    engine = create_audit_engine(settings, url=settings.sqlalchemy_url)

    try:
        profile = profile_postgres_source(settings, engine, policy)
        conn = connection_check(settings, engine)
    finally:
        engine.dispose()

    artifacts_dir = repo_root / policy.artifacts_dir
    classify_result = classify_clinical_entities(
        profile,
        artifacts_dir,
        application_schemas=MAGERYA_APPLICATION_SCHEMAS,
    )

    fingerprint_compare = compare_source_a_fingerprint(repo_root)

    source_audit = {
        **conn,
        "profiled_at": profile.get("profiled_at"),
        "source_id": "magerya_api",
        "database": mg.pg_database,
        "connection_user": mg.audit_user,
        "redacted_url": mg.audit_redacted_url,
        "readonly_user_only": True,
        "extraction_method": "live_readonly_profile",
        "audit_role": role_info,
        "schema_fingerprint_check": fingerprint_compare,
    }
    (artifacts_dir / "source-audit.json").write_text(
        json.dumps(source_audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    write_draft_stage_01_report(artifacts_dir)
    verify_result = verify_stage_01(repo_root, artifacts_dir=artifacts_dir, run_tests=True)
    manifest_hashes = write_manifest(artifacts_dir)
    manifest_ok, manifest_detail = verify_manifest(artifacts_dir)

    return {
        "source_id": "magerya_api",
        "connection_user": mg.audit_user,
        "status": verify_result["status"],
        "verify_status": verify_result["status"],
        "manifest_ok": manifest_ok,
        "manifest_detail": manifest_detail,
        "schema_fingerprint_match": fingerprint_compare.get("fingerprints_match"),
        "relation_count": profile.get("relation_count"),
        "entity_candidates": sum(len(v) for v in classify_result.get("entity_types", {}).values()),
        "artifact_hashes": manifest_hashes,
        "artifacts": [str(artifacts_dir / name) for name in manifest_hashes],
    }
