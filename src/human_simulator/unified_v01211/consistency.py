"""Report consistency: read final report.md from disk (never from in-memory dict alone)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_STATUS_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|")


def statuses_from_report_md(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _STATUS_ROW.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _collect_status_values(doc: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in doc.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, str) and (
            k.endswith("_status")
            or k
            in (
                "status",
                "clinical_validation_status",
                "production_readiness",
                "security_stage_status",
                "post_pack_publication_verification",
            )
        ):
            out[key if prefix else k] = v
        elif isinstance(v, dict):
            out.update(_collect_status_values(v, key))
    return out


FORBIDDEN_FINAL_TOKENS = (
    "PENDING_PUBLISH",
    "NOT_RUN",
)


def detect_stale_publication_tokens(text: str) -> list[str]:
    """Flag stale lifecycle tokens that must not appear in finalized internal docs."""
    findings = []
    for tok in FORBIDDEN_FINAL_TOKENS:
        if tok in text:
            findings.append(tok)
    return findings


def assert_report_consistency_from_disk(
    art_dir: Path,
    *,
    finalized: bool = True,
) -> dict[str, Any]:
    """
    Read report.md / report.json / verification.json / release-verification.json from disk.
    Must run AFTER those files are written; never build from the source Python dict alone.
    """
    report_md_path = art_dir / "report.md"
    report_json_path = art_dir / "report.json"
    ver_path = art_dir / "verification.json"
    rel_path = art_dir / "release-verification.json"

    missing = [
        p.name
        for p in (report_md_path, report_json_path, ver_path, rel_path)
        if not p.is_file()
    ]
    if missing:
        return {
            "ok": False,
            "error": "consistency_check_before_finalization",
            "missing": missing,
            "consistency_check_premature": True,
        }

    md_text = report_md_path.read_text(encoding="utf-8")
    report_md = statuses_from_report_md(md_text)
    report_json = __import__("json").loads(report_json_path.read_text(encoding="utf-8"))
    verification = __import__("json").loads(ver_path.read_text(encoding="utf-8"))
    release = __import__("json").loads(rel_path.read_text(encoding="utf-8"))

    rj = report_json.get("statuses") or {}
    if not isinstance(rj, dict):
        rj = {}
    rj_flat = {k: str(v) for k, v in rj.items() if isinstance(v, str)}
    ver_flat = {
        k: str(v)
        for k, v in verification.items()
        if isinstance(v, str)
        and (k.endswith("_status") or k in ("production_readiness", "post_pack_publication_verification"))
    }
    rel_flat = {
        k: str(v)
        for k, v in release.items()
        if isinstance(v, str)
        and (k.endswith("_status") or k in ("production_readiness", "post_pack_publication_verification"))
    }

    mismatches: list[str] = []
    # report.md vs report.json statuses
    for k in sorted(set(report_md) | set(rj_flat)):
        if k in report_md and k in rj_flat and report_md[k] != rj_flat[k]:
            mismatches.append(f"report.md!=report.json:{k}:{report_md[k]}!={rj_flat[k]}")

    # verification vs release for shared keys
    for k in sorted(set(ver_flat) & set(rel_flat)):
        if ver_flat[k] != rel_flat[k]:
            mismatches.append(f"verification!=release:{k}:{ver_flat[k]}!={rel_flat[k]}")

    stale_md = detect_stale_publication_tokens(md_text) if finalized else []
    # Allow NOT_RUN only for cross_source_transfer / explicit non-execution contexts in md body
    # but not for post_publish_integrity / publication_integrity rows
    stale_status_rows = []
    for k, v in report_md.items():
        if k in (
            "post_publish_integrity_status",
            "publication_integrity_status",
            "pre_publish_verification_status",
        ) and v in ("PENDING_PUBLISH", "NOT_RUN"):
            stale_status_rows.append(f"{k}={v}")
        if k in (
            "content_verification_status",
            "pre_pack_manifest_status",
            "clean_staging_test_status",
        ) and v == "NOT_RUN":
            stale_status_rows.append(f"{k}={v}")

    # Internal docs must not claim post-pack PASS
    forbidden_internal_pass = []
    for surface, flat in (("report.md", report_md), ("verification", ver_flat), ("release", rel_flat)):
        if flat.get("publication_integrity_status") == "PASS":
            forbidden_internal_pass.append(f"{surface}:publication_integrity_status=PASS")
        if flat.get("post_publish_integrity_status") == "PASS":
            forbidden_internal_pass.append(f"{surface}:post_publish_integrity_status=PASS")

    ok = (
        not mismatches
        and not stale_status_rows
        and not forbidden_internal_pass
        and not (finalized and "PENDING_PUBLISH" in md_text)
    )
    return {
        "ok": ok,
        "source": "disk",
        "report_md_path": str(report_md_path),
        "mismatches": mismatches,
        "stale_status_rows": stale_status_rows,
        "forbidden_internal_post_pack_pass": forbidden_internal_pass,
        "pending_publish_in_final": "PENDING_PUBLISH" in md_text,
        "not_run_in_final_md": "NOT_RUN" in md_text,
        "report_md_status_count": len(report_md),
        "consistency_check_premature": False,
    }
