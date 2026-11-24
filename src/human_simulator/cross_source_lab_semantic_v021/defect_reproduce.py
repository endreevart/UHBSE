"""Reproduce v0.2 analyte-identity defects from immutable private graph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.ontology import compare_analytes
from human_simulator.cross_source_lab_semantic_v021.policy import VERSION


def _load_v02_graph(root: Path) -> list[dict[str, Any]]:
    path = (
        Path(root)
        / "private"
        / "cross-source-lab-semantic-v02"
        / "review-pack"
        / "cross-source-candidate-graph.json"
    )
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return list(doc.get("records") or [])


def reproduce_v02_analyte_identity_defects(root: Path) -> dict[str, Any]:
    records = _load_v02_graph(root)
    defects: list[dict[str, Any]] = []

    # Defect 1: total cholesterol ↔ LDL/HDL
    chol = [
        r
        for r in records
        if "Холестерин общий" in str(r.get("a_outcome") or "")
        and str(r.get("b_raw_code")) in {"32", "33"}
        and r.get("analyte_ok") is True
    ]
    for r in chol:
        cmp = compare_analytes(
            str(r.get("a_outcome") or ""),
            str(r.get("b_catalog_name_ru") or ""),
        )
        defects.append(
            {
                "defect_id": "v02_total_chol_vs_ldl_hdl",
                "a_outcome": r.get("a_outcome"),
                "a_unit": r.get("a_unit"),
                "b_raw_code": r.get("b_raw_code"),
                "b_catalog_name_ru": r.get("b_catalog_name_ru"),
                "v02_analyte_ok": r.get("analyte_ok"),
                "v02_candidate_class": r.get("candidate_class"),
                "v02_wrong_if_specimen_only": r.get("candidate_class")
                == "SPECIMEN_MISSING",
                "v021_analyte_ok": cmp.get("analyte_ok"),
                "v021_identity_level": cmp.get("identity_level"),
                "v021_conflict": cmp.get("conflict"),
                "must_not_be_analyte_ok": True,
                "must_not_classify_specimen_missing_alone": True,
                "reproduction_ok": (
                    r.get("analyte_ok") is True
                    and cmp.get("analyte_ok") is False
                    and "CONFLICT" in str(cmp.get("identity_level") or "")
                ),
            }
        )

    # Defect 2: MCHC ↔ HGB
    mchc = [
        r
        for r in records
        if "MCHC" in str(r.get("a_outcome") or "")
        and "1001" in str(r.get("b_raw_code") or "")
        and r.get("analyte_ok") is True
    ]
    for r in mchc:
        cmp = compare_analytes(
            str(r.get("a_outcome") or ""),
            str(r.get("b_catalog_name_ru") or ""),
        )
        defects.append(
            {
                "defect_id": "v02_mchc_vs_hgb",
                "a_outcome": r.get("a_outcome"),
                "a_unit": r.get("a_unit"),
                "b_raw_code": r.get("b_raw_code"),
                "b_catalog_name_ru": r.get("b_catalog_name_ru"),
                "v02_analyte_ok": r.get("analyte_ok"),
                "v02_candidate_class": r.get("candidate_class"),
                "v021_analyte_ok": cmp.get("analyte_ok"),
                "v021_identity_level": cmp.get("identity_level"),
                "v021_conflict": cmp.get("conflict"),
                "must_not_be_analyte_ok": True,
                "reproduction_ok": (
                    r.get("analyte_ok") is True
                    and cmp.get("analyte_ok") is False
                    and "CONFLICT" in str(cmp.get("identity_level") or "")
                ),
            }
        )

    d1_ok = any(d["defect_id"] == "v02_total_chol_vs_ldl_hdl" and d["reproduction_ok"] for d in defects)
    d2_ok = any(d["defect_id"] == "v02_mchc_vs_hgb" and d["reproduction_ok"] for d in defects)
    # At least one row per defect family
    d1_present = any(d["defect_id"] == "v02_total_chol_vs_ldl_hdl" for d in defects)
    d2_present = any(d["defect_id"] == "v02_mchc_vs_hgb" for d in defects)
    ok = d1_ok and d2_ok and d1_present and d2_present and all(
        d.get("reproduction_ok") for d in defects
    )

    return {
        "version": VERSION,
        "V02_ANALYTE_IDENTITY_DEFECT_REPRODUCTION_STATUS": "PASS" if ok else "FAIL",
        "n_defect_rows": len(defects),
        "defect_1_total_chol_ldl_hdl_ok": d1_ok,
        "defect_2_mchc_hgb_ok": d2_ok,
        "defects": defects,
        "root_cause": (
            "v0.2 infer_analyte_family longest-substring set family equality → "
            "analyte_ok=true; family must be retrieval-only"
        ),
        "ok": ok,
    }
