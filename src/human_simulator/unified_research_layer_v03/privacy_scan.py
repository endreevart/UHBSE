"""Public artifact privacy scanner — full-array walk (no [:200] truncation)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v03.policy import VERSION

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_SENSITIVE_COL_RE = re.compile(
    r"(first_name|last_name|patronymic|phone|email|address|passport|"
    r"birth_?date|patient_id|subject_id|source_subject|opaque_subject|"
    r"research_subject)",
    re.I,
)
_HASH_ARRAY_KEYS = frozenset(
    {
        "sample_category_hashes",
        "row_derived_hashes",
        "value_hashes",
        "category_hashes",
        "example_hashes",
    }
)
_DIRECT_ID_KEYS = frozenset(
    {
        "source_subject_id",
        "patient_id",
        "research_subject_id",
        "opaque_subject_key",
        "full_name",
        "email",
        "phone",
        "address",
        "source_subject_key",
    }
)


def _walk(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    """Walk entire structure — NEVER truncate arrays at 200."""
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            out.append((p, v))
            out.extend(_walk(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):  # full array
            out.extend(_walk(v, f"{path}[{i}]"))
    return out


def scan_public_artifacts(art: Path) -> dict[str, Any]:
    direct_hits: list[dict[str, Any]] = []
    hashed_hits: list[dict[str, Any]] = []
    low_entropy: list[dict[str, Any]] = []
    row_derived: list[dict[str, Any]] = []
    sensitive: list[dict[str, Any]] = []
    private_paths: list[dict[str, Any]] = []
    unstructured: list[dict[str, Any]] = []

    for path in sorted(art.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(art).as_posix()
        if "private/" in rel or rel.startswith("private"):
            private_paths.append({"file": rel})
        if path.suffix.lower() != ".json":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            continue
        for p, v in _walk(doc):
            leaf = p.split(".")[-1].split("[")[0]
            if leaf in _DIRECT_ID_KEYS and v not in (None, "", [], {}):
                # allow aggregate counts named similarly? only flag string values
                if isinstance(v, str) and len(v) > 0:
                    direct_hits.append({"file": rel, "path": p})
            if leaf in _HASH_ARRAY_KEYS and v:
                row_derived.append({"file": rel, "path": p})
                low_entropy.append({"file": rel, "path": p})
        # structured sensitive + hashes
        def check(obj: Any) -> None:
            if isinstance(obj, dict):
                col = str(obj.get("column") or "")
                if obj.get("sample_category_hashes") and _SENSITIVE_COL_RE.search(col):
                    sensitive.append({"file": rel, "column": col})
                    hashed_hits.append({"file": rel, "column": col})
                if obj.get("raw_text") or obj.get("document_body"):
                    unstructured.append({"file": rel})
                for vv in obj.values():
                    check(vv)
            elif isinstance(obj, list):
                for vv in obj:  # full
                    check(vv)

        check(doc)
        if _EMAIL_RE.search(text):
            direct_hits.append({"file": rel, "kind": "email"})

    def st(hits: list) -> str:
        return "PASS" if not hits else "FAIL"

    ok = all(
        st(h) == "PASS"
        for h in (direct_hits, hashed_hits, low_entropy, row_derived, sensitive, private_paths, unstructured)
    )
    return {
        "version": VERSION,
        "DIRECT_IDENTIFIER_SCAN_STATUS": st(direct_hits),
        "HASHED_IDENTIFIER_SCAN_STATUS": st(hashed_hits),
        "LOW_ENTROPY_HASH_SCAN_STATUS": st(low_entropy),
        "ROW_DERIVED_VALUE_SCAN_STATUS": st(row_derived),
        "SENSITIVE_COLUMN_SAMPLE_SCAN_STATUS": st(sensitive),
        "UNSTRUCTURED_TEXT_LEAKAGE_STATUS": st(unstructured),
        "PRIVATE_PATH_SCAN_STATUS": st(private_paths),
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY" if ok else "FAIL",
        "PRIVACY_BOUNDARY_STATUS": "PASS" if ok else "FAIL",
        "full_array_walk": True,
        "array_walk_truncated_at_200": False,
        "n_hits": {
            "direct": len(direct_hits),
            "hashed": len(hashed_hits),
            "low_entropy": len(low_entropy),
            "row_derived": len(row_derived),
            "sensitive": len(sensitive),
            "private": len(private_paths),
            "unstructured": len(unstructured),
        },
        "ok": ok,
    }
