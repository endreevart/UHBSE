"""Phase 6 — reviewer workbench v2 (private packet)."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v012.policy import (
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    RUNTIME_DIR,
    TOP_N_REVIEW,
    VERSION,
)
from human_simulator.medication_reference_v012.providers.dsld import dsld_adapter_status


def _suggested_action(mapping: dict[str, Any]) -> str:
    status = mapping.get("final_mapping_status")
    if status == "INSUFFICIENT_SOURCE_DATA":
        return "INSUFFICIENT_SOURCE_DATA"
    if status in {"SUPPLEMENT_REFERENCE_REQUIRED", "PROVIDER_GAP"}:
        return "PROVIDER_GAP"
    if status == "HARD_CONFLICT":
        return "REJECT_CONFLICT"
    if int(mapping.get("n_candidates") or 0) == 0:
        return "PROVIDER_GAP"
    top = (mapping.get("candidates") or [None])[0]
    if top and top.get("hard_conflict"):
        return "REJECT_CONFLICT"
    if top and top.get("ingredient_compatibility") == "COMPATIBLE":
        return "ACCEPT_CANDIDATE"
    if top:
        return "AMBIGUOUS"
    return "INSUFFICIENT_SOURCE_DATA"


def write_reviewer_packet_v2(
    root: Path,
    *,
    profiles: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    readiness: dict[str, Any],
    baseline: dict[str, Any],
    exact_audit: dict[str, Any],
) -> dict[str, Any]:
    pack = root / RUNTIME_DIR / "review-pack"
    pack.mkdir(parents=True, exist_ok=True)
    prof_by = {str(p["source_medicine_id"]): p for p in profiles}

    # Priority: compatible candidates by episode coverage, then gaps
    ranked = sorted(
        mappings,
        key=lambda m: (
            0 if int(m.get("n_candidates") or 0) > 0 else 1,
            -int((m.get("episode_coverage") or {}).get("n_episodes") or 0),
            str(m["source_medicine_id"]),
        ),
    )
    priority = ranked[:TOP_N_REVIEW]

    rows = []
    conflicts = []
    gaps = []
    for m in priority:
        p = prof_by.get(str(m["source_medicine_id"])) or {}
        top = (m.get("candidates") or [None])[0]
        action = _suggested_action(m)
        cov = m.get("episode_coverage") or {}
        row = {
            "source_medicine_id": m["source_medicine_id"],
            "original_name": m.get("original_name"),
            "original_description": (p.get("original_description") or "")[:500],
            "parsed_ingredients": p.get("active_ingredient_tokens"),
            "parsed_form": p.get("dosage_form_tokens"),
            "parsed_strength": p.get("strength_tokens"),
            "parsed_route": p.get("route_hint"),
            "candidate_class": m.get("candidate_class"),
            "provider_concept_id": (top or {}).get("provider_concept_id"),
            "provider_trade_name": (top or {}).get("trade_name"),
            "provider_ingredients": (top or {}).get("ingredients_detected"),
            "provider_form": (top or {}).get("dosage_form"),
            "provider_strength": (top or {}).get("strength"),
            "provider_route": (top or {}).get("route"),
            "positive_evidence": (top or {}).get("positive_evidence") or m.get("positive_evidence"),
            "conflicts": (top or {}).get("negative_evidence") or m.get("negative_evidence"),
            "n_subjects": cov.get("n_subjects"),
            "n_episodes": cov.get("n_episodes"),
            "final_mapping_status": m.get("final_mapping_status"),
            "suggested_action": action,
            "explanation": m.get("human_readable_explanation"),
        }
        rows.append(row)
        if action == "REJECT_CONFLICT" or (top and top.get("hard_conflict")):
            conflicts.append(
                {
                    "source_medicine_id": m["source_medicine_id"],
                    "conflicts": row["conflicts"],
                    "provider_concept_id": row["provider_concept_id"],
                }
            )
        if action in {"PROVIDER_GAP", "INSUFFICIENT_SOURCE_DATA"}:
            gaps.append(
                {
                    "source_medicine_id": m["source_medicine_id"],
                    "candidate_class": m.get("candidate_class"),
                    "routing": m.get("routing"),
                    "status": m.get("final_mapping_status"),
                }
            )

    # Global gap report from all mappings
    all_gaps = [
        {
            "source_medicine_id": m["source_medicine_id"],
            "candidate_class": m.get("candidate_class"),
            "status": m.get("final_mapping_status"),
            "routing": m.get("routing"),
        }
        for m in mappings
        if m.get("final_mapping_status")
        in {
            "SUPPLEMENT_REFERENCE_REQUIRED",
            "PROVIDER_GAP",
            "INSUFFICIENT_SOURCE_DATA",
            "NO_MATCH",
        }
    ]

    # semantic conflicts among all mappings that had only hard conflicts / none
    all_conflicts = [
        {
            "source_medicine_id": m["source_medicine_id"],
            "original_name": m.get("original_name"),
            "status": m.get("final_mapping_status"),
            "note": "no_compatible_candidate_after_ingredient_first_veto",
        }
        for m in mappings
        if int(m.get("n_candidates") or 0) == 0
        and m.get("final_mapping_status") not in {"INSUFFICIENT_SOURCE_DATA"}
    ]

    html_path = pack / "priority-review.html"
    csv_path = pack / "priority-review.csv"
    conflicts_path = pack / "semantic-conflicts.json"
    gaps_path = pack / "provider-gap-report.json"
    # readiness already written to hierarchical-readiness-impact.json
    instr_path = pack / "reviewer-instructions.md"

    # CSV
    fields = [
        "source_medicine_id",
        "original_name",
        "n_episodes",
        "n_subjects",
        "parsed_ingredients",
        "parsed_route",
        "provider_concept_id",
        "provider_trade_name",
        "provider_ingredients",
        "provider_form",
        "provider_strength",
        "final_mapping_status",
        "suggested_action",
        "explanation",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    **r,
                    "parsed_ingredients": ",".join(r.get("parsed_ingredients") or []),
                    "provider_ingredients": ",".join(r.get("provider_ingredients") or []),
                }
            )

    # HTML
    blocks = []
    for r in rows:
        blocks.append(
            "<section style='border-top:1px solid #ccc;padding:12px 0'>"
            f"<h3>#{html.escape(str(r['source_medicine_id']))} "
            f"{html.escape(str(r.get('original_name') or ''))}</h3>"
            f"<p><b>Suggested:</b> {html.escape(r['suggested_action'])} — "
            f"{html.escape(str(r.get('final_mapping_status')))}</p>"
            f"<p><b>Source parsed:</b> ingredients={html.escape(str(r.get('parsed_ingredients')))}; "
            f"form={html.escape(str(r.get('parsed_form')))}; "
            f"strength={html.escape(str(r.get('parsed_strength')))}; "
            f"route={html.escape(str(r.get('parsed_route')))}</p>"
            f"<p><b>Provider:</b> {html.escape(str(r.get('provider_trade_name')))} "
            f"({html.escape(str(r.get('provider_concept_id')))}); "
            f"ings={html.escape(str(r.get('provider_ingredients')))}; "
            f"form={html.escape(str(r.get('provider_form')))}; "
            f"str={html.escape(str(r.get('provider_strength')))}</p>"
            f"<p><b>Positive:</b> {html.escape(str(r.get('positive_evidence')))}</p>"
            f"<p><b>Conflicts:</b> {html.escape(str(r.get('conflicts')))}</p>"
            f"<p><b>Coverage:</b> subjects={r.get('n_subjects')} episodes={r.get('n_episodes')}</p>"
            f"<p><b>Explanation:</b> {html.escape(str(r.get('explanation') or ''))}</p>"
            "</section>"
        )
    html_path.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Medication Semantic Review v0.1.2</title></head><body>"
        "<h1>Priority review (private)</h1>"
        "<p>No automatic HUMAN_ACCEPTED. Gates unchanged "
        f"(subjects≥{GATE_MIN_SUBJECTS}, episodes≥{GATE_MIN_EPISODES}, "
        f"test≥{GATE_MIN_TEST_SUBJECTS}).</p>"
        + "".join(blocks)
        + "</body></html>",
        encoding="utf-8",
    )

    conflicts_path.write_text(
        json.dumps(
            {
                "version": VERSION,
                "n": len(all_conflicts),
                "priority_conflicts": conflicts,
                "items": all_conflicts[:200],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    gaps_path.write_text(
        json.dumps(
            {
                "version": VERSION,
                "n": len(all_gaps),
                "by_status": {},
                "dsld_adapter": dsld_adapter_status(configured=False, network_enabled=False),
                "priority_gaps": gaps,
                "items": all_gaps[:300],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # fill by_status
    from collections import Counter

    gap_doc = json.loads(gaps_path.read_text(encoding="utf-8"))
    gap_doc["by_status"] = dict(Counter(x["status"] for x in all_gaps))
    gaps_path.write_text(json.dumps(gap_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    min_d = (readiness.get("provisional") or {}).get(
        "minimum_human_decisions_for_potential_ready"
    )
    instr_path.write_text(
        f"""# Reviewer instructions — Semantic Matcher v0.1.2

