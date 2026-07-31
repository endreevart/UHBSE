from human_simulator.audit.aggregates import profile_aggregates
from human_simulator.audit.connection import connection_check
from human_simulator.audit.discover import discover_schema
from human_simulator.audit.report import generate_report
from human_simulator.audit.structure import profile_structure
from human_simulator.audit.verify import verify_stage
from human_simulator.config.settings import AuditSettings


def test_generate_report_and_verify(disposable_engine, audit_settings: AuditSettings) -> None:
    bundle = {
        "source_audit": connection_check(audit_settings, disposable_engine),
        "schema_discovery": discover_schema(disposable_engine),
        "structure_profile": profile_structure(
            disposable_engine, discover_schema(disposable_engine)
        ),
        "aggregate_profile": profile_aggregates(
            disposable_engine,
            profile_structure(disposable_engine, discover_schema(disposable_engine)),
        ),
    }
    artifacts_dir = audit_settings.repo_root / audit_settings.artifacts_dir
    path = generate_report(artifacts_dir, bundle)
    assert path.exists()
    result = verify_stage(artifacts_dir)
    assert result["passed"] is False
    assert result["status"] in {"FAIL", "PARTIAL"}
    assert "entity-candidates.yaml" in result["missing"] or result["failures"]


def test_verify_stage_missing(tmp_path) -> None:
    result = verify_stage(tmp_path / "artifacts" / "stage-01")
    assert result["passed"] is False
    assert result["missing"]
