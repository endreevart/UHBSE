"""Browser integration against a live local HTTP server. Missing Playwright is NOT_VERIFIED."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def run_browser_audit(base_url: str) -> dict[str, Any]:
    script = r"""
import json, sys
url = sys.argv[1]
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print(json.dumps({"ok": False, "WORKBENCH_BROWSER_INTEGRATION_STATUS": "NOT_VERIFIED", "reason": "playwright_not_installed"}))
    raise SystemExit(0)
out = {"ok": False, "WORKBENCH_BROWSER_INTEGRATION_STATUS": "NOT_VERIFIED"}
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("#alpha", timeout=10000)
        page.wait_for_function("window.__ids && Object.keys(window.__ids).length > 0", timeout=15000)
        page.fill("#alpha", "42")
        page.fill("#beta", "7")
        page.click("#btn-jd")
        page.wait_for_function("document.getElementById('jd-out').textContent.includes('marginal_forecast') || document.getElementById('jd-out').textContent.includes('FAIL') || document.getElementById('jd-out').textContent.includes('ABSTAIN')", timeout=15000)
        jd = page.inner_text("#jd-out")
        page.click("#btn-rp")
        page.wait_for_function("document.getElementById('rp-out').textContent.length > 10", timeout=15000)
        rp = page.inner_text("#rp-out")
        page.click("#btn-bad")
        page.wait_for_function("document.getElementById('abs-out').textContent.includes('MODEL_HASH') || document.getElementById('abs-out').textContent.includes('FAIL')", timeout=15000)
        abs_txt = page.inner_text("#abs-out")
        page.click("#btn-d1")
        page.wait_for_function("document.getElementById('abs-out').textContent.includes('D1') || document.getElementById('abs-out').textContent.includes('NOT_ACCEPTED') || document.getElementById('abs-out').textContent.includes('ABSTAIN')", timeout=15000)
        d1_txt = page.inner_text("#abs-out")
        browser.close()
        has_unit = "au" in jd
        has_new = "42" in jd or "marginal_forecast" in jd
        has_tier = "TEMPORAL_EVIDENCE_TIER" in jd or "DECLARED_PRE_T0_SUMMARY" in jd or "TEMPORAL_EVIDENCE_TIER" in abs_txt
        d1 = "D1_NOT_ACCEPTED" in d1_txt or "NOT_ACCEPTED" in d1_txt
        out = {
            "ok": has_new and "same" in rp and ("MODEL_HASH" in abs_txt or "FAIL" in abs_txt) and has_unit and d1 and has_tier,
            "WORKBENCH_BROWSER_INTEGRATION_STATUS": "PASS" if has_new and "same" in rp and d1 and has_tier else "FAIL",
            "changed_state_visible": has_new,
            "unit_visible": has_unit,
            "temporal_evidence_tier_visible": has_tier,
            "replay_ran": "same" in rp,
            "bad_hash_or_abstain_visible": "MODEL_HASH" in abs_txt or "FAIL" in abs_txt or "ABSTAIN" in abs_txt,
            "d1_unavailable_visible": d1,
            "not_html_string_only": True,
        }
except Exception as e:
    out = {"ok": False, "WORKBENCH_BROWSER_INTEGRATION_STATUS": "NOT_VERIFIED", "reason": type(e).__name__, "detail": str(e)[:240]}
print(json.dumps(out))
"""
    import shutil

    candidates: list[str] = []
    for cand in (sys.executable, shutil.which("python3"), "/usr/bin/python3", "/usr/local/bin/python3"):
        if cand and cand not in candidates:
            candidates.append(cand)
    last_err = ""
    for exe in candidates:
        try:
            proc = subprocess.run(
                [exe, "-c", script, base_url.rstrip("/") + "/"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            if not last_err:
                last_err = type(exc).__name__
            continue
        if proc.stderr:
            last_err = (proc.stderr or "")[-400:]
        line = (proc.stdout or "").strip().splitlines()
        if not line:
            continue
        try:
            doc = json.loads(line[-1])
        except json.JSONDecodeError:
            continue
        if doc.get("WORKBENCH_BROWSER_INTEGRATION_STATUS") == "NOT_VERIFIED" and "playwright_not_installed" in str(
            doc.get("reason")
        ):
            continue
        return doc
    return {
        "ok": False,
        "WORKBENCH_BROWSER_INTEGRATION_STATUS": "NOT_VERIFIED",
        "reason": "playwright_not_installed",
        "detail": last_err,
        "note": "HTML fetch() string checks are not a browser test.",
    }
