"""Public privacy scan."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_DIRECT = frozenset({"email", "phone", "full_name", "patient_id", "user_id", "address", "passport", "insurance_id"})
_BANNED_KEYS = frozenset(
    {
        "ids",
        "medicine_ref_id",
        "medicine_id",
        "source_scoped_subject_id",
        "target_id",
        "state_id",
        "t0_id",
        "residual_blocks",
        "history_values_json",
        "effective_overlap_group_id",
        "panel_id",
        "history_values",
        "ecdf",
        "chol",
        "rows",
        "paths",
        "p1_payload",
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
    jsonl = []
    for path in sorted(art.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(art).as_posix()
        if "/private/" in f"/{rel}" or rel.startswith("private/"):
            private_paths.append(rel)
        if path.suffix.lower() == ".parquet":
            parquet.append(rel)
        if path.suffix.lower() == ".jsonl":
            jsonl.append(rel)
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
            if leaf in _DIRECT and isinstance(v, str) and v:
                hits.append({"file": rel, "kind": leaf, "path": p})
            if leaf in _BANNED_KEYS and isinstance(v, (list, dict)) and v:
                if leaf == "paths" and isinstance(v, list) and v and isinstance(v[0], list):
                    hits.append({"file": rel, "kind": "banned_key:paths", "path": p})
                elif leaf != "paths":
                    hits.append({"file": rel, "kind": f"banned_key:{leaf}", "path": p})
    ok = not hits and not private_paths and not parquet and not jsonl
    return {
        "ok": ok,
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY" if ok else "FAIL",
        "hits": hits[:40],
        "private_paths": private_paths,
        "parquet": parquet,
        "jsonl": jsonl,
    }
