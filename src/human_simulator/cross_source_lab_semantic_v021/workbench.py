"""Private review pack v0.2.1 — priority by analyte identity, not coverage."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.policy import (
    REVIEW_PACK_DIR,
    VERSION,
)


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_IDENTITY_RANK = {
    "EXACT_ANALYTE_IDENTITY": 5,
    "APPROVED_ANALYTE_SYNONYM": 4,
    "ANALYTE_FAMILY_RETRIEVAL_ONLY": 1,
    "ANALYTE_SUBTYPE_CONFLICT": 0,
    "DERIVED_MEASURE_CONFLICT": 0,
    "INSUFFICIENT_ANALYTE_EVIDENCE": 0,
}


def priority_key(r: dict[str, Any]) -> tuple:
    """1 analyte identity strength, 2 unit, 3 metadata completeness, 4 coverage.
    Coverage must NOT compensate for semantic conflict.
    """
    if r.get("hard_conflict"):
        return (-1, 0, 0, 0, 0)
    id_rank = _IDENTITY_RANK.get(str(r.get("identity_level") or ""), 0)
    unit = 1 if r.get("unit_exact") else 0
    ec = r.get("evidence_contract") or {}
    completeness = sum(1 for v in ec.values() if v)
    coverage = int(r.get("b_subjects_with_pairs") or 0) if r.get("analyte_ok") else 0
    return (id_rank, unit, completeness, coverage, float(r.get("priority_score") or 0))


def bucket_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        if not r.get("b_raw_code"):
            continue
        klass = r.get("candidate_class")
        if klass == "SEMANTICALLY_ALIGNED_CANDIDATE":
            buckets["evidence_complete"].append(r)
        elif klass == "SPECIMEN_MISSING":
            buckets["missing_specimen"].append(r)
        elif klass == "ASSAY_MISSING":
            buckets["missing_assay"].append(r)
        elif klass == "UNIT_CONVERSION_REVIEW_REQUIRED":
            buckets["unit_review_required"].append(r)
        elif klass == "ANALYTE_FAMILY_RETRIEVAL_ONLY":
            buckets["retrieval_only_family"].append(r)
        elif r.get("hard_conflict"):
            buckets["hard_conflict"].append(r)
        else:
            buckets["other"].append(r)
    return {k: sorted(v, key=priority_key, reverse=True) for k, v in buckets.items()}


def build_provider_input_requests(
    a_probe: dict[str, Any], b_probe: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    reqs = []
    if a_probe.get("SOURCE_A_SPECIMEN_METADATA_STATUS") in {
        "NOT_AVAILABLE_IN_SOURCE",
        "SOURCE_DOCUMENTATION_REQUIRED",
    }:
        reqs.append(
            {
                "source": "A",
                "field": "specimen/material",
                "document_needed": "Source A lab catalog / LIS specimen dictionary",
                "status": a_probe.get("SOURCE_A_SPECIMEN_METADATA_STATUS"),
                "why": "empty specimen never compatible; do not invent serum/blood",
            }
        )
    if a_probe.get("SOURCE_A_ASSAY_METADATA_STATUS") in {
        "NOT_AVAILABLE_IN_SOURCE",
        "SOURCE_DOCUMENTATION_REQUIRED",
    }:
        reqs.append(
            {
                "source": "A",
                "field": "method/assay",
                "document_needed": "Source A assay/method documentation",
                "status": a_probe.get("SOURCE_A_ASSAY_METADATA_STATUS"),
            }
        )
    if b_probe.get("catalog_material_all_empty") or b_probe.get(
        "SOURCE_B_SPECIMEN_METADATA_STATUS"
    ) == "NOT_AVAILABLE_IN_SOURCE":
        reqs.append(
            {
                "source": "B",
                "field": "analyses_catalog.material",
                "document_needed": "Filled specimen/material or provider dictionary",
                "status": "NOT_AVAILABLE_IN_SOURCE",
                "why": "column exists but all catalog rows empty is not evidence of specimen",
            }
        )
    if b_probe.get("SOURCE_B_ASSAY_METADATA_STATUS") == "SOURCE_DOCUMENTATION_REQUIRED":
        reqs.append(
            {
                "source": "B",
                "field": "method/assay",
                "document_needed": "Source B assay/method reference per catalog code",
            }
        )
    buckets = bucket_records(records)
    if buckets.get("retrieval_only_family") or buckets.get("hard_conflict"):
        reqs.append(
            {
                "source": "BOTH",
                "field": "analyte_identity_clarification",
                "document_needed": "Provider confirmation of exact analyte concepts",
                "why": "family-only and subtype conflicts cannot unlock accept/shadow",
            }
        )
    return {"version": VERSION, "requests": reqs, "n": len(reqs)}


def write_review_pack(
    *,
    root: Path,
    a_inv: dict[str, Any],
    b_inv: dict[str, Any],
    a_probe: dict[str, Any],
    b_probe: dict[str, Any],
    graph: dict[str, Any],
    controls: dict[str, Any],
    readiness: dict[str, Any],
    metadata_lineage: dict[str, Any],
    defects: dict[str, Any],
) -> dict[str, Any]:
    pack = Path(root) / REVIEW_PACK_DIR
    pack.mkdir(parents=True, exist_ok=True)

    records = list(graph.get("records") or [])
    safe_records = []
    for r in records:
        rr = {k: v for k, v in r.items() if k != "subject_ids_with_pairs"}
        if "outcome_specific_split" in rr and isinstance(rr["outcome_specific_split"], dict):
            rr["outcome_specific_split"] = {
                k: v
                for k, v in rr["outcome_specific_split"].items()
                if k != "subject_ids"
            }
        safe_records.append(rr)

    _write_json(pack / "cross-source-candidate-graph.json", {**{k: v for k, v in graph.items() if k != "records"}, "records": safe_records})
    _write_json(pack / "v02-analyte-identity-defects.json", defects)
    _write_json(pack / "negative-controls.json", controls)
    _write_json(pack / "metadata-recovery-lineage.json", metadata_lineage)
    _write_json(pack / "source-a-raw-metadata-probe.json", a_probe)
    _write_json(pack / "source-b-raw-metadata-probe.json", b_probe)
    _write_json(pack / "threshold-impact-after-discovery.json", readiness)
    reqs = build_provider_input_requests(a_probe, b_probe, safe_records)
    _write_json(pack / "provider-input-required.json", reqs)

    buckets = bucket_records(safe_records)
    _write_json(
        pack / "candidate-buckets.json",
        {k: [{"mapping_id": r["mapping_id"], "a_outcome": r.get("a_outcome"), "b_raw_code": r.get("b_raw_code"), "identity_level": r.get("identity_level"), "candidate_class": r.get("candidate_class")} for r in v[:100]] for k, v in buckets.items()},
    )

    # CSV priority queue — no human decisions
    csv_path = pack / "exhaustive-priority-review.csv"
    ranked = sorted(
        [r for r in safe_records if r.get("b_raw_code")],
        key=priority_key,
        reverse=True,
    )
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "rank",
                "mapping_id",
                "a_outcome",
                "a_unit",
                "b_raw_code",
                "b_unit",
                "identity_level",
                "candidate_class",
                "analyte_ok",
                "hard_conflict",
                "b_subjects_with_pairs",
                "priority_score",
            ],
        )
        w.writeheader()
        for i, r in enumerate(ranked[:500], start=1):
            w.writerow(
                {
                    "rank": i,
                    "mapping_id": r.get("mapping_id"),
                    "a_outcome": r.get("a_outcome"),
                    "a_unit": r.get("a_unit"),
                    "b_raw_code": r.get("b_raw_code"),
                    "b_unit": r.get("b_unit"),
                    "identity_level": r.get("identity_level"),
                    "candidate_class": r.get("candidate_class"),
                    "analyte_ok": r.get("analyte_ok"),
                    "hard_conflict": r.get("hard_conflict"),
                    "b_subjects_with_pairs": r.get("b_subjects_with_pairs"),
                    "priority_score": r.get("priority_score"),
                }
            )

    # Empty decision log — no ingest this release
    log = pack / "decision-log.jsonl"
    if not log.is_file():
        log.write_text("", encoding="utf-8")

    (pack / "reviewer-instructions.md").write_text(
        f"""# Reviewer instructions v{VERSION}

Priority order: analyte identity → unit → metadata completeness → B coverage.
Coverage NEVER overrides semantic conflict or family-only retrieval.

Buckets: evidence-complete / missing specimen / missing assay / unit review /
retrieval-only family / hard conflict / provider documentation required.

Do NOT accept family-only or hard-conflict rows.
This release creates no HUMAN_ACCEPTED decisions.
""",
        encoding="utf-8",
    )

    return {
        "version": VERSION,
        "DOMAIN_REVIEW_WORKBENCH_STATUS": "PASS",
        "pack_dir": REVIEW_PACK_DIR,
        "n_ranked": len(ranked),
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "provider_input_requests": reqs["n"],
        "human_decisions_executed": 0,
        "ok": True,
        "pack_sha_sample": _sha(csv_path),
    }
