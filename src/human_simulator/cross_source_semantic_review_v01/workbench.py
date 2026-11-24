"""Private domain-review workbench (no patient string data)."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.decision_log import decision_log_path
from human_simulator.cross_source_semantic_review_v01.policy import (
    RUNTIME_DIR,
    TYPED_DECISIONS,
    VERSION,
)
from human_simulator.cross_source_semantic_review_v01.readiness import (
    longitudinal_priority_score,
)
from human_simulator.cross_source_semantic_review_v01.t3_audit import render_t3_html


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_missing_evidence_report(classifications: list[dict[str, Any]]) -> dict[str, Any]:
    from collections import Counter

    cats: Counter[str] = Counter()
    for c in classifications:
        for m in c.get("missing_evidence") or []:
            cats[m] += 1
        for x in c.get("conflicts") or []:
            cats[f"conflict:{x}"] += 1
        if c.get("candidate_class"):
            cats[f"class:{c['candidate_class']}"] += 1
    return {
        "version": VERSION,
        "categories": dict(cats),
        "n_mappings": len(classifications),
        "ok": True,
    }


def build_semantic_conflicts(classifications: list[dict[str, Any]]) -> dict[str, Any]:
    conflicts = [
        {
            "mapping_id": c["mapping_id"],
            "a_outcome": c.get("a_outcome"),
            "b_raw_code": c.get("b_raw_code"),
            "candidate_class": c.get("candidate_class"),
            "conflicts": c.get("conflicts"),
            "missing_evidence": c.get("missing_evidence"),
            "a_analyte_hint": c.get("a_analyte_hint"),
            "b_catalog_analyte": c.get("b_catalog_analyte"),
            "b_catalog_name_ru": c.get("b_catalog_name_ru"),
        }
        for c in classifications
        if (c.get("conflicts") or c.get("candidate_class") in {
            "ANALYTE_AMBIGUOUS",
            "UNIT_CONFLICT",
            "SPECIMEN_CONFLICT",
            "ASSAY_CONFLICT",
            "NUMERIC_SEMANTICS_CONFLICT",
        })
    ]
    return {"version": VERSION, "n_conflict_rows": len(conflicts), "rows": conflicts}


def _priority_rows(classifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        [c for c in classifications if c.get("b_raw_code")],
        key=longitudinal_priority_score,
        reverse=True,
    )
    rows = []
    for i, c in enumerate(ranked, start=1):
        cov = c.get("coverage") or {}
        rows.append(
            {
                "priority": i,
                "mapping_id": c["mapping_id"],
                "a_outcome": c.get("a_outcome"),
                "a_unit": c.get("a_unit"),
                "b_raw_code": c.get("b_raw_code"),
                "b_unit": c.get("b_unit"),
                "candidate_class": c.get("candidate_class"),
                "prior_lineage_status": c.get("prior_lineage_status"),
                "b_subjects": cov.get("b_subjects"),
                "b_subjects_with_pairs": cov.get("b_subjects_with_pairs"),
                "b_strict_pairs": cov.get("b_strict_pairs"),
                "zero_shot_shadow_suitable_if_accepted": (
                    c.get("candidate_class")
                    not in {
                        "ANALYTE_AMBIGUOUS",
                        "UNIT_CONFLICT",
                        "NUMERIC_SEMANTICS_CONFLICT",
                        "INSUFFICIENT_EVIDENCE",
                    }
                    and int(cov.get("b_subjects_with_pairs") or 0) > 0
                ),
                "ranking_uses_model_performance": False,
            }
        )
    return rows


def render_priority_html(rows: list[dict[str, Any]]) -> str:
    tr = []
    for r in rows[:50]:
        tr.append(
            "<tr>"
            f"<td>{r['priority']}</td>"
            f"<td><code>{r['mapping_id'][:12]}…</code></td>"
            f"<td>{r.get('a_outcome')}</td>"
            f"<td>{r.get('a_unit')}</td>"
            f"<td>{r.get('b_raw_code')}</td>"
            f"<td>{r.get('b_unit')}</td>"
            f"<td>{r.get('candidate_class')}</td>"
            f"<td>{r.get('b_subjects')}</td>"
            f"<td>{r.get('b_subjects_with_pairs')}</td>"
            f"<td>{r.get('b_strict_pairs')}</td>"
            "</tr>"
        )
    body = "\n".join(tr)
    decisions = ", ".join(TYPED_DECISIONS)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Priority Outcome Mapping Review</title>
<style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;max-width:1200px}}
table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ccc;padding:.35rem .5rem;font-size:.85rem}}
th{{background:#f4f4f4;text-align:left}} .warn{{color:#8a1f11}}
</style></head><body>
<h1>Cross-Source Outcome Semantic Review</h1>
<p class="warn">No automatic ACCEPTED from label/code/unit. Ranked by longitudinal coverage only.</p>
<p>Typed decisions: {decisions}</p>
<table>
<thead><tr>
<th>#</th><th>mapping_id</th><th>A</th><th>A unit</th><th>B code</th><th>B unit</th>
<th>Class</th><th>B subj</th><th>Pairs subj</th><th>Pairs</th>
</tr></thead>
<tbody>
{body}
</tbody></table>
</body></html>
"""


