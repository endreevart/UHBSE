"""Read-only audit and content-addressed recovery for frozen Stage 03 baselines.

Recovery never overwrites published archives. Invalid baseline copies are recorded as
``SUPERSEDED_INVALID_BASELINE_COPY``; accepted bytes are rebuilt into new ``*-recovered-review.zip``
bundles only when member hashes verify against accepted evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage03.changeset_01_constants import (
    BASELINE_VERIFICATION_NAME,
    CHANGESET_DIR,
    DESIGN_CONTENT_MANIFEST_NAME,
    DESIGN_DIR,
    IMPLEMENTATION_DIR,
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
)
from human_simulator.stage03.frozen_evidence import (
    DESIGN_REPORT_NAME,
    DESIGN_VERIFICATION_NAME,
    FROZEN_DESIGN_EVIDENCE_SHA256,
)
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.review_bundle_validation import validate_review_bundle_zip
from human_simulator.stage03_alignment.constants import (
    ACCEPTED_PLAN_V035_ZIP_SHA256,
    EXTERNAL_REVIEW_DIR,
    FROZEN_DESIGN_VERSION,
    FROZEN_PLAN_VERSION,
    RECOVERY_REPORT_NAME,
)

RECOVERY_SOURCE_ARCHIVE = "stage-03-implementation-changeset-01-v0.2.3-review.zip"
INVALID_BASELINE_STATUS = "SUPERSEDED_INVALID_BASELINE_COPY"

FROZEN_DESIGN_ZIP_INVALID = EXTERNAL_REVIEW_DIR / f"stage-03-design-v{FROZEN_DESIGN_VERSION}-review.zip"
FROZEN_PLAN_ZIP_INVALID = (
    EXTERNAL_REVIEW_DIR / f"stage-03-implementation-plan-v{FROZEN_PLAN_VERSION}-review.zip"
)
FROZEN_DESIGN_ZIP_RECOVERED = (
    EXTERNAL_REVIEW_DIR / f"stage-03-design-v{FROZEN_DESIGN_VERSION}-recovered-review.zip"
)
FROZEN_PLAN_ZIP_RECOVERED = (
    EXTERNAL_REVIEW_DIR
    / f"stage-03-implementation-plan-v{FROZEN_PLAN_VERSION}-recovered-review.zip"
)

DESIGN_VERSION_PATTERN = re.compile(rb'document_version:\s*"?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"?')
PLAN_VERSION_PATTERN = re.compile(rb'document_version:\s*"?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"?')


@dataclass(frozen=True)
class MemberSource:
    zip_member: str
    accepted_sha256: str


def _load_accepted_member_hashes(repo_root: Path) -> dict[str, dict[str, str]]:
    baseline_path = repo_root / CHANGESET_DIR / BASELINE_VERIFICATION_NAME
    if not baseline_path.is_file():
        raise FileNotFoundError(f"missing accepted baseline evidence: {baseline_path}")
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    design: dict[str, str] = {}
    plan: dict[str, str] = {}
    for record in payload["frozen_evidence"]["files"]:
        path = record["path"]
        accepted = record.get("accepted_sha256")
        if accepted is None:
            continue
        if path.startswith("artifacts/stage-03/"):
            design[Path(path).name] = accepted
        elif path.startswith("artifacts/stage-03-implementation/"):
            plan[Path(path).name] = accepted
    return {"design": design, "plan": plan}


def _zip_member_version(zip_path: Path, member_suffix: str, pattern: re.Pattern[bytes]) -> str | None:
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if name.endswith(member_suffix):
                match = pattern.search(archive.read(name))
                return match.group(1).decode("utf-8") if match else None
    return None


def _audit_invalid_archive(
    zip_path: Path,
    *,
    expected_version: str,
    version_member_suffix: str,
    version_pattern: re.Pattern[bytes],
    accepted_members: dict[str, str],
) -> dict[str, Any]:
    present = zip_path.is_file()
    result: dict[str, Any] = {
        "path": zip_path.as_posix(),
        "present": present,
        "status": None,
        "archive_sha256": None,
        "declared_version_inside": None,
        "version_matches_label": None,
        "member_verification": None,
    }
    if not present:
        result["status"] = "ABSENT"
        return result

    archive_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    declared = _zip_member_version(zip_path, version_member_suffix, version_pattern)
    mismatches: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        for filename, expected in sorted(accepted_members.items()):
            member = None
            for name in archive.namelist():
                if name.endswith(filename):
                    member = name
                    break
            if member is None:
                mismatches.append(f"{filename}:MEMBER_ABSENT")
                continue
            actual = hashlib.sha256(archive.read(member)).hexdigest()
            if actual != expected:
                mismatches.append(filename)

    version_ok = declared == expected_version
    members_ok = not mismatches
    result.update(
        {
            "archive_sha256": archive_sha,
            "declared_version_inside": declared,
            "version_matches_label": version_ok,
            "member_verification": "PASS" if members_ok else "FAIL",
            "member_mismatches": mismatches,
            "status": INVALID_BASELINE_STATUS
            if (not version_ok or not members_ok)
            else "VALID_BASELINE_COPY",
        }
    )
    return result


def audit_baseline_recovery(repo_root: Path) -> dict[str, Any]:
    """Read-only audit of accepted byte sources and invalid baseline archives."""
    root = repo_root.resolve()
    accepted = _load_accepted_member_hashes(root)
    review_dir = root / EXTERNAL_REVIEW_DIR
    source_archive = review_dir / RECOVERY_SOURCE_ARCHIVE
    source_present = source_archive.is_file()

    source_member_ok: dict[str, bool] = {}
    if source_present:
        with zipfile.ZipFile(source_archive) as archive:
            for category, members in accepted.items():
                for filename, expected in members.items():
                    prefix = "artifacts/stage-03/" if category == "design" else "artifacts/stage-03-implementation/"
                    member = prefix + filename
                    if member not in archive.namelist():
                        source_member_ok[f"{category}/{filename}"] = False
                    else:
                        actual = hashlib.sha256(archive.read(member)).hexdigest()
                        source_member_ok[f"{category}/{filename}"] = actual == expected

    exact_plan_found = False
    if FROZEN_PLAN_ZIP_INVALID.is_file():
        exact_plan_found = (
            hashlib.sha256((root / FROZEN_PLAN_ZIP_INVALID).read_bytes()).hexdigest()
            == ACCEPTED_PLAN_V035_ZIP_SHA256
        )
    for zp in review_dir.glob("*.zip"):
        if hashlib.sha256(zp.read_bytes()).hexdigest() == ACCEPTED_PLAN_V035_ZIP_SHA256:
            exact_plan_found = True

    return {
        "audited_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "accepted_plan_zip_sha256": ACCEPTED_PLAN_V035_ZIP_SHA256,
        "accepted_plan_zip_found": exact_plan_found,
        "recovery_source_archive": RECOVERY_SOURCE_ARCHIVE,
        "recovery_source_present": source_present,
        "recovery_source_members_verified": source_member_ok,
        "recovery_source_complete": bool(source_member_ok) and all(source_member_ok.values()),
        "invalid_archives": {
            "design": _audit_invalid_archive(
                root / FROZEN_DESIGN_ZIP_INVALID,
                expected_version=FROZEN_DESIGN_VERSION,
                version_member_suffix="canonical-id-contract.yaml",
                version_pattern=DESIGN_VERSION_PATTERN,
                accepted_members=accepted["design"],
            ),
            "plan": _audit_invalid_archive(
                root / FROZEN_PLAN_ZIP_INVALID,
                expected_version=FROZEN_PLAN_VERSION,
                version_member_suffix="implementation-plan.yaml",
                version_pattern=PLAN_VERSION_PATTERN,
                accepted_members=accepted["plan"],
            ),
        },
        "recovered_archives": {
            "design": (root / FROZEN_DESIGN_ZIP_RECOVERED).is_file(),
            "plan": (root / FROZEN_PLAN_ZIP_RECOVERED).is_file(),
        },
    }


def _build_review_zip(
    staging: Path,
    *,
    title: str,
    generated_at: str,
    out_zip: Path,
) -> str:
    indexed_files = sorted(
        path.relative_to(staging)
        for path in staging.rglob("*")
        if path.is_file()
    )
    index_lines = [
        f"# {title}",
        "",
        f"Generated: {generated_at}",
        "",
        "Note: This index intentionally excludes its own SHA-256 entry.",
        "",
        "| SHA-256 | Path |",
        "|---------|------|",
    ]
    for rel in indexed_files:
        index_lines.append(f"| `{sha256_file(staging / rel)}` | `{rel.as_posix()}` |")
    (staging / "REVIEW_INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = out_zip.with_suffix(".tmp.zip")
    if temp_zip.exists():
        temp_zip.unlink()
    with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging).as_posix())

    ok, detail = validate_review_bundle_zip(temp_zip)
    if not ok:
        temp_zip.unlink(missing_ok=True)
        raise RuntimeError(f"recovery bundle validation failed: {detail}")

    bundle_sha = sha256_file(temp_zip)
    if out_zip.exists():
        if sha256_file(out_zip) == bundle_sha:
            temp_zip.unlink(missing_ok=True)
            return bundle_sha
        raise RuntimeError(f"refusing to overwrite existing recovery bundle: {out_zip.name}")

    temp_zip.replace(out_zip)
    sidecar = Path(str(out_zip) + ".sha256")
    sidecar.write_text(f"{bundle_sha}  {out_zip.name}\n", encoding="utf-8")
    return bundle_sha


def _write_recovery_attestation(
    *,
    bundle_name: str,
    bundle_sha: str,
    recovery_method: str,
    accepted_zip_sha256: str | None,
    source_archive: str,
) -> None:
    attestation = {
        "bundle": bundle_name,
        "sha256": bundle_sha,
        "recovery_method": recovery_method,
        "accepted_zip_sha256": accepted_zip_sha256,
        "accepted_zip_exact_recovery": recovery_method == "EXACT_ZIP_BYTES",
        "source_archive": source_archive,
        "recovered_at": datetime.now(UTC).isoformat(),
        "invalid_archive_status": INVALID_BASELINE_STATUS,
    }
    path = EXTERNAL_REVIEW_DIR / f"{bundle_name}.attestation.json"
    path.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")


def _write_content_manifest(
    staging: Path,
    *,
    directory: str,
    manifest_name: str,
    members: dict[str, str],
    manifest_files: tuple[str, ...],
) -> None:
    lines = [f"{members[name]}  {name}" for name in manifest_files]
    target = staging / directory / manifest_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _extract_members_to_staging(
    source_zip: Path,
    staging: Path,
    members: dict[str, str],
    *,
    category: str,
) -> None:
    prefix = "artifacts/stage-03/" if category == "design" else "artifacts/stage-03-implementation/"
    with zipfile.ZipFile(source_zip) as archive:
        for filename, expected in sorted(members.items()):
            member = prefix + filename
            if member not in archive.namelist():
                raise RuntimeError(f"recovery source missing member: {member}")
            payload = archive.read(member)
            if hashlib.sha256(payload).hexdigest() != expected:
                raise RuntimeError(f"recovery source member hash mismatch: {member}")
            target = staging / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

    if category == "design":
        content_files = tuple(
            sorted(
                name
                for name in members
                if name not in {DESIGN_REPORT_NAME, DESIGN_VERIFICATION_NAME}
            )
        )
        _write_content_manifest(
            staging,
            directory="artifacts/stage-03",
            manifest_name=DESIGN_CONTENT_MANIFEST_NAME,
            members=members,
            manifest_files=content_files,
        )
    else:
        _write_content_manifest(
            staging,
            directory="artifacts/stage-03-implementation",
            manifest_name=IMPLEMENTATION_PLAN_MANIFEST_NAME,
            members=members,
            manifest_files=tuple(sorted(members)),
        )


def _manifest_entries_from_recovered_zip(zip_path: Path, manifest_member: str) -> bool:
    if not zip_path.is_file():
        return False
    with zipfile.ZipFile(zip_path) as archive:
        if manifest_member not in archive.namelist():
            return False
        return bool(archive.read(manifest_member).decode("utf-8").strip())


def _recovery_bundle_valid(zip_path: Path, *, category: str, accepted_members: dict[str, str]) -> bool:
    if not zip_path.is_file():
        return False
    prefix = "artifacts/stage-03/" if category == "design" else "artifacts/stage-03-implementation/"
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for filename, expected in accepted_members.items():
                member = prefix + filename
                if member not in archive.namelist():
                    return False
                if hashlib.sha256(archive.read(member)).hexdigest() != expected:
                    return False
        ok, _ = validate_review_bundle_zip(zip_path)
        return ok
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return False


def create_recovery_bundles(repo_root: Path, *, force: bool = False) -> dict[str, Any]:
    """Build recovered review bundles without touching invalid baseline archives."""
    root = repo_root.resolve()
    audit = audit_baseline_recovery(root)
    if not audit["recovery_source_complete"]:
        raise RuntimeError(
            "recovery source archive does not carry all accepted member hashes; stopping"
        )

    accepted = _load_accepted_member_hashes(root)
    source_zip = root / EXTERNAL_REVIEW_DIR / RECOVERY_SOURCE_ARCHIVE
    results: dict[str, Any] = {"audit": audit, "bundles": {}}

    design_zip = root / FROZEN_DESIGN_ZIP_RECOVERED
    plan_zip = root / FROZEN_PLAN_ZIP_RECOVERED
    if (
        not force
        and _recovery_bundle_valid(design_zip, category="design", accepted_members=accepted["design"])
        and _recovery_bundle_valid(plan_zip, category="plan", accepted_members=accepted["plan"])
        and _manifest_entries_from_recovered_zip(
            design_zip, "artifacts/stage-03/design-content-manifest.sha256"
        )
        and _manifest_entries_from_recovered_zip(
            plan_zip, "artifacts/stage-03-implementation/implementation-plan-manifest.sha256"
        )
    ):
        results["bundles"]["design"] = {
            "path": design_zip.as_posix(),
            "sha256": sha256_file(design_zip),
            "recovery_method": "RECONSTRUCTED_FROM_ACCEPTED_MEMBERS",
            "reused_existing": True,
        }
        results["bundles"]["plan"] = {
            "path": plan_zip.as_posix(),
            "sha256": sha256_file(plan_zip),
            "recovery_method": "RECONSTRUCTED_FROM_ACCEPTED_MEMBERS",
            "accepted_zip_sha256": ACCEPTED_PLAN_V035_ZIP_SHA256,
            "accepted_zip_found": audit["accepted_plan_zip_found"],
            "reused_existing": True,
        }
        report_path = root / Path("artifacts/stage-03-alignment-candidate") / RECOVERY_REPORT_NAME
        if report_path.is_file():
            results["report_path"] = report_path.as_posix()
            return results

    generated_at = datetime.now(UTC).isoformat()

    with tempfile.TemporaryDirectory(prefix="design-recovery-") as tmp:
        staging = Path(tmp)
        _extract_members_to_staging(source_zip, staging, accepted["design"], category="design")
        reproduce = f"""# Stage 03 Design v{FROZEN_DESIGN_VERSION} — Recovered Review Bundle

