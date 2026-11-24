"""T3 (code 53) full domain-review audit — no automatic acceptance."""

from __future__ import annotations

from typing import Any

from human_simulator.cross_source_semantic_review_v01.policy import VERSION


def build_t3_audit(
    *,
    universe_strata: list[dict[str, Any]],
    classifications: list[dict[str, Any]],
    inventory_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """Show all specimen/method/assay strata and include/exclude volumes per decision."""
    by_id = {c["mapping_id"]: c for c in classifications}
    t3_strata = [
        s
        for s in universe_strata
        if s.get("has_b_candidate")
        and str((s.get("source_b") or {}).get("raw_code") or "") == "53"
    ]
    code53_inventory = [
        r for r in inventory_catalog if str(r.get("raw_code") or "") == "53"
    ]

    decision_scenarios: list[dict[str, Any]] = []
    for s in t3_strata:
        b = s["source_b"]
        c = by_id.get(s["mapping_id"]) or {}
        n_subj = int(b.get("n_subjects") or 0)
        n_pairs = int(b.get("n_strict_consecutive_pairs") or 0)
        n_ge2 = int(b.get("n_subjects_with_pairs") or b.get("n_subjects_with_ge2") or 0)
        unit = str(b.get("unit") or "")
        scenarios = {
            "REJECTED": {
                "included_subjects": 0,
                "excluded_subjects": n_subj,
                "included_pairs": 0,
                "excluded_pairs": n_pairs,
            },
            "INSUFFICIENT_EVIDENCE": {
                "included_subjects": 0,
                "excluded_subjects": n_subj,
                "included_pairs": 0,
                "excluded_pairs": n_pairs,
                "note": "no transfer until evidence complete",
            },
            "AMBIGUOUS": {
                "included_subjects": 0,
                "excluded_subjects": n_subj,
                "included_pairs": 0,
                "excluded_pairs": n_pairs,
            },
            "ACCEPTED_WITH_RESTRICTIONS": {
                "included_subjects": n_ge2,
                "excluded_subjects": max(0, n_subj - n_ge2),
                "included_pairs": n_pairs,
                "excluded_pairs": 0,
                "restrictions": [
                    "specimen_unverified",
                    "method_assay_unverified",
                    "unit_stratum_only:" + unit,
                ],
            },
            "ACCEPTED_COMPARABLE": {
                "included_subjects": n_ge2,
                "excluded_subjects": max(0, n_subj - n_ge2),
                "included_pairs": n_pairs,
                "excluded_pairs": 0,
                "blocked_until": [
                    "specimen_evidence",
                    "method_assay_evidence",
                    "domain_reviewer_accept",
                ],
                "machine_auto_accept": False,
            },
        }
        decision_scenarios.append(
            {
                "mapping_id": s["mapping_id"],
                "a_outcome": (s.get("source_a") or {}).get("outcome"),
                "a_unit": (s.get("source_a") or {}).get("unit"),
                "b_raw_code": "53",
                "b_unit": unit,
                "candidate_class": c.get("candidate_class"),
                "prior_lineage_status": s.get("prior_lineage_status"),
                "specimen_material": b.get("specimen_material"),
                "specimen_empty": b.get("specimen_material_empty", True),
                "method_assay": b.get("method_assay"),
                "method_empty": b.get("method_assay_empty", True),
                "volumes": {
                    "n_subjects": n_subj,
                    "n_components": int(b.get("n_components") or 0),
                    "n_numeric": int(b.get("n_numeric") or 0),
                    "n_dated_numeric": int(b.get("n_dated_numeric") or 0),
                    "n_subjects_with_pairs": n_ge2,
                    "n_strict_consecutive_pairs": n_pairs,
                },
                "decision_include_exclude": scenarios,
            }
        )

    return {
        "version": VERSION,
        "T3_DOMAIN_REVIEW_STATUS": "DOMAIN_REVIEW_REQUIRED",
        "code": "53",
        "catalog_analyte": "free_t3",
        "catalog_name_ru_expected": "Трийодтиронин свободный",
        "auto_accepted": False,
        "n_mapping_strata_code_53": len(t3_strata),
        "n_inventory_unit_strata_code_53": len(code53_inventory),
        "inventory_unit_strata": [
            {
                "unit": r.get("unit"),
                "n_components": r.get("n_components"),
                "n_numeric": r.get("n_numeric"),
                "n_subjects": r.get("n_subjects"),
            }
            for r in code53_inventory
        ],
        "specimen_method_note": (
            "analyses_catalog.material is empty for all catalog rows in live Source B; "
            "canonical observation has no specimen/method columns usable for mapping. "
            "Empty ≠ equivalent. Do not auto-accept T3."
        ),
        "strata": decision_scenarios,
        "ok": True,
    }


def render_t3_html(audit: dict[str, Any]) -> str:
    rows = []
    for s in audit.get("strata") or []:
        v = s.get("volumes") or {}
        rows.append(
            "<tr>"
            f"<td>{s.get('a_outcome')}</td>"
            f"<td>{s.get('a_unit')}</td>"
            f"<td>{s.get('b_unit')}</td>"
            f"<td>{s.get('candidate_class')}</td>"
            f"<td>{v.get('n_subjects')}</td>"
            f"<td>{v.get('n_subjects_with_pairs')}</td>"
            f"<td>{v.get('n_strict_consecutive_pairs')}</td>"
            f"<td>{'empty' if s.get('specimen_empty') else s.get('specimen_material')}</td>"
            f"<td>{'empty' if s.get('method_empty') else s.get('method_assay')}</td>"
            "</tr>"
        )
    body = "\n".join(rows) or "<tr><td colspan='9'>No code-53 mapping strata</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>T3 Domain Review — code 53</title>
<style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;max-width:1100px}}
table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ccc;padding:.4rem .6rem;font-size:.9rem}}
th{{background:#f4f4f4;text-align:left}} .warn{{color:#8a1f11;font-weight:600}}
</style></head><body>
<h1>T3 Domain Review (code 53)</h1>
<p class="warn">AUTO-ACCEPT FORBIDDEN. Status: {audit.get('T3_DOMAIN_REVIEW_STATUS')}</p>
<p>{audit.get('specimen_method_note')}</p>
<table>
<thead><tr>
<th>A outcome</th><th>A unit</th><th>B unit</th><th>Class</th>
<th>B subjects</th><th>With pairs</th><th>Pairs</th><th>Specimen</th><th>Assay</th>
</tr></thead>
<tbody>
{body}
</tbody></table>
<p>Inventory unit strata for code 53: {len(audit.get('inventory_unit_strata') or [])}</p>
</body></html>
"""
