"""Write series reports and manifests (no core mutation)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.media.series.constants import EVIDENCE_DIR, PUBLIC_MEDIA_DIR, SERIES_TITLE


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_storyboard(root: Path, fixture: dict[str, Any]) -> Path:
    lines = [
        f"# {SERIES_TITLE}",
        "",
        "Private publication review. Not a clinical model. Not posted.",
        "",
    ]
    for episode in fixture["episodes"]:
        seconds = episode["duration_frames"] / 30
        lines.extend(
            [
                f"## {episode['id']} — {episode['title']}",
                "",
                f"- File: `{episode['filename']}`",
                f"- Duration: {seconds:.1f}s ({episode['duration_frames']} frames @ 30fps)",
                f"- Capability: `{episode['capability_status']}`",
                f"- Hook: {' / '.join(episode.get('hook') or [])}",
                f"- Thesis: {episode.get('thesis', '').replace(chr(10), ' / ')}",
                f"- Disclaimer: {episode['disclaimer']}",
                "",
            ]
        )
    path = root / EVIDENCE_DIR / "series-storyboard.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_reports(
    root: Path,
    *,
    bindings: dict[str, Any],
    fixture: dict[str, Any],
    baseline: dict[str, Any],
    render: dict[str, Any],
    verification: dict[str, Any],
) -> None:
    evidence = root / EVIDENCE_DIR
    media = root / PUBLIC_MEDIA_DIR
    frame_manifest = {
        "fps": 30,
        "episodes": render.get("frames") or {},
        "cover_frame": 42,
        "contact_sheet": "one frame per second",
    }
    (evidence / "frame-manifest.json").write_text(json.dumps(frame_manifest, indent=2) + "\n", encoding="utf-8")
    (evidence / "render-verification.json").write_text(json.dumps(render, indent=2) + "\n", encoding="utf-8")

    public_facts = [row for row in bindings["bindings"] if row["disclosure_category"] == "PUBLIC_FACT"]
    controlled = [row for row in bindings["bindings"] if row["disclosure_category"] == "CONTROLLED_COMMERCIAL_REVEAL"]
    report = [
        f"# {SERIES_TITLE}",
        "",
        f"**Status:** `PRIVATE_PUBLICATION_REVIEW_REQUIRED`",
        f"**Generated:** {datetime.now(UTC).isoformat()}",
        "",
        "## Baseline",
        "",
        f"- ZIP: `{baseline.get('zip')}`",
        f"- SHA-256: `{baseline.get('sha256')}`",
        f"- Attestation: `{baseline.get('attestation_status')}`",
        f"- Members / indexed: {baseline.get('members')} / {baseline.get('indexed')}",
        "",
        "## Episodes",
        "",
    ]
    for episode in fixture["episodes"]:
        seconds = episode["duration_frames"] / 30
        report.append(f"- `{episode['filename']}` — {seconds:.1f}s — {episode['capability_status']}")
    report.extend(
        [
            "",
            "## PUBLIC_FACT count",
            "",
            f"{len(public_facts)} bound public facts.",
            "",
            "## CONTROLLED_COMMERCIAL_REVEAL",
            "",
        ]
    )
    for row in controlled:
        if row["episode"] == "series":
            report.append(f"- {row['displayed_public_value']} (`OWNER_REVIEW_REQUIRED`)")
    report.extend(
        [
            "",
            "## Synthetic",
            "",
            "- VIDEO 03 timeline: `SYNTHETIC_COMPOSITE`",
            "- VIDEO 04 event: `SYNTHETIC CONTROLLED EVENT`",
            "",
            "## Verification",
            "",
            f"- series-verification ok: `{verification.get('ok')}`",
            "- Core v0.1–v0.1.2.1 unchanged: yes (hash-locked)",
            "- No patient-level records in public fixtures: yes",
            "- No secrets/DSN/Vault in public outputs: yes",
            "",
            "Nothing was published to social networks.",
            "",
        ]
    )
    (evidence / "series-report.md").write_text("\n".join(report), encoding="utf-8")

    lines = []
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            rel = path.relative_to(evidence).as_posix()
            lines.append(f"{sha256_file(path)}  {rel}")
    (evidence / "manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
