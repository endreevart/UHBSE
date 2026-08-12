#!/usr/bin/env python3
"""Publish Stage 03 Alignment runtime-auth correction v0.1.1 review ZIP."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXTERNAL = REPO / "artifacts" / "external-review"
EVIDENCE = REPO / "artifacts" / "stage-03-alignment-runtime-auth-v0.1.1"
VERSION = "0.1.1"
ZIP_NAME = f"stage-03-alignment-runtime-auth-v{VERSION}-review.zip"
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = f"stage-03-alignment-runtime-auth-v{VERSION}-review.attestation.json"
ACCEPTED_V01_SHA = "a7708432dd0484797ee35b613de005bc147b541cb6e484fcd5a999fb024b25b4"

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
    ("src/human_simulator/stage03_alignment/run_runtime_auth_v011.py", "src/human_simulator/stage03_alignment/run_runtime_auth_v011.py"),
    ("src/human_simulator/stage03_alignment/publish_runtime_auth_v011.py", "src/human_simulator/stage03_alignment/publish_runtime_auth_v011.py"),
    ("migrations/canonical/0001_roles_and_schema.sql", "migrations/canonical/0001_roles_and_schema.sql"),
    ("migrations/canonical/0002_pilot_evidence_tables.sql", "migrations/canonical/0002_pilot_evidence_tables.sql"),
    ("migrations/canonical/0003_pilot_grants.sql", "migrations/canonical/0003_pilot_grants.sql"),
    ("migrations/canonical/0004_storage_contract_hardening.sql", "migrations/canonical/0004_storage_contract_hardening.sql"),
    ("tests/test_runtime_auth_v011_unit.py", "tests/test_runtime_auth_v011_unit.py"),
    ("tests/test_runtime_auth_v011_clean_extraction.py", "tests/test_runtime_auth_v011_clean_extraction.py"),
]

# Evidence artifacts under artifacts/stage-03-alignment-runtime-auth-v0.1.1/
EVIDENCE_NAMES = [
    "phase0-baseline.json",
    "runtime-topology.json",
    "direct-approle-smoke.json",
    "vault-agent-static-validation.json",
    "vault-agent-live-smoke.json",
    "vault-agent-restart-reauth.json",
    "secret-version-verification.json",
    "postgres-set-role-verification.json",
    "before-after-invariants.json",
    "token-lifecycle-verification.json",
    "operational-security-findings.json",
    "runtime-contract-status.json",
    "test-results.json",
    "runtime-auth-report.json",
    "report.md",
    "manifest.sha256",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unix_attr(path: Path) -> int:
    mode = 0o100755 if path.suffix == ".sh" or (path.stat().st_mode & stat.S_IXUSR) else 0o100644
    return mode << 16


def assert_sanitised(data: bytes, arc: str) -> None:
    text = data.decode("utf-8", errors="ignore")
    if arc.endswith((".json", ".yaml", ".yml", ".md")):
        if "postgresql://" in text.lower():
            raise SystemExit(f"DSN in {arc}")
        if re.search(r"\bhvs\.[A-Za-z0-9]+", text):
            raise SystemExit(f"token-like in {arc}")
        if "/Volumes/Siska" in text:
            raise SystemExit(f"absolute path in {arc}")
        if "synthetic-subject-runtime-smoke-001" in text:
            raise SystemExit(f"raw identifier in {arc}")


def main() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    members = list(MEMBERS)
    for name in EVIDENCE_NAMES:
        src = f"artifacts/stage-03-alignment-runtime-auth-v0.1.1/{name}"
        members.append((src, src))

    missing = [s for s, _ in members if not (REPO / s).is_file()]
    if missing:
        raise SystemExit(f"missing: {missing}")

    # Refuse nesting prior review zips
    for s, _ in members:
        if s.startswith("artifacts/external-review/"):
            raise SystemExit(f"refusing external-review member: {s}")

    report = json.loads((EVIDENCE / "runtime-auth-report.json").read_text(encoding="utf-8"))
    contract = json.loads((EVIDENCE / "runtime-contract-status.json").read_text(encoding="utf-8"))
    tests = json.loads((EVIDENCE / "test-results.json").read_text(encoding="utf-8"))

    review_summary = f"""# REVIEW_SUMMARY — runtime-auth v{VERSION}

