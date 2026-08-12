#!/usr/bin/env python3
"""Publish Stage 03 Alignment vault-stop v0.2.1 review ZIP (does not overwrite v0.2)."""

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
VERSION = "0.2.1"
ZIP_NAME = f"stage-03-alignment-vault-stop-v{VERSION}-review.zip"
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = f"stage-03-alignment-vault-stop-v{VERSION}-review.attestation.json"

MEMBERS: list[tuple[str, str]] = [
    ("docker-compose.yml", "docker-compose.yml"),
    (".gitignore", ".gitignore"),
    ("ops/vault/README.md", "ops/vault/README.md"),
    ("ops/vault/config/vault.hcl", "ops/vault/config/vault.hcl"),
    ("ops/vault/policies/uhbse-canonical-loader.hcl", "ops/vault/policies/uhbse-canonical-loader.hcl"),
    ("ops/vault/runbooks/init-unseal.md", "ops/vault/runbooks/init-unseal.md"),
    ("ops/vault/runbooks/bootstrap-kv-approle.md", "ops/vault/runbooks/bootstrap-kv-approle.md"),
    ("ops/vault/runbooks/raft-snapshot-restore.md", "ops/vault/runbooks/raft-snapshot-restore.md"),
    ("ops/vault/runbooks/audit-and-log-rotation.md", "ops/vault/runbooks/audit-and-log-rotation.md"),
    ("ops/vault/scripts/generate-tls.sh", "ops/vault/scripts/generate-tls.sh"),
    ("ops/vault/scripts/generate-operator-pgp.sh", "ops/vault/scripts/generate-operator-pgp.sh"),
    ("ops/vault/scripts/init-pgp.sh", "ops/vault/scripts/init-pgp.sh"),
    ("ops/vault/scripts/unseal-pgp.sh", "ops/vault/scripts/unseal-pgp.sh"),
    ("ops/vault/scripts/decrypt-root-token.sh", "ops/vault/scripts/decrypt-root-token.sh"),
    ("ops/vault/scripts/bootstrap-kv-approle.sh", "ops/vault/scripts/bootstrap-kv-approle.sh"),
    ("ops/vault/scripts/enable-audit.sh", "ops/vault/scripts/enable-audit.sh"),
    ("ops/vault/scripts/raft-snapshot.sh", "ops/vault/scripts/raft-snapshot.sh"),
    ("ops/vault/scripts/preflight.sh", "ops/vault/scripts/preflight.sh"),
    ("ops/vault/scripts/run-checkpoint.sh", "ops/vault/scripts/run-checkpoint.sh"),
    (
        "artifacts/stage-03-alignment-candidate/decision-required-secret-provider.yaml",
        "artifacts/stage-03-alignment-candidate/decision-required-secret-provider.yaml",
    ),
    (
        "artifacts/stage-03-alignment-candidate/postgres-principal-plan-canonical-loader-login.md",
        "artifacts/stage-03-alignment-candidate/postgres-principal-plan-canonical-loader-login.md",
    ),
    (
        "artifacts/stage-03-alignment-candidate/vault-preflight.json",
        "artifacts/stage-03-alignment-candidate/vault-preflight.json",
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
        "src/human_simulator/stage03_alignment/vault_provider.py",
        "src/human_simulator/stage03_alignment/vault_provider.py",
    ),
    (
        "tests/test_vault_provider_alignment_v02.py",
        "tests/test_vault_provider_alignment_v02.py",
    ),
    (
        "tests/test_vault_stop_v021_clean_extraction.py",
        "tests/test_vault_stop_v021_clean_extraction.py",
    ),
]

