"""Episode catalog and caption templates."""

from __future__ import annotations

from typing import Any

EPISODES: tuple[dict[str, str], ...] = (
    {
        "id": "Formula",
        "title": "The engine equation",
        "caption": (
            "UHBSE models State_before + Intervention + Context + Time → State_after. "
            "A probabilistic biology engine — not an EHR, not a chatbot. {disclaimer}"
        ),
    },
    {
        "id": "Load",
        "title": "Canonical load",
        "caption": (
            "Source A → canonical evidence. {subject} subjects, {source_record} source records, "
            "{encounter} encounters, {observation} observations. Raw clinic database unchanged. "
            "{disclaimer}"
        ),
    },
    {
        "id": "Provenance",
        "title": "Every value has an origin",
        "caption": (
            "Provenance coverage {valid}/{total}. Observed data is never overwritten. "
            "Synthetic and predicted stay in their own layers. {disclaimer}"
        ),
    },
    {
        "id": "Snapshot",
        "title": "State at time T",
        "caption": (
            "Starting state built for {snapshots} subjects. Future events excluded: "
            "{excluded_future}. No silent imputation. {disclaimer}"
        ),
    },
    {
        "id": "Branches",
        "title": "Three isolated branches",
        "caption": (
            "Control, intervention, dose-change. Same start, three different end states. "
            "Divergence at week {week}. Technical kernel, not a treatment prediction. {disclaimer}"
        ),
    },
    {
        "id": "Scope",
        "title": "Honest scope",
        "caption": (
            "Loaded {cohort}, timelines {timelines}, snapshots {snapshots}, simulated {simulated}. "
            "Sample class: {sample_class}. Clinical validation: {clinical_validation}. {disclaimer}"
        ),
    },
)


def fill_caption(template: str, summary: dict[str, Any]) -> str:
    counts = summary["row_counts"]
    scope = summary["scope"]
    snap = summary["snapshot"]
    prov = summary["provenance"]
    branches = summary["branches"]
    return template.format(
        disclaimer=summary["disclaimer"],
        subject=counts["subject"],
        source_record=counts["source_record"],
        encounter=counts["encounter"],
        observation=counts["observation"],
        valid=prov["valid_records"],
        total=prov["total_records_evaluated"],
        snapshots=scope["snapshots_built_subjects"],
        excluded_future=snap["excluded_future_count"],
        week=branches.get("first_divergence_week") or "n/a",
        cohort=scope["cohort_loaded_subjects"],
        timelines=scope["timelines_built_subjects"],
        simulated=scope["simulated_subjects"],
        sample_class=summary["sample_class"],
        clinical_validation=summary["clinical_validation"],
    )
