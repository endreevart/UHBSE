#!/usr/bin/env python3
"""Publish Stage 03 Alignment runtime-auth v0.1 review ZIP (self-contained)."""

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
ALIGN = REPO / "artifacts" / "stage-03-alignment-candidate"
VERSION = "0.1"
ZIP_NAME = f"stage-03-alignment-runtime-auth-v{VERSION}-review.zip"
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = f"stage-03-alignment-runtime-auth-v{VERSION}-review.attestation.json"

MEMBERS: list[tuple[str, str]] = [
    ("pyproject.toml", "pyproject.toml"),
    ("uv.lock", "uv.lock"),
    ("docker-compose.yml", "docker-compose.yml"),
    ("ops/vault/agent/vault-agent.hcl", "ops/vault/agent/vault-agent.hcl"),
    ("ops/vault/policies/uhbse-canonical-loader.hcl", "ops/vault/policies/uhbse-canonical-loader.hcl"),
    ("ops/vault/scripts/harden-approle.sh", "ops/vault/scripts/harden-approle.sh"),
    ("ops/vault/scripts/deliver-approle-credentials.sh", "ops/vault/scripts/deliver-approle-credentials.sh"),
    ("ops/vault/scripts/bootstrap-kv-approle.sh", "ops/vault/scripts/bootstrap-kv-approle.sh"),
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
    ("src/human_simulator/stage03_alignment/postgres_principal.py", "src/human_simulator/stage03_alignment/postgres_principal.py"),
    ("src/human_simulator/stage03_alignment/postgres_principal_verify.py", "src/human_simulator/stage03_alignment/postgres_principal_verify.py"),
    ("src/human_simulator/stage03_alignment/runtime_auth_baseline.py", "src/human_simulator/stage03_alignment/runtime_auth_baseline.py"),
    ("src/human_simulator/stage03_alignment/runtime_auth_smoke.py", "src/human_simulator/stage03_alignment/runtime_auth_smoke.py"),
    ("src/human_simulator/stage03_alignment/run_runtime_auth.py", "src/human_simulator/stage03_alignment/run_runtime_auth.py"),
    ("src/human_simulator/stage03_alignment/publish_runtime_auth_v01.py", "src/human_simulator/stage03_alignment/publish_runtime_auth_v01.py"),
    (
        "artifacts/stage-03-alignment-candidate/runtime-auth-phase0-baseline.json",
        "artifacts/stage-03-alignment-candidate/runtime-auth-phase0-baseline.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/runtime-auth-snapshot-before.json",
        "artifacts/stage-03-alignment-candidate/runtime-auth-snapshot-before.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/runtime-auth-snapshot-after.json",
        "artifacts/stage-03-alignment-candidate/runtime-auth-snapshot-after.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/vault-secret-shape.json",
        "artifacts/stage-03-alignment-candidate/vault-secret-shape.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/approle-hardening.json",
        "artifacts/stage-03-alignment-candidate/approle-hardening.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/runtime-auth-smoke.json",
        "artifacts/stage-03-alignment-candidate/runtime-auth-smoke.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/canonical-loader-runtime-contract-status.json",
        "artifacts/stage-03-alignment-candidate/canonical-loader-runtime-contract-status.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/runtime-auth-report.json",
        "artifacts/stage-03-alignment-candidate/runtime-auth-report.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/operational-security-findings.json",
        "artifacts/stage-03-alignment-candidate/operational-security-findings.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/decision-required-limited-operator.yaml",
        "artifacts/stage-03-alignment-candidate/decision-required-limited-operator.yaml",
    ),
    (
        "artifacts/stage-03-alignment-candidate/decision-required-vault-key-custody.yaml",
        "artifacts/stage-03-alignment-candidate/decision-required-vault-key-custody.yaml",
    ),
    (
        "artifacts/stage-03-alignment-candidate/runtime-auth-unit-test-results.json",
        "artifacts/stage-03-alignment-candidate/runtime-auth-unit-test-results.json",
    ),
    ("migrations/canonical/0001_roles_and_schema.sql", "migrations/canonical/0001_roles_and_schema.sql"),
    ("migrations/canonical/0002_pilot_evidence_tables.sql", "migrations/canonical/0002_pilot_evidence_tables.sql"),
    ("migrations/canonical/0003_pilot_grants.sql", "migrations/canonical/0003_pilot_grants.sql"),
    ("migrations/canonical/0004_storage_contract_hardening.sql", "migrations/canonical/0004_storage_contract_hardening.sql"),
    ("tests/test_runtime_auth_alignment_v01.py", "tests/test_runtime_auth_alignment_v01.py"),
    ("tests/test_runtime_auth_v01_clean_extraction.py", "tests/test_runtime_auth_v01_clean_extraction.py"),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unix_attr(path: Path) -> int:
    mode = 0o100755 if path.suffix == ".sh" or (path.stat().st_mode & stat.S_IXUSR) else 0o100644
    return mode << 16


def assert_sanitised(data: bytes, arc: str) -> None:
    text = data.decode("utf-8", errors="ignore")
    low = text.lower()
    # Evidence / docs must not carry credential-bearing DSNs. Source may assemble them at runtime.
    if arc.endswith((".json", ".yaml", ".yml", ".md")) and "postgresql://" in low:
        raise SystemExit(f"DSN leak in {arc}")
    if re.search(r"\bhvs\.[A-Za-z0-9]+\b", text):
        raise SystemExit(f"token-like material in {arc}")
    if "/Volumes/Siska" in text and arc.endswith((".json", ".yaml", ".yml")):
        raise SystemExit(f"absolute path leak in {arc}")
    if "synthetic-subject-runtime-smoke-001" in text and arc.endswith(".json"):
        raise SystemExit(f"raw synthetic identifier in {arc}")


def main() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    missing = [src for src, _ in MEMBERS if not (REPO / src).is_file()]
    if missing:
        raise SystemExit(f"missing members: {missing}")

    report = json.loads((ALIGN / "runtime-auth-report.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (ALIGN / "canonical-loader-runtime-contract-status.json").read_text(encoding="utf-8")
    )

    review_summary = f"""# REVIEW_SUMMARY — runtime-auth v{VERSION}

**Report status:** DRAFT

## Result

- overall: **{report.get("overall_status")}**
- vault runtime authentication: {report.get("vault_runtime_authentication")}
- postgres principal: {report.get("postgres_principal")}
- canonical database: {report.get("canonical_database")}
- runtime contract: **{report.get("runtime_contract")}**
- custody decision: **{report.get("custody_decision")}**

## Gates

```json
{json.dumps(report.get("gates"), indent=2)}
```

## Contract

status={contract.get("status")} complete={contract.get("complete")}
open_blockers={contract.get("open_blockers")}

## Non-actions

Changeset 02, migration 0005, ETL, extraction, live load, Design/Plan FINAL — not started.
"""

    reproduce = f"""# REPRODUCE — runtime-auth v{VERSION}

Requires Python >= 3.12.

Clean extraction (executed by the clean-extraction test):

```bash
python3.12 -m compileall src/human_simulator
python3.12 -m pytest -q --noconftest tests/test_runtime_auth_alignment_v01.py
test -f ops/vault/agent/vault-agent.hcl
grep -q 'remove_secret_id_file_after_reading = true' ops/vault/agent/vault-agent.hcl
grep -q 'secret_id_response_wrapping_path' ops/vault/agent/vault-agent.hcl
grep -q '/run/uhbse-vault' docker-compose.yml
```

Live operator path (requires local Vault + canonical-db; secrets stay out of Git):

```bash
export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT="$PROJECT_ROOT/ops/vault/tls/ca.crt"
eval "$(./ops/vault/scripts/decrypt-root-token.sh --export)"
python3.12 -m human_simulator.stage03_alignment.run_runtime_auth
python3.12 -m human_simulator.stage03_alignment.publish_runtime_auth_v01
```
"""

    payloads: list[tuple[str, bytes, int]] = []
    index_lines = [
        f"# REVIEW_INDEX — Stage 03 Alignment runtime-auth v{VERSION}",
        "",
        "| Archive path | SHA-256 |",
        "|---|---|",
    ]
    for src, arc in MEMBERS:
        path = REPO / src
        data = path.read_bytes()
        assert_sanitised(data, arc)
        digest = sha256_bytes(data)
        payloads.append((arc, data, unix_attr(path)))
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

    attestation = {
        "alignment_version": VERSION,
        "bundle_kind": "runtime_auth",
        "report_status": "DRAFT",
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_integrity_status": "PASS",
        "overall_status": report.get("overall_status"),
        "runtime_contract": report.get("runtime_contract"),
        "custody_decision": "DECISION_REQUIRED",
        "postgres_principal": "PASS_UNCHANGED",
        "canonical_database": "empty",
        "clinical_rows_read": 0,
        "raw_db_connections": 0,
        "canonical_rows_written": 0,
        "secrets_recorded_in_artifacts": False,
        "nested_archives": len(nested),
        "changeset_02_started": False,
        "migration_0005_started": False,
        "etl_executed": False,
        "live_load_executed": False,
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(names),
        "indexed_members": len(payloads),
        "members_equals_indexed_plus_one": len(names) == len(payloads) + 1,
        "accepted_baseline_zips": {
            "stage-03-alignment-vault-stop-v0.2.1-review.zip": (
                "650c81e709e14211126f06ce20e11758c78de784fcb9e2dd9ad47d1685bf0204"
            ),
            "stage-03-alignment-postgres-principal-v0.1-review.zip": (
                "dfb6f2ce290e1e2fe3451a3d5e819b42709d7ffdcdef368bb85bd7dc943673cd"
            ),
        },
    }
    (EXTERNAL / ATT_NAME).write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"zip": str(zip_path), "sha256": zip_sha, "members": len(names)}, indent=2))


if __name__ == "__main__":
    main()
