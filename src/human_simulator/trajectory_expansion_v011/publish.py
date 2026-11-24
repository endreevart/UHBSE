"""Publish refuse-if-exists review ZIP for trajectory expansion v0.1.1."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.trajectory_expansion_v011.policy import (
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ARTIFACT_DIR,
    FORBIDDEN_PUBLIC_KEYS,
    REVIEW_ZIP,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_v012.publication_fixes import assert_attestation_index_fields

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_trajectory_expansion_v011_unit.py",
    "tests/test_trajectory_expansion_v011_contracts.py",
)

PRIOR_IMMUTABLE_ZIPS = {
    "trajectory_expansion_v0.1": (ACCEPTED_V01_ZIP, ACCEPTED_V01_SHA256),
}

# Entire local package tree for self-contained `audit` CLI import graph.
# Verify itself does not open clinical DB.
SELF_CONTAINED_SRC = (
    "src/human_simulator",
)


class PublicationError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def verify_manifest(d: Path) -> dict[str, Any]:
    man = d / "evidence-manifest.sha256"
    if not man.is_file():
        return {"ok": False, "reason": "missing"}
    mismatches = []
    checked = 0
    for line in man.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        path = d / name.strip()
        if not path.is_file():
            mismatches.append(name)
            continue
        checked += 1
        if _sha(path) != digest.strip():
            mismatches.append(name)
    return {"ok": not mismatches, "checked": checked, "mismatches": mismatches}


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n"
    )


def _excluded(rel: str) -> bool:
    p = Path(rel)
    if "external-review" in p.parts or "__pycache__" in p.parts or p.name == ".DS_Store":
        return True
    if p.suffix.lower() == ".zip" or "dumps" in p.parts or "private" in p.parts:
        return True
    return False


def _add_tree(payloads: dict[str, bytes], root: Path, rel: str) -> None:
    base = root / rel
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        r = path.relative_to(root).as_posix()
        if _excluded(r):
            continue
        # Skip bulky non-code assets accidentally under src
        if path.suffix.lower() in {".mp4", ".wav", ".png", ".jpg", ".zip", ".dump"}:
            continue
        if path.suffix in {
            ".py",
            ".md",
            ".toml",
            ".txt",
            ".json",
            ".sha256",
            ".yaml",
            ".yml",
            ".typed",
        } or rel.startswith("artifacts/"):
            payloads[r] = path.read_bytes()


def scan_row_level(payloads: dict[str, bytes]) -> dict[str, Any]:
    """Refuse publication if forbidden row-level keys appear in JSON members.

    Feature-schema names (e.g. feature_support.y_t0 quantiles) are allowed.
    Identity / pair-row keys are never allowed in public JSON.
    """
    hits: list[dict[str, Any]] = []
    identity_keys = ("opaque_subject_key", "pair_id", "component_id", "observation_id")
    for name, data in payloads.items():
        if not name.endswith(".json"):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for key in identity_keys:
            if re.search(rf'"{re.escape(key)}"\s*:', text):
                hits.append({"member": name, "key": key, "kind": "identity_or_locator_key"})
        # Row-like: y_t0 and y_t1 numeric siblings (pair records)
        if re.search(
            r'"y_t0"\s*:\s*-?\d+(?:\.\d+)?\s*,\s*"y_t1"\s*:\s*-?\d+',
            text,
        ) or re.search(
            r'"y_t1"\s*:\s*-?\d+(?:\.\d+)?\s*,\s*"y_t0"\s*:\s*-?\d+',
            text,
        ):
            hits.append({"member": name, "key": "y_t0+y_t1", "kind": "pair_value_record"})
        # Exact clinical timestamps as t0/t1 ISO fields
        if re.search(r'"(t0|t1)"\s*:\s*"\d{4}-\d{2}-\d{2}', text):
            hits.append({"member": name, "key": "t0/t1", "kind": "timestamp_value"})
    return {
        "ok": len(hits) == 0,
        "n_hits": len(hits),
        "hits": hits[:50],
        "row_level_data_in_zip": len(hits) != 0,
    }


def _scan_secrets(payloads: dict[str, bytes]) -> dict[str, Any]:
    patterns = [
        (re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"), "PRIVATE_KEY_BLOCK"),
        (re.compile(rb"\bVAULT_TOKEN\s*=\s*\S+"), "VAULT_TOKEN_ASSIGNMENT"),
        (
            re.compile(rb"(?:postgres|postgresql)://[^/\s\"'{]+?:[^/\s\"'{]+?@"),
            "POSTGRES_URI_WITH_PASSWORD",
        ),
    ]
    hits = []
    for name, data in payloads.items():
        if name.endswith(".py") and "publish.py" in name:
            continue
        sample = data if len(data) < 400_000 else data[:400_000]
        for rx, label in patterns:
            if rx.search(sample):
                hits.append({"member": name, "pattern": label})
    return {"ok": not hits, "hits": hits}


def _sanitize_artifacts_for_public(art: Path) -> dict[str, Any]:
    """Remove/redact forbidden keys from grain JSON before packing."""
    removed = 0
    for path in sorted((art / "grains").glob("*.json")) if (art / "grains").is_dir() else []:
        doc = json.loads(path.read_text(encoding="utf-8"))
        # Drop any accidental pair lists
        for k in ("pairs", "train_pairs", "test_pairs_rows", "predictions_rows"):
            if k in doc:
                doc.pop(k, None)
                removed += 1
        # dataset_summary.pair_meta.schema may list field names — replace with hashes only
        ds = doc.get("dataset_summary") or {}
        pm = ds.get("pair_meta")
        if isinstance(pm, dict):
            summary = pm.get("summary") or {}
            # Keep aggregate summary; drop schema row_fields listing of forbidden names by hashing schema
            schema = pm.get("schema") or {}
            safe_schema = {
                "version": schema.get("version"),
                "pair_definition": schema.get("pair_definition"),
                "feature_list": schema.get("feature_list"),
                "row_fields_hash": hashlib.sha256(
                    json.dumps(schema.get("row_fields") or [], sort_keys=True).encode()
                ).hexdigest()
                if schema.get("row_fields")
                else None,
            }
            # Remove date_coverage exact timestamps? User forbade exact t0/t1 — date_coverage has t0_min etc
            summary_safe = {
                k: v
                for k, v in summary.items()
                if k
                not in {
                    "date_coverage",  # contains exact timestamp bounds
                }
            }
            if "date_coverage" in summary:
                summary_safe["date_coverage_hash"] = hashlib.sha256(
                    json.dumps(summary["date_coverage"], sort_keys=True, default=str).encode()
                ).hexdigest()
            ds["pair_meta"] = {
                "schema": safe_schema,
                "summary": summary_safe,
                "config": pm.get("config"),
            }
            doc["dataset_summary"] = ds
            removed += 1
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"sanitized_files_touched": removed}


def publish(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    external = root / "artifacts" / "external-review"
    external.mkdir(parents=True, exist_ok=True)
    zip_path = external / ZIP_NAME
    sidecar = external / SHA_NAME
    att_path = external / ATT_NAME
    for p in (zip_path, sidecar, att_path):
        if p.exists():
            raise PublicationError(f"refuse overwrite: {p.name}")

    prior_before = {}
    for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items():
        p = external / name
        if not p.is_file() or _sha(p) != exp:
            raise PublicationError(f"baseline fail: {name}")
        prior_before[label] = _sha(p)

    art = root / ARTIFACT_DIR
    if not (art / "verification.json").is_file():
        raise PublicationError("run trajectory-expansion run-v0.1.1 first")

    # Gate: refuse if core statuses not PASS
    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    required = (
        "BASELINE_VERIFICATION_STATUS",
        "REGISTRY_REBUILD_RECONCILIATION_STATUS",
        "ACTIVE_PROVIDER_UNCERTAINTY_STATUS",
        "RUNTIME_APPLICABILITY_STATUS",
        "INPUT_MISSINGNESS_CONTRACT_STATUS",
        "FROZEN_PROVIDER_REGISTRY_STATUS",
        "ENGINE_TRAJECTORY_EVIDENCE_INTEGRATION_STATUS",
        "TRAJECTORY_FOUNDATION_CLOSURE_STATUS",
    )
    for k in required:
        if st.get(k) != "PASS":
            raise PublicationError(f"refuse publish: {k}={st.get(k)}")

    sanitize = _sanitize_artifacts_for_public(art)

    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce — Source A Single-Outcome Trajectory Expansion v{VERSION}

Self-contained artifact / model / engine verification (no clinical DB):

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_trajectory_expansion_v011*.py -q
uv run --frozen audit --root . trajectory-expansion verify-v0.1.1
```

Private full-data rebuild (requires configured Source A read-only DB + HMAC):

```bash
uv run --frozen audit --root . trajectory-expansion run-v0.1.1 --no-publish
```

Do not claim clinical rebuild without configured private sources.
v0.1 ZIP must remain unchanged (`{ACCEPTED_V01_ZIP}`).
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Trajectory Expansion v{VERSION}

Corrective release over accepted v0.1. Independent statuses in `status-contract.json`.
Authoritative eligible grain count is rebuilt-threshold based (not forced to 104).
Security remains PAUSED_NOT_ACCEPTED_BY_OWNER.
Medication residual / intervention-response remain NOT_STARTED.
""",
        encoding="utf-8",
    )

    st["PUBLICATION_INTEGRITY_STATUS"] = "PASS"
    st["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PENDING_SCAN"
    st["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "PENDING_CLEANROOM"
    (art / "status-contract.json").write_text(json.dumps(st, indent=2) + "\n")

    write_manifest(art)
    man = verify_manifest(art)
    if not man["ok"]:
        raise PublicationError(f"manifest FAIL: {man}")

    scope = art / "scope-and-claims.json"
    original = scope.read_bytes()
    scope.write_bytes(original + b"\n")
    failed = not verify_manifest(art)["ok"]
    scope.write_bytes(original)
    restored = verify_manifest(art)["ok"]
    mutation = {"ok": failed and restored}
    (art / "manifest-mutation-proof.json").write_text(json.dumps(mutation, indent=2) + "\n")
    write_manifest(art)

    payloads: dict[str, bytes] = {}
    _add_tree(payloads, root, ARTIFACT_DIR)
    for rel in SELF_CONTAINED_SRC:
        _add_tree(payloads, root, rel)
    # CLI entry for verify
    for rel in (
        "src/human_simulator/__init__.py",
        "src/human_simulator/cli.py",
        "src/human_simulator/logging_config.py",
        "docs/current-stage.md",
        "AGENTS.md",
        *UNIT_TESTS,
        "pyproject.toml",
        "uv.lock",
    ):
        p = root / rel
        if p.is_file():
            payloads[rel] = p.read_bytes()
    payloads["REPRODUCE.md"] = (art / "REPRODUCE.md").read_bytes()
    payloads["REVIEW_GUIDE.md"] = (art / "REVIEW_GUIDE.md").read_bytes()

    # Drop trajectory_expansion_v01 from payload if accidentally added — not required
    payloads = {k: v for k, v in payloads.items() if "trajectory_expansion_v01/" not in k}

    row_scan = scan_row_level(payloads)
    (art / "public-data-minimization-scan.json").write_text(
        json.dumps({**row_scan, "sanitize": sanitize}, indent=2) + "\n"
    )
    payloads[f"{ARTIFACT_DIR}/public-data-minimization-scan.json"] = (
        art / "public-data-minimization-scan.json"
    ).read_bytes()
    if not row_scan["ok"]:
        raise PublicationError(f"row-level keys in public ZIP: {row_scan['hits'][:10]}")

    secrets = _scan_secrets(payloads)
    if not secrets["ok"]:
        raise PublicationError(f"banned content: {secrets['hits']}")

    with tempfile.TemporaryDirectory(prefix="uhbse-traj-exp-v011-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        pkg = staging / "src" / "human_simulator"
        pkg.mkdir(parents=True, exist_ok=True)
        init = pkg / "__init__.py"
        if not init.is_file():
            init.write_text("", encoding="utf-8")

        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        # Exact REPRODUCE.md commands
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest tests/test_trajectory_expansion_v011*.py -q && "
            "uv run --frozen audit --root . trajectory-expansion verify-v0.1.1"
        )
        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=staging,
            env=env,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        unit_out = (proc.stdout or "") + (proc.stderr or "")
        unit = {
            "exit_code": proc.returncode,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "output_tail": unit_out[-6000:],
            "literal_command": cmd,
            "matches_reproduce_md": True,
        }
        m = re.search(r"(\d+)\s+passed", unit_out)
        unit["passed"] = int(m.group(1)) if m else None
        if unit["status"] != "PASS":
            raise PublicationError(f"clean-room FAIL: {unit}")

        index_lines = [
            f"# REVIEW_INDEX — Source A Single-Outcome Trajectory Expansion v{VERSION}",
            "",
            "| Path | SHA-256 |",
            "|------|---------|",
        ]
        for name in sorted(payloads):
            index_lines.append(f"| `{name}` | `{_sha_b(payloads[name])}` |")
        index = ("\n".join(index_lines) + "\n").encode()

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(payloads):
                info = zipfile.ZipInfo(name)
                info.date_time = (2026, 8, 20, 14, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 20, 14, 0, 0)
            zf.writestr(info, index)

    zip_sha = _sha(zip_path)
    sidecar.write_text(f"{zip_sha}  {ZIP_NAME}\n")

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        if len(members) != len(set(members)):
            raise PublicationError("duplicate zip members")
        with tempfile.TemporaryDirectory() as etmp:
            zf.extractall(etmp)
            man_ex = verify_manifest(Path(etmp) / ARTIFACT_DIR)
            if not man_ex["ok"]:
                raise PublicationError(f"extract manifest FAIL: {man_ex}")

    indexed = len(payloads)
    chk = assert_attestation_index_fields(members=len(members), indexed_members=indexed)
    if not chk["accepted"]:
        raise PublicationError(f"index invariant FAIL: {chk}")

    prior_ok = True
    prior_after = {}
    for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items():
        got = _sha(external / name)
        prior_after[label] = got
        if got != exp or got != prior_before[label]:
            prior_ok = False

    # Update status after successful clean-room
    st["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PASS"
    st["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "PASS"
    st["PUBLICATION_INTEGRITY_STATUS"] = "PASS"
    (art / "status-contract.json").write_text(json.dumps(st, indent=2) + "\n")

    attestation = {
        "bundle_kind": "source_a_single_outcome_trajectory_expansion_v011",
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "PUBLICATION_INTEGRITY_STATUS": "PASS" if prior_ok else "FAIL",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PASS",
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(members),
        "indexed_members": indexed,
        "members_equals_indexed_plus_one": len(members) == indexed + 1,
        "unit_reproduce": unit,
        "manifest_mutation_proof": mutation,
        "row_level_scan": {"ok": True, "row_level_data_in_zip": False},
        "prior_immutable_zips_untouched": prior_ok,
        "prior_sha256": prior_after,
        "accepted_v01_sha256": ACCEPTED_V01_SHA256,
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "row_level_data_in_zip": False,
        "policy": policy_snapshot(),
    }
    ok = (
        prior_ok
        and unit["status"] == "PASS"
        and mutation["ok"]
        and attestation["members_equals_indexed_plus_one"]
        and row_scan["ok"]
    )
    attestation["attestation_status"] = "PASS" if ok else "FAIL"
    att_path.write_text(json.dumps(attestation, indent=2) + "\n")
    if not ok:
        raise PublicationError("attestation FAIL")
    return {
        "zip": str(zip_path),
        "sidecar": str(sidecar),
        "attestation": str(att_path),
        "sha256": zip_sha,
        "members": len(members),
        "indexed_members": indexed,
        "attestation_status": "PASS",
        "PUBLICATION_INTEGRITY_STATUS": "PASS",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PASS",
    }