Generated: {generated_at}

Recovered from accepted member hashes in `{RECOVERY_SOURCE_ARCHIVE}`.
The invalid archive `{FROZEN_DESIGN_ZIP_INVALID.name}` is marked `{INVALID_BASELINE_STATUS}`.
"""
        (staging / "REPRODUCE.md").write_text(reproduce, encoding="utf-8")
        out_zip = root / FROZEN_DESIGN_ZIP_RECOVERED
        bundle_sha = _build_review_zip(
            staging,
            title=f"Stage 03 Design v{FROZEN_DESIGN_VERSION} — Recovered Review Index",
            generated_at=generated_at,
            out_zip=out_zip,
        )
        _write_recovery_attestation(
            bundle_name=out_zip.name,
            bundle_sha=bundle_sha,
            recovery_method="RECONSTRUCTED_FROM_ACCEPTED_MEMBERS",
            accepted_zip_sha256=None,
            source_archive=RECOVERY_SOURCE_ARCHIVE,
        )
        results["bundles"]["design"] = {
            "path": out_zip.as_posix(),
            "sha256": bundle_sha,
            "recovery_method": "RECONSTRUCTED_FROM_ACCEPTED_MEMBERS",
        }

    with tempfile.TemporaryDirectory(prefix="plan-recovery-") as tmp:
        staging = Path(tmp)
        _extract_members_to_staging(source_zip, staging, accepted["plan"], category="plan")
        reproduce = f"""# Stage 03 Implementation Plan v{FROZEN_PLAN_VERSION} — Recovered Review Bundle

