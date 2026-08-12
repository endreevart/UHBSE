"""Clean extraction test for vault-stop v0.2.1 — executes REPRODUCE.md commands."""

from __future__ import annotations

import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ZIP_PATH = REPO / "artifacts/external-review/stage-03-alignment-vault-stop-v0.2.1-review.zip"


@pytest.mark.skipif(not ZIP_PATH.is_file(), reason="vault-stop v0.2.1 zip not published yet")
def test_clean_extraction_runs_reproduce_commands(tmp_path: Path) -> None:
    extract = tmp_path / "extract"
    extract.mkdir()
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        zf.extractall(extract)
        # Restore executable bits from ZipInfo
        for info in zf.infolist():
            if info.filename.endswith(".sh"):
                mode = info.external_attr >> 16
                target = extract / info.filename
                if mode & 0o111:
                    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    reproduce = (extract / "REPRODUCE.md").read_text(encoding="utf-8")
    assert "bash -n ops/vault/scripts/*.sh" in reproduce
    assert "-tls-skip-verify" in reproduce
    assert 'storage "raft"' in reproduce or "storage \"raft\"" in reproduce

    env = os.environ.copy()
    env["PYTHONPATH"] = str(extract / "src") + os.pathsep + env.get("PYTHONPATH", "")

    commands = [
        "python3 -m compileall ops/vault/scripts src/human_simulator/stage03_alignment/vault_provider.py",
        "bash -n ops/vault/scripts/*.sh",
        "test -x ops/vault/scripts/preflight.sh",
        "test -x ops/vault/scripts/init-pgp.sh",
            # Fail only on active skip-verify usage (comments may mention the ban).
            "! grep -R --include='*.sh' --include='*.yml' --include='*.hcl' -nE -- '-tls-skip-verify|VAULT_SKIP_VERIFY=true' ops/vault docker-compose.yml",
            "grep -q 'storage \"raft\"' ops/vault/config/vault.hcl",
            "grep -q '127.0.0.1:5436:5432' docker-compose.yml",
        ]

    for cmd in commands:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=extract,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"command failed: {cmd}\nstdout={proc.stdout}\nstderr={proc.stderr}"

    # Unit tests shipped in the bundle (noconftest: extract lacks full package deps)
    proc = subprocess.run(
        [
            "python3",
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "tests/test_vault_provider_alignment_v02.py",
        ],
        cwd=extract,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
