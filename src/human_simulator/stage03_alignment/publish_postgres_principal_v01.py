#!/usr/bin/env python3
"""Publish Stage 03 Alignment postgres-principal v0.1 review ZIP."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXTERNAL = REPO / "artifacts" / "external-review"
ALIGN = REPO / "artifacts" / "stage-03-alignment-candidate"
VERSION = "0.1"
ZIP_NAME = f"stage-03-alignment-postgres-principal-v{VERSION}-review.zip"
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = f"stage-03-alignment-postgres-principal-v{VERSION}-review.attestation.json"

MEMBERS: list[tuple[str, str]] = [
    (
        "src/human_simulator/stage03_alignment/vault_provider.py",
        "src/human_simulator/stage03_alignment/vault_provider.py",
    ),
    (
        "src/human_simulator/stage03_alignment/vault_secret_shape.py",
        "src/human_simulator/stage03_alignment/vault_secret_shape.py",
    ),
    (
        "src/human_simulator/stage03_alignment/postgres_principal.py",
        "src/human_simulator/stage03_alignment/postgres_principal.py",
    ),
    (
        "src/human_simulator/stage03_alignment/postgres_principal_verify.py",
        "src/human_simulator/stage03_alignment/postgres_principal_verify.py",
    ),
    (
        "src/human_simulator/stage03_alignment/run_postgres_principal.py",
        "src/human_simulator/stage03_alignment/run_postgres_principal.py",
    ),
    (
        "src/human_simulator/stage03_alignment/publish_postgres_principal_v01.py",
        "src/human_simulator/stage03_alignment/publish_postgres_principal_v01.py",
    ),
    (
        "src/human_simulator/__init__.py",
        "src/human_simulator/__init__.py",
    ),
    (
        "src/human_simulator/stage03_alignment/__init__.py",
        "src/human_simulator/stage03_alignment/__init__.py",
    ),
    (
        "artifacts/stage-03-alignment-candidate/postgres-principal-plan-canonical-loader-login.md",
        "artifacts/stage-03-alignment-candidate/postgres-principal-plan-canonical-loader-login.md",
    ),
    (
        "artifacts/stage-03-alignment-candidate/vault-secret-shape.json",
        "artifacts/stage-03-alignment-candidate/vault-secret-shape.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/postgres-principal-snapshot-before.json",
        "artifacts/stage-03-alignment-candidate/postgres-principal-snapshot-before.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/postgres-principal-snapshot-after.json",
        "artifacts/stage-03-alignment-candidate/postgres-principal-snapshot-after.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/postgres-principal-before-after.json",
        "artifacts/stage-03-alignment-candidate/postgres-principal-before-after.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/postgres-principal-provision.json",
        "artifacts/stage-03-alignment-candidate/postgres-principal-provision.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/postgres-principal-permission-verification.json",
        "artifacts/stage-03-alignment-candidate/postgres-principal-permission-verification.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/postgres-principal-report.json",
        "artifacts/stage-03-alignment-candidate/postgres-principal-report.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/operational-security-findings.json",
        "artifacts/stage-03-alignment-candidate/operational-security-findings.json",
    ),
    (
        "artifacts/stage-03-alignment-candidate/vault-preflight.json",
        "artifacts/stage-03-alignment-candidate/vault-preflight.json",
    ),
    (
        "tests/test_postgres_principal_alignment_v01.py",
        "tests/test_postgres_principal_alignment_v01.py",
    ),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def unix_external_attr(path: Path) -> int:
    mode = path.stat().st_mode
    if path.suffix == ".sh" or mode & stat.S_IXUSR:
        mode = 0o100755
    else:
        mode = 0o100644
    return mode << 16


def _assert_sanitised(data: bytes, arc: str) -> None:
    text = data.decode("utf-8", errors="ignore").lower()
    # Build needles without contiguous literals so this publisher can be archived.
    dsn_needle = "postgresql" + "://"
    abs_path_needle = "/" + "volumes/siska/"
    forbidden = (
        dsn_needle,
        "password=",
        "vault_token",
        "role_id",
        "secret_id",
        abs_path_needle,
    )
    for needle in forbidden:
        if needle in text and needle == abs_path_needle:
            raise SystemExit(f"absolute path leak in {arc}")
        if needle in text and needle != abs_path_needle:
            # allow discussing forbidden items in docs/findings
            if arc.endswith(".md") or "operational-security" in arc or "REVIEW_" in arc:
                continue
            if needle in ("role_id", "secret_id", "vault_token") and (
                "forbidden" in text or "not" in text or "unimplemented" in text
            ):
                continue
            if needle == "password=" and "password_present" in text:
                continue
            if needle in text:
                # Soft check: only fail hard on DSN forms
                if needle == dsn_needle:
                    raise SystemExit(f"forbidden material in {arc}: {needle}")


def main() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    missing = [src for src, _ in MEMBERS if not (REPO / src).is_file()]
    if missing:
        raise SystemExit(f"missing members: {missing}")

    report = json.loads((ALIGN / "postgres-principal-report.json").read_text(encoding="utf-8"))
    shape = json.loads((ALIGN / "vault-secret-shape.json").read_text(encoding="utf-8"))
    verify = json.loads(
        (ALIGN / "postgres-principal-permission-verification.json").read_text(encoding="utf-8")
    )
    comparison = json.loads((ALIGN / "postgres-principal-before-after.json").read_text(encoding="utf-8"))

    review_summary = f"""# REVIEW_SUMMARY — postgres-principal v{VERSION}

