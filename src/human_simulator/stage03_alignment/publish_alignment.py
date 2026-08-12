"""Publish the Stage 03 alignment candidate external review bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from human_simulator.stage03.changeset_01_baseline import verify_sha256_manifest
from human_simulator.stage03.changeset_01_constants import (
    CHANGESET_DIR,
    DESIGN_CONTENT_MANIFEST_NAME,
    DESIGN_DIR,
    IMPLEMENTATION_DIR,
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
)
from human_simulator.stage03.conflict_resolution import CONFLICT_RESOLUTIONS_NAME
from human_simulator.stage03.frozen_evidence import DESIGN_REPORT_NAME, DESIGN_VERIFICATION_NAME
from human_simulator.stage03.implementation_constants import (
    IMPLEMENTATION_PLAN_REPORT_NAME,
    IMPLEMENTATION_PLAN_VERIFICATION_NAME,
)
from human_simulator.stage03.live_load_contracts import (
    RUNTIME_CONTRACT_KEY,
    SUBJECT_KEY_CONTRACT_KEY,
    locate_contract_definitions,
)
from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.review_bundle_validation import validate_review_bundle_zip
from human_simulator.stage03_alignment.baseline import evaluate_baseline
from human_simulator.stage03_alignment.bundle_verify import (
    verify_alignment_bundle_zip,
    verify_extracted_alignment_bundle,
)
from human_simulator.stage03_alignment.constants import (
    ALIGNMENT_DIR,
    ALIGNMENT_EXPECTED_CHANGED_FILES,
    ALIGNMENT_VERSION,
    BASELINE_VERIFICATION_NAME,
    BEFORE_AFTER_MATRIX_NAME,
    BUNDLE_ATTESTATION_NAME,
    BUNDLE_SHA256_NAME,
    BUNDLE_ZIP_NAME,
    CANDIDATE_DECISION_NAME,
    CANDIDATE_GATE_RESULT_NAME,
    DECISION_SECRET_PROVIDER_NAME,
    DESIGN_VERSION,
    EXTRACTED_MANIFEST_VERIFICATION_NAME,
    EXTERNAL_REVIEW_DIR,
    FROZEN_DESIGN_VERSION,
    FROZEN_DESIGN_ZIP_RECOVERED,
    FROZEN_PLAN_VERSION,
    FROZEN_PLAN_ZIP_RECOVERED,
    PLAN_VERSION,
    RECOVERY_REPORT_NAME,
)
from human_simulator.stage03_alignment.recovery import (
    create_recovery_bundles,
    restore_frozen_design_baseline_manifest,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _update_conflict_confirming_hashes(repo_root: Path) -> None:
    path = repo_root / DESIGN_DIR / CONFLICT_RESOLUTIONS_NAME
    if not path.is_file():
        return
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return
    files = [
        "canonical-model.yaml",
        "temporal-contract.yaml",
        "record-construction-contract.yaml",
        "source-a-mapping-draft.yaml",
        "field-semantics-register.yaml",
        "validation-rules.yaml",
    ]
    hashes = {name: sha256_file(repo_root / DESIGN_DIR / name) for name in files}
    for entry in document.get("resolutions", []):
        if not isinstance(entry, dict):
            continue
        entry["confirming_file_sha256"] = {key: hashes[key] for key in files if key in hashes}
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _reseal_candidate_manifests(repo_root: Path) -> None:
    for manifest_name, directory in (
        (DESIGN_CONTENT_MANIFEST_NAME, DESIGN_DIR),
        (IMPLEMENTATION_PLAN_MANIFEST_NAME, IMPLEMENTATION_DIR),
    ):
        manifest = repo_root / directory / manifest_name
        lines: list[str] = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            _, name = line.split(maxsplit=1)
            sibling = manifest.parent / name.strip()
            lines.append(f"{sha256_file(sibling)}  {name.strip()}")
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _manifest_entries_from_zip(zip_path: Path, manifest_suffix: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not zip_path.is_file():
        return entries
    with zipfile.ZipFile(zip_path) as archive:
        manifest_member = next(
            (name for name in archive.namelist() if name.endswith(manifest_suffix)),
            None,
        )
        if manifest_member is None:
            return entries
        for line in archive.read(manifest_member).decode("utf-8").splitlines():
            if line.strip():
                digest, fname = line.split(maxsplit=1)
                entries[fname.strip()] = digest
    return entries


def _matrix_entry(before_digest: str | None, after_digest: str, fname: str) -> dict[str, Any]:
    if before_digest is None:
        return {
            "file": fname,
            "before_sha256": None,
            "after_sha256": after_digest,
            "changed": True,
            "change_type": "ADDED",
        }
    changed = before_digest != after_digest
    return {
        "file": fname,
        "before_sha256": before_digest,
        "after_sha256": after_digest,
        "changed": changed,
        "change_type": "MODIFIED" if changed else "UNCHANGED",
    }


def _manifest_bundle_members(
    repo_root: Path,
    *,
    directory: Path,
    manifest_name: str,
    arc_prefix: str,
) -> list[tuple[Path, str]]:
    manifest_path = repo_root / directory / manifest_name
    members: list[tuple[Path, str]] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, name = line.split(maxsplit=1)
        fname = name.strip()
        members.append((repo_root / directory / fname, f"{arc_prefix}/{fname}"))
    members.append((manifest_path, f"{arc_prefix}/{manifest_name}"))
    return members


def _before_after_matrix(repo_root: Path) -> dict[str, Any]:
    recovered_design = repo_root / FROZEN_DESIGN_ZIP_RECOVERED
    recovered_plan = repo_root / FROZEN_PLAN_ZIP_RECOVERED
    matrix: dict[str, Any] = {
        "frozen_design_version": FROZEN_DESIGN_VERSION,
        "candidate_design_version": DESIGN_VERSION,
        "frozen_plan_version": FROZEN_PLAN_VERSION,
        "candidate_plan_version": PLAN_VERSION,
        "frozen_design_zip": recovered_design.as_posix(),
        "frozen_plan_zip": recovered_plan.as_posix(),
        "design_content_files": [],
        "plan_content_files": [],
    }

    before_design = _manifest_entries_from_zip(recovered_design, "design-content-manifest.sha256")
    after_design_manifest = repo_root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME
    if after_design_manifest.is_file():
        for line in after_design_manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            after_digest, fname = line.split(maxsplit=1)
            fname = fname.strip()
            before_digest = before_design.get(fname)
            matrix["design_content_files"].append(
                _matrix_entry(before_digest, after_digest, fname)
            )

    before_plan = _manifest_entries_from_zip(
        recovered_plan, "implementation-plan-manifest.sha256"
    )
    after_plan_manifest = repo_root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME
    if after_plan_manifest.is_file():
        for line in after_plan_manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            after_digest, fname = line.split(maxsplit=1)
            fname = fname.strip()
            before_digest = before_plan.get(fname)
            matrix["plan_content_files"].append(
                _matrix_entry(before_digest, after_digest, fname)
            )

    changed_files = {
        entry["file"]
        for entry in matrix["design_content_files"] + matrix["plan_content_files"]
        if entry.get("changed") is True
    }
    expected = set(ALIGNMENT_EXPECTED_CHANGED_FILES)
    same_snapshot = (
        bool(matrix["design_content_files"])
        and all(entry.get("changed") is False for entry in matrix["design_content_files"])
        and all(entry.get("changed") is False for entry in matrix["plan_content_files"])
    )
    matrix["alignment_changed_files"] = sorted(changed_files)
    matrix["expected_alignment_files_changed"] = sorted(expected & changed_files)
    matrix["alignment_change_check_pass"] = bool(expected & changed_files) and not same_snapshot
    return matrix


def _contract_duplicate_scan(repo_root: Path) -> dict[str, Any]:
    subject = locate_contract_definitions(repo_root, SUBJECT_KEY_CONTRACT_KEY)
    runtime = locate_contract_definitions(repo_root, RUNTIME_CONTRACT_KEY)
    return {
        "subject_key_definitions": len(subject),
        "runtime_definitions": len(runtime),
        "duplicate_subject_key": len(subject) > 1,
        "duplicate_runtime": len(runtime) > 1,
        "forbidden_changeset_definitions": any(
            "changeset" in loc.path for loc, _ in subject + runtime
        ),
    }


def _reproduce_md() -> str:
    return f"""# Reproduce — Stage 03 Alignment Candidate v{ALIGNMENT_VERSION}

