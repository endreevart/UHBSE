"""Clean-extraction semantics for runtime-auth v0.1.2.

A. Publisher-side clean-extraction verifier (workspace) — not an extracted-bundle suite.
B. Suite executed from extracted review ZIP — skip until v0.1.2 ZIP exists.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

from human_simulator.stage03_alignment.publish_runtime_auth_v012 import (
    publisher_side_clean_extraction_verify,
)

REPO = Path(__file__).resolve().parents[1]
ZIP_PATH = REPO / "artifacts/external-review/stage-03-alignment-runtime-auth-v0.1.2-review.zip"


def test_publisher_side_clean_extraction_verifier_is_not_extracted_suite() -> None:
    result = publisher_side_clean_extraction_verify()
    assert result["kind"] == "publisher_side_clean_extraction_verifier"
    assert result["not_extracted_bundle_suite"] is True
    assert result["passed"] is True
    assert result["manifest_fails_after_content_mutation"] is True


@pytest.mark.skipif(not ZIP_PATH.is_file(), reason="runtime-auth v0.1.2 zip not published yet")
def test_suite_from_extracted_review_bundle(tmp_path: Path) -> None:
    """B: real suite from clean ZIP extract — independent of publisher workspace."""
    extract = tmp_path / "extract"
    extract.mkdir()
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        names = zf.namelist()
        assert not any(n.endswith(".zip") for n in names), "no nested archives"
        assert not any(n.startswith("artifacts/external-review/") for n in names)
        zf.extractall(extract)
        for info in zf.infolist():
            if info.filename.endswith(".sh"):
                mode = info.external_attr >> 16
                target = extract / info.filename
                if mode & 0o111:
                    target.chmod(target.stat().st_mode | stat.S_IXUSR)

        index = (extract / "REVIEW_INDEX.md").read_text(encoding="utf-8")
        indexed: dict[str, str] = {}
        for line in index.splitlines():
            m = re.match(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", line)
            if m:
                indexed[m.group(1)] = m.group(2)
        members = [n for n in names if n != "REVIEW_INDEX.md"]
        assert set(members) == set(indexed)
        for arc, expected in indexed.items():
            digest = hashlib.sha256((extract / arc).read_bytes()).hexdigest()
            assert digest == expected, arc

        # Internal evidence manifest
        evidence = extract / "artifacts/stage-03-alignment-runtime-auth-v0.1.2"
        manifest = evidence / "manifest.sha256"
        assert manifest.is_file()
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, name = line.split(maxsplit=1)
            assert hashlib.sha256((evidence / name.strip()).read_bytes()).hexdigest() == digest

    env = os.environ.copy()
    env["PYTHONPATH"] = str(extract / "src") + os.pathsep + env.get("PYTHONPATH", "")
    py = "python3.12"
    which = subprocess.run(
        ["bash", "-lc", "command -v python3.12"], capture_output=True, text=True, check=False
    )
    if which.returncode != 0:
        py = str(REPO / ".venv" / "bin" / "python")

    def run(cmd: str) -> None:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=extract,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{cmd}\n{proc.stdout}\n{proc.stderr}"

    # Absence of outer ZIP inside extract is expected/acceptable
    assert not (extract / "artifacts/external-review").exists() or not any(
        (extract / "artifacts/external-review").glob("*.zip")
    )

    run(f"{py!r} -m compileall src/human_simulator ops/vault/runtime")
    run(
        f"{py!r} -m pytest -q --noconftest "
        "tests/test_runtime_auth_v012_unit.py "
        "tests/test_runtime_auth_v012_publication.py"
    )
    run("grep -q 'hmac-subject-key?version=1' ops/vault/runtime/vault-agent.hcl")
    run("grep -q 'loader-credential?version=1' ops/vault/runtime/vault-agent.hcl")
    run("grep -q 'canonical-loader-runtime' docker-compose.yml")

    for path in evidence.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "hvs." not in text
        assert "postgresql://" not in text.lower()
        assert "synthetic-subject-runtime-smoke-001" not in text
        assert '"two_independent_wrapped_secret_ids": true' not in text
