"""Private reviewer packet + provider-gap planning."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v014.policy import (
    CAPABLE_LEVELS,
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    RUNTIME_DIR,
    VERSION,
)


def write_provider_gaps(
    classified: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    # Rank by episode coverage among non-capable / family / insufficient
    gaps = []
    for row in classified:
        if row["typed_level"] in CAPABLE_LEVELS and row.get("strength_stratum") not in {
            "unknown_strength",
            "strength_conflict",
        }:
            continue
        missing = []
        ec = row.get("evidence_completeness") or {}
        if not ec.get("ingredient"):
            missing.append("ingredient")
        if not ec.get("chemical_form_specific"):
            missing.append("chemical_form")
        if not ec.get("route"):
            missing.append("route")
        if not ec.get("strength"):
            missing.append("strength")
        if not ec.get("product_identity") and row["typed_level"] == "INGREDIENT_FAMILY_ONLY":
            missing.append("product_identity_or_specific_composition")
        ref = "ESKLP"
        if row.get("candidate_class") == "DIETARY_SUPPLEMENT_CANDIDATE":
            ref = "supplement_reference"
        elif row["typed_level"] == "INSUFFICIENT_SOURCE_EVIDENCE":
            ref = "source_label_or_manual_domain_review"
        cov = row.get("episode_coverage") or {}
        gaps.append(
            {
                "source_medicine_id": row["source_medicine_id"],
                "original_name": row.get("original_name"),
                "typed_level": row["typed_level"],
                "n_episodes": int(cov.get("n_episodes") or 0),
                "n_subjects": int(cov.get("n_subjects") or 0),
                "missing_fields": missing,
                "reference_needed": ref,
                "potential_if_filled": (
                    "recompute_strict_cluster_readiness_after_evidence_upgrade"
                ),
            }
        )
    gaps.sort(key=lambda g: (-g["n_episodes"], -g["n_subjects"], g["source_medicine_id"]))
    return {
        "version": VERSION,
        "n": len(gaps),
        "top_by_episode_impact": gaps[:40],
        "note": "No external API calls; patient-level data not transmitted",
    }


def write_reviewer_packet(
    root: Path,
    *,
    classified: list[dict[str, Any]],
    clusters_doc: dict[str, Any],
    coverage_rows: list[dict[str, Any]],
    readiness: dict[str, Any],
    top_clusters: list[dict[str, Any]],
    gaps: dict[str, Any],
    baseline: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    pack = root / RUNTIME_DIR / "review-pack"
    pack.mkdir(parents=True, exist_ok=True)

    (pack / "strict-concept-clusters.json").write_text(
        json.dumps(clusters_doc, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    (pack / "concept-episode-coverage.json").write_text(
        json.dumps(
            {"version": VERSION, "clusters": coverage_rows},
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    min_sets = (readiness.get("provisional") or {}).get("minimum_honest_decision_sets")
    (pack / "minimum-decision-sets.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "minimum_honest_decision_sets": min_sets,
                "all_attempted": (readiness.get("provisional") or {}).get(
                    "all_attempted_sets"
                ),
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    (pack / "provider-gaps-by-episode-impact.json").write_text(
        json.dumps(gaps, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Priority CSV/HTML — top clusters + their capable members
    by_id = {c["source_medicine_id"]: c for c in classified}
    rows = []
    for tc in top_clusters:
        for mid in tc.get("source_medicine_ids") or []:
            c = by_id.get(mid)
            if not c:
                continue
            allowed = (
                "PRODUCT_IDENTITY_ACCEPTED"
                if c["typed_level"] == "PRODUCT_IDENTITY_CANDIDATE"
                else (
                    "INGREDIENT_FORM_ROUTE_ACCEPTED"
                    if c["typed_level"] in CAPABLE_LEVELS
                    else "INGREDIENT_FAMILY_ONLY|INSUFFICIENT|REJECT"
                )
            )
            if c["typed_level"] != "PRODUCT_IDENTITY_CANDIDATE" and "PRODUCT" in allowed:
                pass
            if c["typed_level"] in {
                "INGREDIENT_FORM_ROUTE_CANDIDATE",
                "INGREDIENT_FORM_ROUTE_STRENGTH_CANDIDATE",
            }:
                allowed = "INGREDIENT_FORM_ROUTE_ACCEPTED (not PRODUCT_IDENTITY)"
            rows.append(
                {
                    "cluster_id": tc["provider_neutral_concept_id"],
                    "cluster_key": tc["cluster_key"],
                    "source_medicine_id": mid,
                    "original_name": c.get("original_name"),
                    "typed_level": c["typed_level"],
                    "ingredients": ",".join(c.get("active_ingredient_set") or []),
                    "chemical_form": c.get("chemical_form"),
                    "route": c.get("route"),
                    "dosage_form_family": c.get("dosage_form_family"),
                    "strength_stratum": c.get("strength_stratum"),
                    "provider_trade": c.get("provider_trade_name"),
                    "provider_concept_id": c.get("provider_concept_id"),
                    "n_subjects_cluster": tc.get("n_subjects"),
                    "n_episodes_cluster": tc.get("n_episodes"),
                    "n_test_subjects_cluster": tc.get("n_test_subjects"),
                    "allowed_typed_decision": allowed,
                    "evidence_hash": c.get("evidence_hash"),
                    "blockers_note": tc.get("why_merge_or_not"),
                }
            )

    csv_path = pack / "intervention-concept-priority.csv"
    fields = list(rows[0].keys()) if rows else ["source_medicine_id"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    sections = [
        "<h1>Intervention concept priority (private)</h1>",
        f"<p>Status: <b>{html.escape(status)}</b></p>",
        f"<p>Gates unchanged: subjects≥{GATE_MIN_SUBJECTS}, episodes≥{GATE_MIN_EPISODES}, "
        f"test≥{GATE_MIN_TEST_SUBJECTS}. Provisional READY always false. "
        "No association training.</p>",
        "<h2>Top clusters</h2>",
    ]
    for tc in top_clusters:
        sections.append(
            "<section style='border-top:1px solid #ccc;padding:10px 0'>"
            f"<h3>{html.escape(tc['provider_neutral_concept_id'])}</h3>"
            f"<p><b>Key:</b> {html.escape(str(tc.get('cluster_key')))}</p>"
            f"<p>subjects={tc.get('n_subjects')} episodes={tc.get('n_episodes')} "
            f"test_subjects={tc.get('n_test_subjects')} capable={tc.get('n_capable')} "
            f"grains_pass={tc.get('n_grains_passing_gates')}</p>"
            f"<p>{html.escape(str(tc.get('why_merge_or_not')))}</p>"
            f"<p>IDs: {html.escape(','.join(tc.get('source_medicine_ids') or []))}</p>"
            "</section>"
        )
    sections.append("<h2>Member cards</h2>")
    for r in rows[:60]:
        sections.append(
            "<section style='border-top:1px solid #eee;padding:8px 0'>"
            f"<h4>#{html.escape(str(r['source_medicine_id']))} "
            f"{html.escape(str(r.get('original_name')))}</h4>"
            f"<p>level={html.escape(str(r['typed_level']))}; "
            f"ings={html.escape(str(r['ingredients']))}; chem={html.escape(str(r['chemical_form']))}; "
            f"route={html.escape(str(r['route']))}; form={html.escape(str(r['dosage_form_family']))}; "
            f"strength={html.escape(str(r['strength_stratum']))}</p>"
            f"<p>provider={html.escape(str(r.get('provider_trade')))} "
            f"({html.escape(str(r.get('provider_concept_id')))})</p>"
            f"<p><b>Allowed decision:</b> {html.escape(str(r['allowed_typed_decision']))}</p>"
            f"<p>evidence_hash={html.escape(str(r.get('evidence_hash')))}</p>"
            "</section>"
        )
    html_path = pack / "intervention-concept-priority.html"
    html_path.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
        + "".join(sections)
        + "</body></html>",
        encoding="utf-8",
    )

    instr = pack / "reviewer-instructions.md"
    instr.write_text(
        f"""# Reviewer instructions — Intervention Cohort Discovery v0.1.4