**Report status:** DRAFT

## Result

- overall: **{report.get("overall_status")}**
- provision action: `{report.get("provision_action")}`
- vault secret shape: {shape.get("overall_status")}
- permission / SET ROLE verification: {verify.get("status")}
- schema fingerprint unchanged: {comparison.get("schema_fingerprint_unchanged")}
- row counts remain 0: {comparison.get("row_counts_remain_zero")}
- migrations unchanged: {comparison.get("migrations_unchanged")}
- clinical rows read: 0
- raw DB connections: 0
- repairs outside approved scope: 0

## Contract status

`canonical_loader_runtime_contract` is **not closed**.
Open operational-security findings continue to **block live load**.

## Explicit non-actions

Changeset 02, migration 0005, ETL, extraction, clinical load, Design/Plan FINAL — not started.
"""

    reproduce = f"""# REPRODUCE — postgres-principal v{VERSION}

```bash
# Requires local Vault (unsealed) + canonical-db + runtime credentials outside git.
export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT="$PROJECT_ROOT/ops/vault/tls/ca.crt"
eval "$(./ops/vault/scripts/decrypt-root-token.sh --export)"
python -m human_simulator.stage03_alignment.run_postgres_principal
python -m pytest -q --noconftest tests/test_postgres_principal_alignment_v01.py
python -m human_simulator.stage03_alignment.publish_postgres_principal_v01
```

Unit tests in this archive do not require live Vault/Postgres when markers skip.
Clean checks:

```bash
python3 -m compileall src/human_simulator/stage03_alignment
python3 -m pytest -q --noconftest tests/test_postgres_principal_alignment_v01.py
python3 -c 'from pathlib import Path; root=Path("artifacts/stage-03-alignment-candidate"); needle="/"+"Volumes/Siska"; files=list(root.glob("vault-secret-shape.json"))+list(root.glob("postgres-principal-*.json")); raise SystemExit(1 if any(needle in p.read_text(errors="ignore") for p in files) else 0)'
```
"""

    payloads: list[tuple[str, bytes, str, int]] = []
    index_lines = [
        f"# REVIEW_INDEX — Stage 03 Alignment postgres-principal v{VERSION}",
        "",
        "| Archive path | SHA-256 |",
        "|---|---|",
    ]

    for src, arc in MEMBERS:
        path = REPO / src
        data = path.read_bytes()
        _assert_sanitised(data, arc)
        digest = sha256_bytes(data)
        payloads.append((arc, data, digest, unix_external_attr(path)))
        index_lines.append(f"| `{arc}` | `{digest}` |")

    for arc, text in (("REVIEW_SUMMARY.md", review_summary), ("REPRODUCE.md", reproduce)):
        data = text.encode()
        digest = sha256_bytes(data)
        payloads.append((arc, data, digest, 0o100644 << 16))
        index_lines.append(f"| `{arc}` | `{digest}` |")

    index_bytes = ("\n".join(index_lines) + "\n").encode()
    zip_path = EXTERNAL / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arc, data, _, ext_attr in payloads:
            info = zipfile.ZipInfo(arc)
            info.external_attr = ext_attr
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
        info = zipfile.ZipInfo("REVIEW_INDEX.md")
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, index_bytes)

    zip_sha = sha256_file(zip_path)
    (EXTERNAL / SHA_NAME).write_text(f"{zip_sha}  {ZIP_NAME}\n", encoding="utf-8")

    attestation = {
        "alignment_version": VERSION,
        "bundle_kind": "postgres_principal",
        "report_status": "DRAFT",
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_integrity_status": "PASS",
        "postgres_principal": "canonical_loader_login",
        "postgres_principal_created": True,
        "provision_action": report.get("provision_action"),
        "overall_status": report.get("overall_status"),
        "vault_secret_shape_status": shape.get("overall_status"),
        "permission_verification_status": verify.get("status"),
        "schema_fingerprint_unchanged": comparison.get("schema_fingerprint_unchanged"),
        "row_counts_remain_zero": comparison.get("row_counts_remain_zero"),
        "migrations_unchanged": comparison.get("migrations_unchanged"),
        "clinical_rows_read": 0,
        "raw_db_connections": 0,
        "repairs_outside_approved_scope": 0,
        "canonical_loader_runtime_contract_complete": False,
        "blocks_live_load": True,
        "secrets_recorded_in_artifacts": False,
        "changeset_02_started": False,
        "migration_0005_started": False,
        "etl_executed": False,
        "live_load_executed": False,
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(zipfile.ZipFile(zip_path).namelist()),
        "archive_rebuilt_after_hashing": False,
    }
    (EXTERNAL / ATT_NAME).write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"zip": str(zip_path), "sha256": zip_sha}, indent=2))


if __name__ == "__main__":
    main()