Generated: {generated_at}

Recovered from accepted member hashes in `{RECOVERY_SOURCE_ARCHIVE}`.
Accepted plan ZIP SHA `{ACCEPTED_PLAN_V035_ZIP_SHA256}` was not found byte-for-byte in this workspace.
The invalid archive `{FROZEN_PLAN_ZIP_INVALID.name}` is marked `{INVALID_BASELINE_STATUS}`.
"""
        (staging / "REPRODUCE.md").write_text(reproduce, encoding="utf-8")
        out_zip = root / FROZEN_PLAN_ZIP_RECOVERED
        bundle_sha = _build_review_zip(
            staging,
            title=f"Stage 03 Implementation Plan v{FROZEN_PLAN_VERSION} — Recovered Review Index",
            generated_at=generated_at,
            out_zip=out_zip,
        )
        plan_method = (
            "EXACT_ZIP_BYTES"
            if audit["accepted_plan_zip_found"] and bundle_sha == ACCEPTED_PLAN_V035_ZIP_SHA256
            else "RECONSTRUCTED_FROM_ACCEPTED_MEMBERS"
        )
        _write_recovery_attestation(
            bundle_name=out_zip.name,
            bundle_sha=bundle_sha,
            recovery_method=plan_method,
            accepted_zip_sha256=ACCEPTED_PLAN_V035_ZIP_SHA256,
            source_archive=RECOVERY_SOURCE_ARCHIVE,
        )
        results["bundles"]["plan"] = {
            "path": out_zip.as_posix(),
            "sha256": bundle_sha,
            "recovery_method": plan_method,
            "accepted_zip_sha256": ACCEPTED_PLAN_V035_ZIP_SHA256,
            "accepted_zip_found": audit["accepted_plan_zip_found"],
        }

    report = _format_recovery_report(audit, results)
    report_path = root / Path("artifacts/stage-03-alignment-candidate") / RECOVERY_REPORT_NAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    results["report_path"] = report_path.as_posix()
    return results


def _format_recovery_report(audit: dict[str, Any], results: dict[str, Any]) -> str:
    design_invalid = audit["invalid_archives"]["design"]
    plan_invalid = audit["invalid_archives"]["plan"]
    design_bundle = results["bundles"]["design"]
    plan_bundle = results["bundles"]["plan"]
    return f"""# Stage 03 Alignment — Baseline Recovery Report

