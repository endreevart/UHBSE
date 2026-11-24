"""Executable local workbench. Synthetic default. Calls the live research API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v012.policy import VERSION

SECTIONS = [
    "Sources",
    "Individual State",
    "Longitudinal History",
    "Natural-History Forecast",
    "Event Probability",
    "Joint Outcome Distribution",
    "Classifier Evidence",
    "QSP/PKPD Synthetic Sandbox",
    "Applicability and Abstention",
    "Provenance and Model Evidence",
    "Deterministic Replay",
    "External Validation Readiness",
]


def render_workbench() -> str:
    nav = "".join(f'<a href="#s{i}">{s}</a>' for i, s in enumerate(SECTIONS, 1))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>UHBSE Research Workbench v{VERSION}</title>
<style>
:root {{ --ink:#1b1b1b; --lab:#f1f5f8; --warn:#8a1f1f; --a:#2c4a6e; --b:#6a4a2c; }}
body {{ margin:0; font:15px/1.45 ui-sans-serif,system-ui; color:var(--ink); }}
header {{ padding:1rem 1.5rem; border-bottom:1px solid #ddd; }}
.warn {{ background:#fff3f1; color:var(--warn); padding:.75rem 1.5rem; font-weight:600; }}
nav {{ display:flex; flex-wrap:wrap; gap:.6rem 1rem; padding:1rem 1.5rem; background:var(--lab); }}
section {{ padding:1.2rem 1.5rem; border-bottom:1px solid #eee; }}
.chip {{ display:inline-block; padding:.15rem .5rem; border:1px solid #ccc; margin-right:.4rem; }}
.source-a {{ color:var(--a); border-color:var(--a); }}
.source-b {{ color:var(--b); border-color:var(--b); }}
.sandbox {{ outline:2px dashed #6a4a2c; background:#fbf7f1; }}
pre {{ background:#f7f7f7; padding:.75rem; overflow:auto; }}
button {{ margin:.25rem .4rem .25rem 0; }}
</style>
</head>
<body>
<header>
  <h1>UHBSE Integrated Research Runtime v{VERSION}</h1>
  <p>Default mode: <strong>SYNTHETIC_FIXTURE</strong>. Bind 127.0.0.1. Not production.</p>
</header>
<div class="warn">Not a clinical product. D1 is not accepted. Output is a distribution at one requested horizon, not a coherent trajectory.</div>
<nav>{nav}</nav>
<section id="s1"><h2>1. Sources</h2>
  <p><span class="chip source-a">Source A</span> distinct from <span class="chip source-b">Source B</span>. Unified layer is not a third clinical source.</p>
  <pre id="sources-out">loading…</pre>
</section>
<section id="s2"><h2>2. Individual State</h2>
  <label>alpha <input id="alpha" type="number" value="1"/></label>
  <label>beta <input id="beta" type="number" value="2"/></label>
</section>
<section id="s3"><h2>3. Longitudinal History</h2>
  <p>Synthetic pre-t0 summary. Units shown on every outcome.</p>
</section>
<section id="s4"><h2>4. Natural-History Forecast</h2>
  <button id="btn-nh" type="button">Run forecast</button>
  <pre id="nh-out"></pre>
</section>
<section id="s5"><h2>5. Event Probability</h2>
  <button id="btn-ev" type="button">Run synthetic event probability</button>
  <pre id="ev-out"></pre>
</section>
<section id="s6"><h2>6. Joint Outcome Distribution</h2>
  <p>Route D0. D1 unavailable because accepted route count = 0.</p>
  <button id="btn-jd" type="button">Run joint distribution</button>
  <button id="btn-bad" type="button">Send bad model hash</button>
  <button id="btn-d1" type="button">Request D1</button>
  <pre id="jd-out"></pre>
</section>
<section id="s7"><h2>7. Classifier Evidence</h2>
  <p>TRAJECTORY_EVENT_CLASSIFIER_STATUS=EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL. REVIEW_VIEW_ONLY.</p>
</section>
<section id="s8" class="sandbox"><h2>8. QSP/PKPD Synthetic Sandbox</h2>
  <p>Visually separated from patient natural history. Synthetic only.</p>
  <button id="btn-qsp" type="button">Run synthetic QSP</button>
  <pre id="qsp-out"></pre>
</section>
<section id="s9"><h2>9. Applicability and Abstention</h2>
  <pre id="abs-out">Abstention and hashes appear in forecast responses.</pre>
</section>
<section id="s10"><h2>10. Provenance and Model Evidence</h2>
  <pre id="models-out">loading…</pre>
</section>
<section id="s11"><h2>11. Deterministic Replay</h2>
  <button id="btn-rp" type="button">Replay same state/seed</button>
  <pre id="rp-out"></pre>
</section>
<section id="s12"><h2>12. External Validation Readiness</h2>
  <p>OWNER_REPORTED_IROS_CONTACT_STATUS=RESPONSE_RECEIVED_PENDING_REPOSITORY_EVIDENCE. AUTOMATED_EXTERNAL_CONTACT_STATUS=NOT_RUN. IROS_PROVIDER_COMMITMENT_STATUS=NOT_ESTABLISHED.</p>
</section>
<script>
async function jget(p) {{
  const r = await fetch(p);
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('html')) return {{ html: await r.text() }};
  return r.json();
}}
async function jpost(p, body) {{
  const r = await fetch(p, {{ method: 'POST', headers: {{'Content-Type':'application/json'}}, body: JSON.stringify(body) }});
  const j = await r.json();
  j.http_status = r.status;
  return j;
}}
function identitiesFromModels(models) {{
  const ids = {{}};
  for (const m of (models.synthetic || [])) {{
    ids[m.outcome_key] = {{
      active_payload_sha256: m.active_payload_sha256,
      feature_order_sha256: m.feature_order_sha256,
      scaler_sha256: m.scaler_sha256,
      residual_distribution_sha256: m.residual_distribution_sha256,
      unit: m.unit
    }};
  }}
  return ids;
}}
function commonBody() {{
  const a = Number(document.getElementById('alpha').value);
  const b = Number(document.getElementById('beta').value);
  return {{
    namespace: 'SYNTHETIC_FIXTURE',
    source_system: 'synthetic',
    requested_horizon_days: 90,
    outcome_keys: ['SYN::alpha::au', 'SYN::beta::au'],
    state_at_t0: {{ 'SYN::alpha::au': a, 'SYN::beta::au': b }},
    history: {{ 'SYN::alpha::au': [a], 'SYN::beta::au': [b] }},
    history_days: {{ 'SYN::alpha::au': [], 'SYN::beta::au': [] }},
    history_is_pre_t0_summary: true,
    cutoff_t0: '2000-01-01T00:00:00Z',
    cell_identities: window.__ids,
    n_paths: 8,
    seed: 42,
    replay_key: 'workbench'
  }};
}}
async function boot() {{
  const h = await jget('/health');
  const s = await jget('/research/sources');
  const m = await jget('/research/models');
  window.__ids = identitiesFromModels(m);
  document.getElementById('sources-out').textContent = JSON.stringify({{ health: h, sources: s }}, null, 2);
  document.getElementById('models-out').textContent = JSON.stringify(m, null, 2);
}}
function showAbs(out) {{
  document.getElementById('abs-out').textContent = JSON.stringify({{
    status: out.status, reason: out.reason, http_status: out.http_status,
    hashes: (out.per_outcome || []).map(x => ({{ unit: x.unit, model: x.marginal_provider_identity, residual: x.residual_provider_identity }})),
    d1: out.D1_JOINT_DEPENDENCE_STATUS
  }}, null, 2);
}}
document.getElementById('btn-nh').onclick = async () => {{
  const out = await jpost('/research/natural-history/forecast', commonBody());
  document.getElementById('nh-out').textContent = JSON.stringify(out, null, 2);
  showAbs(out);
}};
document.getElementById('btn-ev').onclick = async () => {{
  const b = {{
    namespace: 'SYNTHETIC_FIXTURE', source_system: 'synthetic', endpoint: 'TIME_TO_NEXT_LAB_PANEL',
    requested_horizon_days: 90, model_id: (await jget('/research/models')).synthetic_event_probability_model_id,
    feature_order_sha256: window.__ids['SYN::alpha::au'].feature_order_sha256,
    cutoff_t0: '2000-01-01T00:00:00Z', state_at_t0: {{ history_depth: 2 }}
  }};
  document.getElementById('ev-out').textContent = JSON.stringify(await jpost('/research/event-probability', b), null, 2);
}};
document.getElementById('btn-jd').onclick = async () => {{
  const out = await jpost('/research/joint-outcome-distribution', commonBody());
  document.getElementById('jd-out').textContent = JSON.stringify(out, null, 2);
  showAbs(out);
}};
document.getElementById('btn-bad').onclick = async () => {{
  const b = commonBody();
  const k = Object.keys(b.cell_identities)[0];
  b.cell_identities[k] = {{ ...b.cell_identities[k], active_payload_sha256: '0'.repeat(64) }};
  const out = await jpost('/research/joint-outcome-distribution', b);
  document.getElementById('jd-out').textContent = JSON.stringify(out, null, 2);
  showAbs(out);
}};
document.getElementById('btn-d1').onclick = async () => {{
  const b = commonBody();
  b.force_d1 = true;
  const out = await jpost('/research/joint-outcome-distribution', b);
  document.getElementById('abs-out').textContent = JSON.stringify(out, null, 2);
}};
document.getElementById('btn-qsp').onclick = async () => {{
  document.getElementById('qsp-out').textContent = JSON.stringify(await jpost('/research/qsp/reference-run', {{ model_id: 'SYNTHETIC_REFERENCE_COMPOUND_X_PKPD', synthetic_only: true }}), null, 2);
}};
document.getElementById('btn-rp').onclick = async () => {{
  const b = commonBody();
  const a = await jpost('/research/replay', b);
  const c = await jpost('/research/replay', b);
  document.getElementById('rp-out').textContent = JSON.stringify({{ same: JSON.stringify(a.per_outcome) === JSON.stringify(c.per_outcome), a }}, null, 2);
}};
boot();
</script>
</body>
</html>
"""


def write_workbench(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_workbench()
    path.write_text(html, encoding="utf-8")
    return {
        "RESEARCH_WORKBENCH_STATUS": "BUILT",
        "WORKBENCH_API_INTEGRATION_STATUS": "HTML_CLIENT_PRESENT_NOT_BROWSER_PROOF",
        "WORKBENCH_SYNTHETIC_DEFAULT_STATUS": "PASS",
        "sections": SECTIONS,
        "calls_fetch": "fetch(" in html,
        "ok": True,
    }
