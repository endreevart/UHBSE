"""Profiling policy loaded from config/profiling-policy.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ProfilingPolicy:
    forbidden_operations: tuple[str, ...]
    max_rows_sample: int
    max_tables: int | None
    sensitive_column_patterns: tuple[re.Pattern[str], ...]
    artifacts_dir: Path
    evidence_dir: Path

    @classmethod
    def from_repo(cls, repo_root: Path | None = None) -> ProfilingPolicy:
        root = repo_root or Path.cwd()
        path = root / "config" / "profiling-policy.yaml"
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

        limits = data.get("limits", {})
        pii = data.get("pii", {})
        output = data.get("output", {})
        patterns = tuple(
            re.compile(p, re.IGNORECASE) for p in pii.get("never_sample_columns_matching", [])
        )
        return cls(
            forbidden_operations=tuple(data.get("forbidden_operations", [])),
            max_rows_sample=int(limits.get("max_rows_sample", 1000)),
            max_tables=limits.get("max_tables"),
            sensitive_column_patterns=patterns,
            artifacts_dir=Path(output.get("artifacts_dir", "artifacts/stage-01")),
            evidence_dir=Path(output.get("evidence_dir", "artifacts/stage-01/evidence")),
        )

    def is_sensitive_column(self, column_name: str) -> bool:
        return any(pattern.search(column_name) for pattern in self.sensitive_column_patterns)