Generated: {audit["audited_at"]}

## Summary

| Item | Result |
|------|--------|
| Recovery source | `{RECOVERY_SOURCE_ARCHIVE}` |
| Source members verified | `{audit["recovery_source_complete"]}` |
| Accepted Plan ZIP SHA | `{ACCEPTED_PLAN_V035_ZIP_SHA256}` |
| Accepted Plan ZIP found | `{audit["accepted_plan_zip_found"]}` |
| Design recovered bundle | `{design_bundle["path"]}` |
| Plan recovered bundle | `{plan_bundle["path"]}` |

## Invalid baseline archives (not overwritten)

| Archive | Status | Archive SHA-256 | Version inside |
|---------|--------|-----------------|----------------|
| `{design_invalid["path"]}` | `{design_invalid.get("status")}` | `{design_invalid.get("archive_sha256")}` | `{design_invalid.get("declared_version_inside")}` |
| `{plan_invalid["path"]}` | `{plan_invalid.get("status")}` | `{plan_invalid.get("archive_sha256")}` | `{plan_invalid.get("declared_version_inside")}` |

Both invalid copies are marked **`{INVALID_BASELINE_STATUS}`**. Original files were left in place.

## Recovered bundles

| Bundle | SHA-256 | Method |
|--------|---------|--------|
| `{Path(design_bundle["path"]).name}` | `{design_bundle["sha256"]}` | `{design_bundle["recovery_method"]}` |
| `{Path(plan_bundle["path"]).name}` | `{plan_bundle["sha256"]}` | `{plan_bundle["recovery_method"]}` |

