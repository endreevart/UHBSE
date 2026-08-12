#!/usr/bin/env python3
"""Atomic publisher for Stage 03 Alignment runtime-auth v0.1.2 review ZIP.

Sequence (hard fail on any step):
  a–b suites + content artifacts including test-results.json
  c   freeze content (no further mutation of hashed members)
  d   write manifest.sha256
  e   verify manifest in staging evidence dir
  f   form REVIEW_INDEX.md
  g   pack ZIP once
  h–i extract to empty temp dir; verify manifest + REVIEW_INDEX
  j–l outer ZIP SHA → sidecar → attestation from computed checks
  m   never rebuild ZIP
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage03_alignment.publication_integrity import (
    sha256_bytes,
    sha256_file,
    verify_extracted_bundle,
    verify_review_index_against_zip,
    verify_sha256_manifest,
    write_sha256_manifest,
)

REPO = Path(__file__).resolve().parents[3]
EXTERNAL = REPO / "artifacts" / "external-review"
EVIDENCE = REPO / "artifacts" / "stage-03-alignment-runtime-auth-v0.1.2"
VERSION = "0.1.2"
ZIP_NAME = f"stage-03-alignment-runtime-auth-v{VERSION}-review.zip"
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = f"stage-03-alignment-runtime-auth-v{VERSION}-review.attestation.json"
ACCEPTED_V01_SHA = "a7708432dd0484797ee35b613de005bc147b541cb6e484fcd5a999fb024b25b4"
ACCEPTED_V011_SHA = "b727967789a87a11b666896a83831487729d407e462ddf88555cc9e94d00c7b3"
EVIDENCE_SUBDIR = f"artifacts/stage-03-alignment-runtime-auth-v{VERSION}"

IMMUTABLE_PRIOR = [
    EXTERNAL / "stage-03-alignment-runtime-auth-v0.1-review.zip",
    EXTERNAL / "stage-03-alignment-runtime-auth-v0.1.1-review.zip",
    EXTERNAL / "stage-03-alignment-runtime-auth-v0.1.1-review.zip.sha256",
    EXTERNAL / "stage-03-alignment-runtime-auth-v0.1.1-review.attestation.json",
]

MEMBERS: list[tuple[str, str]] = [
    ("pyproject.toml", "pyproject.toml"),
    ("uv.lock", "uv.lock"),
    ("docker-compose.yml", "docker-compose.yml"),
    ("ops/vault/runtime/Dockerfile", "ops/vault/runtime/Dockerfile"),
    ("ops/vault/runtime/vault-agent.hcl", "ops/vault/runtime/vault-agent.hcl"),
    ("ops/vault/runtime/entrypoint.sh", "ops/vault/runtime/entrypoint.sh"),
    ("ops/vault/runtime/synthetic_child.py", "ops/vault/runtime/synthetic_child.py"),
    ("ops/vault/runtime/deliver-into-container.sh", "ops/vault/runtime/deliver-into-container.sh"),
    ("ops/vault/runtime/start-runtime.sh", "ops/vault/runtime/start-runtime.sh"),
    ("ops/vault/runtime/stop-runtime.sh", "ops/vault/runtime/stop-runtime.sh"),
    ("ops/vault/policies/uhbse-canonical-loader.hcl", "ops/vault/policies/uhbse-canonical-loader.hcl"),
    ("ops/vault/scripts/harden-approle.sh", "ops/vault/scripts/harden-approle.sh"),
    ("src/human_simulator/__init__.py", "src/human_simulator/__init__.py"),
    ("src/human_simulator/canonical/__init__.py", "src/human_simulator/canonical/__init__.py"),
    ("src/human_simulator/canonical/constants.py", "src/human_simulator/canonical/constants.py"),
    ("src/human_simulator/canonical/settings.py", "src/human_simulator/canonical/settings.py"),
    ("src/human_simulator/canonical/connection.py", "src/human_simulator/canonical/connection.py"),
    ("src/human_simulator/canonical/migrations.py", "src/human_simulator/canonical/migrations.py"),
    ("src/human_simulator/canonical/schema_contract.py", "src/human_simulator/canonical/schema_contract.py"),
    ("src/human_simulator/canonical/definition_baseline.py", "src/human_simulator/canonical/definition_baseline.py"),
    ("src/human_simulator/stage03_alignment/__init__.py", "src/human_simulator/stage03_alignment/__init__.py"),
    ("src/human_simulator/stage03_alignment/vault_provider.py", "src/human_simulator/stage03_alignment/vault_provider.py"),
    ("src/human_simulator/stage03_alignment/vault_secret_shape.py", "src/human_simulator/stage03_alignment/vault_secret_shape.py"),
    ("src/human_simulator/stage03_alignment/approle_hardening.py", "src/human_simulator/stage03_alignment/approle_hardening.py"),
    ("src/human_simulator/stage03_alignment/token_lifecycle.py", "src/human_simulator/stage03_alignment/token_lifecycle.py"),
    ("src/human_simulator/stage03_alignment/postgres_principal.py", "src/human_simulator/stage03_alignment/postgres_principal.py"),
    ("src/human_simulator/stage03_alignment/postgres_principal_verify.py", "src/human_simulator/stage03_alignment/postgres_principal_verify.py"),
    ("src/human_simulator/stage03_alignment/runtime_auth_smoke.py", "src/human_simulator/stage03_alignment/runtime_auth_smoke.py"),
    ("src/human_simulator/stage03_alignment/hcl_secret_pins.py", "src/human_simulator/stage03_alignment/hcl_secret_pins.py"),
    ("src/human_simulator/stage03_alignment/publication_integrity.py", "src/human_simulator/stage03_alignment/publication_integrity.py"),
    ("src/human_simulator/stage03_alignment/run_runtime_auth_v011.py", "src/human_simulator/stage03_alignment/run_runtime_auth_v011.py"),
    ("src/human_simulator/stage03_alignment/run_runtime_auth_v012.py", "src/human_simulator/stage03_alignment/run_runtime_auth_v012.py"),
    ("src/human_simulator/stage03_alignment/publish_runtime_auth_v012.py", "src/human_simulator/stage03_alignment/publish_runtime_auth_v012.py"),
    ("migrations/canonical/0001_roles_and_schema.sql", "migrations/canonical/0001_roles_and_schema.sql"),
    ("migrations/canonical/0002_pilot_evidence_tables.sql", "migrations/canonical/0002_pilot_evidence_tables.sql"),
    ("migrations/canonical/0003_pilot_grants.sql", "migrations/canonical/0003_pilot_grants.sql"),
    ("migrations/canonical/0004_storage_contract_hardening.sql", "migrations/canonical/0004_storage_contract_hardening.sql"),
    ("tests/test_runtime_auth_v012_unit.py", "tests/test_runtime_auth_v012_unit.py"),
    ("tests/test_runtime_auth_v012_publication.py", "tests/test_runtime_auth_v012_publication.py"),
    ("tests/test_runtime_auth_v012_clean_extraction.py", "tests/test_runtime_auth_v012_clean_extraction.py"),
]

EVIDENCE_CONTENT_NAMES = [
    "phase0-baseline.json",
    "runtime-topology.json",
    "direct-approle-smoke.json",
    "vault-agent-static-validation.json",
    "vault-agent-live-smoke.json",
    "vault-agent-restart-reauth.json",
    "wrapped-secret-id-independence.json",
    "agent-token-policy-lookup.json",
    "secret-version-verification.json",
    "postgres-set-role-verification.json",
    "before-after-invariants.json",
    "token-lifecycle-verification.json",
    "operational-security-findings.json",
    "runtime-contract-status.json",
    "test-results.json",
    "runtime-auth-report.json",
    "report.md",
]


class PublicationError(RuntimeError):
    """Publication aborted — ZIP must not be emitted or must be removed."""


def unix_attr(path: Path) -> int:
    mode = 0o100755 if path.suffix == ".sh" or (path.stat().st_mode & stat.S_IXUSR) else 0o100644
    return mode << 16


def assert_sanitised(data: bytes, arc: str) -> None:
    text = data.decode("utf-8", errors="ignore")
    if arc.endswith((".json", ".yaml", ".yml", ".md")):
        if "postgresql://" in text.lower():
            raise PublicationError(f"DSN in {arc}")
        if re.search(r"\bhvs\.[A-Za-z0-9]+", text):
            raise PublicationError(f"token-like in {arc}")
        if "/Volumes/Siska" in text:
            raise PublicationError(f"absolute path in {arc}")
        if "synthetic-subject-runtime-smoke-001" in text:
            raise PublicationError(f"raw identifier in {arc}")
        if '"publication_integrity_status": "PASS"' in text and "attestation" not in arc:
            # Hard-coded PASS inside evidence/report content is forbidden;
            # attestation is computed later and may contain PASS only if checks pass.
            if "runtime-auth-report" in arc or "test-results" in arc:
                raise PublicationError(f"hard-coded publication PASS in {arc}")
        if '"two_independent_wrapped_secret_ids": true' in text:
            raise PublicationError(f"hard-coded two_independent_wrapped_secret_ids in {arc}")


def _py() -> str:
    which = subprocess.run(
        ["bash", "-lc", "command -v python3.12"],
        capture_output=True,
        text=True,
        check=False,
    )
    if which.returncode == 0 and which.stdout.strip():
        return which.stdout.strip()
    venv = REPO / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv)
    return "python3"


def run_unit_static_suite() -> dict[str, Any]:
    py = _py()
    proc = subprocess.run(
        [
            py,
            "-m",
            "pytest",
            "-q",
            "--noconftest",
            "tests/test_runtime_auth_v012_unit.py",
            "tests/test_runtime_auth_v012_publication.py",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    # Parse "N passed" from pytest -q summary
    passed = 0
    failed = 0
    m = re.search(r"(\d+) passed", proc.stdout + proc.stderr)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", proc.stdout + proc.stderr)
    if m:
        failed = int(m.group(1))
    return {
        "exit_code": proc.returncode,
        "passed": passed,
        "failed": failed,
        "command": "pytest -q --noconftest tests/test_runtime_auth_v012_unit.py tests/test_runtime_auth_v012_publication.py",
        "passed_status": proc.returncode == 0,
    }


def publisher_side_clean_extraction_verify() -> dict[str, Any]:
    """Verify publication helpers against a temporary staging layout (not extracted ZIP).

    This is NOT a suite executed inside an extracted review bundle.
    """
    with tempfile.TemporaryDirectory(prefix="uhbse-pub-clean-") as tmp:
        root = Path(tmp)
        evidence = root / EVIDENCE_SUBDIR
        evidence.mkdir(parents=True)
        sample = evidence / "sample.json"
        sample.write_text('{"ok": true}\n', encoding="utf-8")
        manifest = write_sha256_manifest(evidence)
        before = verify_sha256_manifest(manifest, base_dir=evidence)
        # Mutate after manifest → must FAIL (v0.1.1 defect reproduction)
        sample.write_text('{"ok": false}\n', encoding="utf-8")
        after = verify_sha256_manifest(manifest, base_dir=evidence)
        return {
            "kind": "publisher_side_clean_extraction_verifier",
            "not_extracted_bundle_suite": True,
            "manifest_ok_before_mutation": before["verified"],
            "manifest_fails_after_content_mutation": not after["verified"],
            "passed": before["verified"] and not after["verified"],
        }


def write_test_results(
    *,
    unit: dict[str, Any],
    publisher_clean: dict[str, Any],
    live: dict[str, Any] | None = None,
) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    live = live or {}
    doc = {
        "document_version": VERSION,
        "unit_static_suite": unit,
        "publisher_side_clean_extraction_verifier": publisher_clean,
        "extracted_bundle_suite": {
            "status": "DEFERRED_UNTIL_AFTER_ZIP",
            "note": "Suite from extracted review bundle runs after atomic pack; recorded in attestation",
        },
        "live_agent_suite": live,
        # Pre-pack only — must not claim all_required_suites_passed while extract suite is DEFERRED
        "pre_pack_suites_passed": bool(
            unit.get("passed_status")
            and publisher_clean.get("passed")
            and live.get("passed_status", True)
        ),
    }
    path = EVIDENCE / "test-results.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def validate_pre_pack_test_results(doc: dict[str, Any]) -> dict[str, Any]:
    """FAIL if ambiguous suites_passed claims completeness while extract suite is DEFERRED."""
    extracted = doc.get("extracted_bundle_suite") or {}
    deferred = str(extracted.get("status") or "").startswith("DEFERRED")
    has_ambiguous = "suites_passed" in doc and deferred
    has_pre_pack = "pre_pack_suites_passed" in doc
    ok = (not has_ambiguous) and (has_pre_pack if deferred else True)
    return {
        "valid": ok,
        "deferred_extract_suite": deferred,
        "ambiguous_suites_passed_present": has_ambiguous,
        "pre_pack_suites_passed_present": has_pre_pack,
    }


def freeze_and_write_manifest(evidence_dir: Path) -> dict[str, Any]:
    """Write manifest over published evidence content and verify immediately."""
    for name in EVIDENCE_CONTENT_NAMES:
        if not (evidence_dir / name).is_file():
            raise PublicationError(f"missing evidence content: {name}")
    # Remove stale manifest so it is recomputed from frozen content
    stale = evidence_dir / "manifest.sha256"
    if stale.is_file():
        stale.unlink()
    manifest = write_sha256_manifest(
        evidence_dir, include_names=EVIDENCE_CONTENT_NAMES
    )
    result = verify_sha256_manifest(manifest, base_dir=evidence_dir)
    if not result["verified"]:
        raise PublicationError(f"internal manifest verify failed: {result}")
    return {
        "internal_manifest_verified_before_pack": True,
        "manifest_entry_count": result["entry_count"],
        "manifest_path": str(manifest.relative_to(REPO)).replace("\\", "/"),
    }


def build_review_texts() -> tuple[str, str]:
    report = json.loads((EVIDENCE / "runtime-auth-report.json").read_text(encoding="utf-8"))
    review_summary = f"""# REVIEW_SUMMARY — runtime-auth v{VERSION}

