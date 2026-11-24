"""Publication gate — refuse 0-accepted / provider-missing bundles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.policy import ARTIFACT_DIR, REVIEW_ZIP, VERSION


def publish(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    status_path = root / ARTIFACT_DIR / "status-contract.json"
    if not status_path.is_file():
        return {"ok": False, "error": "status_contract_missing", "publication": "REFUSED"}

    status = json.loads(status_path.read_text(encoding="utf-8"))
    pipeline = status.get("PIPELINE_STATUS")
    accepted = int(status.get("DRUG_CONCEPT_ACCEPTED_COUNT") or 0)

    if pipeline == "PROVIDER_INPUT_REQUIRED":
        return {
            "ok": False,
            "publication": "REFUSED",
            "reason": "PROVIDER_INPUT_REQUIRED",
            "expected_esklp_snapshot": status.get("expected_esklp_snapshot"),
            "message": "Do not publish another 0-accepted network-failure bundle.",
        }
    if pipeline in {
        "DOMAIN_REVIEW_DECISION_REQUIRED",
        "NO_PROVIDER_COVERAGE_ESTABLISHED",
        "MAPPING_DIAGNOSTIC_REQUIRED",
    } or accepted == 0:
        return {
            "ok": False,
            "publication": "REFUSED",
            "reason": pipeline or "DOMAIN_REVIEW_DECISION_REQUIRED",
            "DRUG_CONCEPT_ACCEPTED_COUNT": accepted,
            "private_review_pack": status.get("private_review_pack"),
            "private_diagnostics_dir": status.get("private_diagnostics_dir"),
            "message": (
                "Publication requires evidence-backed accepted mappings, "
                "or an explicit owner request after a verified nonzero provider index."
            ),
            "review_zip_name_if_eligible": REVIEW_ZIP,
            "version": VERSION,
        }

    # Explicit owner-gated path not auto-executed here
    return {
        "ok": False,
        "publication": "REFUSED_PENDING_OWNER_PUBLISH_IMPLEMENTATION",
        "reason": (
            "Accepted mappings present, but v0.1.1 publish packer runs only on "
            "explicit owner request after readiness review."
        ),
        "DRUG_CONCEPT_ACCEPTED_COUNT": accepted,
        "PIPELINE_STATUS": pipeline,
        "review_zip_name": REVIEW_ZIP,
    }