## Accepted design evidence (pinned)

| File | SHA-256 |
|------|---------|
| `{DESIGN_REPORT_NAME}` | `{FROZEN_DESIGN_EVIDENCE_SHA256[DESIGN_REPORT_NAME]}` |
| `{DESIGN_VERIFICATION_NAME}` | `{FROZEN_DESIGN_EVIDENCE_SHA256[DESIGN_VERIFICATION_NAME]}` |
"""


def restore_frozen_design_baseline_manifest(repo_root: Path) -> None:
    """Restore design-baseline-manifest.sha256 to accepted v0.7.4 bytes from recovery source."""
    root = repo_root.resolve()
    source_zip = root / EXTERNAL_REVIEW_DIR / RECOVERY_SOURCE_ARCHIVE
    member = "artifacts/stage-03-implementation/design-baseline-manifest.sha256"
    accepted = _load_accepted_member_hashes(root)["plan"]["design-baseline-manifest.sha256"]
    with zipfile.ZipFile(source_zip) as archive:
        payload = archive.read(member)
    if hashlib.sha256(payload).hexdigest() != accepted:
        raise RuntimeError("design-baseline-manifest.sha256 does not match accepted hash")
    target = root / IMPLEMENTATION_DIR / "design-baseline-manifest.sha256"
    if target.read_bytes() != payload:
        target.write_bytes(payload)