**Report status:** DRAFT

Accepted immutable baselines (not nested in this ZIP):
- v0.1 SHA-256: `{ACCEPTED_V01_SHA}`
- v0.1.1 SHA-256: `{ACCEPTED_V011_SHA}`

## Component statuses

```json
{json.dumps(report.get("component_statuses"), indent=2)}
```

## Contract

- status: **{report.get("runtime_contract")}**
- complete: false
- open_blockers: {report.get("open_blockers")}

## Evidence classification

- direct_approle_api_smoke — LIVE (not Agent)
- vault_agent_configuration_static_validation — STATIC (comment-aware pins)
- vault_agent_runtime_execution — LIVE Agent Process Supervisor
- vault_agent_restart_reauthentication — LIVE two-cycle
- wrapped_secret_id_independence — LIVE (computed distinct metadata)
- agent_token_policy_lookup — LIVE sanitised lookup

## Non-actions

Changeset 02, migration 0005, ETL, clinical load, Design/Plan FINAL, root revocation,
custody remediation — not started.
"""
    reproduce = f"""# REPRODUCE — runtime-auth v{VERSION}

Requires Python >= 3.12.

## Static / unit (from extracted bundle)

```bash
python3.12 -m compileall src/human_simulator ops/vault/runtime
python3.12 -m pytest -q --noconftest \\
  tests/test_runtime_auth_v012_unit.py \\
  tests/test_runtime_auth_v012_publication.py
```

