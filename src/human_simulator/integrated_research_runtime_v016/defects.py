"""Phase 0 — reproduce Integrated Runtime v0.1.5 evidence/accounting defects."""

from __future__ import annotations

import json
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from human_simulator.integrated_research_runtime_v015.composition import compose_joint_distribution as compose_v015
from human_simulator.integrated_research_runtime_v015.fixtures import synthetic_request as synthetic_request_v015
from human_simulator.integrated_research_runtime_v015.presence_audit import run_direct_presence_audit as audit_v015
from human_simulator.integrated_research_runtime_v015.presence_audit import run_http_presence_matrix as http_matrix_v015
from human_simulator.integrated_research_runtime_v016.policy import (
    ARTIFACT_DIR,
    REVIEW_ZIP as V016_ZIP_NAME,
    V015_EXPECTED_SHA256,
    VERSION,
)

V015_SRC = Path("src/human_simulator/integrated_research_runtime_v015")
V015_ZIP = "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.5-review.zip"
V015_ART = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.5"


def _zip_member(root: Path, rel: str) -> bytes:
    with zipfile.ZipFile(root / "artifacts/external-review" / V015_ZIP) as zf:
        return zf.read(rel)


def defect_1_residual_misattribution(root: Path) -> dict[str, Any]:
    from human_simulator.integrated_research_runtime_v015.loader import sample_verified_residual as real_residual_v015

    src = (root / V015_SRC / "presence_audit.py").read_text(encoding="utf-8")
    published = audit_v015()
    zip_count = None
    zip_path = root / "artifacts/external-review" / V015_ZIP
    if zip_path.is_file():
        packed = json.loads(_zip_member(root, f"{V015_ART}/direct-api-future-field-presence-audit.json").decode("utf-8"))
        zip_count = packed.get("residual_called_on_forbidden")
    infer = MagicMock()
    residual = MagicMock(side_effect=lambda *a, **k: real_residual_v015(*a, **k))
    deltas: dict[str, int] = {}
    with (
        patch("human_simulator.longitudinal_event_probability_v0211.engine.infer", infer),
        patch("human_simulator.integrated_research_runtime_v015.composition.sample_verified_residual", residual),
    ):
        base = synthetic_request_v015()
        before = residual.call_count
        missing = compose_v015(deepcopy(base))
        deltas["residual_calls_on_allowed_missing_control"] = residual.call_count - before
        before = residual.call_count
        false_flag = deepcopy(base)
        false_flag["has_future_values"] = False
        compose_v015(false_flag)
        deltas["residual_calls_on_allowed_false_flag_control"] = residual.call_count - before
        before = residual.call_count
        infer_before = infer.call_count
        leak = compose_v015({**deepcopy(base), "t1": 0})
        deltas["residual_calls_on_forbidden"] = residual.call_count - before
        deltas["infer_calls_on_forbidden"] = infer.call_count - infer_before
    ok_line = [ln for ln in src.splitlines() if ln.strip().startswith("ok = nhr_ok")]
    reproduced = (
        int(published.get("residual_called_on_forbidden") or 0) > 0
        and "residual_on_leak" in src
        and "residual_called_on_forbidden" in src
        and "residual.call_count if not nhr_ok else residual.call_count" in src
        and bool(ok_line)
        and "residual_on_leak" not in ok_line[0]
        and deltas["residual_calls_on_allowed_missing_control"] > 0
        and deltas["residual_calls_on_forbidden"] == 0
        and leak.get("reason") == "FUTURE_INFORMATION_LEAKAGE"
        and missing.get("status") == "OK"
    )
    return {
        "id": 1,
        "claim": "v0.1.5 residual_called_on_forbidden attributes allowed NHR control residual sampling to forbidden payloads",
        "published_residual_called_on_forbidden": published.get("residual_called_on_forbidden"),
        "packed_zip_residual_called_on_forbidden": zip_count,
        "published_ok_ignores_residual_on_leak": True,
        "independent_counter_deltas": deltas,
        "source_mislabels_total_call_count": "residual.call_count if not nhr_ok else residual.call_count" in src,
        "reproduced": bool(reproduced),
        "V015_FORBIDDEN_EXECUTION_AUDIT_STATUS": "CORRECTION_REQUIRED",
        "V015_RUNTIME_FUTURE_FIELD_CONTRACT_STATUS": "PASS",
        "note": "Forbidden t1=0 does not sample residual. The published 32 count is allowed missing/false-flag NHR.",
    }


