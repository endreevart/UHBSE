"""Tests for Stage 03 implementation planning verification."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest
import yaml

from human_simulator.stage03.implementation_constants import (
    IMPLEMENTATION_CONTENT_ARTIFACTS,
    IMPLEMENTATION_PLAN_REPORT_NAME,
    PILOT_SOURCE_RELATIONS,
    SOURCE_A_PILOT_CONSTRUCTION_GROUPS,
    STAGE03_DESIGN_VERSION,
    STAGE03_IMPLEMENTATION_PLAN_VERSION,
)
from human_simulator.stage03.implementation_review_bundle import BUNDLE_ZIP_NAME, COPY_PATHS
from human_simulator.stage03.review_bundle_validation import validate_review_bundle_zip
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.verify_implementation_plan import (
    _check_report_semantic_validation,
    verify_implementation_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPL_DIR = REPO_ROOT / "artifacts" / "stage-03-implementation"
STAGE03_DIR = REPO_ROOT / "artifacts" / "stage-03"


def _prior_stages_ready() -> bool:
    stage01 = REPO_ROOT / "artifacts" / "stage-01" / "stage-01-report.md"
    stage02_verify = REPO_ROOT / "artifacts" / "stage-02" / "verify-stage-02.json"
    if not stage01.exists() or not stage02_verify.exists():
        return False
    verify = json.loads(stage02_verify.read_text(encoding="utf-8"))
    report = stage01.read_text(encoding="utf-8")
    return ("**Report status:** FINAL" in report or "Report status: FINAL" in report) and verify.get("status") == "PASS"


def test_all_implementation_plan_artifacts_exist() -> None:
    for name in IMPLEMENTATION_CONTENT_ARTIFACTS:
        assert (IMPL_DIR / name).exists(), name


def test_design_baseline_matches_live_manifest() -> None:
    live = (STAGE03_DIR / "design-content-manifest.sha256").read_text(encoding="utf-8")
    baseline = (IMPL_DIR / "design-baseline-manifest.sha256").read_text(encoding="utf-8")
    assert live == baseline


def test_review_bundle_copy_paths_include_full_package() -> None:
    assert "src/human_simulator" in COPY_PATHS
    assert "tests/test_verify_stage_03_design.py" in COPY_PATHS


def test_pilot_source_relation_graph_complete() -> None:
    doc = yaml.safe_load((IMPL_DIR / "pilot-slice.yaml").read_text(encoding="utf-8"))
    graph = {item["source_relation"] for item in doc["source_relation_graph"]}
    assert graph == set(PILOT_SOURCE_RELATIONS)


def test_source_record_groups_explicit_fields() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    groups = [g for g in contract["construction_groups"] if g.get("target_entity") == "SourceRecord"]
    assert len(groups) == 4
    for group in groups:
        assert group["relationship_fields"]["source_system_id"]["pilot_value"] == "magerya_api"
        assert "." not in group["constant_fields"]["source_relation"]


def test_observation_load_order_subject_only() -> None:
    pipeline = yaml.safe_load((IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    observation = next(item for item in pipeline["table_load_order"] if item["entity"] == "Observation")
    assert observation["depends_on"] == ["Subject"]
    fk = pipeline["fk_dependencies"]
    assert fk["Observation.encounter_id"] == "deferred_null_for_pilot"


def test_cohort_policy_rooted_at_subject() -> None:
    pipeline = yaml.safe_load((IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    cohort = pipeline["cohort_policy"]["first_live_pilot"]
    assert cohort["root"]["relation"] == "account_patient"
    assert cohort["root"]["limit"] == 100
    assert all(v["independent_limit"] == "forbidden" for v in cohort["related_rows"].values())


def test_source_snapshot_fingerprint_contract() -> None:
    pipeline = yaml.safe_load((IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    fp = pipeline["source_snapshot_fingerprint"]
    assert "source_snapshot_fingerprint" in fp["identical_snapshot_requires"]
    assert "raw_ids" in fp["per_relation"]["forbidden_persisted"]


def test_idempotent_promotion_five_cases() -> None:
    pipeline = yaml.safe_load((IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    cases = pipeline["idempotent_promotion"]["cases"]
    assert cases["new_canonical_id"]["action"] == "INSERT"
    assert cases["existing_canonical_id_same_payload_hash"]["action"] == "NOOP_ALREADY_PUBLISHED"
    assert cases["existing_canonical_id_different_payload_hash_same_input_version"]["action"] == "SOURCE_PAYLOAD_CHANGED"
    assert cases["existing_canonical_id_different_payload_hash_mapping_or_transform_version"]["action"] == "VERSIONED_REBUILD_REQUIRED"
    assert cases["existing_canonical_id_unclassified_conflict"]["action"] == "CANONICAL_PAYLOAD_CONFLICT"


def test_zero_open_blocking_decisions() -> None:
    doc = yaml.safe_load((IMPL_DIR / "unresolved-implementation-decisions.yaml").read_text(encoding="utf-8"))
    assert doc["open_blocking_count"] == 0
    open_blocking = [
        d for d in doc["decisions"] if d["resolution_status"] == "OPEN" and d["blocking_for_next_phase"]
    ]
    assert not open_blocking


def test_verify_implementation_plan_passes() -> None:
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    result = verify_implementation_plan(REPO_ROOT, run_pytest=False, publish_artifacts=False)
    assert result["status"] == "PASS", result.get("failures")


def test_verify_without_publish_is_side_effect_free() -> None:
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    before = {str(p.relative_to(IMPL_DIR)): sha256_file(p) for p in sorted(IMPL_DIR.rglob("*")) if p.is_file()}
    verify_implementation_plan(REPO_ROOT, run_pytest=False, publish_artifacts=False)
    after = {str(p.relative_to(IMPL_DIR)): sha256_file(p) for p in sorted(IMPL_DIR.rglob("*")) if p.is_file()}
    assert before == after


def test_review_bundle_imports_human_simulator() -> None:
    bundle = REPO_ROOT / "artifacts/external-review" / BUNDLE_ZIP_NAME
    if not bundle.exists():
        pytest.skip("review bundle missing")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(tmp)
        tmp_path = Path(tmp)
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from human_simulator.audit import report; "
                "from human_simulator.stage03.preconditions import check_stage_03_preconditions; "
                "from human_simulator.cli import main; print('ok')",
            ],
            cwd=tmp_path,
            env={"PYTHONPATH": str(tmp_path / "src"), **dict(__import__("os").environ)},
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr


def test_design_baseline_version_is_074() -> None:
    plan = yaml.safe_load((IMPL_DIR / "implementation-plan.yaml").read_text(encoding="utf-8"))
    assert plan["design_baseline_version"] == STAGE03_DESIGN_VERSION == "0.7.5"
    assert plan["document_version"] == STAGE03_IMPLEMENTATION_PLAN_VERSION == "0.3.6"


def test_report_v02_regression_fails_semantic_validation() -> None:
    plan = yaml.safe_load((IMPL_DIR / "implementation-plan.yaml").read_text(encoding="utf-8"))
    stale_report = (REPO_ROOT / "artifacts/stage-03-implementation/implementation-plan-report.md").read_text(encoding="utf-8")
    stale_report = stale_report.replace(
        f"Stage 03 — Implementation Planning v{STAGE03_IMPLEMENTATION_PLAN_VERSION}",
        "Stage 03 — Implementation Planning v0.2",
    )
    stale_report = stale_report.replace(
        f"Planning checkpoint v{STAGE03_IMPLEMENTATION_PLAN_VERSION} reached.",
        "Planning checkpoint v0.2 reached.",
    )
    stale_report = stale_report.replace("**v0.7.4**", "Design **v0.7.3**")
    checks: list = []

    def add(check) -> None:
        checks.append(check)

    _check_report_semantic_validation(add, report_text=stale_report, plan=plan, impl_dir=IMPL_DIR)
    assert any(c.name == "report_phase_version_matches_plan" and c.status == "FAIL" for c in checks)
    assert any(c.name == "report_no_stale_active_baseline" and c.status == "FAIL" for c in checks)


def test_review_bundle_zip_matches_index_exactly() -> None:
    bundle = REPO_ROOT / "artifacts/external-review" / BUNDLE_ZIP_NAME
    if not bundle.exists():
        pytest.skip("review bundle missing")
    ok, detail = validate_review_bundle_zip(bundle)
    assert ok, detail


def test_gate_return_matches_on_disk_verification_when_present() -> None:
    verification_path = IMPL_DIR / "implementation-plan-verification.json"
    if not verification_path.exists():
        pytest.skip("verification artifact missing")
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    on_disk = json.loads(verification_path.read_text(encoding="utf-8"))
    result = verify_implementation_plan(REPO_ROOT, run_pytest=False, publish_artifacts=False)
    assert result["status"] == on_disk["overall_status"]
    assert result["checks_total"] == on_disk["checks_total"]
    assert result["checks_passed"] == on_disk["checks_passed"]
    assert result["checks_failed"] == on_disk["checks_failed"]
    assert len(result["checks"]) == on_disk["checks_total"]
