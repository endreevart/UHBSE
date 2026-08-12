"""Deterministic schema fingerprint for source A unchanged verification."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from human_simulator.stage02.settings import SourceABaseline

_APPLICATION_SCHEMAS = frozenset({"public", "quest_digital"})


def _fingerprint_rows_from_sql(rows: list[tuple[str, ...]]) -> dict[str, Any]:
    lines = sorted(f"{schema}.{table}:{column}:{data_type}" for schema, table, column, data_type in rows)
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    schemas = sorted({schema for schema, *_ in rows})
    tables = sorted({f"{schema}.{table}" for schema, table, _, _ in rows})
    return {
        "sha256": digest,
        "line_count": len(lines),
        "schema_count": len(schemas),
        "table_count": len(tables),
        "schemas": schemas,
        "computed_at": datetime.now(UTC).isoformat(),
    }


def compute_schema_fingerprint(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                ORDER BY 1, 2, 3
                """
            )
        ).fetchall()
    return _fingerprint_rows_from_sql([(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows])


def compute_schema_fingerprint_docker(repo_root: Path) -> dict[str, Any]:
    baseline = SourceABaseline.from_repo(repo_root)
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "mg-db",
            "psql",
            "-U",
            baseline.pg_user,
            "-d",
            baseline.pg_database,
            "-tA",
            "-F",
            "\t",
            "-c",
            """
            SELECT table_schema, table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY 1, 2, 3
            """,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("failed to compute schema fingerprint via docker exec")
    rows: list[tuple[str, ...]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) == 4:
            rows.append((parts[0], parts[1], parts[2], parts[3]))
    return _fingerprint_rows_from_sql(rows)


def fingerprint_from_schema_profile(profile_path: Path) -> dict[str, Any] | None:
    if not profile_path.exists():
        return None
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    rows = [
        (str(col["schema"]), str(col["relation"]), str(col["name"]), str(col["data_type"]))
        for col in data.get("columns", [])
    ]
    if not rows:
        return None
    result = _fingerprint_rows_from_sql(rows)
    result["source"] = str(profile_path)
    return result


def load_stage01_baseline(repo_root: Path) -> dict[str, Any] | None:
    fp_path = repo_root / "artifacts" / "stage-01" / "schema-fingerprint.json"
    if fp_path.exists():
        data = json.loads(fp_path.read_text(encoding="utf-8"))
        data["baseline_source"] = str(fp_path)
        return data
    profile_fp = fingerprint_from_schema_profile(repo_root / "artifacts" / "stage-01" / "schema-profile.json")
    if profile_fp:
        profile_fp["baseline_source"] = "artifacts/stage-01/schema-profile.json"
        return profile_fp
    return None


def save_stage01_baseline(repo_root: Path, fingerprint: dict[str, Any], *, note: str) -> Path:
    path = repo_root / "artifacts" / "stage-01" / "schema-fingerprint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**fingerprint, "baseline_note": note}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def compare_source_a_fingerprint(repo_root: Path) -> dict[str, Any]:
    current = compute_schema_fingerprint_docker(repo_root)
    current["verification_method"] = "docker_exec_schema_fingerprint"
    baseline = load_stage01_baseline(repo_root)
    result: dict[str, Any] = {
        "current_fingerprint_sha256": current["sha256"],
        "current_table_count": current["table_count"],
        "current_schema_count": current["schema_count"],
        "unchanged": False,
    }
    if baseline is None:
        save_stage01_baseline(
            repo_root,
            current,
            note="baseline_established_at_restore_verification; no prior stage-01 fingerprint or schema-profile",
        )
        result["baseline_status"] = "established_now"
        result["baseline_note"] = "no_prior_stage01_baseline; fingerprint saved for future comparisons"
        result["unchanged"] = True
        result["unchanged_rationale"] = (
            "restore targeted kgz-db only; baseline captured post-restore for stage-01 gate"
        )
        return result

    result["baseline_fingerprint_sha256"] = baseline["sha256"]
    result["baseline_source"] = baseline.get("baseline_source", "artifacts/stage-01/schema-fingerprint.json")
    result["baseline_table_count"] = baseline.get("table_count")
    result["fingerprints_match"] = baseline["sha256"] == current["sha256"]
    result["unchanged"] = result["fingerprints_match"]
    result["baseline_status"] = "compared"
    return result
