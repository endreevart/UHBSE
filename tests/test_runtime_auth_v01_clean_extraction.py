"""Clean extraction test for runtime-auth v0.1 — runs REPRODUCE.md commands."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ZIP_PATH = REPO / "artifacts/external-review/stage-03-alignment-runtime-auth-v0.1-review.zip"


@pytest.mark.skipif(not ZIP_PATH.is_file(), reason="runtime-auth v0.1 zip not published yet")
def test_clean_extraction_runs_reproduce_and_index(tmp_path: Path) -> None:
    extract = tmp_path / "extract"
    extract.mkdir()
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        names = zf.namelist()
        assert not any(n.endswith(".zip") for n in names), "nested archives forbidden"
        zf.extractall(extract)
        for info in zf.infolist():
            if info.filename.endswith(".sh"):
                mode = info.external_attr >> 16
                target = extract / info.filename
                if mode & 0o111:
                    target.chmod(target.stat().st_mode | stat.S_IXUSR)

        # Verify REVIEW_INDEX hashes and no unindexed members
        index = (extract / "REVIEW_INDEX.md").read_text(encoding="utf-8")
        indexed: dict[str, str] = {}
        for line in index.splitlines():
            m = re.match(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", line)
            if m:
                indexed[m.group(1)] = m.group(2)
        assert "REVIEW_INDEX.md" not in indexed
        members = [n for n in names if n != "REVIEW_INDEX.md"]
        assert set(members) == set(indexed)
        for arc, expected in indexed.items():
            digest = hashlib.sha256((extract / arc).read_bytes()).hexdigest()
            assert digest == expected, arc

    env = os.environ.copy()
    env["PYTHONPATH"] = str(extract / "src") + os.pathsep + env.get("PYTHONPATH", "")

    py = "python3.12"
    which = subprocess.run(
        ["bash", "-lc", "command -v python3.12"],
        capture_output=True,
        text=True,
        check=False,
    )
    if which.returncode != 0:
        candidate = REPO / ".venv" / "bin" / "python"
        assert candidate.is_file(), "Python >= 3.12 required for clean extraction"
        py = str(candidate)

    def run_cmd(cmd: str) -> None:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=extract,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{cmd}\n{proc.stdout}\n{proc.stderr}"

    run_cmd(f"{py!r} -m compileall src/human_simulator")
    run_cmd(f"{py!r} -m pytest -q --noconftest tests/test_runtime_auth_alignment_v01.py")
    run_cmd("test -f ops/vault/agent/vault-agent.hcl")
    run_cmd("grep -q 'remove_secret_id_file_after_reading = true' ops/vault/agent/vault-agent.hcl")
    run_cmd("grep -q 'secret_id_response_wrapping_path' ops/vault/agent/vault-agent.hcl")
    run_cmd("grep -q '/run/uhbse-vault' docker-compose.yml")

    # No secret-like material in extracted evidence JSON
    for path in (extract / "artifacts/stage-03-alignment-candidate").glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "hvs." not in text
        assert "postgresql://" not in text.lower()
        assert "synthetic-subject-runtime-smoke-001" not in text
