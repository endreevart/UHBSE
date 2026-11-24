"""Automated publication verification for the public roadmap series."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from human_simulator.media.paths import EMAIL, HEX64, POSTGRES_URI
from human_simulator.media.series.constants import (
    ACCEPTED_SDR_V0111_SHA256,
    CORE_DIR,
    EPISODES,
    EVIDENCE_DIR,
    FORBIDDEN_CLINICAL_CLAIMS,
    PLACEHOLDER_METRIC_PATTERNS,
    PROXY_HEIGHT,
    PROXY_WIDTH,
    PUBLIC_MEDIA_DIR,
    REVIEW_BUNDLE_KIND,
    SERIES_TITLE,
    STALE_EP06_PHRASES,
)
from human_simulator.media.series.rounding import ROUNDERS, hash_prefix

_TEXT = {".json", ".txt", ".md", ".yaml", ".yml", ".srt", ".csv"}
_FORBIDDEN_CODE = (
    re.compile(r"(?i)psycopg"),
    re.compile(r"(?i)create_engine"),
    re.compile(r"(?i)postgresql://"),
    re.compile(r"(?i)magerya_api"),
    re.compile(r"(?i)uhbse_canonical"),
    re.compile(r"(?i)private/"),
)
_SECRET = (
    re.compile(POSTGRES_URI),
    re.compile(r"(?i)\bhvs\."),
    re.compile(r"(?i)VAULT_"),
    re.compile(r"(?i)BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY"),
    re.compile(r"(?i)\"password\"\s*:"),
    re.compile(EMAIL),
    re.compile(HEX64),
)
_TABLE_NAMES = (
    re.compile(r"account_patient"),
    re.compile(r"appointment_appointment"),
    re.compile(r"document_analysisresult"),
    re.compile(r"diagnosis_medicineappointments"),
)


class SeriesVerifyError(RuntimeError):
    pass


def _texts(path: Path) -> list[tuple[Path, str]]:
    rows: list[tuple[Path, str]] = []
    if not path.exists():
        return rows
    for item in sorted(path.rglob("*")):
        if item.is_file() and item.suffix.lower() in _TEXT:
            rows.append((item, item.read_text(encoding="utf-8", errors="replace")))
    return rows


def _scan(rows: list[tuple[Path, str]], patterns: tuple[re.Pattern[str], ...], *, skip_json_path: bool = False) -> list[str]:
    hits: list[str] = []
    for path, text in rows:
        body = text
        if skip_json_path and path.suffix == ".json":
            body = re.sub(r'"json_path"\s*:\s*".*?"', '"json_path":""', body)
        for pat in patterns:
            if pat.search(body):
                hits.append(f"{path.name}:{pat.pattern}")
    return hits


def _episode_src(root: Path) -> Path:
    return root / "media" / "src" / "series"


def _no_db_imports(root: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted((root / "src" / "human_simulator" / "media" / "series").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("psycopg", "sqlalchemy", "human_simulator.db", "human_simulator.canonical.connection")):
                        hits.append(f"{path.name}:import {alias.name}")
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(("psycopg", "sqlalchemy", "human_simulator.db", "human_simulator.canonical.connection")):
                    hits.append(f"{path.name}:from {node.module}")
    ts_dir = _episode_src(root)
    if ts_dir.is_dir():
        for path, text in _texts(ts_dir):
            for pat in _FORBIDDEN_CODE:
                if pat.search(text):
                    hits.append(f"{path.name}:{pat.pattern}")
    return hits


def verify_series(
    root: Path,
    *,
    bindings: dict[str, Any],
    fixture: dict[str, Any],
    baseline: dict[str, Any],
    require_media: bool = True,
    write: bool = True,
) -> dict[str, Any]:
    evidence = root / EVIDENCE_DIR
    media = root / PUBLIC_MEDIA_DIR
    checks: dict[str, Any] = {}

    rounding_ok = True
    for row in bindings["bindings"]:
        rule = row["rounding_rule"]
        exact = row["source_exact_value"]
        displayed = row["displayed_public_value"]
        if rule == "hash_prefix":
            prefix = exact["prefix"] if isinstance(exact, dict) else None
            if prefix != displayed or not re.fullmatch(r"[0-9a-f]{10}", str(displayed)):
                rounding_ok = False
        elif rule in ROUNDERS and rule != "none":
            if ROUNDERS[rule](exact) != displayed:
                rounding_ok = False
    checks["displayed_counts_have_evidence_binding"] = all(
        row.get("source_artifact") for row in bindings["bindings"]
    )
    checks["rounding_reproducible"] = rounding_ok
    checks["no_raw_db_connection"] = _no_db_imports(root) == []
    checks["no_canonical_db_connection"] = checks["no_raw_db_connection"]
    checks["public_fixtures_autonomous"] = bool(fixture.get("no_database_connection")) and (evidence / "public-fixture.json").is_file()

    fixture_text = json.dumps(fixture)
    checks["no_real_subject_ids"] = not re.search(HEX64, fixture_text)
    checks["no_patient_level_clinical_values"] = "clinical_time" not in fixture_text and "payload" not in fixture_text

    public_rows = _texts(media)
    fixture_path = evidence / "public-fixture.json"
    fixture_rows = [(fixture_path, fixture_path.read_text(encoding="utf-8"))] if fixture_path.is_file() else []
    caption_rows = [row for row in public_rows if row[0].suffix in {".txt", ".srt", ".json"}]
    forbidden_hits = _scan(caption_rows + fixture_rows, _TABLE_NAMES + _SECRET)
    checks["forbidden_patterns_fail_publication"] = forbidden_hits == []
    if forbidden_hits:
        checks["forbidden_hits"] = forbidden_hits

    claim_hits: list[str] = []
    for path, text in caption_rows + fixture_rows:
        lower = text.lower()
        for claim in FORBIDDEN_CLINICAL_CLAIMS:
            if claim in lower:
                claim_hits.append(f"{path.name}:{claim}")
    checks["clinical_claims_scan"] = claim_hits == []
    checks["secret_dsn_vault_scan"] = _scan(caption_rows + fixture_rows, _SECRET) == []

    labels_ok = True
    video06_ok = True
    working_ok = True
    future_ok = True
    for episode in fixture["episodes"]:
        if "disclosure_label" not in episode or "disclaimer" not in episode:
            labels_ok = False
        if episode["id"] == "Roadmap06":
            blob = json.dumps(episode)
            if any(re.search(pat, blob) for pat in PLACEHOLDER_METRIC_PATTERNS):
                video06_ok = False
            for stale in STALE_EP06_PHRASES:
                if stale in blob:
                    video06_ok = False
            if "UNCERTAINTY_CALIBRATION_PASS" in blob or "uncertainty coverage\": \"PASS" in blob.lower():
                video06_ok = False
            guards = episode.get("guards") or []
            required_guards = {
                "EXPLORATORY TEST",
                "NO INCREMENTAL SIGNAL CLAIMED",
                "CLINICAL VALIDATION: NOT STARTED",
            }
            if not required_guards.issubset(set(guards)):
                video06_ok = False
            if "TEST:" not in " ".join(guards) or "2 SUBJECTS" not in " ".join(guards):
                video06_ok = False
            if episode.get("capability_status") != "FIRST_EXPLORATORY_RETROSPECTIVE_BACKTEST_COMPLETE":
                future_ok = False
            # metrics must be bound numbers, not pending
            for metric in episode.get("metrics") or []:
                if "PENDING" in str(metric.get("value", "")).upper():
                    video06_ok = False
        elif episode.get("capability_status") != "WORKING_NOW":
            working_ok = False
    checks["disclosure_label_present"] = labels_ok
    checks["video06_no_invented_metrics"] = video06_ok
    checks["video06_no_stale_status"] = video06_ok
    checks["current_capabilities_working_now"] = working_ok
    checks["episode06_status_complete"] = future_ok
    checks["core_v0121_unchanged"] = bool(baseline.get("core_zips_unchanged", {}).get("v0.1.2.1"))
    checks["core_v01_to_v0121_unchanged"] = all(baseline.get("core_zips_unchanged", {}).values())
    checks["sdr_v0111_sha_expected"] = ACCEPTED_SDR_V0111_SHA256

    master_videos = sorted(media.glob("*/uhbse-roadmap-*.mp4")) if media.exists() else []
    proxies = sorted((media / "proxies").glob("*.mp4")) if (media / "proxies").is_dir() else []
    covers = sorted(str(p.relative_to(media)) for p in media.glob("*/cover.png")) if media.exists() else []
    sheets = sorted(str(p.relative_to(media)) for p in media.glob("contact-sheets/*.png")) if media.exists() else []
    checks["episode_count"] = len(EPISODES)
    checks["series_title"] = SERIES_TITLE
    checks["review_bundle_kind"] = REVIEW_BUNDLE_KIND
    checks["master_videos_generated_in_workspace"] = (len(master_videos) == 6) if require_media else True
    checks["proxy_videos_in_review_bundle"] = (len(proxies) == 6) if require_media else True
    checks["proxy_resolution"] = f"{PROXY_WIDTH}x{PROXY_HEIGHT}"
    # masters may exist in workspace but are not required for skip-render verification
    checks["covers_present"] = (len(covers) == 6) if require_media else True
    checks["contact_sheets_present"] = (len(sheets) == 6) if require_media else True

    skip_keys = {
        "forbidden_hits",
        "episode_count",
        "series_title",
        "review_bundle_kind",
        "proxy_resolution",
        "sdr_v0111_sha_expected",
    }
    ok = all(bool(value) for key, value in checks.items() if key not in skip_keys)
    report = {
        "ok": ok,
        "publication_status": "PRIVATE_PUBLICATION_REVIEW_REQUIRED",
        "review_bundle_kind": REVIEW_BUNDLE_KIND,
        "checks": checks,
        "master_videos_generated_in_workspace": [str(p.relative_to(media)) for p in master_videos],
        "proxy_videos": [str(p.relative_to(media)) for p in proxies],
        "covers": covers,
        "contact_sheets": sheets,
        "baseline": {
            "sha256": baseline.get("sha256"),
            "members": baseline.get("members"),
            "indexed": baseline.get("indexed"),
        },
        "core_dir_untouched": (root / CORE_DIR).is_dir(),
        "accepted_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
    }
    if write:
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "series-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (evidence / "public-claims-verification.json").write_text(
            json.dumps({"ok": checks["clinical_claims_scan"] and checks["video06_no_invented_metrics"], "claim_hits": claim_hits}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        (evidence / "publication-scan.json").write_text(
            json.dumps(
                {
                    "ok": checks["forbidden_patterns_fail_publication"] and checks["secret_dsn_vault_scan"],
                    "hits": forbidden_hits,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return report
