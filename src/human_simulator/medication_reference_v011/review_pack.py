"""Private domain-review package (CSV/JSON/HTML) — never packed into public ZIP."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.policy import RUNTIME_DIR, TOP_N_REVIEW, VERSION


def build_review_pack(root: Path, mappings: list[dict[str, Any]]) -> dict[str, Any]:
    pack_dir = root / RUNTIME_DIR / "review-pack"
    pack_dir.mkdir(parents=True, exist_ok=True)

    # Sort by coverage (mappings already prioritized)
    top20 = mappings[:TOP_N_REVIEW]
    rest = mappings[TOP_N_REVIEW:]

    def row_view(m: dict[str, Any]) -> dict[str, Any]:
        cands = m.get("candidates") or []
        suggested = "REVIEW"
        if m["drug_concept_status"] == "EXACT_PROVIDER_MATCH":
            suggested = "ACCEPT_EXACT"
        elif m["drug_concept_status"] == "NO_MATCH":
            suggested = "NO_PROVIDER_CANDIDATE"
        elif m["drug_concept_status"] in {"AMBIGUOUS", "CANDIDATE", "CONFLICT"}:
            suggested = "HUMAN_REVIEW"
        return {
            "source_medicine_id": m["source_medicine_id"],
            "original_name": m.get("original_name"),
            "original_description": m.get("original_description"),
            "n_episodes": (m.get("episode_coverage") or {}).get("n_episodes"),
            "n_subjects": (m.get("episode_coverage") or {}).get("n_subjects"),
            "status": m.get("drug_concept_status"),
            "provider": m.get("provider"),
            "provider_concept_id": m.get("provider_concept_id"),
            "inn": m.get("inn"),
            "product_name": m.get("product_name"),
            "strength": m.get("strength"),
            "form": m.get("form"),
            "ingredients": m.get("ingredients"),
            "methods": m.get("methods_tried"),
            "transformation_method": m.get("transformation_method"),
            "conflicts": m.get("conflict_reasons"),
            "ambiguity": m.get("ambiguity_reasons"),
            "n_candidates": m.get("n_candidates"),
            "candidates": cands,
            "suggested_decision": suggested,
            "provider_evidence_hash": m.get("provider_evidence_hash"),
            "provider_snapshot_hash": m.get("provider_snapshot_hash"),
            "source_medication_hash": m.get("source_medication_hash"),
        }

    queue = [row_view(m) for m in mappings]
    top_views = [row_view(m) for m in top20]

    json_path = pack_dir / "review-queue.json"
    json_path.write_text(
        json.dumps(
            {
                "version": VERSION,
                "n_total": len(queue),
                "n_top": len(top_views),
                "top20": top_views,
                "all": queue,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    csv_path = pack_dir / "review-queue.csv"
    fieldnames = [
        "source_medicine_id",
        "original_name",
        "n_episodes",
        "n_subjects",
        "status",
        "provider",
        "provider_concept_id",
        "inn",
        "product_name",
        "strength",
        "form",
        "n_candidates",
        "suggested_decision",
        "conflicts",
        "ambiguity",
        "transformation_method",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in queue:
            w.writerow(
                {
                    **r,
                    "conflicts": ";".join(r.get("conflicts") or []),
                    "ambiguity": ";".join(r.get("ambiguity") or []),
                }
            )

    html_path = pack_dir / "review-queue.html"
    html_path.write_text(_render_html(top_views, n_rest=len(rest)), encoding="utf-8")

    top_eps = sum(int(r.get("n_episodes") or 0) for r in top_views)
    return {
        "private_review_pack_dir": str(pack_dir.relative_to(root)),
        "files": [
            str(csv_path.relative_to(root)),
            str(json_path.relative_to(root)),
            str(html_path.relative_to(root)),
        ],
        "n_total": len(queue),
        "n_top20": len(top_views),
        "top20_episode_coverage": top_eps,
        "in_public_zip": False,
    }


def _render_html(top_views: list[dict[str, Any]], *, n_rest: int) -> str:
    rows = []
    for r in top_views:
        cands = r.get("candidates") or []
        cand_html = "<ul>" + "".join(
            f"<li><code>{html.escape(str(c.get('provider_concept_id')))}</code> "
            f"{html.escape(str(c.get('method')))} — "
            f"{html.escape(str(c.get('trade_name') or ''))} / "
            f"{html.escape(str(c.get('inn') or ''))}</li>"
            for c in cands[:5]
        ) + "</ul>"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(r['source_medicine_id']))}</td>"
            f"<td>{html.escape(str(r.get('original_name') or ''))}</td>"
            f"<td>{r.get('n_episodes')}</td>"
            f"<td>{r.get('n_subjects')}</td>"
            f"<td>{html.escape(str(r.get('status')))}</td>"
            f"<td>{html.escape(str(r.get('suggested_decision')))}</td>"
            f"<td>{cand_html}</td>"
            "</tr>"
        )
    body = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/>
<title>UHBSE medication domain review (private)</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 1.5rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; vertical-align: top; }}
th {{ background: #f4f4f4; text-align: left; }}
code {{ font-size: 12px; }}
.note {{ color: #444; margin-bottom: 1rem; }}
</style></head><body>
<h1>Private domain-review pack (top 20)</h1>
<p class="note">Read-only local report. Not for public review ZIP.
Remaining queue size: {n_rest}. CLINICAL_USE_PROHIBITED.</p>
<table>
<thead><tr>
<th>medicine_id</th><th>name</th><th>episodes</th><th>subjects</th>
<th>status</th><th>suggested</th><th>candidates</th>
</tr></thead>
<tbody>
{body}
</tbody></table>
</body></html>
"""