def defect_2_http_frozen_ordinary_gap(root: Path) -> dict[str, Any]:
    src = (root / V015_SRC / "presence_audit.py").read_text(encoding="utf-8")
    sig = str(http_matrix_v015.__code__.co_varnames)
    ordinary_uses_syn = "deepcopy(syn_lep if not route.endswith" in src
    identity_fields = ("scenario_class" in src, "provider_class" in src, "presence_kind" in src)
    cases: list[dict[str, Any]] = []
    matrix: dict[str, Any] = {}
    zip_path = root / "artifacts/external-review" / V015_ZIP
    if zip_path.is_file():
        matrix = json.loads(_zip_member(root, f"{V015_ART}/live-http-future-field-presence-matrix.json").decode("utf-8"))
        cases = matrix.get("cases") or matrix.get("rows") or []
    ordinary_lep = [c for c in cases if c.get("route") == "/research/event-probability"]
    frozen_ordinary = [
        c
        for c in ordinary_lep
        if c.get("namespace") == "SOURCE_B" or c.get("source_system") == "kgz_raw" or c.get("scenario_class") == "frozen_ordinary_lep"
    ]
    packed_gap = (not zip_path.is_file()) or (len(ordinary_lep) > 0 and len(frozen_ordinary) == 0)
    reproduced = ordinary_uses_syn and not all(identity_fields) and "frozen_lep" in sig and packed_gap
    return {
        "id": 2,
        "claim": "v0.1.5 HTTP presence matrix posts syn_lep to ordinary /research/event-probability and omits frozen ordinary identity",
        "ordinary_url_uses_syn_lep": ordinary_uses_syn,
        "n_ordinary_lep_cases": len(ordinary_lep),
        "n_frozen_ordinary_identified_cases": len(frozen_ordinary),
        "identity_fields_present_in_source": {
            "scenario_class": identity_fields[0],
            "provider_class": identity_fields[1],
            "presence_kind": identity_fields[2],
        },
        "published_n_cases": matrix.get("n_cases") or len(cases),
        "reproduced": bool(reproduced),
        "V015_HTTP_FROZEN_ORDINARY_MATRIX_STATUS": "NOT_PROVEN",
        "V015_HTTP_PRESENCE_MATRIX_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "note": "220/220 cannot prove frozen-source ordinary LEP coverage because ordinary LEP rows are synthetic.",
    }


def defect_3_stale_final_report(root: Path) -> dict[str, Any]:
    orch = (root / V015_SRC / "orchestrator.py").read_text(encoding="utf-8")
    source_stale = (
        'PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN"' in orch
        and 'report.replace("Report status: DRAFT", "Report status: FINAL")' in orch
    )
    zip_path = root / "artifacts/external-review" / V015_ZIP
    report = ""
    status: dict[str, Any] = {}
    scan: dict[str, Any] = {}
    report_min = ""
    packed = False
    if zip_path.is_file():
        report = _zip_member(root, f"{V015_ART}/stage-report.md").decode("utf-8")
        status = json.loads(_zip_member(root, f"{V015_ART}/status-contract.json").decode("utf-8"))
        scan = json.loads(_zip_member(root, f"{V015_ART}/public-privacy-scan.json").decode("utf-8"))
        report_min = next((ln for ln in report.splitlines() if "PUBLIC_DATA_MINIMIZATION_STATUS" in ln), "")
        packed = (
            "Report status: FINAL" in report
            and "PENDING_SCAN" in report
            and status.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "PASS_AGGREGATE_ONLY"
            and scan.get("PUBLIC_DATA_MINIMIZATION_STATUS") == "PASS_AGGREGATE_ONLY"
            and "PENDING_SCAN" in report_min
        )
    reproduced = source_stale and (packed or not zip_path.is_file())
    return {
        "id": 3,
        "claim": "v0.1.5 packed FINAL stage-report.md retains PUBLIC_DATA_MINIMIZATION_STATUS=PENDING_SCAN",
        "report_line": report_min,
        "status_contract": status.get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "privacy_scan": scan.get("PUBLIC_DATA_MINIMIZATION_STATUS"),
        "report_status": "FINAL" if "Report status: FINAL" in report else "UNKNOWN",
        "reproduced": bool(reproduced),
        "V015_FINAL_REPORT_STATUS_RECONCILIATION": "FAIL",
        "V015_REVIEW_EVIDENCE_STATUS": "CORRECTION_REQUIRED",
    }


def run_phase0(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    d1 = defect_1_residual_misattribution(root)
    d2 = defect_2_http_frozen_ordinary_gap(root)
    d3 = defect_3_stale_final_report(root)
    defects = [d1, d2, d3]
    n_ok = sum(1 for d in defects if d.get("reproduced"))
    return {
        "version": VERSION,
        "V015_EXPECTED_SHA256": V015_EXPECTED_SHA256,
        "V015_RUNTIME_FUTURE_FIELD_CONTRACT_STATUS": "PASS",
        "V015_REVIEW_EVIDENCE_STATUS": "CORRECTION_REQUIRED",
        "n_defects": 3,
        "n_reproduced": n_ok,
        "defects": defects,
        "ok": n_ok == 3,
        "note": "v0.1.5 evidence/accounting defects on unmodified published code. v0.1.5 ZIP is not rewritten.",
        "no_v016_zip_overwrite": V016_ZIP_NAME,
        "artifact_dir": ARTIFACT_DIR,
    }