def reviewer_instructions() -> str:
    return f"""# Domain Reviewer Instructions — Cross-Source Outcome Semantic Review v{VERSION}

## Purpose

Promote UNKNOWN/HYPOTHESIS mappings to typed decisions. Machine ranking is coverage-only.
Label + unit match is **never** sufficient for ACCEPTED.

## Required evidence for scientifically usable ACCEPTED

1. Analyte/concept equivalence
2. Specimen/material (empty ≠ empty)
3. Method/assay compatibility (missing assay blocks unrestricted ACCEPTED)
4. Unit identity **or** pre-approved conversion contract
5. Numeric semantics
6. Temporal semantics
7. Provenance isolation (A and B remain separate; no identity merge)
8. Explicit domain-review decision by a named reviewer

## Typed decisions

{", ".join(TYPED_DECISIONS)}

## Decision log (append-only)

Path: `private/cross-source-outcome-review-v01/decision-log.jsonl`

Each ACCEPTED_* entry **must** include:

- `reviewer_id`
- `reviewer_role`
- `reason`
- `evidence_file_hashes` (SHA-256 of evidence files used)

Do not rewrite prior lines. Append only.

## Forbidden

- Auto-accept from name/code/unit similarity
- Using model MAE / test performance for ranking or acceptance
- Unverified unit conversion
- Identity merge A↔B
- Training Current State Classifier in this stage
- Running A→B zero-shot without scientifically usable accepted mappings

## T3 (code 53)

See `t3-domain-review.html`. Do not auto-accept free T3.
"""


def write_private_workbench(
    *,
    root: Path,
    classifications: list[dict[str, Any]],
    strata: list[dict[str, Any]],
    t3_audit: dict[str, Any],
    readiness: dict[str, Any],
    conflicts: dict[str, Any],
    missing: dict[str, Any],
) -> dict[str, Any]:
    runtime = Path(root) / RUNTIME_DIR
    runtime.mkdir(parents=True, exist_ok=True)

    profiles = {
        "version": VERSION,
        "n": len(strata),
        "profiles": [
            {
                "mapping_id": s["mapping_id"],
                "prior_lineage_status": s.get("prior_lineage_status"),
                "source_a": {
                    k: v
                    for k, v in (s.get("source_a") or {}).items()
                    if k
                    not in {
                        # keep hashes; drop nothing sensitive — no patient strings present
                    }
                },
                "source_b": s.get("source_b"),
                "has_b_candidate": s.get("has_b_candidate"),
            }
            for s in strata
        ],
    }
    _write_json(runtime / "mapping-candidate-profiles.json", profiles)
    _write_json(runtime / "semantic-conflicts.json", conflicts)
    _write_json(runtime / "missing-evidence-report.json", missing)
    _write_json(runtime / "readiness-impact.json", readiness)

    priority = _priority_rows(classifications)
    (runtime / "priority-review.html").write_text(
        render_priority_html(priority), encoding="utf-8"
    )
    with (runtime / "priority-review.csv").open("w", encoding="utf-8", newline="") as f:
        if priority:
            w = csv.DictWriter(f, fieldnames=list(priority[0].keys()))
            w.writeheader()
            w.writerows(priority)
        else:
            f.write("priority,mapping_id\n")

    (runtime / "t3-domain-review.html").write_text(
        render_t3_html(t3_audit), encoding="utf-8"
    )
    (runtime / "reviewer-instructions.md").write_text(
        reviewer_instructions(), encoding="utf-8"
    )

    log_path = decision_log_path(runtime)
    if not log_path.is_file():
        log_path.write_text("", encoding="utf-8")

    required = [
        "priority-review.html",
        "priority-review.csv",
        "mapping-candidate-profiles.json",
        "semantic-conflicts.json",
        "missing-evidence-report.json",
        "t3-domain-review.html",
        "readiness-impact.json",
        "reviewer-instructions.md",
        "decision-log.jsonl",
    ]
    present = {n: (runtime / n).is_file() for n in required}
    hashes = {n: _sha(runtime / n) for n, ok in present.items() if ok}
    return {
        "version": VERSION,
        "DOMAIN_REVIEW_WORKBENCH_STATUS": (
            "PASS" if all(present.values()) else "FAIL"
        ),
        "runtime_dir": RUNTIME_DIR,
        "required_files": present,
        "file_hashes": hashes,
        "n_priority_rows": len(priority),
        "top_candidates": priority[:15],
        "ok": all(present.values()),
    }
