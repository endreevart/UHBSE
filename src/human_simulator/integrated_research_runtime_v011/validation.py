"""External validation readiness. No email. No calendar. Split owner vs system action."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v011.policy import VALIDATION_DIR, VERSION

PROPOSAL_ID = "SERUM_FREE_T3_RETROSPECTIVE_EXTERNAL_VALIDATION"


def write_private_pack(root: Path) -> dict[str, Any]:
    d = Path(root) / VALIDATION_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "iros-owner-contact-status.md").write_text(
        """# Owner-reported IROS contact

AUTOMATED_EXTERNAL_CONTACT_STATUS=NOT_RUN

OWNER_REPORTED_IROS_CONTACT_STATUS=RESPONSE_RECEIVED_PENDING_REPOSITORY_EVIDENCE

IROS_PROVIDER_COMMITMENT_STATUS=NOT_ESTABLISHED

Owner reported that IROS replied and proposed an introductory call.

This file is not repository-verified provider acceptance. No dataset grant is claimed.
No email was sent by this runtime. No calendar event was created.
""",
        encoding="utf-8",
    )
    (d / "iros-scoping-call-brief.md").write_text(
        """# IROS scoping-call brief (draft, not scheduled)

Purpose: if a call occurs, ask only about assay identity, specimen type, unit, and
whether a governed retrospective extract is even possible.

This brief is not an invitation and not a scheduled meeting.
""",
        encoding="utf-8",
    )
    (d / "free-t3-minimum-variable-specification.md").write_text(
        """# Free T3 minimum variable specification (draft)

Required before any mapping discussion:

- analyte identity (serum free T3)
- specimen
- assay / method
- native unit
- observation time
- source-local subject key (provider-held)
- no automatic unit conversion
""",
        encoding="utf-8",
    )
    (d / "free-t3-predeclared-analysis-plan-draft.md").write_text(
        """# Free T3 predeclared analysis plan (draft)

Not executed. Frozen UHBSE models are not retuned on external data.

Metrics if a later governed extract exists: CRPS, interval coverage, calibration slope.
Not clinical validation.
""",
        encoding="utf-8",
    )
    (d / "provider-questions.md").write_text(
        """# Provider questions (unsent)

1. Which assay identifies free T3?
2. What is the native unit and specimen?
3. Would any extract remain at the provider?
4. What ethics / DUA path exists?

These questions were not emailed.
""",
        encoding="utf-8",
    )
    gaps = {
        "version": VERSION,
        "AUTOMATED_EXTERNAL_CONTACT_STATUS": "NOT_RUN",
        "OWNER_REPORTED_IROS_CONTACT_STATUS": "RESPONSE_RECEIVED_PENDING_REPOSITORY_EVIDENCE",
        "IROS_PROVIDER_COMMITMENT_STATUS": "NOT_ESTABLISHED",
        "EXTERNAL_VALIDATION_STATUS": "NOT_RUN",
        "data_access": "NOT_GRANTED",
        "ethics_approval": "NOT_ESTABLISHED",
        "mapping_acceptance": "NOT_ACCEPTED",
        "validation_execution": "NOT_RUN",
        "email_sent": False,
        "calendar_event_created": False,
    }
    (d / "external-validation-readiness-gaps.json").write_text(
        json.dumps(gaps, indent=2) + "\n", encoding="utf-8"
    )
    return gaps


def public_protocol() -> dict[str, Any]:
    return {
        "proposal_id": PROPOSAL_ID,
        "EXTERNAL_VALIDATION_PROTOCOL_STATUS": "READY_FOR_PROVIDER_SCOPING",
        "EXTERNAL_VALIDATION_STATUS": "NOT_RUN",
        "AUTOMATED_EXTERNAL_CONTACT_STATUS": "NOT_RUN",
        "OWNER_REPORTED_IROS_CONTACT_STATUS": "RESPONSE_RECEIVED_PENDING_REPOSITORY_EVIDENCE",
        "IROS_PROVIDER_COMMITMENT_STATUS": "NOT_ESTABLISHED",
        "mapping_accepted": False,
        "contacted_iros_global_claim_forbidden": True,
        "email_sent": False,
        "calendar_event_created": False,
        "research_question": "Frozen source-aware free T3 forecast vs retrospective external measurements, after assay review.",
        "horizons_days": [30, 90, 180, 365],
        "no_external_tuning": True,
        "non_claims": [
            "not_clinical_validation",
            "not_production",
            "not_causal",
            "not_mapping_acceptance",
            "not_provider_dataset_grant",
        ],
    }
