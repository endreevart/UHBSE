"""ESKLP XLSX readers — data-sheet selection, annotation headers, row iteration."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL_NS = {
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_SKIP_SHEETS = frozenset({"описание", "аннотация"})


def _col_letter_to_index(col: str) -> int:
    n = 0
    for ch in col:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _load_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root.findall("m:si", _NS):
        texts = [t.text or "" for t in si.findall(".//m:t", _NS)]
        out.append("".join(texts))
    return out


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    v_el = cell.find("m:v", _NS)
    if v_el is None or v_el.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        idx = int(v_el.text)
        return shared[idx] if 0 <= idx < len(shared) else ""
    return v_el.text


def _workbook_sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Return [(sheet_name, worksheet_path), ...]."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target: dict[str, str] = {}
    for rel in rels:
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            rid_to_target[rid] = target
    out: list[tuple[str, str]] = []
    for sh in wb.findall("m:sheets/m:sheet", _NS):
        name = sh.attrib.get("name") or ""
        rid = sh.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        target = rid_to_target.get(rid or "", "")
        if not target:
            continue
        path = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
        out.append((name, path))
    return out


def select_data_sheet(sheets: list[tuple[str, str]]) -> tuple[str, str] | None:
    for name, path in sheets:
        if name.casefold() in _SKIP_SHEETS:
            continue
        return name, path
    return None


def select_annotation_sheet(sheets: list[tuple[str, str]]) -> tuple[str, str] | None:
    for name, path in sheets:
        if name.casefold() == "аннотация":
            return name, path
    return None


def _iter_sheet_rows(
    zf: zipfile.ZipFile, sheet_path: str, shared: list[str]
) -> Iterator[tuple[int, dict[int, str]]]:
    """Yield (1-based row_number, {col_index: value})."""
    root = ET.fromstring(zf.read(sheet_path))
    for row in root.findall(".//m:sheetData/m:row", _NS):
        r_attr = row.attrib.get("r")
        row_num = int(r_attr) if r_attr and r_attr.isdigit() else 0
        cells: dict[int, str] = {}
        for c in row.findall("m:c", _NS):
            ref = c.attrib.get("r", "")
            m = re.match(r"([A-Z]+)(\d+)", ref)
            if not m:
                continue
            cells[_col_letter_to_index(m.group(1))] = _cell_value(c, shared)
        if cells:
            yield row_num, cells


def _is_numeric_header_row(cells: dict[int, str]) -> bool:
    try:
        a = float((cells.get(0) or "").strip())
        b = float((cells.get(1) or "").strip())
    except ValueError:
        return False
    return a == 1.0 and b == 2.0


def _guess_role_from_header(header: str) -> str | None:
    h = header.casefold()
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("inn", ("мнн", "standard_inn", "группировочн", "действующ", "inn")),
        (
            "trade_name",
            (
                "торговое",
                "trade",
                "наименование лп",
                "trade_name",
                "tn ",
                "tn_",
            ),
        ),
        ("form", ("форм", "form", "dosage_form", "лекформ")),
        ("strength", ("дозиров", "dose", "strength", "concentration", "doze")),
        ("unit", ("единиц", "unit")),
        ("route", ("путь", "route", "введен")),
        (
            "manufacturer",
            ("производит", "manufacturer", "держатель", "holder"),
        ),
        (
            "product_id",
            (
                "код узла смнн",
                "смнн",
                "smnn",
                "клп",
                "klp",
                "номер регистрац",
                "reg_number",
                "registration",
            ),
        ),
        ("atc", ("атх", "atc")),
    ]
    # Prefer more specific product_id phrases before generic "код"
    for role, aliases in rules:
        for a in aliases:
            if a in h:
                return role
    if h.strip() in {"код", "code"} or h.startswith("код "):
        return "product_id"
    return None


def parse_esklp_xlsx(path: Path) -> dict[str, Any]:
    """Parse one ESKLP workbook into typed rows + profile (no patient data)."""
    with zipfile.ZipFile(path) as zf:
        sheets = _workbook_sheets(zf)
        shared = _load_shared_strings(zf)
        data = select_data_sheet(sheets)
        if data is None:
            return {
                "ok": False,
                "path": path.name,
                "format": "xlsx",
                "parse_error": "NO_DATA_SHEET",
                "sheet_names": [n for n, _ in sheets],
                "n_rows": 0,
                "headers": [],
                "field_roles": [],
                "rows": [],
            }
        sheet_name, sheet_path = data
        raw_rows = list(_iter_sheet_rows(zf, sheet_path, shared))

        # Locate numeric column-index header (1.0, 2.0, ...)
        numeric_idx = None
        text_header: dict[int, str] = {}
        best_header_width = 0
        for i, (_rn, cells) in enumerate(raw_rows):
            if _is_numeric_header_row(cells):
                numeric_idx = i
                break
            # Keep the widest text header row before the numeric index row
            nonempty = sum(1 for v in cells.values() if str(v).strip())
            if nonempty > best_header_width:
                best_header_width = nonempty
                text_header = dict(cells)

        if numeric_idx is None:
            # Fallback: first row as header, rest as data
            if not raw_rows:
                return {
                    "ok": False,
                    "path": path.name,
                    "format": "xlsx",
                    "parse_error": "EMPTY_DATA_SHEET",
                    "sheet_names": [n for n, _ in sheets],
                    "data_sheet": sheet_name,
                    "n_rows": 0,
                    "headers": [],
                    "field_roles": [],
                    "rows": [],
                }
            text_header = dict(raw_rows[0][1])
            data_rows = [cells for _, cells in raw_rows[1:]]
        else:
            data_rows = [cells for _, cells in raw_rows[numeric_idx + 1 :]]

        max_col = max(
            [max(text_header.keys(), default=-1)]
            + [max(r.keys(), default=-1) for r in data_rows[:50]],
            default=-1,
        )
        headers: list[str] = []
        for c in range(max_col + 1):
            label = (text_header.get(c) or "").strip()
            headers.append(label if label else f"col_{c}")

        roles = [_guess_role_from_header(h) or "unknown" for h in headers]
        dict_rows: list[dict[str, str]] = []
        for cells in data_rows:
            row = {
                headers[c] if c < len(headers) else f"col_{c}": (cells.get(c) or "").strip()
                for c in range(len(headers))
            }
            if any(row.values()):
                dict_rows.append(row)

        return {
            "ok": True,
            "path": path.name,
            "format": "xlsx",
            "supported": True,
            "sheet_names": [n for n, _ in sheets],
            "data_sheet": sheet_name,
            "shared_string_count": len(shared),
            "n_xml_rows_scanned": len(raw_rows),
            "numeric_header_row_index": numeric_idx,
            "n_rows": len(dict_rows),
            "headers": headers,
            "field_roles": roles,
            "observed_fields": [h for h in headers if h and not h.startswith("col_")],
            "rows": dict_rows,
            "encoding": "xlsx-sharedStrings-utf8",
        }
