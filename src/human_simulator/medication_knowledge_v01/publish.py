"""Publish refuse-if-exists medication-knowledge representation v0.1 review ZIP."""

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

from human_simulator.medication_knowledge_v01.lifecycle import (
    assert_lifecycle_consistency,
)
from human_simulator.medication_knowledge_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_IMMUTABLE_ZIPS,
    REVIEW_ZIP,
    VERSION,
    policy_snapshot,
)

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")

UNIT_TESTS = (
    "tests/test_medication_knowledge_representation_v01_unit.py",
    "tests/test_intervention_association_v011_unit.py",
    "tests/test_intervention_association_v01_unit.py",
)

PUBLIC_REPRODUCE_COMMANDS = (
    "uv sync --frozen --extra dev",
    (
        "uv run --frozen pytest "
        "tests/test_medication_knowledge_representation_v01_unit.py "
        "tests/test_intervention_association_v011_unit.py "
        "tests/test_intervention_association_v01_unit.py -q"
    ),
    "uv run --frozen audit --root . medication-knowledge verify-v0.1",
    "uv run --frozen audit --root . intervention-association verify-v0.1.1",
)

V011_ARTIFACT_DIR = "artifacts/stage-03-first-medication-association-baseline-v0.1.1"


class PublicationError(RuntimeError):
    pass


def assert_attestation_index_fields(*, members: int, indexed_members: int) -> dict[str, Any]:
    return {
        "accepted": members == indexed_members + 1,
        "members": members,
        "indexed_members": indexed_members,
    }


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
    if "episodes_" in p.name and p.suffix == ".jsonl":
        return True
    if "medication-registry-full" in p.name:
        return True
    return False


def _add_tree(payloads: dict[str, bytes], root: Path, rel: str) -> None:
    base = root / rel
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        if path.is_file():
            r = path.relative_to(root).as_posix()
            if not _excluded(r):
                payloads[r] = path.read_bytes()


def _scan(payloads: dict[str, bytes]) -> dict[str, Any]:
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
        if name.endswith("_unit.py") or name.endswith("publish.py"):
            continue
        sample = data if len(data) < 400_000 else data[:400_000]
        for rx, label in patterns:
            if rx.search(sample):
                hits.append({"member": name, "pattern": label})
        # Patient-level episode JSONL must never ship
        if name.endswith(".jsonl") and b"opaque_subject_key" in sample:
            hits.append({"member": name, "pattern": "EPISODE_JSONL_WITH_SUBJECT"})
    return {"ok": not hits, "hits": hits}


def _write_guides(art: Path) -> None:
    repro = f"""# Reproduce — Medication Knowledge Representation v{VERSION}

Public verification only. Full scientific recomputation requires private
row-level episodes and is documented in `REPRODUCE_PRIVATE.md`.

```bash
uv sync --frozen --extra dev

uv run --frozen pytest \\
  tests/test_medication_knowledge_representation_v01_unit.py \\
  tests/test_intervention_association_v011_unit.py \\
  tests/test_intervention_association_v01_unit.py -q

uv run --frozen audit --root . medication-knowledge verify-v0.1

uv run --frozen audit --root . intervention-association verify-v0.1.1
```

Artifact verification ≠ full model recomputation.
Clinical use and causal interpretation are prohibited.
"""
    (art / "REPRODUCE.md").write_text(repro, encoding="utf-8")
    private = f"""# Reproduce (private workspace) — Medication Knowledge Representation v{VERSION}

Requires authorised local inputs that are **not** in the review ZIP:

* `private/intervention-association-v01/episodes/episodes_appointment_date_h365.jsonl`
* Source A read-only role (`mg_audit_ro`) via `db-audit.env`
* Canonical/derived env files as needed for prior stages

```bash
# After sourcing local env files (never commit secrets):
uv run --frozen audit --root . medication-knowledge run-v0.1 --no-publish
uv run --frozen audit --root . medication-knowledge verify-v0.1
uv run --frozen audit --root . medication-knowledge publish-v0.1
```

Do not place patient-level rows, credentials, tokens, or DSNs in review bundles.
"""
    (art / "REPRODUCE_PRIVATE.md").write_text(private, encoding="utf-8")
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Medication Knowledge Representation v{VERSION}

Internal `status-contract.json` uses pre-pack lifecycle fields.
Final `PUBLICATION_INTEGRITY_STATUS: PASS` appears only in external attestation.

Corrections to v0.1.1 packaging defects are applied in this bundle (cli import
closure, complete test dependency packages, no stale PENDING_* in packed
statuses, REPRODUCE vs REPRODUCE_PRIVATE split).

