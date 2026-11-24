"""Privacy scans for public artifacts + private state plane."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.unified_individual_state_v01.policy import (
    OVERLAP_DIR,
    STATES_DIR,
    VERSION,
)

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_DIRECT_KEYS = frozenset(
    {
        "email",
        "phone",
        "full_name",
        "patient_id",
        "user_id",
        "address",
        "passport",
    }
)
_FORBIDDEN_COLS = frozenset(
    {
        "email",
        "phone",
        "first_name",
        "last_name",
        "path",
        "description",
        "patient_id",
        "user_id",
    }
)


def _walk(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            out.append((p, v))
            out.extend(_walk(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_walk(v, f"{path}[{i}]"))
    return out


def scan_public(art: Path) -> dict[str, Any]:
    hits = []
    private_paths = []
    parquet = []
    for path in sorted(art.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(art).as_posix()
        if "/private/" in f"/{rel}" or rel.startswith("private/"):
            private_paths.append(rel)
        if path.suffix.lower() == ".parquet":
            parquet.append(rel)
        if path.suffix.lower() != ".json":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _EMAIL_RE.search(text):
            hits.append({"file": rel, "kind": "email"})
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            continue
        for p, v in _walk(doc):
            leaf = p.split(".")[-1].split("[")[0]
            if leaf in _DIRECT_KEYS and isinstance(v, str) and v:
                hits.append({"file": rel, "path": p})
    ok = not hits and not private_paths and not parquet
    return {
        "version": VERSION,
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY" if ok else "FAIL",
        "PRIVACY_BOUNDARY_STATUS": "PASS" if ok else "FAIL",
        "hits": hits[:20],
        "private_paths": private_paths,
        "parquet_in_public": parquet,
        "ok": ok,
    }


def scan_private_plane(root: Path) -> dict[str, Any]:
    findings = []
    files = 0
    for base in (root / STATES_DIR, root / OVERLAP_DIR):
        for path in base.glob("*.parquet"):
            files += 1
            names = [f.name.lower() for f in pq.read_schema(path)]
            for n in names:
                if n in _FORBIDDEN_COLS:
                    findings.append({"file": path.name, "column": n})
    ok = files > 0 and not findings
    return {
        "version": VERSION,
        "PRIVATE_RESEARCH_PLANE_STATUS": "PASS" if ok else "FAIL",
        "STATE_PRIVACY_STATUS": "PASS" if ok else "FAIL",
        "files_scanned": files,
        "findings": findings,
        "ok": ok,
    }
