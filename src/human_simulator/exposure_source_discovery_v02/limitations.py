"""Reproduce v0.1 method limits from the frozen source and artifacts.

These limits belong to the separate discovery run. They are not Stage 05 v0.1.1 defects.
"""

from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.policy import V01_DIR, V01_DISCOVER


def _load(root: Path, name: str) -> dict[str, Any]:
    return json.loads((root / V01_DIR / name).read_text(encoding="utf-8"))


def _function_source(source: str, tree: ast.AST, name: str) -> str:
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    return ""


def _v01_privacy_misses_numeric_id(tmp: Path) -> dict[str, Any]:
    from human_simulator.intervention_response_readiness_v01.privacy import scan_public

    art = tmp / "v01scan"
    art.mkdir()
    (art / "leak.json").write_text(json.dumps({"patient_id": 424242}) + "\n", encoding="utf-8")
    (art / "note.md").write_text("patient text is not scanned because this file is markdown\n", encoding="utf-8")
    result = scan_public(art)
    return {
        "numeric_patient_id_status": result.get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "numeric_patient_id_missed": result.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "PASS_AGGREGATE_ONLY",
        "markdown_not_content_scanned": True,
        "scanner": "human_simulator.intervention_response_readiness_v01.privacy.scan_public",
        "direct_identifier_check_requires_string": True,
    }


def reproduce(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    source = (root / V01_DISCOVER).read_text(encoding="utf-8")
    tree = ast.parse(source)
    json_profile = _function_source(source, tree, "_json_profile")
    flatten = _function_source(source, tree, "_flatten_strings")
    discover_a = _function_source(source, tree, "discover_source_a")
    followup = _function_source(source, tree, "discover_followup")
    a = _load(root, "source-a-discovery.json")
    b = _load(root, "source-b-discovery.json")
    follow = _load(root, "followup-discovery.json")
    rec = a["document_recommendation_document"]
    report = a["document_medicalreport_document"]
    change = b["feedback.change_drugs"]
    decline = b["feedback.decline_drugs"]
    consult = b["consultations.recommendations"]
    chain = follow["source_b_feedback_after_drug_recommendation"]
    with tempfile.TemporaryDirectory(prefix="uhbse-v01-privacy-") as tmp:
        privacy = _v01_privacy_misses_numeric_id(Path(tmp))
    claims = [
        {
            "claim": 1,
            "holds": "_flatten_strings(doc" in json_profile and "string_content" in json_profile,
            "statement": "Source A pattern rates are computed on every string in the JSON document, not only recommendations[].items.",
            "evidence": "discover.py _json_profile calls _flatten_strings on the whole document before _text_profile.",
        },
        {
            "claim": 2,
            "holds": "anamnesis" in report["key_paths_supported"] and "recommendations" in report["key_paths_supported"],
            "statement": "document_medicalreport.document pattern hits are not confined to the recommendations block.",
            "evidence": "The same whole-document flatten is used, and the frozen key inventory contains both anamnesis and recommendations.",
        },
        {
            "claim": 3,
            "holds": rec["catalog_mention_fraction"] == 0.6216 and "\\b" not in json_profile and "catalog.search" in json_profile,
            "statement": "catalog_mention_fraction=0.6216 is a substring search without word boundaries and without section localization.",
            "evidence": "discover.py compiles catalog names with re.escape joined by '|' and searches the flattened document.",
        },
        {
            "claim": 4,
            "holds": "ap.patient_id = m.patient_id" in discover_a and "86400" in discover_a,
            "statement": "The medicine-appointment to recommendation-document link uses only the same patient and created within 86400 seconds.",
            "evidence": "SQL a_medicineappointment_to_recommendation_doc_same_day. Frozen fraction 0.0589. Absence in that window is not evidence of no link.",
            "frozen_fraction": a["medicineappointments_linkage"]["fraction"],
        },
        {
            "claim": 5,
            "holds": change["non_empty_fraction"] == 0.8203
            and decline["non_empty_fraction"] == 0.8204
            and change["length"]["p50"] == 3
            and decline["length"]["p50"] == 3,
            "statement": "change_drugs and decline_drugs are about 82% non-empty with median length 3.",
            "evidence": "source-b-discovery.json length.p50 and non_empty_fraction.",
        },
        {
            "claim": 6,
            "holds": consult["length"]["p50"] == 5922 and consult["pattern_fraction_of_non_empty"]["dose_amount"] == 0.9995,
            "statement": "consultations.recommendations is nearly all pattern hits at median length 5922, which can be a template effect.",
            "evidence": "source-b-discovery.json consultations.recommendations. Not interpreted as medication instructions.",
        },
        {
            "claim": 7,
            "holds": "f.user_id" in followup and chain["fraction"] == 0.6697 and "UNKNOWN" in chain["subject_key_assumption"],
            "statement": "The 67% figure uses the unconfirmed equality feedback.user_id = consultations.patient_id.",
            "evidence": "followup-discovery.json subject_key_assumption and fraction 0.6697.",
        },
        {
            "claim": 8,
            "holds": privacy["numeric_patient_id_missed"] is True,
            "statement": "The v0.1 privacy scanner reads JSON content, misses a numeric patient_id, and does not prove that no patient-level text was published.",
            "evidence": privacy,
        },
    ]
    return {
        "ok": all(item["holds"] for item in claims),
        "applies_to": "exposure-source-discovery-v0.1",
        "not_a_stage_05_v011_defect": True,
        "claims": claims,
        "functions_present": {
            "_flatten_strings": bool(flatten),
            "_json_profile": bool(json_profile),
        },
    }
