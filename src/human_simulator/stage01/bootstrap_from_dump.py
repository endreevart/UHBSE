"""Bootstrap preliminary Stage 01 schema-only artifacts from dump (not FINAL)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import yaml

from human_simulator.classify.entities import classify_clinical_entities
from human_simulator.stage01.dump_schema_profile import profile_schema_from_dump
from human_simulator.stage01.settings import MAGERYA_APPLICATION_SCHEMAS

PRELIMINARY_STATUS = "PRELIMINARY_SCHEMA_ONLY"
PRELIMINARY_DIR_NAME = "stage-01-preliminary"


def bootstrap_preliminary_from_dump(repo_root: Path, dump_path: Path | None = None) -> dict[str, object]:
    root = repo_root
    dump = dump_path or (root / "dumps" / "stage_magerya_api.dump")
    if not dump.exists():
        raise FileNotFoundError(f"Missing source A dump: {dump}")

    artifacts_dir = root / "artifacts" / PRELIMINARY_DIR_NAME
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    profile = profile_schema_from_dump(dump, database="magerya_api", source_id="magerya_api")
    (artifacts_dir / "schema-profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    classify_result = classify_clinical_entities(
        profile,
        artifacts_dir,
        application_schemas=MAGERYA_APPLICATION_SCHEMAS,
    )

    source_audit = {
        "reachable": False,
        "profiled_at": profile["profiled_at"],
        "source_id": "magerya_api",
        "database": "magerya_api",
        "redacted_url": "dump://stage_magerya_api.dump",
        "extraction_method": "offline_dump_schema_only",
        "readonly_user_only": False,
        "status": PRELIMINARY_STATUS,
        "note": "Not suitable for assess-source-relationship or compare gate without live profile",
    }
    (artifacts_dir / "source-audit.json").write_text(
        json.dumps(source_audit, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    evidence_dir = artifacts_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "query-index.json").write_text(
        json.dumps(
            {
                "note": "offline schema extract from dump; no live query evidence",
                "generated_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifacts_dir / "profiling-query-log.json").write_text(
        json.dumps({"queries": [], "offline_schema_extract": True}, indent=2) + "\n",
        encoding="utf-8",
    )

    report = {
        "title": "Stage 01 Preliminary Report (schema-only)",
        "generated_at": datetime.now(UTC).isoformat(),
        "report_status": PRELIMINARY_STATUS,
        "not_final": True,
        "relations": profile["relation_count"],
        "entity_candidates": sum(len(v) for v in classify_result.get("entity_types", {}).values()),
    }
    (artifacts_dir / "stage-01-preliminary-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "status": PRELIMINARY_STATUS,
        "relations": profile["relation_count"],
        "entity_candidates": sum(len(v) for v in classify_result.get("entity_types", {}).values()),
        "artifacts_dir": str(artifacts_dir),
    }


def bootstrap_stage01_from_dump(repo_root: Path, dump_path: Path | None = None) -> dict[str, object]:
    """Backward-compatible alias — always writes preliminary artifacts only."""
    return bootstrap_preliminary_from_dump(repo_root, dump_path)
