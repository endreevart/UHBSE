"""Private reviewer packets for 813 and omega-3 priority set."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v013.policy import (
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    RUNTIME_DIR,
    VERSION,
)


def write_813_card(root: Path, card: dict[str, Any]) -> Path:
    path = root / RUNTIME_DIR / "review-pack" / "813-exact-review.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    s = card.get("source") or {}
    p = card.get("provider") or {}
    diffs = card.get("diffs") or []
    matches = card.get("matches") or []
    path.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>813 Exact Review</title></head><body>"
        "<h1>813 — Нитрофурал / Фурациллин</h1>"
        "<p><b>Eligibility:</b> "
        f"{html.escape(str(card.get('eligibility')))}</p>"
        "<p>SCIENTIFICALLY_USABLE_ACCEPTED="
        f"{card.get('SCIENTIFICALLY_USABLE_ACCEPTED')} "
        "(historical EXACT unchanged)</p>"
        "<h2>Source</h2>"
        f"<pre>{html.escape(json.dumps(s, ensure_ascii=False, indent=2))}</pre>"
        "<h2>ESKLP candidate</h2>"
        f"<pre>{html.escape(json.dumps(p, ensure_ascii=False, indent=2))}</pre>"
        f"<h2>Matches</h2><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in matches)}</ul>"
        f"<h2>Diffs / doubts</h2><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in diffs)}</ul>"
        "<h2>Allowed decisions</h2>"
        "<p>PRODUCT_IDENTITY_ACCEPTED | INGREDIENT_FORM_ROUTE_ACCEPTED | "
        "AMBIGUOUS | HUMAN_REJECTED</p>"
        "<p>No automatic acceptance.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    return path


def write_omega3_packet(
    root: Path, cards: list[dict[str, Any]], omacor: dict[str, Any]
) -> dict[str, str]:
    pack = root / RUNTIME_DIR / "review-pack"
    pack.mkdir(parents=True, exist_ok=True)
    html_path = pack / "omega3-priority-review.html"
    csv_path = pack / "omega3-priority-review.csv"

    sections = [
        "<h1>Omega-3 evidence review (private)</h1>",
        "<p>Zhiznivek / generic omega-3 / fish oil are <b>not</b> product-identity "
        "to Омакор. Gates unchanged "
        f"({GATE_MIN_SUBJECTS}/{GATE_MIN_EPISODES}/{GATE_MIN_TEST_SUBJECTS}).</p>",
        "<h2>ESKLP Омакор</h2>",
        f"<pre>{html.escape(json.dumps(omacor, ensure_ascii=False, indent=2))}</pre>",
    ]
    for c in cards:
        sections.append(
            "<section style='border-top:1px solid #ccc;padding:12px 0'>"
            f"<h3>#{html.escape(str(c['source_medicine_id']))} "
            f"{html.escape(str(c.get('original_name')))}</h3>"
            f"<p><b>Suggested action:</b> {html.escape(str(c.get('suggested_review_action')))}</p>"
            f"<p><b>Neutral concept:</b> {html.escape(str(c.get('provider_neutral_concept')))}</p>"
            f"<p><b>Chemical form:</b> {html.escape(str(c.get('chemical_form')))}; "
            f"strength vs Omacor: {html.escape(str(c.get('strength_comparability_vs_omacor')))}</p>"
            f"<p><b>EPA/DHA:</b> {html.escape(str(c.get('epa_dha')))}</p>"
            f"<p><b>Eligibility:</b> {html.escape(str(c.get('eligibility')))}</p>"
            f"<p><b>Evidence completeness:</b> "
            f"{html.escape(str(c.get('evidence_completeness')))} "
            f"(score={c.get('evidence_completeness_score')})</p>"
            f"<p><b>Description:</b> {html.escape(str(c.get('original_description') or '')[:600])}</p>"
            f"<p>{html.escape(str(c.get('human_readable')))}</p>"
            "</section>"
        )
    html_path.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
        + "".join(sections)
        + "</body></html>",
        encoding="utf-8",
    )

    fields = [
        "source_medicine_id",
        "original_name",
        "candidate_class",
        "chemical_form",
        "provider_neutral_concept",
        "strength_comparability_vs_omacor",
        "suggested_review_action",
        "evidence_completeness_score",
        "forbidden_product_identity_as_omacor",
        "evidence_hash",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for c in cards:
            w.writerow(
                {
                    "source_medicine_id": c["source_medicine_id"],
                    "original_name": c.get("original_name"),
                    "candidate_class": c.get("candidate_class"),
                    "chemical_form": c.get("chemical_form"),
                    "provider_neutral_concept": c.get("provider_neutral_concept"),
                    "strength_comparability_vs_omacor": c.get(
                        "strength_comparability_vs_omacor"
                    ),
                    "suggested_review_action": c.get("suggested_review_action"),
                    "evidence_completeness_score": c.get("evidence_completeness_score"),
                    "forbidden_product_identity_as_omacor": (
                        c.get("eligibility") or {}
                    ).get("forbidden_product_identity_as_omacor"),
                    "evidence_hash": c.get("evidence_hash"),
                }
            )

    blob = html_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8")
    for forbidden in ("opaque_subject_key", "patient_id", "post_value", "pre_value"):
        if forbidden in blob:
            raise ValueError(f"patient_level_field_leaked:{forbidden}")

    return {
        "html": str(html_path.relative_to(root)),
        "csv": str(csv_path.relative_to(root)),
    }


def write_reviewer_instructions(
    root: Path,
    *,
    status: str,
    min_decisions: dict[str, Any] | None,
) -> Path:
    path = root / RUNTIME_DIR / "review-pack" / "reviewer-instructions.md"
    path.write_text(
        f"""# Reviewer instructions — Acceptance Semantics v0.1.3

## Decision types

- `PRODUCT_IDENTITY_ACCEPTED` — same product (not merely similar composition)
- `INGREDIENT_SET_ACCEPTED` — ingredients only (≠ product identity)
- `INGREDIENT_FORM_ROUTE_ACCEPTED` — ingredients + chemical form + form + route
- `INGREDIENT_FAMILY_ONLY` — exploratory; **cannot** open authoritative cohort
- `AMBIGUOUS` / `INSUFFICIENT_SOURCE_EVIDENCE` / `HUMAN_REJECTED`

## Command

```bash
uv run --frozen audit --root . medication-reference review decide <medicine_id> \\
  --candidate <candidate_id> \\
  --decision <decision_type> \\
  --reviewer <reviewer_id> \\
  --reason "<text>" \\
  --evidence-hash <hash>
```

## Rules

- Do **not** accept Жизнивек / fish oil / unspecified omega-3 as product «Омакор»
- Do **not** auto-accept 813; review `813-exact-review.html` first
- Gates remain {GATE_MIN_SUBJECTS}/{GATE_MIN_EPISODES}/{GATE_MIN_TEST_SUBJECTS}
- Association baseline stays NOT_RUN until scientifically usable accepted + READY
- v0.1.1 decision log is immutable; typed decisions go to v0.1.3 log only

## Current status

`{status}`

## Minimum human decisions (provisional)

```json
{json.dumps(min_decisions, ensure_ascii=False, indent=2) if min_decisions else "null"}
```
""",
        encoding="utf-8",
    )
    return path
