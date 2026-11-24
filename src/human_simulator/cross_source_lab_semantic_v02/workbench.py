"""Private review pack for lab semantic discovery v0.2."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v02.policy import (
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


def priority_key(r: dict[str, Any]) -> tuple:
    """1 semantic completeness, 2 no hard conflicts, 3 pairs, 4 test, 5 strict pairs."""
    ec = r.get("evidence_contract") or {}
    completeness = sum(1 for v in ec.values() if v)
    return (
        0 if r.get("hard_conflict") else 1,
        completeness,
        int(r.get("b_subjects_with_pairs") or 0),
        int((r.get("outcome_specific_split") or {}).get("by_role_subjects_with_pairs", {}).get("test") or 0),
        int(r.get("b_strict_pairs") or 0),
        float(r.get("priority_score") or 0),
    )


def build_provider_input_requests(
    a_meta: dict[str, Any], b_inv: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    reqs = []
    if (a_meta.get("specimen") or {}).get("status") == "MISSING_SOURCE_DOCUMENTATION_REQUIRED":
        reqs.append(
            {
                "source": "A",
                "field": "specimen/material",
                "document_needed": "Source A lab catalog / LIS specimen dictionary",
                "why": "specimen required for SCIENTIFICALLY_USABLE accept",
                "blocks": ["SCIENTIFICALLY_USABLE for all A grains lacking specimen"],
            }
        )
    if (a_meta.get("assay") or {}).get("status") == "MISSING_SOURCE_DOCUMENTATION_REQUIRED":
        reqs.append(
            {
                "source": "A",
                "field": "method/assay",
                "document_needed": "Source A assay/method documentation per analysis code",
                "why": "assay compatibility required for unrestricted scientific accept",
                "blocks": ["ACCEPTED_COMPARABLE without assay evidence"],
            }
        )
    if b_inv.get("catalog_material_all_empty"):
        codes = sorted(
            {
                str(r.get("b_raw_code"))
                for r in records
                if r.get("b_raw_code")
                and "specimen_material" in (r.get("missing_evidence") or [])
            }
        )[:30]
        reqs.append(
            {
                "source": "B",
                "field": "analyses_catalog.material",
                "source_codes_sample": codes,
                "document_needed": "Source B specimen/material dictionary or filled material column",
                "why": "empty specimen ≠ matched specimen",
                "blocks": ["SCIENTIFICALLY_USABLE for specimen-missing candidates"],
            }
        )
        reqs.append(
            {
                "source": "B",
                "field": "method/assay",
                "document_needed": "Source B assay/method reference per catalog code",
                "why": "assay missing blocks unrestricted ACCEPTED",
                "blocks": ["ACCEPTED_COMPARABLE"],
            }
        )
    return {"version": VERSION, "requests": reqs, "n": len(reqs)}


def write_review_pack(
    *,
    root: Path,
    a_inv: dict[str, Any],
    b_inv: dict[str, Any],
    graph: dict[str, Any],
    controls: dict[str, Any],
    splits: dict[str, Any],
    readiness: dict[str, Any],
    metadata_lineage: dict[str, Any],
) -> dict[str, Any]:
    pack = Path(root) / REVIEW_PACK_DIR
    pack.mkdir(parents=True, exist_ok=True)

    records = list(graph.get("records") or [])
    # public-safe graph without subject id lists
    safe_records = []
    for r in records:
        rr = {k: v for k, v in r.items() if k != "subject_ids_with_pairs"}
        if "outcome_specific_split" in rr and isinstance(rr["outcome_specific_split"], dict):
            split = {
                k: v
                for k, v in rr["outcome_specific_split"].items()
                if k != "subject_ids"
            }
            rr["outcome_specific_split"] = split
        safe_records.append(rr)

    ranked = sorted(
        [r for r in safe_records if r.get("b_raw_code")],
        key=priority_key,
        reverse=True,
    )
    for i, r in enumerate(ranked, 1):
        r["priority"] = i

    _write_json(
        pack / "full-source-a-provider-inventory.json",
        {k: v for k, v in a_inv.items() if k != "grains"}
        | {
            "grains": [
                {kk: vv for kk, vv in g.items() if kk != "raw_row"}
                for g in a_inv.get("grains") or []
            ]
        },
    )
    # B inventory: drop huge strata from private pack? User asked for full inventory in pack.
    # Keep aggregates + strata without inventing — OK private.
    _write_json(
        pack / "full-source-b-outcome-unit-inventory.json",
        {
            **{k: v for k, v in b_inv.items() if k != "strata"},
            "strata": [
                {kk: vv for kk, vv in s.items() if kk != "subject_ids_with_pairs"}
                for s in (b_inv.get("strata") or [])
            ],
        },
    )
    _write_json(
        pack / "cross-source-candidate-graph.json",
        {**{k: v for k, v in graph.items() if k != "records"}, "records": safe_records},
    )
    conflicts = [
        r
        for r in safe_records
        if r.get("hard_conflict") or r.get("conflicts")
    ]
    _write_json(
        pack / "semantic-conflicts.json",
        {"version": VERSION, "n": len(conflicts), "rows": conflicts[:500]},
    )
    _write_json(pack / "metadata-recovery-lineage.json", metadata_lineage)
    _write_json(
        pack / "provider-input-required.json",
        build_provider_input_requests(
            a_inv.get("metadata_lineage") or {}, b_inv, safe_records
        ),
    )
    _write_json(pack / "outcome-specific-b-split-coverage.json", splits)
    _write_json(pack / "threshold-impact-after-discovery.json", readiness)
    _write_json(pack / "negative-controls.json", controls)

    # CSV / HTML priority
    fields = [
        "priority",
        "mapping_id",
        "a_outcome",
        "a_unit",
        "b_raw_code",
        "b_unit",
        "b_catalog_name_ru",
        "candidate_class",
        "hard_conflict",
        "b_subjects",
        "b_subjects_with_pairs",
        "b_strict_pairs",
        "priority_score",
    ]
    with (pack / "exhaustive-priority-review.csv").open(
        "w", encoding="utf-8", newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(ranked)

    def _table(rows: list[dict[str, Any]], limit: int = 80) -> str:
        tr = []
        for r in rows[:limit]:
            tr.append(
                "<tr>"
                f"<td>{r.get('priority')}</td>"
                f"<td>{r.get('a_outcome')}</td>"
                f"<td>{r.get('a_unit')}</td>"
                f"<td>{r.get('b_raw_code')}</td>"
                f"<td>{r.get('b_unit')}</td>"
                f"<td>{(r.get('b_catalog_name_ru') or '')[:40]}</td>"
                f"<td>{r.get('candidate_class')}</td>"
                f"<td>{r.get('b_subjects_with_pairs')}</td>"
                f"<td>{r.get('b_strict_pairs')}</td>"
                "</tr>"
            )
        return "\n".join(tr)

    (pack / "exhaustive-priority-review.html").write_text(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>Exhaustive Priority Review v{VERSION}</title>
<style>body{{font-family:system-ui;margin:2rem}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:.3rem;font-size:.85rem}}th{{background:#f4f4f4}}
.warn{{color:#8a1f11}}</style></head><body>
<h1>Exhaustive Cross-Source Lab Discovery</h1>
<p class="warn">No automatic ACCEPTED. Ranking ignores model performance.</p>
<table><thead><tr>
<th>#</th><th>A</th><th>A unit</th><th>B code</th><th>B unit</th><th>B name</th>
<th>Class</th><th>Pairs subj</th><th>Pairs</th>
</tr></thead><tbody>{_table(ranked)}</tbody></table>
</body></html>
""",
        encoding="utf-8",
    )

    t3 = [r for r in ranked if str(r.get("b_raw_code")) == "53" or "Т3" in str(r.get("a_outcome"))]
    thyroid = [
        r
        for r in ranked
        if any(
            x in str(r.get("a_outcome") or "")
            for x in ("Т3", "Т4", "ТТГ")
        )
        or str(r.get("b_raw_code")) in {"53", "54", "55", "56", "1"}
    ]
    (pack / "t3-review-v02.html").write_text(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>T3 Review v02</title>
<style>body{{font-family:system-ui;margin:2rem}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:.3rem}}</style></head><body>
<h1>T3 Domain Review v0.2</h1>
<p>Auto-accept forbidden. Exhaustive candidates only.</p>
<table><thead><tr><th>#</th><th>A</th><th>unit</th><th>B</th><th>B unit</th><th>name</th><th>class</th><th>pairs</th></tr></thead>
<tbody>{_table(t3, 50)}</tbody></table></body></html>
""",
        encoding="utf-8",
    )
    (pack / "thyroid-panel-review.html").write_text(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Thyroid Panel Review</title>
<style>body{{font-family:system-ui;margin:2rem}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:.3rem}}</style></head><body>
<h1>Thyroid Panel Review</h1>
<p>Negative controls: ТТГ≠free T4; ТТГ≠seconds; free≠total.</p>
<table><thead><tr><th>#</th><th>A</th><th>unit</th><th>B</th><th>B unit</th><th>name</th><th>class</th><th>pairs</th></tr></thead>
<tbody>{_table(thyroid, 80)}</tbody></table></body></html>
""",
        encoding="utf-8",
    )

    (pack / "reviewer-instructions.md").write_text(
        f"""# Reviewer Instructions — Lab Semantic Discovery v{VERSION}

## Ranking
1. Semantic completeness  
2. No hard conflicts  
3. B subjects with pairs  
4. B test subjects  
5. B strict pairs  

Model performance is forbidden in ranking/acceptance.

## Levels
- DOMAIN_ACCEPTED — human decision only
- TECHNICAL_SHADOW_ELIGIBLE — analyte+unit+numeric/temporal; specimen/assay may be unverified
- SCIENTIFICALLY_USABLE — full evidence contract including specimen+assay

## Hard conflicts
Cannot ACCEPTED_WITH_RESTRICTIONS until new evidence + stratum rebuild + new classification hash
removes hard-conflict class. `new_evidence_artifact_hash` alone is insufficient.
""",
        encoding="utf-8",
    )

    log = pack / "decision-log.jsonl"
    if not log.is_file():
        log.write_text("", encoding="utf-8")

    required = [
        "exhaustive-priority-review.html",
        "exhaustive-priority-review.csv",
        "full-source-a-provider-inventory.json",
        "full-source-b-outcome-unit-inventory.json",
        "cross-source-candidate-graph.json",
        "semantic-conflicts.json",
        "metadata-recovery-lineage.json",
        "provider-input-required.json",
        "outcome-specific-b-split-coverage.json",
        "t3-review-v02.html",
        "thyroid-panel-review.html",
        "threshold-impact-after-discovery.json",
        "reviewer-instructions.md",
        "decision-log.jsonl",
    ]
    present = {n: (pack / n).is_file() for n in required}
    return {
        "version": VERSION,
        "DOMAIN_REVIEW_WORKBENCH_STATUS": "PASS" if all(present.values()) else "FAIL",
        "pack_dir": REVIEW_PACK_DIR,
        "required_files": present,
        "file_hashes": {n: _sha(pack / n) for n, ok in present.items() if ok},
        "n_priority": len(ranked),
        "top": ranked[:20],
        "ok": all(present.values()),
    }
