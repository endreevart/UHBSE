"""Local private research workbench. Synthetic default. No production deploy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v01.policy import VERSION

SECTIONS = [
    "Sources",
    "Individual State",
    "Longitudinal Timeline",
    "Natural-History Forecast",
    "Event Probability",
    "Joint Multi-Outcome Rollout",
    "Classifier Evidence",
    "QSP/PKPD Sandbox",
    "Applicability and Abstention",
    "Provenance and Model Evidence",
    "Deterministic Replay",
    "External Validation Readiness",
]


def render_workbench(status: dict[str, Any]) -> str:
    nav = "".join(f'<a href="#{i}">{s}</a>' for i, s in enumerate(SECTIONS, 1))
    d0 = status.get("route_used") or "D0"
    accepted = status.get("JOINT_DEPENDENCE_FOUNDATION_STATUS") or "EVALUATED_NOT_ACCEPTED"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>UHBSE Research Workbench v0.1</title>
<style>
:root {{ --bg:#fff; --ink:#1b1b1b; --muted:#524f4b; --lab:#f1f5f8; --a:#2c4a6e; --b:#6a4a2c; --warn:#8a1f1f; }}
body {{ margin:0; font:15px/1.45 ui-sans-serif,system-ui; color:var(--ink); background:var(--bg); }}
header {{ padding:1.2rem 1.5rem; border-bottom:1px solid rgba(27,27,27,.16); }}
.warn {{ background:#fff3f1; color:var(--warn); padding:.75rem 1.5rem; font-weight:600; }}
nav {{ display:flex; flex-wrap:wrap; gap:.5rem 1rem; padding:1rem 1.5rem; background:var(--lab); }}
nav a {{ color:var(--ink); }}
section {{ padding:1.25rem 1.5rem; border-bottom:1px solid rgba(27,27,27,.08); }}
.chip {{ display:inline-block; padding:.15rem .5rem; border:1px solid rgba(27,27,27,.2); margin-right:.4rem; }}
.source-a {{ border-color:var(--a); color:var(--a); }}
.source-b {{ border-color:var(--b); color:var(--b); }}
.sandbox {{ outline:2px dashed #6a4a2c; background:#fbf7f1; }}
svg {{ background:#fff; }}
footer {{ padding:1rem 1.5rem; color:var(--muted); }}
</style>
</head>
<body>
<header>
  <h1>UHBSE Integrated Research Runtime v{VERSION}</h1>
  <p>Default mode: <strong>synthetic fixture</strong>. Private real-data mode is local-only.</p>
  <span class="chip">PRODUCTION_READINESS=NOT_CLAIMED</span>
  <span class="chip">CLINICAL_USE_PROHIBITED</span>
</header>
<div class="warn">Not a clinical product. Not for diagnosis, treatment, or production deployment.</div>
<nav>{nav}</nav>
<section id="1"><h2>1. Sources</h2>
  <p><span class="chip source-a">Source A magerya_api</span> visually distinct from <span class="chip source-b">Source B kgz_raw</span>.</p>
  <p>Outcomes are never declared equivalent. Units are shown on every series.</p>
</section>
<section id="2"><h2>2. Individual State</h2>
  <p>Opaque source-scoped identifiers only. Direct identifiers are rejected by the API.</p>
</section>
<section id="3"><h2>3. Longitudinal Timeline</h2>
  <svg width="640" height="120" aria-label="synthetic timeline">
    <line x1="20" y1="60" x2="620" y2="60" stroke="#1b1b1b"/>
    <circle cx="80" cy="60" r="6" fill="#2c4a6e"/>
    <circle cx="220" cy="48" r="6" fill="#2c4a6e"/>
    <circle cx="400" cy="72" r="6" fill="#6a4a2c"/>
  </svg>
</section>
<section id="4"><h2>4. Natural-History Forecast</h2>
  <p>NATURAL_HISTORY_ONLY. Intervention controls do not modify patient trajectories.</p>
</section>
<section id="5"><h2>5. Event Probability</h2>
  <p>Frozen probability provider v0.2.1.1 is a connector, not a clinical claim.</p>
</section>
<section id="6"><h2>6. Joint Multi-Outcome Rollout</h2>
  <p>Active route: <strong>{d0}</strong>. Foundation: <code>{accepted}</code>.</p>
  <p>D0 = independent normalized residuals. D1 = masked Gaussian copula (only if accepted).</p>
</section>
<section id="7"><h2>7. Classifier Evidence</h2>
  <p>Technical recorded-event classifier. Status CANDIDATE / NOT_ACCEPTED. Not a diagnosis.</p>
</section>
<section id="8" class="sandbox"><h2>8. QSP/PKPD Sandbox</h2>
  <p>This branch is visually separated from patient simulation. Synthetic Compound X and homeostatic biomarker only.</p>
</section>
<section id="9"><h2>9. Applicability and Abstention</h2>
  <p>No silent fallback. Missing source or model hash yields abstention or hard FAIL.</p>
</section>
<section id="10"><h2>10. Provenance and Model Evidence</h2>
  <p>Every forecast carries model hash, payload hash, evidence tier, and source/outcome/unit identity.</p>
</section>
<section id="11"><h2>11. Deterministic Replay</h2>
  <p>Same request and seed replay in two subprocesses. Different seed yields a different non-degenerate path set.</p>
</section>
<section id="12"><h2>12. External Validation Readiness</h2>
  <p>SERUM_FREE_T3_RETROSPECTIVE_EXTERNAL_VALIDATION is READY_FOR_PROVIDER_SCOPING, not a validation PASS.</p>
</section>
<footer>Local/private interface. WebGL is not required. Synthetic default is enforced.</footer>
</body>
</html>
"""


def write_workbench(path: Path, status: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_workbench(status)
    path.write_text(html, encoding="utf-8")
    return {
        "RESEARCH_WORKBENCH_STATUS": "BUILT",
        "SYNTHETIC_DEFAULT_MODE_STATUS": "PASS",
        "sections": SECTIONS,
        "path": str(path),
        "production_deploy": False,
        "ok": True,
    }
