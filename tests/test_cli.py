from human_simulator.cli import main


def test_cli_verify_stage_missing(audit_settings, monkeypatch) -> None:
    monkeypatch.chdir(audit_settings.repo_root)
    (audit_settings.repo_root / "docs").mkdir(exist_ok=True)
    (audit_settings.repo_root / "docs" / "current-stage.md").write_text("Stage 01", encoding="utf-8")
    code = main(["--root", str(audit_settings.repo_root), "verify-stage"])
    assert code in {1, 2}