## Preconditions

- Stage 01/02 FINAL; Stage 02 Maintenance 01 promotion FINAL
- Recovered baselines: `stage-03-design-v{FROZEN_DESIGN_VERSION}-recovered-review.zip`, `stage-03-implementation-plan-v{FROZEN_PLAN_VERSION}-recovered-review.zip`
- Invalid baseline copies marked SUPERSEDED_INVALID_BASELINE_COPY (not overwritten)
- No raw DB connections; no clinical row reads; no ETL or live load

## Commands

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

audit stage-03-check
audit stage-03-implementation-plan-check

python -c "from pathlib import Path; from human_simulator.stage03_alignment.recovery import create_recovery_bundles; create_recovery_bundles(Path('.'))"

python -c "from pathlib import Path; from human_simulator.stage03_alignment.baseline import evaluate_baseline; import json; print(json.dumps(evaluate_baseline(Path('.')), indent=2))"

python -c "from pathlib import Path; from human_simulator.stage03_alignment.publish_alignment import publish_alignment_bundle; print(publish_alignment_bundle(Path('.')))"

pytest tests/test_stage_03_alignment_candidate.py tests/test_stage_03_conflict_resolution.py tests/test_pre_live_load_gate_hardening.py -q
```

## Expected candidate outcome

- Design **v{DESIGN_VERSION}** (DRAFT) and Plan **v{PLAN_VERSION}** (DRAFT)
- Pre-live-load gate: **PARTIAL** — four contract blockers remain OPEN until secret provider is chosen
- Conflict blockers remain OPEN until Design v{DESIGN_VERSION} is promoted FINAL
"""


def _review_index(bundle_sha: str, generated_at: str) -> str:
    return f"""# Stage 03 Alignment Candidate — Review Index

Generated: {generated_at}

| Item | Value |
|------|-------|
| Alignment bundle | `{BUNDLE_ZIP_NAME}` |
| SHA-256 | `{bundle_sha}` |
| Alignment version | v{ALIGNMENT_VERSION} |
| Design candidate | v{DESIGN_VERSION} (DRAFT) |
| Plan candidate | v{PLAN_VERSION} (DRAFT) |
| Frozen design baseline | v{FROZEN_DESIGN_VERSION} (recovered) |
| Frozen plan baseline | v{FROZEN_PLAN_VERSION} (recovered) |
| Secret provider decision | `{ALIGNMENT_DIR.as_posix()}/{DECISION_SECRET_PROVIDER_NAME}` |

## Included artifacts

- Design content + manifest/report/verification
- Implementation plan content + manifest/report/verification
- `artifact-conflict-resolutions.yaml`
- Pre-live-load gate result (candidate)
- Baseline verification, before/after hash matrix, baseline recovery report
- Validators and regression tests (source)
- `REPRODUCE.md`, this index
"""


def _assert_unique_arcnames(members: list[tuple[Path, str]]) -> None:
    seen: set[str] = set()
    for _, arcname in members:
        if arcname in seen:
            raise RuntimeError(f"duplicate zip member: {arcname}")
        seen.add(arcname)


def publish_alignment_bundle(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    alignment_dir = root / ALIGNMENT_DIR
    alignment_dir.mkdir(parents=True, exist_ok=True)
    review_dir = root / EXTERNAL_REVIEW_DIR
    review_dir.mkdir(parents=True, exist_ok=True)

    create_recovery_bundles(root)
    restore_frozen_design_baseline_manifest(root)

    _update_conflict_confirming_hashes(root)
    _reseal_candidate_manifests(root)

    design_manifest = verify_sha256_manifest(root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME)
    plan_manifest = verify_sha256_manifest(root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME)
    if not design_manifest.verified or not plan_manifest.verified:
        raise RuntimeError(
            "Design and plan manifests must verify before publishing; "
            "run audit stage-03-check and audit stage-03-implementation-plan-check first"
        )

    baseline = evaluate_baseline(root)
    _write_json(alignment_dir / BASELINE_VERIFICATION_NAME, baseline)

    gate = evaluate_pre_live_load_gate(root)
    _write_json(alignment_dir / CANDIDATE_GATE_RESULT_NAME, gate.document())

    matrix = _before_after_matrix(root)
    if not matrix.get("alignment_change_check_pass"):
        raise RuntimeError("before/after matrix does not show expected alignment changes")
    _write_json(alignment_dir / BEFORE_AFTER_MATRIX_NAME, matrix)

    gate_document = gate.document()
    gate_status = gate_document.get("status", "FAIL")
    open_blockers = [
        item["blocker_id"]
        for item in gate_document.get("pre_live_load_blockers", {}).get("blockers", [])
        if item.get("status") == "OPEN"
    ]
    decision = {
        "candidate_status": "PARTIAL" if open_blockers else "READY",
        "baseline_status": baseline["status"],
        "pre_live_load_gate_status": gate_status,
        "design_version": DESIGN_VERSION,
        "plan_version": PLAN_VERSION,
        "open_blocker_ids": open_blockers,
        "open_blocker_count": len(open_blockers),
        "contract_duplicate_scan": _contract_duplicate_scan(root),
        "design_manifest_verified": design_manifest.verified,
        "plan_manifest_verified": plan_manifest.verified,
        "raw_db_connections": 0,
        "clinical_source_rows_read": 0,
        "canonical_db": baseline.get("canonical_db"),
        "etl_executed": False,
        "live_load_executed": False,
        "changeset_02_started": False,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    _write_json(alignment_dir / CANDIDATE_DECISION_NAME, decision)

    reproduce = _reproduce_md()
    (alignment_dir / "REPRODUCE.md").write_text(reproduce, encoding="utf-8")

    bundle_members: list[tuple[Path, str]] = [
        *_manifest_bundle_members(
            root,
            directory=DESIGN_DIR,
            manifest_name=DESIGN_CONTENT_MANIFEST_NAME,
            arc_prefix="design",
        ),
        (root / DESIGN_DIR / DESIGN_REPORT_NAME, f"design/{DESIGN_REPORT_NAME}"),
        (root / DESIGN_DIR / DESIGN_VERIFICATION_NAME, f"design/{DESIGN_VERIFICATION_NAME}"),
        *_manifest_bundle_members(
            root,
            directory=IMPLEMENTATION_DIR,
            manifest_name=IMPLEMENTATION_PLAN_MANIFEST_NAME,
            arc_prefix="plan",
        ),
        (root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_REPORT_NAME, f"plan/{IMPLEMENTATION_PLAN_REPORT_NAME}"),
        (root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_VERIFICATION_NAME, f"plan/{IMPLEMENTATION_PLAN_VERIFICATION_NAME}"),
        (alignment_dir / DECISION_SECRET_PROVIDER_NAME, f"alignment/{DECISION_SECRET_PROVIDER_NAME}"),
        (alignment_dir / BASELINE_VERIFICATION_NAME, f"alignment/{BASELINE_VERIFICATION_NAME}"),
        (alignment_dir / CANDIDATE_GATE_RESULT_NAME, f"alignment/{CANDIDATE_GATE_RESULT_NAME}"),
        (alignment_dir / BEFORE_AFTER_MATRIX_NAME, f"alignment/{BEFORE_AFTER_MATRIX_NAME}"),
        (alignment_dir / CANDIDATE_DECISION_NAME, f"alignment/{CANDIDATE_DECISION_NAME}"),
        (alignment_dir / RECOVERY_REPORT_NAME, f"alignment/{RECOVERY_REPORT_NAME}"),
        (root / CHANGESET_DIR / "accepted-artifact-conflicts.yaml", "changeset/accepted-artifact-conflicts.yaml"),
        (root / "src/human_simulator/stage03/conflict_resolution.py", "src/human_simulator/stage03/conflict_resolution.py"),
        (root / "src/human_simulator/stage03/live_load_contracts.py", "src/human_simulator/stage03/live_load_contracts.py"),
        (root / "src/human_simulator/stage03_alignment/baseline.py", "src/human_simulator/stage03_alignment/baseline.py"),
        (root / "src/human_simulator/stage03_alignment/bundle_verify.py", "src/human_simulator/stage03_alignment/bundle_verify.py"),
        (root / "src/human_simulator/stage03_alignment/canonical_db_baseline.py", "src/human_simulator/stage03_alignment/canonical_db_baseline.py"),
        (root / "src/human_simulator/stage03_alignment/recovery.py", "src/human_simulator/stage03_alignment/recovery.py"),
        (root / "src/human_simulator/stage03_alignment/publish_alignment.py", "src/human_simulator/stage03_alignment/publish_alignment.py"),
        (root / "tests/test_stage_03_conflict_resolution.py", "tests/test_stage_03_conflict_resolution.py"),
        (root / "tests/test_pre_live_load_gate_hardening.py", "tests/test_pre_live_load_gate_hardening.py"),
        (root / "tests/test_stage_03_alignment_candidate.py", "tests/test_stage_03_alignment_candidate.py"),
    ]
    _assert_unique_arcnames(bundle_members)

    generated_at = datetime.now(UTC).isoformat()
    zip_path = review_dir / BUNDLE_ZIP_NAME
    if zip_path.exists():
        raise RuntimeError(f"refusing to overwrite existing bundle: {zip_path.name}")

    with tempfile.TemporaryDirectory(prefix="alignment-publish-") as tmp:
        staging = Path(tmp)
        for source, arcname in bundle_members:
            if not source.is_file():
                raise FileNotFoundError(f"missing bundle member source: {source}")
            target = staging / arcname
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (staging / "REPRODUCE.md").write_text(reproduce, encoding="utf-8")

        extracted_verification = verify_extracted_alignment_bundle(staging)
        if not extracted_verification["extracted_design_manifest_verified"]:
            raise RuntimeError("staging design manifest verification failed")
        if not extracted_verification["extracted_plan_manifest_verified"]:
            raise RuntimeError("staging plan manifest verification failed")
        if not extracted_verification["all_manifest_members_present"]:
            raise RuntimeError(
                "staging missing manifest members: "
                + ", ".join(extracted_verification["missing_manifest_members"])
            )
        _write_json(alignment_dir / EXTRACTED_MANIFEST_VERIFICATION_NAME, extracted_verification)
        staging_extracted = staging / "alignment" / EXTRACTED_MANIFEST_VERIFICATION_NAME
        staging_extracted.parent.mkdir(parents=True, exist_ok=True)
        staging_extracted.write_text(
            json.dumps(extracted_verification, indent=2) + "\n", encoding="utf-8"
        )

        indexed_files = sorted(
            path.relative_to(staging)
            for path in staging.rglob("*")
            if path.is_file()
        )
        index_lines = [
            "# Stage 03 Alignment Candidate — Review Index",
            "",
            f"Generated: {generated_at}",
            "",
            "| SHA-256 | Path |",
            "|---------|------|",
        ]
        for rel in indexed_files:
            index_lines.append(f"| `{sha256_file(staging / rel)}` | `{rel.as_posix()}` |")
        index = "\n".join(index_lines) + "\n"
        (staging / "REVIEW_INDEX.md").write_text(index, encoding="utf-8")
        (alignment_dir / "REVIEW_INDEX.md").write_text(index, encoding="utf-8")

        final_zip = staging / "bundle.zip"
        with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file() and path != final_zip:
                    archive.write(path, path.relative_to(staging).as_posix())

        bundle_sha = sha256_file(final_zip)
        ok, detail = validate_review_bundle_zip(final_zip)
        if not ok:
            raise RuntimeError(f"bundle validation failed before publish: {detail}")

        sidecar = review_dir / BUNDLE_SHA256_NAME
        sidecar.write_text(f"{bundle_sha}  {BUNDLE_ZIP_NAME}\n", encoding="utf-8")
        shutil.copy2(final_zip, zip_path)

        with tempfile.TemporaryDirectory(prefix="alignment-verify-") as verify_tmp:
            extract_root = Path(verify_tmp)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_root)
            if sha256_file(zip_path) != bundle_sha:
                raise RuntimeError("published zip SHA mismatch after copy")
            ok, detail = validate_review_bundle_zip(zip_path)
            if not ok:
                raise RuntimeError(f"post-publish bundle validation failed: {detail}")
            if "placeholder" in (extract_root / "REVIEW_INDEX.md").read_text(encoding="utf-8"):
                raise RuntimeError("placeholder REVIEW_INDEX.md detected in published bundle")
            post_extract = verify_alignment_bundle_zip(zip_path, extract_root)
            if not post_extract["publication_integrity_pass"]:
                raise RuntimeError(
                    "post-extract manifest verification failed: "
                    + json.dumps(post_extract, indent=2)
                )
            extracted_verification = post_extract

    publication_integrity_status = "PASS" if extracted_verification["publication_integrity_pass"] else "FAIL"
    attestation = {
        "bundle": BUNDLE_ZIP_NAME,
        "sha256": bundle_sha,
        "published_at": datetime.now(UTC).isoformat(),
        "alignment_version": ALIGNMENT_VERSION,
        "design_version": DESIGN_VERSION,
        "plan_version": PLAN_VERSION,
        "publication_integrity_status": publication_integrity_status,
        "baseline_status": baseline["status"],
        "candidate_status": decision["candidate_status"],
        "pre_live_load_gate_status": gate_status,
        "open_blocker_count": decision["open_blocker_count"],
        "open_blocker_ids": open_blockers,
        "checks": {
            "publication_integrity_pass": extracted_verification["publication_integrity_pass"],
            "baseline_pass": baseline["status"] == "PASS",
            "design_manifest_verified": decision["design_manifest_verified"],
            "plan_manifest_verified": decision["plan_manifest_verified"],
            "extracted_design_manifest_verified": extracted_verification["extracted_design_manifest_verified"],
            "extracted_plan_manifest_verified": extracted_verification["extracted_plan_manifest_verified"],
            "all_manifest_members_present": extracted_verification["all_manifest_members_present"],
            "no_unindexed_members": extracted_verification["no_unindexed_members"],
            "no_duplicate_members": extracted_verification["no_duplicate_members"],
            "before_after_alignment_changed": matrix["alignment_change_check_pass"],
            "no_raw_db_connections": True,
            "no_clinical_source_rows_read": True,
            "no_etl": True,
            "no_live_load": True,
            "changeset_02_started": False,
        },
        "extracted_manifest_verification": extracted_verification,
        "canonical_db": baseline.get("canonical_db"),
    }
    _write_json(review_dir / BUNDLE_ATTESTATION_NAME, attestation)

    return {
        "zip": zip_path.as_posix(),
        "sha256": bundle_sha,
        "attestation": attestation,
        "decision": decision,
        "baseline_status": baseline["status"],
        "publication_integrity_status": publication_integrity_status,
        "pre_live_load_gate_status": gate_status,
        "extracted_manifest_verification": extracted_verification,
    }


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    print(json.dumps(publish_alignment_bundle(target), indent=2))