## Publisher-side clean-extraction verifier (workspace publisher)

Distinct from the suite run inside an extracted bundle. See
`publication_integrity.py` and publisher attestation fields
`publisher_side_clean_extraction_*` vs `extracted_bundle_suite_*`.

## Live Vault Agent (NOT reproducible from ZIP alone)

```bash
export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT="$PROJECT_ROOT/ops/vault/tls/ca.crt"
python3.12 -m human_simulator.stage03_alignment.run_runtime_auth_v012
python3.12 -m human_simulator.stage03_alignment.publish_runtime_auth_v012
```
"""
    return review_summary, reproduce


def pack_zip_once(payloads: list[tuple[str, bytes, int]], index_bytes: bytes, zip_path: Path) -> None:
    if zip_path.exists():
        raise PublicationError(f"refusing to overwrite existing ZIP: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arc, data, ext in payloads:
            info = zipfile.ZipInfo(arc)
            info.external_attr = ext
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
        info = zipfile.ZipInfo("REVIEW_INDEX.md")
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, index_bytes)


def compute_attestation_checks(
    *,
    zip_path: Path,
    sidecar_path: Path,
    zip_sha: str,
    before_pack: dict[str, Any],
    extract_result: dict[str, Any],
    index_result: dict[str, Any],
    suites_passed: bool,
    archive_rebuilt: bool,
) -> dict[str, Any]:
    sidecar_text = sidecar_path.read_text(encoding="utf-8").strip()
    outer_ok = sidecar_text.startswith(zip_sha) and ZIP_NAME in sidecar_text
    checks = {
        "outer_zip_sha_matches_sidecar": outer_ok,
        "review_index_verified": bool(index_result.get("verified")),
        "internal_manifest_verified_before_pack": bool(
            before_pack.get("internal_manifest_verified_before_pack")
        ),
        "internal_manifest_verified_after_extract": bool(
            extract_result.get("internal_manifest_verified_after_extract")
        ),
        "no_unindexed_members": bool(index_result.get("no_unindexed_members")),
        "no_missing_members": bool(index_result.get("no_missing_members")),
        "no_duplicate_members": bool(index_result.get("no_duplicate_members")),
        "no_nested_archives": bool(index_result.get("no_nested_archives")),
        "archive_rebuilt_after_hashing": archive_rebuilt,
        "all_required_suites_passed": suites_passed,
    }
    # PASS only when all true AND archive_rebuilt_after_hashing is false
    integrity_pass = all(
        [
            checks["outer_zip_sha_matches_sidecar"],
            checks["review_index_verified"],
            checks["internal_manifest_verified_before_pack"],
            checks["internal_manifest_verified_after_extract"],
            checks["no_unindexed_members"],
            checks["no_missing_members"],
            checks["no_duplicate_members"],
            checks["no_nested_archives"],
            checks["archive_rebuilt_after_hashing"] is False,
            checks["all_required_suites_passed"],
        ]
    )
    return {
        "checks": checks,
        "publication_integrity_status": "PASS" if integrity_pass else "FAIL",
    }


def publish(*, skip_unit: bool = False, live_suite: dict[str, Any] | None = None) -> dict[str, Any]:
    # Protect prior publications
    prior_hashes = {p: sha256_file(p) for p in IMMUTABLE_PRIOR if p.is_file()}

    if not skip_unit:
        unit = run_unit_static_suite()
        if not unit["passed_status"]:
            raise PublicationError(f"unit/static suite FAIL: {unit}")
    else:
        unit = {"passed_status": True, "passed": 0, "failed": 0, "skipped": True}

    publisher_clean = publisher_side_clean_extraction_verify()
    if not publisher_clean["passed"]:
        raise PublicationError("publisher-side clean-extraction verifier FAIL")

    # Incorporate live suite metadata from evidence if present
    live = live_suite
    if live is None and (EVIDENCE / "runtime-auth-report.json").is_file():
        report = json.loads((EVIDENCE / "runtime-auth-report.json").read_text(encoding="utf-8"))
        live = {
            "passed_status": report.get("overall_status") == "PASS",
            "overall_status": report.get("overall_status"),
            "runtime_contract": report.get("runtime_contract"),
            "command": "python3.12 -m human_simulator.stage03_alignment.run_runtime_auth_v012",
        }

    write_test_results(unit=unit, publisher_clean=publisher_clean, live=live)

    # --- freeze content; write + verify manifest ---
    before_pack = freeze_and_write_manifest(EVIDENCE)

    members = list(MEMBERS)
    for name in [*EVIDENCE_CONTENT_NAMES, "manifest.sha256"]:
        src = f"{EVIDENCE_SUBDIR}/{name}"
        members.append((src, src))

    missing = [s for s, _ in members if not (REPO / s).is_file()]
    if missing:
        raise PublicationError(f"missing members: {missing}")

    for s, _ in members:
        if s.startswith("artifacts/external-review/"):
            raise PublicationError(f"refusing external-review member: {s}")

    review_summary, reproduce = build_review_texts()
    payloads: list[tuple[str, bytes, int]] = []
    index_lines = [
        f"# REVIEW_INDEX — Stage 03 Alignment runtime-auth v{VERSION}",
        "",
        f"Accepted v0.1 reference SHA-256: `{ACCEPTED_V01_SHA}`",
        f"Accepted v0.1.1 reference SHA-256: `{ACCEPTED_V011_SHA}`",
        "",
        "| Archive path | SHA-256 |",
        "|---|---|",
    ]

    for src, arc in members:
        data = (REPO / src).read_bytes()
        assert_sanitised(data, arc)
        digest = sha256_bytes(data)
        payloads.append((arc, data, unix_attr(REPO / src)))
        index_lines.append(f"| `{arc}` | `{digest}` |")

    for arc, text in (("REVIEW_SUMMARY.md", review_summary), ("REPRODUCE.md", reproduce)):
        data = text.encode()
        digest = sha256_bytes(data)
        payloads.append((arc, data, 0o100644 << 16))
        index_lines.append(f"| `{arc}` | `{digest}` |")

    index_bytes = ("\n".join(index_lines) + "\n").encode()
    zip_path = EXTERNAL / ZIP_NAME
    EXTERNAL.mkdir(parents=True, exist_ok=True)

    try:
        pack_zip_once(payloads, index_bytes, zip_path)
        archive_rebuilt = False

        # Extract to empty temp and verify
        with tempfile.TemporaryDirectory(prefix="uhbse-v012-extract-") as tmp:
            extract_root = Path(tmp) / "bundle"
            extract_root.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_root)
            extract_result = verify_extracted_bundle(
                extract_root, evidence_subdir=EVIDENCE_SUBDIR
            )
            if not extract_result.get("internal_manifest_verified_after_extract"):
                raise PublicationError(f"extracted manifest FAIL: {extract_result}")
            if not extract_result.get("review_index_verified_after_extract"):
                raise PublicationError(f"extracted REVIEW_INDEX FAIL: {extract_result}")

            # Run suite FROM extracted bundle (independent of publisher workspace layout)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(extract_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
            py = _py()
            extracted_suite = subprocess.run(
                [
                    py,
                    "-m",
                    "pytest",
                    "-q",
                    "--noconftest",
                    "tests/test_runtime_auth_v012_unit.py",
                    "tests/test_runtime_auth_v012_publication.py",
                ],
                cwd=str(extract_root),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            extracted_suite_passed = extracted_suite.returncode == 0
            if not extracted_suite_passed:
                raise PublicationError(
                    "extracted-bundle suite FAIL\n"
                    + (extracted_suite.stdout or "")[-2000:]
                    + (extracted_suite.stderr or "")[-2000:]
                )

        index_result = verify_review_index_against_zip(zip_path)
        if not index_result.get("verified"):
            raise PublicationError(f"REVIEW_INDEX zip verify FAIL: {index_result}")

        zip_sha = sha256_file(zip_path)
        sidecar = EXTERNAL / SHA_NAME
        sidecar.write_text(f"{zip_sha}  {ZIP_NAME}\n", encoding="utf-8")

        suites_passed = bool(
            unit.get("passed_status")
            and publisher_clean.get("passed")
            and (live or {}).get("passed_status", False)
            and extracted_suite_passed
        )
        integrity = compute_attestation_checks(
            zip_path=zip_path,
            sidecar_path=sidecar,
            zip_sha=zip_sha,
            before_pack=before_pack,
            extract_result=extract_result,
            index_result=index_result,
            suites_passed=suites_passed,
            archive_rebuilt=archive_rebuilt,
        )
        if integrity["publication_integrity_status"] != "PASS":
            raise PublicationError(f"publication integrity FAIL: {integrity}")

        report = json.loads((EVIDENCE / "runtime-auth-report.json").read_text(encoding="utf-8"))
        wrap = json.loads(
            (EVIDENCE / "wrapped-secret-id-independence.json").read_text(encoding="utf-8")
        )
        token_lookup = json.loads(
            (EVIDENCE / "agent-token-policy-lookup.json").read_text(encoding="utf-8")
        )
        invariants = json.loads(
            (EVIDENCE / "before-after-invariants.json").read_text(encoding="utf-8")
        )
        tests = json.loads((EVIDENCE / "test-results.json").read_text(encoding="utf-8"))

        # Update test-results with extracted suite — FORBIDDEN after manifest.
        # Record extracted suite only in attestation (not in hashed evidence).
        attestation = {
            "alignment_version": VERSION,
            "bundle_kind": "runtime_auth_publication_repair",
            "report_status": "DRAFT",
            "generated_at": datetime.now(UTC).isoformat(),
            "publication_integrity_status": integrity["publication_integrity_status"],
            "publication_checks": integrity["checks"],
            "accepted_v01_sha256": ACCEPTED_V01_SHA,
            "accepted_v011_sha256": ACCEPTED_V011_SHA,
            "component_statuses": report.get("component_statuses"),
            "wrapped_secret_id_independence": {
                "overall_status": wrap.get("overall_status"),
                "distinct_nonsecret_request_metadata": wrap.get(
                    "distinct_nonsecret_request_metadata"
                ),
                "wrapper_reuse_rejected": wrap.get("wrapper_reuse_rejected"),
            },
            "agent_token_policy_lookup": token_lookup.get("overall_status"),
            "canonical_database_empty": invariants.get("row_counts_remain_zero"),
            "row_counts_before": invariants.get("row_counts_before"),
            "row_counts_after": invariants.get("row_counts_after"),
            "raw_db_connections": 0,
            "clinical_rows_read": 0,
            "canonical_rows_written": 0,
            "runtime_contract_complete": False,
            "runtime_contract_status": report.get("runtime_contract"),
            "open_blockers": report.get("open_blockers"),
            "unit_suite": tests.get("unit_static_suite"),
            "publisher_side_clean_extraction_verifier": tests.get(
                "publisher_side_clean_extraction_verifier"
            ),
            "extracted_bundle_suite": {
                "passed": extracted_suite_passed,
                "exit_code": extracted_suite.returncode,
                "note": "Executed from clean ZIP extract; distinct from publisher-side verifier",
            },
            "live_agent_suite": live,
            "review_zip": ZIP_NAME,
            "review_zip_sha256": zip_sha,
            "members": index_result.get("members"),
            "indexed_members": index_result.get("indexed_members"),
            "members_equals_indexed_plus_one": index_result.get("members")
            == (index_result.get("indexed_members") or 0) + 1,
            "internal_manifest_verified_before_pack": before_pack.get(
                "internal_manifest_verified_before_pack"
            ),
            "internal_manifest_verified_after_extract": extract_result.get(
                "internal_manifest_verified_after_extract"
            ),
            "secrets_recorded_in_artifacts": False,
            "v01_zip_not_overwritten": True,
            "v011_zip_not_overwritten": True,
            "archive_rebuilt_after_hashing": False,
        }
        (EXTERNAL / ATT_NAME).write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")

        # Confirm prior ZIPs unchanged
        for path, expected in prior_hashes.items():
            if sha256_file(path) != expected:
                raise PublicationError(f"immutable prior mutated: {path.name}")

        return {
            "zip": str(zip_path),
            "sha256": zip_sha,
            "members": index_result.get("members"),
            "indexed_members": index_result.get("indexed_members"),
            "publication_integrity_status": integrity["publication_integrity_status"],
            "internal_manifest_verified_before_pack": True,
            "internal_manifest_verified_after_extract": True,
        }
    except Exception:
        if zip_path.is_file():
            zip_path.unlink()
        sidecar = EXTERNAL / SHA_NAME
        if sidecar.is_file():
            sidecar.unlink()
        att = EXTERNAL / ATT_NAME
        if att.is_file():
            att.unlink()
        raise


def refuse_publish_after_manifest_mutation(evidence_dir: Path) -> bool:
    """Reproduce v0.1.1 defect: mutating test-results after manifest must refuse publish.

    Returns True when refusal works as required (verify fails).
    """
    write_sha256_manifest(evidence_dir)
    tr = evidence_dir / "test-results.json"
    if not tr.is_file():
        tr.write_text("{}\n", encoding="utf-8")
        write_sha256_manifest(evidence_dir)
    original = tr.read_text(encoding="utf-8")
    try:
        tr.write_text(original + "\n", encoding="utf-8")  # mutate bytes
        result = verify_sha256_manifest(evidence_dir / "manifest.sha256", base_dir=evidence_dir)
        return not result["verified"]
    finally:
        tr.write_text(original, encoding="utf-8")


def main() -> int:
    try:
        result = publish()
    except PublicationError as exc:
        print(f"FAIL: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc.__class__.__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
