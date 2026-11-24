"""External validation readiness pack. Do not contact IROS. Not a validation PASS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v01.policy import VERSION

PROPOSAL_ID = "SERUM_FREE_T3_RETROSPECTIVE_EXTERNAL_VALIDATION"


def protocol_private() -> str:
    return f"""# {PROPOSAL_ID}

Status: READY_FOR_PROVIDER_SCOPING (not external validation PASS).
Free T3 A↔external mapping is not accepted without specimen/assay review.

## Research question
Can a frozen source-aware natural-history forecast for serum free T3, trained without external
tuning, rank or calibrate retrospective held-out measurements in a governed external laboratory
dataset under a predeclared horizon?

## Endpoint identity
- Analyte: serum free triiodothyronine (free T3)
- Source A local key remains source-local; no automatic mapping
- Specimen/assay evidence required before any unit conversion

## Inclusion / exclusion (draft)
- Adult research cohort with written consent for secondary research use
- At least one pre-index free T3 and one post-index measurement
- Exclude samples lacking assay identity

## Index time and horizon
- Index: last eligible pre-horizon observation (t0)
- Horizons: predeclared 30/90/180/365 day grid; exact requested horizon is a request parameter

## Frozen feature contract
Persistence value, history depth, days since previous, requested horizon. No medication features.
No test-based retuning.

## Missingness
- Missing outcomes are not zero-filled
- Source-specific missingness remains source-specific

## Persistence baseline
Last observation carried forward in native units.

## Metrics
CRPS, interval coverage, calibration slope, sample-size feasibility (to be scoped with provider).

## Secure compute / privacy
Patient-level data stay at the provider. No outbound transfer from UHBSE. Cursor does not email IROS.

## Explicit non-claims
Not clinical validation. Not production. Not causal. Not a mapping acceptance.
"""


def protocol_public() -> dict[str, Any]:
    return {
        "proposal_id": PROPOSAL_ID,
        "EXTERNAL_VALIDATION_PROTOCOL_STATUS": "READY_FOR_PROVIDER_SCOPING",
        "EXTERNAL_VALIDATION_STATUS": "NOT_RUN",
        "mapping_accepted": False,
        "contacted_iros": False,
        "research_question": "Frozen source-aware free T3 forecast vs retrospective external measurements, after assay review.",
        "horizons_days": [30, 90, 180, 365],
        "no_external_tuning": True,
        "non_claims": [
            "not_clinical_validation",
            "not_production",
            "not_causal",
            "not_mapping_acceptance",
        ],
    }


def write_validation_pack(private_dir: Path, public_dir: Path) -> dict[str, Any]:
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / "protocol-synopsis.md").write_text(protocol_private(), encoding="utf-8")
    pub = protocol_public()
    (public_dir / "external-validation-protocol-public.json").write_text(
        __import__("json").dumps(pub, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**pub, "ok": True, "version": VERSION}
