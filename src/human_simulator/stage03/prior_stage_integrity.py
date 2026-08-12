"""Prior-stage byte integrity for Stage 01/02 during implementation planning.

Evaluation in this module is strictly read-only. Restoring the accepted baseline is a
separate, explicitly confirmed operation exposed only through the
``restore-prior-stage-baseline --confirm`` CLI command; verifiers, gates and tests must
never repair a detected change.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from human_simulator.stage03.implementation_constants import (
    STAGE01_PRECONDITION_ARTIFACTS,
    STAGE02_PRECONDITION_ARTIFACTS,
    STAGE03_PRIOR_STAGE_DEPENDENCY_ARTIFACTS,
)
from human_simulator.stage03.preconditions import sha256_file

PRIOR_STAGE_INTEGRITY_NAME = "prior-stage-integrity.json"

BASELINE_SOURCE_KIND = "accepted_review_bundle"
BASELINE_SOURCE_PATH = "stage-03-design-v0.7.1-review.zip"
BASELINE_SOURCE_ZIP = f"artifacts/external-review/{BASELINE_SOURCE_PATH}"
BASELINE_SOURCE_ZIP_SHA256 = "bfaaac69df65c3b21c195f76ae3ee722acf4d17aadf3bf8dba85fac18fc32084"
BASELINE_SOURCE_NOTE = (
    "Accepted Stage 01/02 bytes are content-addressed. No Git commit in this repository "
    "contains the accepted Stage 02 artifacts, so no Git provenance is claimed."
)

ACCEPTED_SHA256: dict[str, str] = {
    "artifacts/stage-01/schema-profile.json": "d549e612a1df27dcdd34dfdcc884a69b08485a3d387edf1f75678b5e96535d0e",
    "artifacts/stage-01/stage-01-report.md": "f34852cb3eabcd1948524af404bf57a60d325d22f9f52c6e6577ad2c4bcd62ff",
    "artifacts/stage-02/verify-stage-02.json": "57818466c22e9f48968a2e5a421b80462728c03500c480f2c04ffe9efa57bf6a",
    "artifacts/stage-02/stage-02-report.md": "4b64553783594b5c5c6954615ddd230e0b0982ef765966ad1a34897efc77319e",
    "artifacts/stage-02/stage-02-final-manifest.sha256": "7752deef1009bc1d846aecb2d2548f73681155528209914eef55ee72d01c5eca",
    "artifacts/stage-02/entity-crosswalk.yaml": "f0b93b4e6ccea2732483b66001d28368365bc8eeb197c39b302f36975a74f920",
    "artifacts/stage-02/identity-linkage-assessment.json": "9bc39761915a77308569fef183523a7310bc8248ab62849e648206867c685cd6",
    "artifacts/stage-02/subject-root-analysis.json": "9a685d76cc45cdb948b89d28cc13c6df61984dd15f21c424c5d42f21f76c98e8",
    "artifacts/stage-02/schema-profile-kgz.json": "1065db5d00edcabb0fe714cedf6cd80c1a7d19890c34d277bdb6c4694c4238ce",
}

CONTROLLED_PRIOR_STAGE_PATHS: tuple[str, ...] = (
    STAGE01_PRECONDITION_ARTIFACTS
    + STAGE02_PRECONDITION_ARTIFACTS
    + STAGE03_PRIOR_STAGE_DEPENDENCY_ARTIFACTS
)


@dataclass(frozen=True)
class PriorStageFileRecord:
    path: str
    accepted_sha256: str | None
    current_sha256: str
    unchanged: bool


def snapshot_prior_stage_hashes(repo_root: Path) -> dict[str, str]:
    """Read current hashes of controlled files without touching them."""
    root = repo_root.resolve()
    return {
        rel: sha256_file(root / rel)
        for rel in CONTROLLED_PRIOR_STAGE_PATHS
        if (root / rel).exists()
    }


def evaluate_prior_stage_integrity(repo_root: Path) -> tuple[bool, list[PriorStageFileRecord]]:
    """Compare controlled Stage 01/02 files against accepted hashes. Never writes."""
    root = repo_root.resolve()
    records: list[PriorStageFileRecord] = []
    all_ok = True
    for rel in CONTROLLED_PRIOR_STAGE_PATHS:
        path = root / rel
        accepted = ACCEPTED_SHA256[rel]
        if not path.exists():
            all_ok = False
            records.append(
                PriorStageFileRecord(
                    path=rel,
                    accepted_sha256=accepted,
                    current_sha256="",
                    unchanged=False,
                )
            )
            continue
        current = sha256_file(path)
        unchanged = current == accepted
        if not unchanged:
            all_ok = False
        records.append(
            PriorStageFileRecord(
                path=rel,
                accepted_sha256=accepted,
                current_sha256=current,
                unchanged=unchanged,
            )
        )
    return all_ok, records


def baseline_source_descriptor(repo_root: Path) -> dict[str, Any]:
    """Describe where the accepted bytes come from, verifying member hashes when available."""
    zip_path = repo_root.resolve() / BASELINE_SOURCE_ZIP
    bundle_sha256 = ""
    member_hashes_verified = False
    if zip_path.exists():
        bundle_sha256 = sha256_file(zip_path)
        try:
            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())
                member_hashes_verified = all(
                    rel in names
                    and hashlib.sha256(archive.read(rel)).hexdigest() == ACCEPTED_SHA256[rel]
                    for rel in CONTROLLED_PRIOR_STAGE_PATHS
                )
        except zipfile.BadZipFile:
            member_hashes_verified = False
    return {
        "kind": BASELINE_SOURCE_KIND,
        "path": BASELINE_SOURCE_PATH,
        "bundle_sha256": bundle_sha256 or BASELINE_SOURCE_ZIP_SHA256,
        "bundle_sha256_expected": BASELINE_SOURCE_ZIP_SHA256,
        "bundle_present_in_workspace": zip_path.exists(),
        "member_hashes_verified": member_hashes_verified,
        "note": BASELINE_SOURCE_NOTE,
    }


def build_prior_stage_integrity_document(
    repo_root: Path,
    *,
    hashes_before_test_suite: dict[str, str] | None = None,
    hashes_after_test_suite: dict[str, str] | None = None,
    test_suite_unchanged_prior_stages: bool | None = None,
) -> dict[str, Any]:
    unchanged, records = evaluate_prior_stage_integrity(repo_root)
    before = hashes_before_test_suite or snapshot_prior_stage_hashes(repo_root)
    after = hashes_after_test_suite or before
    suite_unchanged = test_suite_unchanged_prior_stages
    if suite_unchanged is None:
        suite_unchanged = before == after
    return {
        "baseline_source": baseline_source_descriptor(repo_root),
        "controlled_file_count": len(CONTROLLED_PRIOR_STAGE_PATHS),
        "controlled_files": [asdict(record) for record in records],
        "unchanged": unchanged and suite_unchanged,
        "hashes_before_test_suite": before,
        "hashes_after_test_suite": after,
        "test_suite_unchanged_prior_stages": suite_unchanged,
        "automatic_restore_performed": False,
        "restore_command": "audit restore-prior-stage-baseline --confirm",
    }


def write_prior_stage_integrity(repo_root: Path, document: dict[str, Any]) -> Path:
    path = repo_root / "artifacts" / "stage-03-implementation" / PRIOR_STAGE_INTEGRITY_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def restore_prior_stage_baseline(repo_root: Path, *, confirm: bool = False) -> list[str]:
    """Restore accepted Stage 01/02 bytes.

    Only the explicit ``restore-prior-stage-baseline --confirm`` CLI command may call this.
    Verifiers, gates and tests must not invoke it.
    """
    if not confirm:
        raise PermissionError(
            "restore_prior_stage_baseline requires explicit confirmation: "
            "audit restore-prior-stage-baseline --confirm"
        )
    root = repo_root.resolve()
    zip_path = root / BASELINE_SOURCE_ZIP
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing baseline source bundle: {BASELINE_SOURCE_ZIP}")
    restored: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for rel in CONTROLLED_PRIOR_STAGE_PATHS:
            if rel not in names:
                raise FileNotFoundError(f"Baseline bundle missing controlled path: {rel}")
            payload = archive.read(rel)
            if hashlib.sha256(payload).hexdigest() != ACCEPTED_SHA256[rel]:
                raise ValueError(f"Baseline bundle member does not match accepted hash: {rel}")
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() == payload:
                continue
            target.write_bytes(payload)
            restored.append(rel)
    return restored
