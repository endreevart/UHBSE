"""FINAL stage report. Every uppercase status key is emitted for full reconciliation."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_response_readiness_v01.policy import STAGE_NAME, VERSION
from human_simulator.intervention_response_readiness_v01.reconciliation import canon, is_status_key, status_keys


def status_lines(status: dict[str, Any]) -> dict[str, str]:
    return {key: canon(value) for key, value in status_keys(status).items()}


def render_stage_report(status: dict[str, Any], extra_sections: list[str] | None = None) -> str:
    lines: list[str] = [
        f"# {STAGE_NAME} v{VERSION}",
        "",
        f"Report status: {status.get('Report status', 'FINAL')}",
        "",
        "This is a readiness audit. It does not train an intervention-response model,",
        "does not reopen held-out gates, and does not claim treatment or causal effects.",
        "Technical audit PASS does not mean scientific model readiness.",
        "",
        "## Evidence sources",
        "",
        "- `artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6/status-contract.json`",
        "- `artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6/external-validation-protocol.json`",
        "- `artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/status-contract.json`",
        "- `artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/cell-registry-public.json`",
        "- `artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/medication-source-accounting.json`",
        "- `artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/source-a-medication-schema-profile.json`",
        "- `artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/source-a-medication-time-semantics.json`",
        "",
        "## Hard boundary",
        "",
        "- No intervention-response training.",
        "- No held-out reopen.",
        "- Frozen NHR, D0, and LEP unchanged.",
        "- Recorded association is not prescription or administration.",
        "- `appointment_date` remains `CANDIDATE_TECHNICAL_EVENT_TIMESTAMP`.",
        "- Source B medication context is not created by transferring Source A mappings.",
        "- IROS mapping remains unaccepted; no letters or calendar events.",
        "",
        "## Status contract",
        "",
    ]
    for key, value in sorted(status_lines(status).items()):
        lines.append(f"- `{key}`={value}")
    lines.extend(
        [
            "",
            "## Outcome",
            "",
            "Phase 0 unreadiness was reproduced from published artifacts and registries.",
            "No source-specific cell passed G0–G10 as an intervention-response eligible cell.",
            "`DOMAIN_ACCEPTED_MAPPING_COUNT=0` forces `INTERVENTION_RESPONSE_READINESS_STATUS=NOT_READY`",
            "and zero intervention-response eligible cells. Recorded-association cells are inventory only.",
            "",
        ]
    )
    if extra_sections:
        lines.extend(extra_sections)
        lines.append("")
    return "\n".join(lines) + "\n"