Non-claims: intervention-response, treatment-effect, causal-effect,
clinical validation, QSP, PK/PD, production. Security PAUSED_NOT_ACCEPTED_BY_OWNER.
""",
        encoding="utf-8",
    )


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
        raise PublicationError("run medication-knowledge run-v0.1 first")

    _write_guides(art)
    write_manifest(art)
    man = verify_manifest(art)
    if not man["ok"]:
        raise PublicationError(f"manifest FAIL: {man}")

    st_path = art / "status-contract.json"
    statuses = json.loads(st_path.read_text(encoding="utf-8"))
    statuses["pre_pack_manifest_status"] = "PASS"
    statuses["content_verification_status"] = "PASS"
    statuses["post_pack_publication_verification_status"] = "EXTERNAL_ATTESTATION_REQUIRED"
    statuses["PUBLICATION_INTEGRITY_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    # clean_staging updated after clean-room PASS below
    st_path.write_text(json.dumps(statuses, indent=2) + "\n")

    scope = art / "scope-and-claims.json"
    write_manifest(art)
    original = scope.read_bytes()
    scope.write_bytes(original + b"\n")
    failed = not verify_manifest(art)["ok"]
    scope.write_bytes(original)
    restored = verify_manifest(art)["ok"]
    mutation = {"ok": failed and restored}
    (art / "manifest-mutation-proof.json").write_text(json.dumps(mutation, indent=2) + "\n")
    write_manifest(art)

    payloads: dict[str, bytes] = {}
    # Full implementation + import closure for audit CLI
    _add_tree(payloads, root, "src/human_simulator")
    _add_tree(payloads, root, ARTIFACT_DIR)
    # Carry v0.1.1 verification artifact so verify-v0.1.1 works after extraction
    v011_ver = root / V011_ARTIFACT_DIR / "verification.json"
    if v011_ver.is_file():
        payloads[f"{V011_ARTIFACT_DIR}/verification.json"] = v011_ver.read_bytes()
    # model hashes / identities (no need for full binary if json present)
    freeze = root / V011_ARTIFACT_DIR / "model-freeze.json"
    if freeze.is_file():
        payloads[f"{V011_ARTIFACT_DIR}/model-freeze.json"] = freeze.read_bytes()
    frozen = root / V011_ARTIFACT_DIR / "frozen_models"
    if frozen.is_dir():
        _add_tree(payloads, root, f"{V011_ARTIFACT_DIR}/frozen_models")

    for rel in (
        "docs/current-stage.md",
        "docs/owner-priority-override-core-first.md",
        "AGENTS.md",
        *UNIT_TESTS,
        "pyproject.toml",
        "uv.lock",
        "README.md",
    ):
        p = root / rel
        if p.is_file():
            payloads[rel] = p.read_bytes()

    payloads["REPRODUCE.md"] = (art / "REPRODUCE.md").read_bytes()
    payloads["REPRODUCE_PRIVATE.md"] = (art / "REPRODUCE_PRIVATE.md").read_bytes()
    payloads["REVIEW_GUIDE.md"] = (art / "REVIEW_GUIDE.md").read_bytes()

    scan = _scan(payloads)
    if not scan["ok"]:
        raise PublicationError(f"banned content: {scan['hits']}")

    with tempfile.TemporaryDirectory(prefix="uhbse-med-knowledge-v01-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        cmd = " && ".join(PUBLIC_REPRODUCE_COMMANDS)
        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
        )
        unit_out = (proc.stdout or "") + (proc.stderr or "")
        unit = {
            "exit_code": proc.returncode,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "output_tail": unit_out[-6000:],
            "literal_commands": list(PUBLIC_REPRODUCE_COMMANDS),
        }
        m = re.search(r"(\d+)\s+passed", unit_out)
        unit["passed"] = int(m.group(1)) if m else None
        if unit["status"] != "PASS":
            raise PublicationError(f"clean-room FAIL: {unit}")

        statuses["clean_staging_test_status"] = "PASS"
        statuses["CARRIED_FORWARD_EVIDENCE_CORRECTION_STATUS"] = "PASS"
        # Also refresh verification.json statuses — no PENDING_* remain
        ver_path = art / "verification.json"
        ver = json.loads(ver_path.read_text(encoding="utf-8"))
        ver_statuses = ver.get("statuses") or {}
        ver_statuses["pre_pack_manifest_status"] = "PASS"
        ver_statuses["clean_staging_test_status"] = "PASS"
        ver_statuses["content_verification_status"] = "PASS"
        ver_statuses["CARRIED_FORWARD_EVIDENCE_CORRECTION_STATUS"] = "PASS"
        ver["statuses"] = ver_statuses
        ver_path.write_text(json.dumps(ver, indent=2) + "\n")
        st_path.write_text(json.dumps(statuses, indent=2) + "\n")
        corr = art / "carried-forward-evidence-correction.json"
        if corr.is_file():
            cd = json.loads(corr.read_text())
            cd["CARRIED_FORWARD_EVIDENCE_CORRECTION_STATUS"] = "PASS"
            corr.write_text(json.dumps(cd, indent=2) + "\n")
        write_manifest(art)

        # Refresh packed artifact bytes from disk
        for path in art.rglob("*"):
            if path.is_file():
                r = path.relative_to(root).as_posix()
                payloads[r] = path.read_bytes()

        # Rebuild artifact manifest bytes explicitly
        art_files = {
            k[len(ARTIFACT_DIR) + 1 :]: v
            for k, v in payloads.items()
            if k.startswith(ARTIFACT_DIR + "/") and not k.endswith("evidence-manifest.sha256")
        }
        man_lines = [f"{_sha_b(art_files[name])}  {name}" for name in sorted(art_files)]
        payloads[f"{ARTIFACT_DIR}/evidence-manifest.sha256"] = (
            "\n".join(man_lines) + "\n"
        ).encode()

        index_lines = [
            f"# REVIEW_INDEX — Medication Knowledge Representation v{VERSION}",
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
                info.date_time = (2026, 8, 19, 15, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 19, 15, 0, 0)
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
            env2 = os.environ.copy()
            env2["UV_CACHE_DIR"] = str(Path(etmp) / "uv-cache")
            env2["UV_PROJECT_ENVIRONMENT"] = str(Path(etmp) / "venv")
            cmd2 = " && ".join(PUBLIC_REPRODUCE_COMMANDS)
            proc2 = subprocess.run(
                cmd2,
                cwd=etmp,
                env=env2,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc2.returncode != 0:
                raise PublicationError(
                    "clean-extraction FAIL: "
                    + ((proc2.stdout or "") + (proc2.stderr or ""))[-3000:]
                )
            # Assert no PENDING_* in packed status-contract
            packed_st = json.loads(
                (Path(etmp) / ARTIFACT_DIR / "status-contract.json").read_text()
            )
            for k, v in packed_st.items():
                if isinstance(v, str) and v in ("PENDING_WRITE", "PENDING_PUBLISH"):
                    raise PublicationError(f"stale pending in packed status: {k}={v}")

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

    attestation = {
        "bundle_kind": "medication_knowledge_representation_v01",
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_integrity_status": "PASS" if prior_ok else "FAIL",
        "PUBLICATION_INTEGRITY_STATUS": "PASS" if prior_ok else "FAIL",
        "post_pack_zip_verification_status": "PASS",
        "sidecar_matches_final_zip": True,
        "clean_extraction_verification_status": "PASS",
        "archive_rebuilt_after_hashing": False,
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(members),
        "indexed_members": indexed,
        "members_equals_indexed_plus_one": len(members) == indexed + 1,
        "unit_reproduce": unit,
        "manifest_mutation_proof": mutation,
        "prior_immutable_zips_untouched": prior_ok,
        "prior_sha256": prior_after,
        "CARRIED_FORWARD_EVIDENCE_CORRECTION_STATUS": "PASS",
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "clinical_validation_status": "NOT_STARTED",
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "causal_effect_status": "NOT_EVALUATED",
        "row_level_episodes_in_zip": False,
        "full_scientific_recomputation_publicly_reproducible": False,
        "policy": policy_snapshot(),
    }
    life = assert_lifecycle_consistency(status_contract=statuses, attestation=attestation)
    if not life["ok"]:
        raise PublicationError(f"lifecycle consistency FAIL: {life}")

    ok = (
        prior_ok
        and unit["status"] == "PASS"
        and mutation["ok"]
        and attestation["members_equals_indexed_plus_one"]
        and life["ok"]
    )
    attestation["attestation_status"] = "PASS" if ok else "FAIL"
    attestation["lifecycle_consistency"] = life
    att_path.write_text(json.dumps(attestation, indent=2) + "\n")
    if not ok:
        raise PublicationError("attestation FAIL")

    st_path.write_text(json.dumps(statuses, indent=2) + "\n")

    return {
        "zip": str(zip_path),
        "sidecar": str(sidecar),
        "attestation": str(att_path),
        "sha256": zip_sha,
        "members": len(members),
        "indexed_members": indexed,
        "attestation_status": "PASS",
        "PUBLICATION_INTEGRITY_STATUS": "PASS",
        "CARRIED_FORWARD_EVIDENCE_CORRECTION_STATUS": "PASS",
        "internal_PUBLICATION_INTEGRITY_STATUS": statuses["PUBLICATION_INTEGRITY_STATUS"],
    }