## Status

`{status}`

## Rules

- Do **not** create HUMAN_ACCEPTED / typed accepts automatically
- Do **not** propose PRODUCT_IDENTITY when only ingredient/form is evidenced
- Family-only cannot open authoritative cohort
- Gates remain {GATE_MIN_SUBJECTS}/{GATE_MIN_EPISODES}/{GATE_MIN_TEST_SUBJECTS}
- Association baseline stays NOT_RUN
- v0.1.1 decision log immutable; use v0.1.3 `review decide` for typed decisions

## Minimum honest decision sets

```json
{json.dumps(min_sets, ensure_ascii=False, indent=2) if min_sets else "null"}
```

## Baseline

```json
{json.dumps({k: baseline.get(k) for k in ('snapshot_ok','n_compatible_candidates','scientifically_usable_accepted','decision_log_ok')}, ensure_ascii=False, indent=2)}
```
""",
        encoding="utf-8",
    )

    blob = html_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8")
    for forbidden in ("opaque_subject_key", "patient_id", "post_value", "pre_value"):
        if forbidden in blob:
            raise ValueError(f"patient_level_leaked:{forbidden}")

    return {
        "pack_dir": str(pack.relative_to(root)),
        "files": [
            str((pack / name).relative_to(root))
            for name in (
                "intervention-concept-priority.html",
                "intervention-concept-priority.csv",
                "strict-concept-clusters.json",
                "concept-episode-coverage.json",
                "minimum-decision-sets.json",
                "provider-gaps-by-episode-impact.json",
                "reviewer-instructions.md",
            )
        ],
    }
