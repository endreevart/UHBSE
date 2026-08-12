"""Regression tests for Changeset 01 v0.2.1 — Publication Isolation Fix.

Three defects made v0.2 ship a review bundle containing regenerated Design evidence:

1. no hash pinned the two generated Design evidence files, so nothing noticed the swap;
2. publication-capable tests wrote into the working tree and restored afterwards, which is
   not safe when two runs overlap;
3. nothing prevented two publishers from running at once.

Each is covered below. Nothing here touches a real artifact: every test that writes runs in a
throwaway copy of the workspace.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from human_simulator.stage03.changeset_01_review_bundle import ChangesetBundleError
from human_simulator.stage03.frozen_evidence import (
    DESIGN_EVIDENCE_SOURCE_ARCHIVES,
    DESIGN_REPORT_NAME,
    DESIGN_VERIFICATION_NAME,
    FROZEN_DESIGN_EVIDENCE_SHA256,
    FROZEN_MIGRATION_SHA256,
    FrozenEvidenceDrift,
    evaluate_frozen_evidence,
    frozen_evidence_fingerprint,
    frozen_evidence_records,
    recover_design_evidence,
    repair_entry_points_used,
    require_frozen_evidence,
)
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.publication_lock import (
    LOCK_NAME,
    PublicationLocked,
    is_stale,
    lock_path,
    publication_lock,
)

DESIGN_DIR = Path("artifacts") / "stage-03"


# --------------------------------------------------------------------------------------
# 1. Frozen evidence is pinned by hash, including the files no manifest covers
# --------------------------------------------------------------------------------------


def test_the_audited_design_evidence_hashes_are_pinned() -> None:
    assert FROZEN_DESIGN_EVIDENCE_SHA256 == {
        DESIGN_REPORT_NAME: "6f30b6aaa25a2efa9a6ead3ab7f76563fa688f1f61d94818c2562015d70a6785",
        DESIGN_VERIFICATION_NAME: "ae4a426aa5cb44e03cf509afed54c917af25a2d6283486ab393ae19159f8254c",
    }


def test_the_workspace_carries_the_audited_design_evidence(repo_root: Path) -> None:
    for name, accepted in FROZEN_DESIGN_EVIDENCE_SHA256.items():
        assert sha256_file(repo_root / DESIGN_DIR / name) == accepted, name


def test_frozen_evidence_covers_every_required_category(repo_root: Path) -> None:
    records = frozen_evidence_records(repo_root)
    counts: dict[str, int] = {}
    for record in records:
        counts[record.category] = counts.get(record.category, 0) + 1
    assert counts["stage_01_02_controlled"] == 9
    assert counts["design_content_artifact"] == 12
    assert counts["design_evidence"] == 2
    assert counts["design_manifest"] == 1
    assert counts["plan_manifest"] == 1
    assert counts["plan_artifact"] >= 1
    assert counts["migration"] == len(FROZEN_MIGRATION_SHA256) == 4


def test_frozen_evidence_passes_on_the_current_checkpoint(repo_root: Path) -> None:
    document = evaluate_frozen_evidence(repo_root)
    assert document["status"] == "PASS", document["changed"]
    assert document["all_unchanged"] is True
    assert document["frozen_design_report_match"] is True
    assert document["frozen_design_verification_match"] is True
    assert document["repairs_performed"] == 0
    assert document["automatic_restore_performed"] is False


def test_a_regenerated_design_report_is_detected(isolated_workspace: Path) -> None:
    victim = isolated_workspace / DESIGN_DIR / DESIGN_REPORT_NAME
    victim.write_text(victim.read_text(encoding="utf-8") + "\nregenerated\n", encoding="utf-8")

    document = evaluate_frozen_evidence(isolated_workspace)
    assert document["status"] == "FAIL"
    assert document["frozen_design_report_match"] is False
    assert [record["path"] for record in document["changed"]] == [
        (DESIGN_DIR / DESIGN_REPORT_NAME).as_posix()
    ]


def test_a_regenerated_design_verification_is_detected(isolated_workspace: Path) -> None:
    victim = isolated_workspace / DESIGN_DIR / DESIGN_VERIFICATION_NAME
    payload = json.loads(victim.read_text(encoding="utf-8"))
    payload["verified_at"] = "2000-01-01T00:00:00+00:00"
    victim.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    document = evaluate_frozen_evidence(isolated_workspace)
    assert document["status"] == "FAIL"
    assert document["frozen_design_verification_match"] is False


def test_a_modified_migration_is_detected(isolated_workspace: Path) -> None:
    victim = isolated_workspace / "migrations" / "canonical" / "0004_storage_contract_hardening.sql"
    victim.write_text(victim.read_text(encoding="utf-8") + "\n-- edited\n", encoding="utf-8")
    assert evaluate_frozen_evidence(isolated_workspace)["status"] == "FAIL"


def test_drift_raises_and_restores_nothing(isolated_workspace: Path) -> None:
    victim = isolated_workspace / DESIGN_DIR / DESIGN_REPORT_NAME
    mutated = victim.read_text(encoding="utf-8") + "\nregenerated\n"
    victim.write_text(mutated, encoding="utf-8")

    with pytest.raises(FrozenEvidenceDrift) as error:
        require_frozen_evidence(isolated_workspace, context="in a test")
    assert "never by regenerating them" in str(error.value)
    assert victim.read_text(encoding="utf-8") == mutated


# --------------------------------------------------------------------------------------
# 2. Recovery is explicit, verified against the audited hashes, and never automatic
# --------------------------------------------------------------------------------------


def test_recovery_without_confirmation_writes_nothing(repo_root: Path, tmp_path: Path) -> None:
    import shutil

    workspace = tmp_path / "workspace"
    (workspace / DESIGN_DIR).mkdir(parents=True)
    (workspace / "artifacts" / "external-review").mkdir(parents=True)
    for archive in DESIGN_EVIDENCE_SOURCE_ARCHIVES:
        source = repo_root / "artifacts" / "external-review" / archive
        if source.is_file():
            shutil.copy2(source, workspace / "artifacts" / "external-review" / archive)
    for name in FROZEN_DESIGN_EVIDENCE_SHA256:
        (workspace / DESIGN_DIR / name).write_text("regenerated\n", encoding="utf-8")

    result = recover_design_evidence(workspace, confirm=False)
    assert result["confirmed"] is False
    assert len(result["restored"]) == 2
    for name in FROZEN_DESIGN_EVIDENCE_SHA256:
        assert (workspace / DESIGN_DIR / name).read_text(encoding="utf-8") == "regenerated\n"


def test_recovery_installs_only_the_audited_bytes(repo_root: Path, tmp_path: Path) -> None:
    import shutil

    workspace = tmp_path / "workspace"
    (workspace / DESIGN_DIR).mkdir(parents=True)
    (workspace / "artifacts" / "external-review").mkdir(parents=True)
    available = False
    for archive in DESIGN_EVIDENCE_SOURCE_ARCHIVES:
        source = repo_root / "artifacts" / "external-review" / archive
        if source.is_file():
            shutil.copy2(source, workspace / "artifacts" / "external-review" / archive)
            available = True
    if not available:
        pytest.skip("no accepted release archive available in this workspace")
    for name in FROZEN_DESIGN_EVIDENCE_SHA256:
        (workspace / DESIGN_DIR / name).write_text("regenerated\n", encoding="utf-8")

    recover_design_evidence(workspace, confirm=True)
    for name, accepted in FROZEN_DESIGN_EVIDENCE_SHA256.items():
        assert sha256_file(workspace / DESIGN_DIR / name) == accepted


def test_recovery_fails_when_no_archive_carries_the_audited_bytes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / DESIGN_DIR).mkdir(parents=True)
    (workspace / "artifacts" / "external-review").mkdir(parents=True)
    for name in FROZEN_DESIGN_EVIDENCE_SHA256:
        (workspace / DESIGN_DIR / name).write_text("regenerated\n", encoding="utf-8")

    with pytest.raises(FrozenEvidenceDrift):
        recover_design_evidence(workspace, confirm=True)
    for name in FROZEN_DESIGN_EVIDENCE_SHA256:
        assert (workspace / DESIGN_DIR / name).read_text(encoding="utf-8") == "regenerated\n"


def test_no_gate_or_suite_can_reach_the_recovery_path(repo_root: Path) -> None:
    """Recovery must be unreachable from anything a pipeline runs.

    Looks for a real import or call, since a verifier may legitimately name the symbol in a
    failure message.
    """
    for name in (
        "changeset_01_baseline.py",
        "verify_changeset_01.py",
        "publish_changeset_01.py",
        "changeset_01_review_bundle.py",
        "changeset_01_attestation.py",
        "release_verification.py",
        "pre_live_load_gate.py",
    ):
        source = (repo_root / "src" / "human_simulator" / "stage03" / name).read_text(
            encoding="utf-8"
        )
        assert repair_entry_points_used(source) == [], (
            f"{name} must not be able to repair evidence"
        )


def test_the_reachability_check_catches_a_real_call() -> None:
    """The detector must fire on a call and stay silent on a mention."""
    assert repair_entry_points_used("recover_design_evidence(root, confirm=True)") == [
        "recover_design_evidence"
    ]
    assert repair_entry_points_used(
        "from human_simulator.stage03.frozen_evidence import recover_design_evidence"
    ) == ["recover_design_evidence"]
    assert repair_entry_points_used('detail = "run recover_design_evidence --confirm"') == []


# --------------------------------------------------------------------------------------
# 3. The bundle builder refuses regenerated Design evidence
# --------------------------------------------------------------------------------------


def test_builder_refuses_to_package_regenerated_design_evidence(isolated_workspace: Path) -> None:
    from human_simulator.stage03.changeset_01_review_bundle import (
        build_changeset_01_review_bundle,
    )

    victim = isolated_workspace / DESIGN_DIR / DESIGN_REPORT_NAME
    victim.write_text(victim.read_text(encoding="utf-8") + "\nregenerated\n", encoding="utf-8")

    with pytest.raises(ChangesetBundleError) as error:
        build_changeset_01_review_bundle(isolated_workspace, generated_at="2026-01-01T00:00:00Z")
    message = str(error.value)
    assert "Design evidence" in message or "design" in message.lower()

    published = isolated_workspace / "artifacts" / "external-review"
    assert not list(published.glob("*changeset-01-v*.zip"))


# --------------------------------------------------------------------------------------
# 4. Publication-capable tests never write into the working tree
# --------------------------------------------------------------------------------------


def test_the_isolated_workspace_is_a_copy(repo_root: Path, isolated_workspace: Path) -> None:
    assert isolated_workspace != repo_root
    assert repo_root not in isolated_workspace.parents
    assert (isolated_workspace / DESIGN_DIR / DESIGN_REPORT_NAME).is_file()
    assert (isolated_workspace / "pyproject.toml").is_file()


def test_writing_in_the_copy_leaves_the_real_workspace_alone(
    repo_root: Path, isolated_workspace: Path
) -> None:
    before = frozen_evidence_fingerprint(repo_root)
    (isolated_workspace / DESIGN_DIR / DESIGN_REPORT_NAME).write_text("x\n", encoding="utf-8")
    assert frozen_evidence_fingerprint(repo_root) == before


def test_no_test_publishes_into_the_real_workspace(repo_root: Path) -> None:
    """Every publishing call site must be pointed at a copy, not at REPO_ROOT."""
    offenders: list[str] = []
    for path in sorted((repo_root / "tests").glob("test_*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "publish_artifacts=True" not in line and "publish=True" not in line:
                continue
            if "REPO_ROOT" in line or "repo_root" in line:
                offenders.append(f"{path.name}:{number}")
    assert offenders == [], f"tests publishing into the working tree: {offenders}"


# --------------------------------------------------------------------------------------
# 5. Concurrent publication is impossible
# --------------------------------------------------------------------------------------


def test_a_second_thread_is_refused_immediately(isolated_workspace: Path) -> None:
    """Another thread is refused exactly as another process would be."""
    import threading

    outcome: dict[str, str] = {}

    def contend() -> None:
        try:
            with publication_lock(isolated_workspace, operation="second"):
                outcome["result"] = "acquired"
        except PublicationLocked as error:
            outcome["result"] = "refused"
            outcome["detail"] = str(error)

    with publication_lock(isolated_workspace, operation="first"):
        thread = threading.Thread(target=contend)
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert outcome["result"] == "refused"
    assert "already in progress" in outcome["detail"]


def test_nesting_on_the_acquiring_thread_is_allowed(isolated_workspace: Path) -> None:
    """The publisher holds the lock while calling publishing steps inside it."""
    with publication_lock(isolated_workspace, operation="publish") as outer:
        with publication_lock(isolated_workspace, operation="snapshot") as inner:
            assert inner.operation == outer.operation
            assert lock_path(isolated_workspace).is_file()
        # The inner block must not release a lock it did not create.
        assert lock_path(isolated_workspace).is_file()
    assert not lock_path(isolated_workspace).exists()


def test_the_lock_is_released_afterwards(isolated_workspace: Path) -> None:
    with publication_lock(isolated_workspace, operation="first"):
        assert lock_path(isolated_workspace).is_file()
    assert not lock_path(isolated_workspace).exists()

    with publication_lock(isolated_workspace, operation="second"):
        pass


def test_the_lock_records_no_secret(isolated_workspace: Path) -> None:
    with publication_lock(isolated_workspace, operation="changeset_01_publish"):
        payload = json.loads(lock_path(isolated_workspace).read_text(encoding="utf-8"))
    assert set(payload) == {"pid", "host", "operation", "acquired_at"}
    text = json.dumps(payload).lower()
    for forbidden in ("password", "secret", "token", "postgres://", "postgresql://", "hmac"):
        assert forbidden not in text


def test_a_lock_owned_by_a_dead_process_is_stale(isolated_workspace: Path) -> None:
    import socket

    path = lock_path(isolated_workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    dead = subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
    assert dead.returncode == 0
    path.write_text(
        json.dumps(
            {
                # A pid that has certainly exited: this interpreter just reaped it.
                "pid": 2**22 - 1,
                "host": socket.gethostname(),
                "operation": "abandoned",
                "acquired_at": "2000-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    assert is_stale(isolated_workspace) is True

    with publication_lock(isolated_workspace, operation="recovering"):
        payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["operation"] == "recovering"


def test_a_live_lock_is_not_stale(isolated_workspace: Path) -> None:
    with publication_lock(isolated_workspace, operation="live"):
        assert is_stale(isolated_workspace) is False


def test_a_corrupt_lock_is_stale_and_recoverable(isolated_workspace: Path) -> None:
    path = lock_path(isolated_workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ truncated", encoding="utf-8")
    assert is_stale(isolated_workspace) is True
    with publication_lock(isolated_workspace, operation="after_corrupt"):
        assert json.loads(path.read_text(encoding="utf-8"))["operation"] == "after_corrupt"


# The child announces on stdout that it holds the lock, then blocks on stdin until the parent
# has finished its own attempt. Both handoffs are blocking pipe reads, so the test is decided by
# real synchronization rather than by a timing guess.
CONTENDER = """
import json, sys
from pathlib import Path
from human_simulator.stage03.publication_lock import PublicationLocked, publication_lock

