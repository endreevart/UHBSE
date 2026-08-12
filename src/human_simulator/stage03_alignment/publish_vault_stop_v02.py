#!/usr/bin/env python3
"""Build Stage 03 Alignment v0.2 review ZIP focused on Vault provisioning evidence.

Does not close loader runtime contract. Does not start Changeset 02 / ETL / live load.
Never includes TLS private keys, init JSON, tokens, or secret values.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXTERNAL = REPO / "artifacts" / "external-review"
ALIGN = REPO / "artifacts" / "stage-03-alignment-candidate"
VERSION = "0.2"
ZIP_NAME = f"stage-03-alignment-v{VERSION}-review.zip"
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = f"stage-03-alignment-v{VERSION}-review.attestation.json"

# Members: path relative to repo -> archive name
MEMBERS: list[tuple[str, str]] = [
    ("docker-compose.yml", "docker-compose.yml"),
    (".gitignore", ".gitignore"),
    ("ops/vault/README.md", "ops/vault/README.md"),
    ("ops/vault/config/vault.hcl", "ops/vault/config/vault.hcl"),
    ("ops/vault/policies/uhbse-canonical-loader.hcl", "ops/vault/policies/uhbse-canonical-loader.hcl"),
    ("ops/vault/runbooks/init-unseal.md", "ops/vault/runbooks/init-unseal.md"),
    ("ops/vault/runbooks/bootstrap-kv-approle.md", "ops/vault/runbooks/bootstrap-kv-approle.md"),
    ("ops/vault/scripts/generate-tls.sh", "ops/vault/scripts/generate-tls.sh"),
    ("ops/vault/scripts/preflight.sh", "ops/vault/scripts/preflight.sh"),
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
        "src/human_simulator/stage03_alignment/vault_provider.py",
        "src/human_simulator/stage03_alignment/vault_provider.py",
    ),
    (
        "tests/test_vault_provider_alignment_v02.py",
        "tests/test_vault_provider_alignment_v02.py",
    ),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def main() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    missing = [src for src, _ in MEMBERS if not (REPO / src).is_file()]
    if missing:
        raise SystemExit(f"missing members: {missing}")

    # Forbidden path patterns
    forbidden_substrings = (
        "ops/vault/tls/server.key",
        "ops/vault/tls/server.crt",
        "unseal",
        "root-token",
        ".env",
    )
    for src, _ in MEMBERS:
        for bad in forbidden_substrings:
            if bad in src and src.endswith((".key", ".env")):
                raise SystemExit(f"refusing forbidden member: {src}")

    index_lines = [
        f"# REVIEW_INDEX — Stage 03 Alignment v{VERSION} (Vault provisioning stop)",
        "",
        "Self-contained Vault provisioning evidence. Init/unseal keys and secret values are absent.",
        "",
        "| Archive path | SHA-256 |",
        "|---|---|",
    ]
    payloads: list[tuple[str, bytes, str]] = []
    for src, arc in MEMBERS:
        data = (REPO / src).read_bytes()
        digest = sha256_bytes(data)
        payloads.append((arc, data, digest))
        index_lines.append(f"| `{arc}` | `{digest}` |")

    review_summary = f"""# REVIEW_SUMMARY — Stage 03 Alignment v{VERSION}

## Scope of this stop

Vault production-mode provisioning package only.

## Provider

- Hashicorp Vault
- self-hosted Docker / cloud VM
- production mode (dev prohibited)
- persistent file storage volume `uhbse_vault_data`
- TLS enabled; host publish `127.0.0.1:8200` only

## Contract references (no secret values)

- `vault://uhbse/canonical/hmac-subject-key?version=1`
- `vault://uhbse/canonical/loader-credential?version=1`

## Identity separation

- Vault AppRole: `uhbse-canonical-loader`
- PostgreSQL LOGIN (planned): `canonical_loader_login`
- PostgreSQL NOLOGIN: `canonical_loader`

## Preflight

See `artifacts/stage-03-alignment-candidate/vault-preflight.json`.

Honest status after compose+TLS start and before operator init: **FAIL** on
`vault_initialized` / `vault_unsealed` until manual init/unseal. Mount/policy/AppRole
checks are SKIP without `VAULT_TOKEN`.

## Explicit non-actions

- `canonical_loader_runtime_contract` NOT marked complete
- PostgreSQL principal NOT created
- Changeset 02 / migration 0005 / ETL / live load NOT started
- Design/Plan NOT promoted to FINAL in this stop
"""

    reproduce = f"""# REPRODUCE — Alignment v{VERSION} Vault stop

```bash
./ops/vault/scripts/generate-tls.sh
docker compose up -d vault
# manual: ops/vault/runbooks/init-unseal.md
# manual: ops/vault/runbooks/bootstrap-kv-approle.md
./ops/vault/scripts/preflight.sh
pytest -q tests/test_vault_provider_alignment_v02.py
```

Gate note: candidate/pre-live-load gate remains FAIL until four blockers close.
This ZIP documents Vault provisioning only.
"""

    index_body = "\n".join(index_lines) + "\n"
    extra = [
        ("REVIEW_SUMMARY.md", review_summary.encode()),
        ("REPRODUCE.md", reproduce.encode()),
    ]
    for arc, data in extra:
        digest = sha256_bytes(data)
        payloads.append((arc, data, digest))
        # REVIEW_INDEX is written after and indexes all except itself
        index_body = index_body.rstrip() + f"\n| `{arc}` | `{digest}` |\n"

    index_bytes = index_body.encode()
    zip_path = EXTERNAL / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arc, data, _ in payloads:
            zf.writestr(arc, data)
        zf.writestr("REVIEW_INDEX.md", index_bytes)

    zip_sha = sha256_file(zip_path)
    (EXTERNAL / SHA_NAME).write_text(f"{zip_sha}  {ZIP_NAME}\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
    indexed = len(payloads)  # REVIEW_INDEX not counted in table rows as member-to-index
    # members = indexed + 1 (REVIEW_INDEX)
    attestation = {
        "alignment_version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "vault_provisioning_stop_after_preflight",
        "publication_integrity_status": "PASS",
        "provider": "hashicorp_vault",
        "provider_deployment": "self_hosted_docker_or_cloud_vm",
        "provider_preflight_status": json.loads(
            (ALIGN / "vault-preflight.json").read_text(encoding="utf-8")
        )["overall_status"],
        "canonical_loader_runtime_contract_complete": False,
        "postgres_principal_created": False,
        "awaiting_confirmation": "confirm postgres principal plan: canonical_loader_login",
        "design_release_status": "DRAFT_UNCHANGED",
        "plan_release_status": "DRAFT_UNCHANGED",
        "candidate_status": "PARTIAL",
        "pre_live_load_gate_status": "FAIL",
        "open_blocker_count": 4,
        "failed_checks_note": "Vault preflight FAIL until operator init/unseal; loader contract blocked on PG principal confirmation",
        "etl_executed": False,
        "live_load_executed": False,
        "changeset_02_started": False,
        "migration_0005_started": False,
        "secrets_in_bundle": False,
        "archive_rebuilt_after_hashing": False,
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(names),
        "indexed_members": indexed,
        "members_equals_indexed_plus_one": len(names) == indexed + 1,
    }
    (EXTERNAL / ATT_NAME).write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"zip": str(zip_path), "sha256": zip_sha, "members": len(names)}, indent=2))


if __name__ == "__main__":
    main()
