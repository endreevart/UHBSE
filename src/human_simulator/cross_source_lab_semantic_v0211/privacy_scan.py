"""Public artifact privacy scanner — beyond JSON key names."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v0211.policy import VERSION

_MD5_RE = re.compile(r"\b[a-f0-9]{32}\b", re.I)
_SHA_RE = re.compile(r"\b[a-f0-9]{64}\b", re.I)
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE_RE = re.compile(r"\+?\d[\d\-\s()]{8,}\d")
_SENSITIVE_COL_RE = re.compile(
    r"(first_name|last_name|patronymic|middle_name|phone|email|address|"
    r"passport|birth_?date|date_of_birth|patient_id|subject_id|"
    r"source_subject|opaque_subject|research_subject)",
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
        for i, v in enumerate(obj[:200]):
            out.extend(_walk(v, f"{path}[{i}]"))
    return out


def scan_public_artifacts(art: Path) -> dict[str, Any]:
    direct_hits: list[dict[str, Any]] = []
    hashed_id_hits: list[dict[str, Any]] = []
    low_entropy_hits: list[dict[str, Any]] = []
    row_derived_hits: list[dict[str, Any]] = []
    sensitive_sample_hits: list[dict[str, Any]] = []
    private_path_hits: list[dict[str, Any]] = []

    for path in sorted(art.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(art).as_posix()
        if "private" in rel.split("/"):
            private_path_hits.append({"file": rel, "reason": "private_path_in_public_art"})
        if path.suffix.lower() not in {".json", ".md", ".csv", ".html", ".txt", ".sha256"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".json":
            try:
                doc = json.loads(text)
            except json.JSONDecodeError:
                doc = None
            if doc is not None:
                for p, v in _walk(doc):
                    leaf = p.split(".")[-1].split("[")[0]
                    if leaf in _DIRECT_ID_KEYS:
                        direct_hits.append({"file": rel, "path": p, "kind": "direct_key"})
                    if leaf in _HASH_ARRAY_KEYS and v:
                        row_derived_hits.append(
                            {
                                "file": rel,
                                "path": p,
                                "kind": "row_derived_hash_array",
                                "n": len(v) if isinstance(v, list) else 1,
                            }
                        )
                        # sensitive context?
                        parent = ".".join(p.split(".")[:-1])
                        if _SENSITIVE_COL_RE.search(parent) or _SENSITIVE_COL_RE.search(
                            json.dumps(doc)[:500] if False else ""
                        ):
                            sensitive_sample_hits.append(
                                {"file": rel, "path": p, "kind": "hash_near_sensitive"}
                            )
                    # column + hashes pattern
                    if leaf == "column" and isinstance(v, str) and _SENSITIVE_COL_RE.search(v):
                        # look for nearby hashes in same object — approximate via sibling walk
                        pass
                    if leaf in {"sample_category_hashes", "category_hashes"} and v:
                        low_entropy_hits.append(
                            {
                                "file": rel,
                                "path": p,
                                "classification": "PROHIBITED_ROW_DERIVED_LOW_ENTROPY_HASH",
                            }
                        )

                # structured field objects with column + sample_category_hashes
                def check_fields(obj: Any) -> None:
                    if isinstance(obj, dict):
                        col = str(obj.get("column") or "")
                        hashes = obj.get("sample_category_hashes")
                        if hashes and _SENSITIVE_COL_RE.search(col):
                            sensitive_sample_hits.append(
                                {
                                    "file": rel,
                                    "column": col,
                                    "kind": "sensitive_column_sample_hash",
                                }
                            )
                            hashed_id_hits.append(
                                {
                                    "file": rel,
                                    "column": col,
                                    "kind": "hashed_identifier_context",
                                }
                            )
                        for vv in obj.values():
                            check_fields(vv)
                    elif isinstance(obj, list):
                        for vv in obj:
                            check_fields(vv)

                check_fields(doc)

        # textual scans for emails only (do not flag documentation mentioning hash keys)
        if _EMAIL_RE.search(text):
            direct_hits.append({"file": rel, "kind": "email_pattern"})
        if path.suffix != ".sha256" and _PHONE_RE.search(text):
            if _SENSITIVE_COL_RE.search(text):
                direct_hits.append({"file": rel, "kind": "phone_near_sensitive"})

    def _status(hits: list) -> str:
        return "PASS" if not hits else "FAIL"

    direct_s = _status(direct_hits)
    hashed_s = _status(hashed_id_hits)
    low_s = _status(low_entropy_hits)
    row_s = _status(row_derived_hits)
    sens_s = _status(sensitive_sample_hits)
    priv_ok = not private_path_hits

    ok = all(
        s == "PASS" for s in (direct_s, hashed_s, low_s, row_s, sens_s)
    ) and priv_ok

    return {
        "version": VERSION,
        "DIRECT_IDENTIFIER_SCAN_STATUS": direct_s,
        "HASHED_IDENTIFIER_SCAN_STATUS": hashed_s,
        "LOW_ENTROPY_HASH_SCAN_STATUS": low_s,
        "ROW_DERIVED_VALUE_SCAN_STATUS": row_s,
        "SENSITIVE_COLUMN_SAMPLE_SCAN_STATUS": sens_s,
        "PUBLIC_DATA_MINIMIZATION_STATUS": (
            "PASS_AGGREGATE_ONLY" if ok else "FAIL"
        ),
        "n_direct": len(direct_hits),
        "n_hashed_identifier": len(hashed_id_hits),
        "n_low_entropy_hash": len(low_entropy_hits),
        "n_row_derived": len(row_derived_hits),
        "n_sensitive_samples": len(sensitive_sample_hits),
        "n_private_paths": len(private_path_hits),
        "hits_sample": {
            "direct": direct_hits[:10],
            "hashed": hashed_id_hits[:10],
            "low_entropy": low_entropy_hits[:10],
            "row_derived": row_derived_hits[:10],
            "sensitive": sensitive_sample_hits[:10],
        },
        "ok": ok,
    }
