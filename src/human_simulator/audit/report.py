"""Report generation and artifact persistence."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPORT_FILENAME = "stage-01-report.md"
REPORT_STATUS_DRAFT = "DRAFT"
REPORT_STATUS_FINAL = "FINAL"


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {**payload, "written_at": datetime.now(UTC).isoformat()}
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_draft_stage_01_report(artifacts_dir: Path) -> Path:
    """Create or refresh the Stage 01 report with DRAFT status."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / REPORT_FILENAME
    path.write_text(_render_stage_01_report(artifacts_dir, REPORT_STATUS_DRAFT), encoding="utf-8")
    return path


def finalize_stage_01_report(artifacts_dir: Path) -> Path:
    """Promote the Stage 01 report from DRAFT to FINAL."""
    path = artifacts_dir / REPORT_FILENAME
    path.write_text(_render_stage_01_report(artifacts_dir, REPORT_STATUS_FINAL), encoding="utf-8")
    return path


def read_report_status(artifacts_dir: Path) -> str | None:
    path = artifacts_dir / REPORT_FILENAME
    if not path.exists():
        return None
    match = re.search(r"\*\*Report status:\*\*\s*(\w+)", path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def generate_report(artifacts_dir: Path, bundle: dict[str, Any]) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    write_json(artifacts_dir / "source-audit.json", bundle["source_audit"])
    write_json(artifacts_dir / "schema-profile.json", bundle["schema_discovery"])
    write_json(artifacts_dir / "structure-profile.json", bundle["structure_profile"])
    write_json(artifacts_dir / "aggregate-profile.json", bundle["aggregate_profile"])

    report_path = artifacts_dir / REPORT_FILENAME
    report_path.write_text(_render_legacy_markdown(bundle), encoding="utf-8")
    return report_path


def _render_stage_01_report(artifacts_dir: Path, status: str) -> str:
    schema_profile = _load_json(artifacts_dir / "schema-profile.json")
    entity_candidates = _load_yaml(artifacts_dir / "entity-candidates.yaml")
    unknown_semantics = _read_text(artifacts_dir / "unknown-semantics.md")

    candidate_count = 0
    if entity_candidates and entity_candidates.get("entity_types"):
        candidate_count = sum(len(items) for items in entity_candidates["entity_types"].values())
    unknown_count = unknown_semantics.count("**UNKNOWN**") if unknown_semantics else 0

    lines = [
        "# Stage 01 Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        f"**Report status:** {status}",
        "",
        "## Source",
        "",
        f"- Database: `{schema_profile.get('database', 'unknown') if schema_profile else 'unknown'}`",
        f"- Relations profiled: **{schema_profile.get('relation_count', 0) if schema_profile else 0}**",
        f"- Columns profiled: **{schema_profile.get('column_count', 0) if schema_profile else 0}**",
        "",
        "## Entity candidates",
        "",
        f"- Candidate mappings: **{candidate_count}**",
        f"- Unknown relations documented: **{unknown_count}**",
        "",
        "## Artifacts",
        "",
        "- `source-audit.json`",
        "- `schema-profile.json`",
        "- `entity-candidates.yaml`",
        "- `relation-graph.md`",
        "- `unknown-semantics.md`",
        "- `profiling-query-log.json`",
        "- `verify-result.json`",
        "",
        "## Evidence",
        "",
        "Profiling query identifiers are recorded in `profiling-query-log.json` and `evidence/query-index.json`.",
        "",
        "## Unresolved questions",
        "",
        "_Review `unknown-semantics.md` and record any clinic-specific clarifications needed from a human reviewer._",
        "",
    ]
    if status == REPORT_STATUS_FINAL:
        lines.extend(
            [
                "## Gate status",
                "",
                "**PASS** — Stage 01 gate reached.",
                "",
            ]
        )
    return "\n".join(lines)


def _render_legacy_markdown(bundle: dict[str, Any]) -> str:
    source = bundle["source_audit"]
    schema = bundle["schema_discovery"]
    lines = [
        "# Stage 01 Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        f"**Report status:** {REPORT_STATUS_DRAFT}",
        "",
        "## Source audit",
        "",
        f"- Reachable: `{source.get('reachable')}`",
        f"- Database: `{source.get('database')}`",
        f"- Connection: `{source.get('redacted_url')}`",
        "",
        "## Schema discovery",
        "",
        f"- Tables discovered: **{schema.get('table_count', 0)}**",
        "",
        "## Evidence",
        "",
        "- Profiling results: `schema-profile.json`, `structure-profile.json`, `aggregate-profile.json`",
        "",
        "## Unresolved questions",
        "",
        "_None recorded._",
        "",
    ]
    return "\n".join(lines)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""