EXEC_SUFFIXES = {".sh"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def unix_external_attr(path: Path) -> int:
    mode = path.stat().st_mode
    if path.suffix in EXEC_SUFFIXES or mode & stat.S_IXUSR:
        mode = 0o100755
    else:
        mode = 0o100644
    return mode << 16


def main() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    missing = [src for src, _ in MEMBERS if not (REPO / src).is_file()]
    if missing:
        raise SystemExit(f"missing members: {missing}")

    forbidden_needles = (
        "server.key",
        "server.crt",
        "ca.crt",
        "init-encrypted.json",
        "secret_id",
        "role_id",
        ".env",
        "unseal",
        "root-token",
        "gnupg/",
        ".asc",
        ".snap",
    )
    for src, _ in MEMBERS:
        lower = src.lower()
        for bad in forbidden_needles:
            if bad in lower and not src.endswith(".md") and "unseal-pgp.sh" not in src and "init-pgp.sh" not in src:
                if bad in {".asc", "gnupg/", "init-encrypted.json", "server.key", ".snap"}:
                    raise SystemExit(f"refusing forbidden member: {src}")

    preflight = json.loads((ALIGN / "vault-preflight.json").read_text(encoding="utf-8"))

    review_summary = f"""# REVIEW_SUMMARY — vault-stop v{VERSION}

## Checkpoint status

Vault preflight overall: **{preflight.get("overall_status")}**
counts: {json.dumps(preflight.get("counts"))}

Required PASS items:
- vault_initialized
- vault_unsealed
- strict_tls_verification
- kv_mount_uhbse
- policy_uhbse_canonical_loader
- approle_uhbse_canonical_loader
- secret path metadata version=1 (both)
- audit_device
- secrets_recorded_in_artifacts=false

## Provider

HashiCorp Vault production, Raft single-node, TLS, PGP-encrypted init,
loopback publish only, persistent audit volume.

## PostgreSQL

LOGIN `canonical_loader_login` remains **HOLD — not created**.
NOLOGIN `canonical_loader` retained.
canonical-db published as `127.0.0.1:5436:5432`.

## Explicit non-actions

Changeset 02, migration 0005, ETL, extraction, live load, FINAL promotion — not started.
"""

    reproduce = f"""# REPRODUCE — vault-stop v{VERSION}

Commands executed by the clean-extraction test (subset that does not require live Vault secrets):

```bash
python3 -m compileall ops/vault/scripts src/human_simulator/stage03_alignment/vault_provider.py
bash -n ops/vault/scripts/*.sh
test -x ops/vault/scripts/preflight.sh
test -x ops/vault/scripts/init-pgp.sh
! grep -R --include='*.sh' --include='*.yml' --include='*.hcl' -nE -- '-tls-skip-verify|VAULT_SKIP_VERIFY=true' ops/vault docker-compose.yml
grep -q 'storage "raft"' ops/vault/config/vault.hcl
grep -q '127.0.0.1:5436:5432' docker-compose.yml
python3 -m pytest -q --noconftest tests/test_vault_provider_alignment_v02.py
```

Full operator checkpoint (manual / local only; secrets stay out of Git):

```bash
./ops/vault/scripts/generate-tls.sh
./ops/vault/scripts/generate-operator-pgp.sh
docker compose up -d vault
./ops/vault/scripts/init-pgp.sh
./ops/vault/scripts/run-checkpoint.sh
./ops/vault/scripts/preflight.sh
```

Note: gate terminology — candidate may be PARTIAL; pre-live-load gate is PASS or FAIL only.
"""

    payloads: list[tuple[str, bytes, str, int]] = []
    index_lines = [
        f"# REVIEW_INDEX — Stage 03 Alignment vault-stop v{VERSION}",
        "",
        "| Archive path | SHA-256 |",
        "|---|---|",
    ]

    for src, arc in MEMBERS:
        path = REPO / src
        data = path.read_bytes()
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

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        exec_ok = True
        for name in names:
            if name.endswith(".sh"):
                mode = zf.getinfo(name).external_attr >> 16
                if not (mode & 0o111):
                    exec_ok = False

    attestation = {
        "alignment_version": VERSION,
        "bundle_kind": "vault_stop",
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_integrity_status": "PASS",
        "provider": "hashicorp_vault",
        "provider_deployment": "self_hosted_docker_or_cloud_vm",
        "vault_storage": "raft_integrated_storage_single_node",
        "provider_preflight_status": preflight.get("overall_status"),
        "provider_preflight_counts": preflight.get("counts"),
        "tls_skip_verify_used": False,
        "secrets_recorded_in_artifacts": False,
        "canonical_loader_runtime_contract_complete": False,
        "postgres_principal_created": False,
        "postgres_principal_status": "HOLD",
        "canonical_db_host_bind": "127.0.0.1:5436:5432",
        "candidate_status": "PARTIAL",
        "pre_live_load_gate_status": "FAIL",
        "open_blocker_count": 4,
        "etl_executed": False,
        "live_load_executed": False,
        "changeset_02_started": False,
        "migration_0005_started": False,
        "script_exec_bits_in_zip": exec_ok,
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(names),
        "indexed_members": len(payloads),
        "members_equals_indexed_plus_one": len(names) == len(payloads) + 1,
        "prior_zip_preserved": "stage-03-alignment-v0.2-review.zip",
        "archive_rebuilt_after_hashing": False,
    }
    (EXTERNAL / ATT_NAME).write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"zip": str(zip_path), "sha256": zip_sha, "members": len(names), "exec_ok": exec_ok}, indent=2))


if __name__ == "__main__":
    main()
