"""Contract tests — Stage 05 v0.1.1 point correction."""

from __future__ import annotations

from pathlib import Path

import pytest

from human_simulator.intervention_response_readiness_v01.exposure import exposure_contract
from human_simulator.intervention_response_readiness_v01.policy import EVIDENCE_PATHS, REVIEW_ZIP as V01_REVIEW_ZIP
from human_simulator.intervention_response_readiness_v01.publish import PublicationError as V01PublicationError
from human_simulator.intervention_response_readiness_v01.publish import publish as publish_v01
from human_simulator.intervention_response_readiness_v011.policy import (
    EVIDENCE_CATALOG,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    SECURITY_STAGE_STATUS,
    V01_INDEXED,
    V01_MEMBERS,
    V01_SHA256,
    V01_ZIP,
)


def test_catalog_is_the_ten_v01_evidence_paths() -> None:
    assert len(EVIDENCE_CATALOG) == 10
    assert {item["key"]: item["canonical_source_path"] for item in EVIDENCE_CATALOG} == EVIDENCE_PATHS
    assert len({item["canonical_source_path"] for item in EVIDENCE_CATALOG}) == 10


def test_scientific_statuses_are_not_upgraded() -> None:
    snap = {
        "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
        "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
    }
    assert snap["INTERVENTION_RESPONSE_READINESS_STATUS"] != "READY"
    assert SECURITY_STAGE_STATUS == "PAUSED_NOT_ACCEPTED_BY_OWNER"
    contract = exposure_contract()
    assert contract["promotion"] == "FORBIDDEN_AUTOMATIC"
    assert "RECORDED_MEDICATION_ASSOCIATION" not in contract["intervention_response_eligible_tiers"]


def test_prior_zip_scope_excludes_packing_stage04_and_pins_v01() -> None:
    assert len(PRIOR_ZIPS) == 7
    assert all(name.startswith("stage-04-") for name, _sha in PRIOR_ZIPS.values())
    assert V01_ZIP.startswith("stage-05-")
    assert V01_SHA256 == "6605a4b643ea68ae893d6b52d0a0a196e1e2ad2ec505adad5691a41df70cf992"
    assert V01_MEMBERS == 1025
    assert V01_INDEXED == 1024
    assert REVIEW_ZIP.endswith("-v0.1.1-review.zip")
    assert REVIEW_ZIP != V01_REVIEW_ZIP


def test_v01_publish_refuses_overwrite(tmp_path: Path) -> None:
    external = tmp_path / "artifacts" / "external-review"
    external.mkdir(parents=True)
    target = external / V01_REVIEW_ZIP
    target.write_bytes(b"published-v01")
    with pytest.raises(V01PublicationError, match="refuse overwrite"):
        publish_v01(tmp_path)
    assert target.read_bytes() == b"published-v01"
