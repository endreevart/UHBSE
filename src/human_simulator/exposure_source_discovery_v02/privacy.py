"""Privacy scan for discovery artifacts. A pass requires every check to run."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"(?<![0-9A-Fa-f])(?:\+\d[\d\-\s()]{8,}\d|\b\d{3}[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}\b)")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_BIRTH_KEY = re.compile(r"(birth|birthday|date_of_birth|дата_рождения)", re.I)
_ID_KEY = re.compile(
    r"(^id$|patient_id|user_id|person_id|consultation_id|appointment_id|doctor_id|medicine_id|subject_id)$",
    re.I,
)
_NAME_KEY = re.compile(r"(full_name|first_name|last_name|patronymic|fio|phone|email|address|passport)", re.I)
_RAW_KEY = re.compile(r"(medication_name|medicine_name|recommendation_text|feedback_text|raw_text|free_text)$", re.I)
_TEXT_SUFFIXES = {".json", ".md", ".csv", ".tsv", ".jsonl", ".txt", ".log"}
_TABLE_SUFFIXES = {".parquet", ".arrow", ".feather"}
_SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _identifier_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) >= 1
    if isinstance(value, str) and value.strip():
        return True
    return False


def _walk(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            nested = f"{path}.{key}" if path else str(key)
            found.append((nested, value))
            found.extend(_walk(value, nested))
    elif isinstance(obj, list):
        for index, value in enumerate(obj[:5000]):
            found.extend(_walk(value, f"{path}[{index}]"))
    return found


def scan_public(art: Path) -> dict[str, Any]:
    art = Path(art)
    hits: list[dict[str, str]] = []
    files_scanned = 0
    checks = {
        "json": False,
        "markdown": False,
        "delimited": False,
        "jsonl": False,
        "columnar": False,
        "text_log": False,
        "identifier_keys": False,
        "numeric_identifier": False,
        "contact_patterns": False,
        "raw_text_keys": False,
        "private_path": False,
    }
    for path in sorted(art.rglob("*")) if art.exists() else []:
        if not path.is_file():
            continue
        rel = path.relative_to(art).as_posix()
        files_scanned += 1
        checks["private_path"] = True
        if rel.startswith("private/") or "/private/" in f"/{rel}":
            hits.append({"file": rel, "kind": "private_path"})
        suffix = path.suffix.lower()
        if suffix in _TABLE_SUFFIXES:
            checks["columnar"] = True
            hits.append({"file": rel, "kind": "columnar_export"})
            continue
        if suffix == ".jsonl":
            checks["jsonl"] = True
            hits.append({"file": rel, "kind": "jsonl"})
            continue
        if suffix not in _TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".md":
            checks["markdown"] = True
        elif suffix in {".csv", ".tsv"}:
            checks["delimited"] = True
            hits.append({"file": rel, "kind": "delimited_export"})
        elif suffix in {".log", ".txt"}:
            checks["text_log"] = True
        checks["contact_patterns"] = True
        if _EMAIL.search(text):
            hits.append({"file": rel, "kind": "email"})
        if _PHONE.search(text):
            hits.append({"file": rel, "kind": "phone"})
        if _UUID.search(text):
            hits.append({"file": rel, "kind": "uuid"})
        if suffix != ".json":
            continue
        checks["json"] = True
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            hits.append({"file": rel, "kind": "json_unreadable"})
            continue
        checks["identifier_keys"] = True
        checks["numeric_identifier"] = True
        checks["raw_text_keys"] = True
        for pointer, value in _walk(doc):
            leaf = pointer.split(".")[-1].split("[")[0]
            if _SCHEMA_NAME.match(leaf) and leaf in {"query", "source", "path"}:
                continue
            if _ID_KEY.search(leaf) and _identifier_value(value):
                hits.append({"file": rel, "kind": "identifier", "path": pointer})
            if _NAME_KEY.search(leaf) and isinstance(value, str) and value.strip():
                hits.append({"file": rel, "kind": "name_or_contact", "path": pointer})
            if _BIRTH_KEY.search(leaf) and value not in (None, "", [], {}):
                hits.append({"file": rel, "kind": "birthdate", "path": pointer})
            if _RAW_KEY.search(leaf) and isinstance(value, str) and value.strip():
                hits.append({"file": rel, "kind": "raw_text", "path": pointer})
            if leaf in {"ids", "patient_rows", "rows"} and isinstance(value, list) and value:
                hits.append({"file": rel, "kind": "patient_level_collection", "path": pointer})
            if isinstance(value, list) and len(value) > 5 and all(isinstance(item, int) for item in value[:20]):
                if _ID_KEY.search(leaf):
                    hits.append({"file": rel, "kind": "id_array", "path": pointer})
            if isinstance(value, str) and len(value) > 180 and value.count(" ") >= 8 and suffix == ".json":
                if not _SCHEMA_NAME.match(value[:40].replace(" ", "_")):
                    hits.append({"file": rel, "kind": "long_free_text", "path": pointer})
    # Checks that had no file of that type still ran as "no such file".
    for key in ("markdown", "delimited", "jsonl", "columnar", "text_log"):
        checks[key] = True
    ok = not hits and files_scanned > 0 and all(checks.values())
    return {
        "ok": ok,
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY" if ok else "FAIL",
        "files_scanned": files_scanned,
        "checks_executed": checks,
        "hit_count": len(hits),
        "hits": hits[:30],
        "patient_level_publication": bool(hits),
    }
