"""FINAL stage report. Every uppercase status key is emitted."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_response_readiness_v01.reconciliation import canon, status_keys
from human_simulator.intervention_response_readiness_v011.policy import STAGE_NAME, VERSION


def render_stage_report(status: dict[str, Any]) -> str:
    lines = [
        f"# {STAGE_NAME} v{VERSION}",
        "",
        f"Report status: {status.get('Report status', 'FINAL')}",
        "",
        "Point correction of v0.1 evidence provenance and clean-extraction replay.",
        "The negative readiness conclusion is unchanged. This run does not train",
        "an intervention-response model and does not claim a treatment or causal effect.",
        "",
        "## Status contract",
        "",
    ]
    for key, value in sorted({name: canon(item) for name, item in status_keys(status).items()}.items()):
        lines.append(f"- `{key}`={value}")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Recorded association stays inventory. Eligible intervention-response cells stay 0",
            "while domain-accepted mappings stay 0. Prior ZIP bytes stay outside this bundle.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
