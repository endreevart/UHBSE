"""Scan media outputs for leaked identifiers, timestamps, and secrets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from human_simulator.media.paths import EMAIL, HEX64, ISO_TS, PATIENT_ID, POSTGRES_URI, out_dir

_TEXT_SUFFIXES = {".json", ".txt", ".md", ".yaml", ".yml", ".csv", ".svg"}
_PATTERNS = (
    re.compile(HEX64),
    re.compile(ISO_TS),
    re.compile(POSTGRES_URI),
    re.compile(PATIENT_ID),
    re.compile(EMAIL),
    re.compile(r"(?i)\bhvs\."),
    re.compile(r"(?i)\"password\"\s*:"),
)


def scan_tree(path: Path) -> dict[str, Any]:
    hits: list[str] = []
    files: list[str] = []
    if not path.exists():
        return {"ok": False, "hits": [f"missing:{path}"], "files": []}
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        files.append(str(item.relative_to(path)))
        if item.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        text = item.read_text(encoding="utf-8", errors="replace")
        for pat in _PATTERNS:
            if pat.search(text):
                hits.append(f"{item.name}:{pat.pattern}")
    return {"ok": len(hits) == 0, "hits": hits, "files": files}


def verify_media(root: Path) -> dict[str, Any]:
    target = out_dir(root)
    scan = scan_tree(target)
    videos = [f for f in scan["files"] if f.endswith(".mp4")]
    stills = [f for f in scan["files"] if f.endswith(".png")]
    captions = [f for f in scan["files"] if f.endswith("caption.txt")]
    report = {
        "ok": scan["ok"] and len(stills) >= 1 and len(captions) >= 1,
        "out_dir": str(target),
        "videos": videos,
        "stills": stills,
        "captions": captions,
        "hits": scan["hits"],
        "files": scan["files"],
    }
    (target / "verify.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