root = Path(sys.argv[1])
try:
    with publication_lock(root, operation="contender"):
        print(json.dumps({"event": "held"}), flush=True)
        sys.stdin.readline()
    print(json.dumps({"result": "acquired"}), flush=True)
except PublicationLocked as error:
    print(json.dumps({"result": "refused", "detail": str(error)}), flush=True)
"""


def test_two_concurrent_processes_cannot_both_publish(
    isolated_workspace: Path, tmp_path: Path
) -> None:
    """Exactly one of two real, overlapping processes may hold the lock."""
    script = tmp_path / "contender.py"
    script.write_text(CONTENDER, encoding="utf-8")

    first = subprocess.Popen(
        [sys.executable, str(script), str(isolated_workspace)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert first.stdout is not None and first.stdin is not None
        announcement = first.stdout.readline()
        assert json.loads(announcement)["event"] == "held"

        with pytest.raises(PublicationLocked) as error:
            with publication_lock(isolated_workspace, operation="second_in_parent"):
                pytest.fail("the parent acquired a lock the child was holding")
        assert str(first.pid) in str(error.value)
    finally:
        stdout, stderr = first.communicate(input="release\n", timeout=60)

    assert first.returncode == 0, stderr
    assert json.loads(stdout.strip().splitlines()[-1])["result"] == "acquired"
    assert not lock_path(isolated_workspace).exists()


def test_read_only_gates_do_not_require_the_lock(isolated_workspace: Path) -> None:
    """A held lock must not block a reviewer running a read-only gate."""
    from human_simulator.stage03.changeset_01_baseline import evaluate_baseline
    from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate

    with publication_lock(isolated_workspace, operation="publishing"):
        assert evaluate_baseline(isolated_workspace)["status"] == "PASS"
        assert evaluate_pre_live_load_gate(isolated_workspace).status == "FAIL"
        assert evaluate_frozen_evidence(isolated_workspace)["status"] == "PASS"


# --------------------------------------------------------------------------------------
# 6. A full mandatory suite run leaves every frozen input byte identical
# --------------------------------------------------------------------------------------


@pytest.mark.publisher_only
def test_the_full_mandatory_suite_does_not_touch_frozen_evidence(repo_root: Path) -> None:
    """Run the mandatory suite for real and prove nothing frozen moved.

    This is the check that would have caught the v0.2 defect at the moment it happened, rather
    than after the archive had been hashed and shipped.
    """
    from human_simulator.stage03.release_verification import full_repository_suite_command

    before = frozen_evidence_fingerprint(repo_root)
    completed = subprocess.run(
        full_repository_suite_command(),
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    after = frozen_evidence_fingerprint(repo_root)

    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    assert changed == [], f"the suite modified frozen evidence: {changed}"
    assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-2000:]

    document = evaluate_frozen_evidence(repo_root)
    assert document["status"] == "PASS"
    assert document["repairs_performed"] == 0
    assert document["automatic_restore_performed"] is False


def test_the_lock_file_never_reaches_a_review_bundle(repo_root: Path) -> None:
    from human_simulator.stage03.review_dependencies import (
        get_changeset_01_review_bundle_paths,
    )

    bundled = get_changeset_01_review_bundle_paths()
    assert not any(LOCK_NAME in path for path in bundled)
    assert not any(path.startswith("artifacts/external-review") for path in bundled)