## Non-negotiables

- Do **not** auto-accept. No HUMAN_ACCEPTED without explicit reviewer + reason.
- Do **not** weaken readiness gates ({GATE_MIN_SUBJECTS}/{GATE_MIN_EPISODES}/{GATE_MIN_TEST_SUBJECTS}).
- Do **not** train association models on unconfirmed concepts.
- Append-only decision log in v0.1.1 remains immutable; existing `endreev` rejects stay.
- Marketing token «Про» has **zero** identity weight.

## Suggested actions

- `ACCEPT_CANDIDATE` — ingredient + form/route/strength evidence supports the ESKLP concept
- `REJECT_CONFLICT` — hard conflict (ingredient family, route, form, strength)
- `AMBIGUOUS` — multiple plausible candidates
- `PROVIDER_GAP` / `INSUFFICIENT_SOURCE_DATA` — needs better source text or supplement reference

## Exact match audit

Automatic EXACT (v0.1.1) audit status: **{exact_audit.get('status')}**

## Provisional minimum decisions

{json.dumps(min_d, ensure_ascii=False, indent=2) if min_d else "None — no provisional set passes unchanged gates."}

## Baseline

{json.dumps({k: baseline.get(k) for k in ('snapshot_ok','n_source_medicines','n_human_rejected','authoritative_accepted')}, ensure_ascii=False, indent=2)}
""",
        encoding="utf-8",
    )

    # Patient-field leak scan
    blob = html_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8")
    for forbidden in ("opaque_subject_key", "patient_id", "post_value", "pre_value", "episode_id"):
        if forbidden in blob:
            raise ValueError(f"patient_level_field_leaked:{forbidden}")

    return {
        "pack_dir": str(pack.relative_to(root)),
        "files": [
            str(html_path.relative_to(root)),
            str(csv_path.relative_to(root)),
            str(conflicts_path.relative_to(root)),
            str(gaps_path.relative_to(root)),
            str((pack / "hierarchical-readiness-impact.json").relative_to(root)),
            str(instr_path.relative_to(root)),
        ],
        "n_priority_rows": len(rows),
    }