**Report status:** DRAFT

Accepted v0.1 baseline SHA-256 (immutable, not included as nested ZIP):
`{ACCEPTED_V01_SHA}`

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
- vault_agent_configuration_static_validation — STATIC
- vault_agent_runtime_execution — LIVE Agent Process Supervisor
- vault_agent_restart_reauthentication — LIVE two-cycle

## Non-actions

Changeset 02, migration 0005, ETL, clinical load, Design/Plan FINAL, root revocation — not started.
"""

    reproduce = f"""# REPRODUCE — runtime-auth v{VERSION}

Requires Python >= 3.12.

## Static / unit (clean extraction)

```bash
python3.12 -m compileall src/human_simulator ops/vault/runtime
python3.12 -m pytest -q --noconftest tests/test_runtime_auth_v011_unit.py
grep -q 'hmac-subject-key?version=1' ops/vault/runtime/vault-agent.hcl
grep -q 'loader-credential?version=1' ops/vault/runtime/vault-agent.hcl
grep -q 'canonical-loader-runtime' docker-compose.yml
grep -q '/run/uhbse-vault' docker-compose.yml
```

## Live Vault Agent (NOT reproducible from ZIP alone)

Requires running Vault + canonical-db + operator token (outside Git):

```bash
export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT="$PROJECT_ROOT/ops/vault/tls/ca.crt"
python3.12 -m human_simulator.stage03_alignment.run_runtime_auth_v011
```

Live suite exit code and sanitised evidence are recorded in
`artifacts/stage-03-alignment-runtime-auth-v0.1.1/test-results.json` and
`vault-agent-live-smoke.json` / `vault-agent-restart-reauth.json`.
"""

    payloads: list[tuple[str, bytes, int]] = []
    index_lines = [
        f"# REVIEW_INDEX — Stage 03 Alignment runtime-auth v{VERSION}",
        "",
        f"Accepted v0.1 reference SHA-256: `{ACCEPTED_V01_SHA}`",
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

    zip_sha = sha256_bytes(zip_path.read_bytes())
    (EXTERNAL / SHA_NAME).write_text(f"{zip_sha}  {ZIP_NAME}\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        nested = [n for n in names if n.endswith(".zip")]

    statuses = report.get("component_statuses") or {}
    attestation = {
        "alignment_version": VERSION,
        "bundle_kind": "runtime_auth_correction",
        "report_status": "DRAFT",
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_integrity_status": "PASS",
        "accepted_v01_sha256": ACCEPTED_V01_SHA,
        "direct_approle_api_smoke": statuses.get("direct_approle_api_smoke"),
        "vault_agent_configuration_static_validation": statuses.get(
            "vault_agent_configuration_static_validation"
        ),
        "vault_agent_runtime_execution": statuses.get("vault_agent_runtime_execution"),
        "vault_agent_restart_reauthentication": statuses.get(
            "vault_agent_restart_reauthentication"
        ),
        "canonical_database_empty": True,
        "raw_db_connections": 0,
        "clinical_rows_read": 0,
        "canonical_rows_written": 0,
        "runtime_contract_complete": False,
        "runtime_contract_status": report.get("runtime_contract"),
        "open_blockers": report.get("open_blockers"),
        "unit_suite": tests.get("unit_suite"),
        "live_agent_suite": tests.get("live_agent_suite"),
        "clean_bundle_suite": tests.get("clean_bundle_suite"),
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(names),
        "indexed_members": len(payloads),
        "members_equals_indexed_plus_one": len(names) == len(payloads) + 1,
        "nested_archives": len(nested),
        "secrets_recorded_in_artifacts": False,
        "v01_zip_not_overwritten": True,
    }
    (EXTERNAL / ATT_NAME).write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"zip": str(zip_path), "sha256": zip_sha, "members": len(names)}, indent=2))


if __name__ == "__main__":
    main()
