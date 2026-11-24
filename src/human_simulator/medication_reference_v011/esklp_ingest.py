"""ESKLP offline snapshot ingestion — format discovery, safe unpack, provider index."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import unicodedata
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.esklp_xlsx import parse_esklp_xlsx
from human_simulator.medication_reference_v011.policy import (
    EXPECTED_ESKLP_SNAPSHOT,
    RUNTIME_DIR,
    VERSION,
)

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "inn": (
        "стандартизованное мнн",
        "мнн",
        "inn",
        "standard_inn",
        "группировочн",
        "действующ",
        "active",
        "ingredient",
    ),
    "trade_name": (
        "торговое наименование",
        "торговое",
        "trade",
        "наименование лп",
        "product_name",
        "klp_name",
        "brand",
    ),
    "form": (
        "стандартизованная лекарственная форма",
        "лекарственная форма",
        "форма",
        "form",
        "dosage_form",
        "лекформ",
    ),
    "strength": (
        "стандартизованная дозировка",
        "дозиров",
        "dose",
        "strength",
        "concentration",
        "doze",
        "dosage",
    ),
    "unit": ("единиц", "unit", "ед."),
    "route": ("путь", "route", "введен"),
    "manufacturer": ("производит", "manufacturer", "holder", "держатель"),
    "product_id": (
        "код узла смнн",
        "код клп",
        "smnn",
        "смнн",
        "klp",
        "клп",
        "номер регистрац",
        "reg_number",
        "registration",
    ),
}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_term(s: str) -> str:
    t = unicodedata.normalize("NFKC", str(s)).replace("ё", "е").replace("Ё", "Е")
    t = t.casefold()
    t = re.sub(r"[\"'`«»“”]", "", t)
    t = re.sub(r"[^\w\s+/.-]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


# Back-compat alias used by mapping
_norm = normalize_term


def expected_snapshot_path(root: Path) -> Path:
    return root / EXPECTED_ESKLP_SNAPSHOT


def safe_extract_zip(zip_path: Path, dest: Path) -> dict[str, Any]:
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    names: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    rejected: list[str] = []
    extracted = 0
    members_meta: list[dict[str, Any]] = []

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name in seen:
                duplicates.append(name)
            seen.add(name)
            names.append(name)
            members_meta.append(
                {
                    "name": name,
                    "file_size": info.file_size,
                    "compress_size": info.compress_size,
                    "is_dir": info.is_dir() or name.endswith("/"),
                }
            )
            if name.startswith("/") or name.startswith("\\") or ".." in Path(name).parts:
                rejected.append(name)
                continue
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest_resolved)):
                rejected.append(name)
                continue
            if info.is_dir() or name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            extracted += 1

    if rejected:
        shutil.rmtree(dest, ignore_errors=True)
        return {
            "ok": False,
            "reason": "UNSAFE_ZIP_REJECTED",
            "rejected_members": rejected,
            "members": names,
            "duplicates": duplicates,
        }
    return {
        "ok": True,
        "members": names,
        "members_meta": members_meta,
        "n_members": len(names),
        "n_extracted_files": extracted,
        "duplicates": duplicates,
        "duplicate_members_detected": bool(duplicates),
    }


def _guess_field_role(header: str) -> str | None:
    h = header.casefold()
    for role, aliases in _FIELD_ALIASES.items():
        for a in sorted(aliases, key=len, reverse=True):
            if a in h:
                return role
    return None


def _read_delimited(path: Path, delimiter: str) -> tuple[list[str], list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        headers = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({k: (v or "").strip() for k, v in row.items() if k is not None})
        return headers, rows, [_guess_field_role(h) or "unknown" for h in headers]


def _read_json_rows(path: Path) -> tuple[list[str], list[dict[str, str]], list[str]]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if isinstance(data, dict):
        for key in ("records", "items", "data", "rows"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return [], [], []
    rows: list[dict[str, str]] = []
    headers: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        flat = {str(k): "" if v is None else str(v).strip() for k, v in item.items()}
        rows.append(flat)
        for k in flat:
            if k not in headers:
                headers.append(k)
    return headers, rows, [_guess_field_role(h) or "unknown" for h in headers]


def _read_jsonl(path: Path) -> tuple[list[str], list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                continue
            flat = {str(k): "" if v is None else str(v).strip() for k, v in item.items()}
            rows.append(flat)
            for k in flat:
                if k not in headers:
                    headers.append(k)
    return headers, rows, [_guess_field_role(h) or "unknown" for h in headers]


def _profile_file(path: Path) -> dict[str, Any]:
    suffix = path.suffix.casefold()
    size = path.stat().st_size
    if suffix in {".docx", ".pdf", ".doc"}:
        return {
            "path": path.name,
            "format": suffix.lstrip("."),
            "supported": False,
            "skipped_reason": "documentation_not_indexed",
            "n_rows": 0,
            "headers": [],
            "field_roles": [],
            "size_bytes": size,
        }
    try:
        if suffix == ".csv":
            headers, rows, roles = _read_delimited(path, ",")
            fmt = "csv"
        elif suffix == ".tsv":
            headers, rows, roles = _read_delimited(path, "\t")
            fmt = "tsv"
        elif suffix == ".json":
            headers, rows, roles = _read_json_rows(path)
            fmt = "json"
        elif suffix == ".jsonl":
            headers, rows, roles = _read_jsonl(path)
            fmt = "jsonl"
        elif suffix == ".xlsx":
            parsed = parse_esklp_xlsx(path)
            if not parsed.get("ok"):
                return {
                    "path": path.name,
                    "format": "xlsx",
                    "supported": False,
                    "parse_error": parsed.get("parse_error"),
                    "sheet_names": parsed.get("sheet_names"),
                    "n_rows": 0,
                    "headers": [],
                    "field_roles": [],
                    "size_bytes": size,
                }
            # Re-map roles with local aliases (more complete than xlsx module)
            headers = list(parsed["headers"])
            roles = [_guess_field_role(h) or "unknown" for h in headers]
            return {
                "path": path.name,
                "format": "xlsx",
                "supported": True,
                "n_rows": parsed["n_rows"],
                "headers": headers,
                "field_roles": roles,
                "observed_fields": [h for h in headers if h and not h.startswith("col_")],
                "data_sheet": parsed.get("data_sheet"),
                "sheet_names": parsed.get("sheet_names"),
                "numeric_header_row_index": parsed.get("numeric_header_row_index"),
                "encoding": parsed.get("encoding"),
                "size_bytes": size,
                "_rows": parsed.get("rows") or [],
            }
        else:
            return {
                "path": path.name,
                "format": suffix.lstrip(".") or "unknown",
                "supported": False,
                "skipped_reason": "unsupported_extension",
                "n_rows": 0,
                "headers": [],
                "field_roles": [],
                "size_bytes": size,
            }
    except Exception as exc:  # noqa: BLE001
        return {
            "path": path.name,
            "format": suffix.lstrip("."),
            "supported": False,
            "parse_error": type(exc).__name__,
            "n_rows": 0,
            "headers": [],
            "field_roles": [],
            "size_bytes": size,
        }
    return {
        "path": path.name,
        "format": fmt,
        "supported": True,
        "n_rows": len(rows),
        "headers": headers,
        "field_roles": roles,
        "observed_fields": sorted({h for h in headers if h}),
        "size_bytes": size,
        "encoding": "utf-8",
        "_rows": rows,
    }


def _row_to_concept(
    row: dict[str, str],
    headers: list[str],
    roles: list[str],
    *,
    source_file: str,
    row_index: int,
) -> dict[str, Any] | None:
    role_map: dict[str, str] = {}
    for h, role in zip(headers, roles, strict=False):
        val = (row.get(h) or "").strip()
        if role != "unknown" and val and role not in role_map:
            role_map[role] = val
    trade = role_map.get("trade_name") or ""
    inn = role_map.get("inn") or ""
    product_id = role_map.get("product_id") or ""
    if not (trade or inn or product_id):
        return None
    concept_id = product_id or f"{source_file}:{row_index}"
    ingredients: list[str] = []
    if inn:
        ingredients = [p.strip() for p in re.split(r"\s*[+/;]\s*", inn) if p.strip()]
    nt = normalize_term(trade) if trade else ""
    ni = normalize_term(inn) if inn else ""
    return {
        "provider": "ESKLP",
        "provider_concept_id": concept_id,
        "trade_name": trade,
        "inn": inn,
        "ingredients": ingredients,
        "form": role_map.get("form") or None,
        "strength": role_map.get("strength") or None,
        "unit": role_map.get("unit") or None,
        "route": role_map.get("route") or None,
        "manufacturer": role_map.get("manufacturer") or None,
        "normalized_trade": nt,
        "normalized_inn": ni,
        "normalized_terms": sorted({t for t in (nt, ni) if t}),
        "source_file": source_file,
        "row_index": row_index,
        "evidence_fields": {k: v for k, v in role_map.items() if v},
        "has_usable_search_term": bool(nt or ni),
    }


def build_provider_index(concepts: list[dict[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    by_trade: dict[str, list[str]] = {}
    by_inn: dict[str, list[str]] = {}
    by_form: dict[str, list[str]] = {}
    by_strength: dict[str, list[str]] = {}
    by_token: dict[str, set[str]] = {}
    duplicates = 0
    no_search = 0
    for c in concepts:
        cid = str(c["provider_concept_id"])
        if cid in by_id:
            duplicates += 1
            prev = by_id[cid]
            alts = list(prev.get("alternate_sources") or [])
            alts.append({"source_file": c.get("source_file"), "row_index": c.get("row_index")})
            prev["alternate_sources"] = alts[:20]
            # Prefer filling empty trade/inn from later duplicate
            if not prev.get("normalized_trade") and c.get("normalized_trade"):
                prev["trade_name"] = c.get("trade_name")
                prev["normalized_trade"] = c.get("normalized_trade")
            if not prev.get("normalized_inn") and c.get("normalized_inn"):
                prev["inn"] = c.get("inn")
                prev["normalized_inn"] = c.get("normalized_inn")
                prev["ingredients"] = c.get("ingredients") or []
            continue
        by_id[cid] = c
        nt = c.get("normalized_trade") or ""
        ni = c.get("normalized_inn") or ""
        if not (nt or ni):
            no_search += 1
        if nt:
            by_trade.setdefault(nt, []).append(cid)
        if ni:
            by_inn.setdefault(ni, []).append(cid)
        nf = normalize_term(c.get("form") or "")
        if nf:
            by_form.setdefault(nf, []).append(cid)
        ns = normalize_term(c.get("strength") or "")
        if ns:
            by_strength.setdefault(ns, []).append(cid)
        for term in (nt, ni):
            for tok in term.split():
                if len(tok) >= 3:
                    by_token.setdefault(tok, set()).add(cid)

    # Freeze token sets to lists for JSON
    by_token_lists = {k: sorted(v) for k, v in by_token.items()}
    searchable = set(by_trade) | set(by_inn)
    n_product_ids = sum(
        1
        for c in by_id.values()
        if c.get("provider_concept_id")
        and not str(c["provider_concept_id"]).startswith(str(c.get("source_file") or "\0"))
    )
    return {
        "by_id": by_id,
        "by_trade_name": by_trade,
        "by_inn": by_inn,
        "by_form": by_form,
        "by_strength": by_strength,
        "by_token": by_token_lists,
        "n_concepts": len(by_id),
        "n_indexed_rows_seen": len(concepts),
        "n_unique_trade_names": len(by_trade),
        "n_unique_inn": len(by_inn),
        "n_unique_searchable_terms": len(searchable),
        "n_with_strength": sum(1 for c in by_id.values() if c.get("strength")),
        "n_with_form": sum(1 for c in by_id.values() if c.get("form")),
        "n_with_registration_or_product_id": n_product_ids,
        "n_duplicate_ids_collapsed": duplicates,
        "n_without_searchable_term": no_search,
    }


def ingest_esklp_snapshot(root: Path, snapshot_path: Path | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    snap = Path(snapshot_path) if snapshot_path else expected_snapshot_path(root)
    if not snap.is_file():
        return {
            "ok": False,
            "PROVIDER_INPUT_REQUIRED": True,
            "ESKLP_PROVIDER_STATUS": "NOT_AVAILABLE_NO_APPROVED_SNAPSHOT",
            "PIPELINE_STATUS": "PROVIDER_INPUT_REQUIRED",
            "expected_path": str(expected_snapshot_path(root).relative_to(root)),
            "absolute_expected_path": str(expected_snapshot_path(root)),
            "message": (
                "Place an approved offline ESKLP snapshot at the expected path, "
                "then re-run. No network RxNorm fallback will be executed for 487 records."
            ),
        }

    content_hash = _sha_file(snap)
    work = root / RUNTIME_DIR / "provider-snapshots" / "esklp"
    work.mkdir(parents=True, exist_ok=True)
    dest_zip = work / "esklp.zip"
    if snap.resolve() != dest_zip.resolve():
        dest_zip.write_bytes(snap.read_bytes())

    extract_dir = work / "extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    extract_report = safe_extract_zip(dest_zip, extract_dir)
    if not extract_report.get("ok"):
        return {
            "ok": False,
            "ESKLP_PROVIDER_STATUS": "UNSAFE_ZIP_REJECTED",
            "PIPELINE_STATUS": "PROVIDER_SNAPSHOT_REJECTED",
            "snapshot_sha256": content_hash,
            "extract": extract_report,
        }

    file_profiles: list[dict[str, Any]] = []
    concepts: list[dict[str, Any]] = []
    formats = Counter()
    n_processed = 0
    n_skipped = 0
    for path in sorted(extract_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        prof = _profile_file(path)
        formats[prof.get("format") or "unknown"] += 1
        rows = prof.pop("_rows", [])
        file_profiles.append(prof)
        if not prof.get("supported"):
            n_skipped += 1
            continue
        n_processed += 1
        headers = prof.get("headers") or []
        roles = prof.get("field_roles") or []
        for i, row in enumerate(rows):
            concept = _row_to_concept(
                row, headers, roles, source_file=path.name, row_index=i
            )
            if concept:
                concepts.append(concept)

    index = build_provider_index(concepts)
    searchable = int(index.get("n_unique_searchable_terms") or 0)

    index_dir = work / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / "provider-index.jsonl"
    with index_path.open("w", encoding="utf-8") as fh:
        for c in index["by_id"].values():
            fh.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")

    lookup = {
        "by_trade_name": index["by_trade_name"],
        "by_inn": index["by_inn"],
        "by_form": index["by_form"],
        "by_strength": index["by_strength"],
        "by_token": index["by_token"],
        "n_concepts": index["n_concepts"],
        "n_unique_searchable_terms": searchable,
    }
    (index_dir / "lookup-maps.json").write_text(
        json.dumps(lookup, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    date_matches = re.findall(r"(20\d{6})", " ".join(extract_report.get("members") or []))
    source_date = date_matches[0] if date_matches else None
    index_hash = _sha_file(index_path)

    stats = {
        "n_archive_members": extract_report.get("n_members"),
        "n_extracted_files": extract_report.get("n_extracted_files"),
        "n_processed_files": n_processed,
        "n_skipped_files": n_skipped,
        "formats": dict(formats),
        "n_concepts": index["n_concepts"],
        "n_indexed_rows_seen": index["n_indexed_rows_seen"],
        "n_unique_searchable_terms": searchable,
        "n_unique_trade_names": index["n_unique_trade_names"],
        "n_unique_inn": index["n_unique_inn"],
        "n_with_strength": index["n_with_strength"],
        "n_with_form": index["n_with_form"],
        "n_with_registration_or_product_id": index["n_with_registration_or_product_id"],
        "n_duplicate_ids_collapsed": index["n_duplicate_ids_collapsed"],
        "n_without_searchable_term": index["n_without_searchable_term"],
    }

    if searchable <= 0:
        manifest = {
            "version": VERSION,
            "provider_name": "ESKLP",
            "snapshot_sha256": content_hash,
            "index_sha256": index_hash,
            "retrieved_at": _now(),
            "source_date_from_filename": source_date,
            "ESKLP_PROVIDER_STATUS": "INDEX_EMPTY_NO_SEARCHABLE_TERMS",
            "stats": stats,
            "file_profiles_sanitized": file_profiles,
            "members_meta": extract_report.get("members_meta"),
        }
        (work / "snapshot-manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return {
            "ok": False,
            "ESKLP_PROVIDER_STATUS": "INDEX_EMPTY_NO_SEARCHABLE_TERMS",
            "PIPELINE_STATUS": "NO_PROVIDER_COVERAGE_ESTABLISHED",
            "snapshot_sha256": content_hash,
            "index_sha256": index_hash,
            "n_concepts": index["n_concepts"],
            "n_unique_searchable_terms": 0,
            "manifest": manifest,
            "index": index,
            "stats": stats,
            "private_index_path": str(index_path.relative_to(root)),
        }

    manifest = {
        "version": VERSION,
        "provider_name": "ESKLP",
        "snapshot_file": "esklp.zip",
        "snapshot_sha256": content_hash,
        "index_sha256": index_hash,
        "retrieved_at": _now(),
        "source_date_from_filename": source_date,
        "source_url": None,
        "ESKLP_PROVIDER_STATUS": "INDEXED",
        "stats": stats,
        "duplicate_zip_members": extract_report.get("duplicates") or [],
        "file_profiles_sanitized": file_profiles,
        "members_meta": extract_report.get("members_meta"),
        "observed_field_roles": sorted(
            {
                r
                for p in file_profiles
                for r in (p.get("field_roles") or [])
                if r and r != "unknown"
            }
        ),
        "licensing_usage_status": "LOCAL_APPROVED_SNAPSHOT",
    }
    (work / "snapshot-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "ok": True,
        "ESKLP_PROVIDER_STATUS": "INDEXED",
        "PIPELINE_STATUS": "PROVIDER_INDEX_READY",
        "snapshot_sha256": content_hash,
        "index_sha256": index_hash,
        "n_concepts": index["n_concepts"],
        "n_unique_searchable_terms": searchable,
        "manifest": manifest,
        "index": index,
        "stats": stats,
        "private_index_path": str(index_path.relative_to(root)),
    }


def load_esklp_index(root: Path) -> dict[str, Any] | None:
    path = root / RUNTIME_DIR / "provider-snapshots" / "esklp" / "index" / "provider-index.jsonl"
    if not path.is_file():
        return None
    concepts = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                concepts.append(json.loads(line))
    return build_provider_index(concepts)
