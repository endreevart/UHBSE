"""Profile source B using read-only audit user kgz_audit_ro."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.audit.postgres_profile import profile_postgres_source
from human_simulator.stage02.classify_second_source import build_source_b_audit, finalize_source_b_audit, _rename_stage02_artifacts
from human_simulator.classify.entities import classify_clinical_entities
from human_simulator.config.policy import ProfilingPolicy
from human_simulator.config.settings import AuditSettings
from human_simulator.db.session import create_audit_engine
from human_simulator.stage02.settings import KgzRestoreSettings


def _audit_settings_for_profiling(kgz: KgzRestoreSettings) -> AuditSettings:
    password = kgz.audit_password.get_secret_value()
    if not password:
        raise RuntimeError("KGZ_AUDIT_PASSWORD missing in db-kgz.env")
    return AuditSettings(
        pg_host=kgz.pg_host,
        pg_port=kgz.pg_port,
        pg_database=kgz.pg_database,
        pg_user=kgz.audit_user,
        pg_password=kgz.audit_password,
        repo_root=kgz.repo_root,
        artifacts_dir=kgz.artifacts_dir,
    )


def _stage02_policy(repo_root: Path) -> ProfilingPolicy:
    base = ProfilingPolicy.from_repo(repo_root)
    return replace(
        base,
        artifacts_dir=Path("artifacts/stage-02"),
        evidence_dir=Path("artifacts/stage-02/evidence"),
    )


def _rename_profile_artifact(artifacts_dir: Path) -> None:
    src = artifacts_dir / "schema-profile.json"
    dst = artifacts_dir / "schema-profile-kgz.json"
    if src.exists():
        if dst.exists():
            dst.unlink()
        shutil.move(str(src), str(dst))


def profile_second_source(repo_root: Path) -> dict[str, Any]:
    kgz = KgzRestoreSettings.from_repo(repo_root)
    if kgz.audit_user != "kgz_audit_ro":
        raise RuntimeError(f"profiling must use audit user kgz_audit_ro, got {kgz.audit_user!r}")

    settings = _audit_settings_for_profiling(kgz)
    policy = _stage02_policy(repo_root)
    engine = create_audit_engine(settings, url=settings.sqlalchemy_url)

    try:
        profile = profile_postgres_source(settings, engine, policy)
    finally:
        engine.dispose()

    artifacts_dir = repo_root / policy.artifacts_dir
    profile_path = artifacts_dir / "schema-profile.json"
    if profile_path.exists():
        import json as json_mod

        data = json_mod.loads(profile_path.read_text(encoding="utf-8"))
        data["source_id"] = "kgz"
        profile_path.write_text(json_mod.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    profile_path = artifacts_dir / "schema-profile.json"
    with profile_path.open(encoding="utf-8") as handle:
        schema_profile = json.load(handle)
    classify_result = classify_clinical_entities(schema_profile, artifacts_dir)
    _rename_profile_artifact(artifacts_dir)
    _rename_stage02_artifacts(artifacts_dir)

    profile_path = artifacts_dir / "schema-profile-kgz.json"
    classify_result["profiled_at"] = datetime.now(UTC).isoformat()
    source_audit = build_source_b_audit(
        repo_root,
        classify_result,
        profile_path=profile_path,
    )
    source_audit = finalize_source_b_audit(repo_root, source_audit)

    return {
        "source_id": "kgz",
        "status": source_audit["status"],
        "connection_user": kgz.audit_user,
        "redacted_url": kgz.audit_redacted_url,
        "relation_count": profile.get("relation_count"),
        "column_count": profile.get("column_count"),
        "entity_candidates": sum(len(v) for v in classify_result.get("entity_types", {}).values()),
        "checks_passed": sum(1 for check in source_audit["checks"] if check["status"] == "PASS"),
        "checks_total": len(source_audit["checks"]),
        "artifacts": [
            str(artifacts_dir / "schema-profile-kgz.json"),
            str(artifacts_dir / "entity-candidates-kgz.yaml"),
            str(artifacts_dir / "relation-graph-kgz.md"),
            str(artifacts_dir / "unknown-semantics-kgz.md"),
            str(artifacts_dir / "source-b-audit.json"),
        ],
    }
