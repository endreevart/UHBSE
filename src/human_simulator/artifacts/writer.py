"""Artifact writers for stage deliverables."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def artifacts_dir(repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    return root / "artifacts" / "stage-01"


def write_json(name: str, payload: dict[str, Any], repo_root: Path | None = None) -> Path:
    out_dir = artifacts_dir(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    body = {**payload, "written_at": datetime.now(UTC).isoformat()}
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_evidence_sql(slug: str, sql: str, repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    evidence_dir = root / "artifacts" / "stage-01" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{slug}.sql"
    path.write_text(sql.strip() + "\n", encoding="utf-8")
    return path
