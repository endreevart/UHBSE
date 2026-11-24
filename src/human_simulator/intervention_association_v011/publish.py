"""Publish refuse-if-exists v0.1.1 review ZIP with explicit publication lifecycle."""

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

from human_simulator.intervention_association_v011.lifecycle import (
    assert_lifecycle_consistency,
)
from human_simulator.intervention_association_v011.policy import (
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ARTIFACT_DIR,
    PRIOR_IMMUTABLE_ZIPS,
    REVIEW_ZIP,
    VERSION,
    policy_snapshot,
)


def assert_attestation_index_fields(*, members: int, indexed_members: int) -> dict[str, Any]:
    return {
        "accepted": members == indexed_members + 1,
        "members": members,
        "indexed_members": indexed_members,
    }

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_intervention_association_v011_unit.py",
    "tests/test_intervention_association_v01_unit.py",
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
    if "episodes_" in p.name and p.suffix == ".jsonl":
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
        if "publish.py" in name or name.endswith("_unit.py"):
            continue
        sample = data if len(data) < 400_000 else data[:400_000]
        for rx, label in patterns:
            if rx.search(sample):
                hits.append({"member": name, "pattern": label})
    return {"ok": not hits, "hits": hits}


def _write_guides(art: Path) -> None:
    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce — Medication-Association Baseline v{VERSION}

```bash
uv run --frozen audit --root . intervention-association verify-v0.1.1
uv run --frozen audit --root . intervention-association run-v0.1.1 --no-publish
uv run --frozen pytest tests/test_intervention_association_v011_unit.py -q
```

Authoritative comparison: M1 vs M2C (signed feature hashing).
Legacy ordinal M2 is diagnostic only.
Clinical use and causal interpretation are prohibited.
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Medication-Association Baseline v{VERSION}

Internal `status-contract.json` uses pre-pack lifecycle fields.
Final `PUBLICATION_INTEGRITY_STATUS: PASS` appears only in external attestation.

Non-claims unchanged: intervention-response, treatment-effect, causal-effect,
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
        raise PublicationError("run intervention-association run-v0.1.1 first")

    _write_guides(art)
    write_manifest(art)
    man = verify_manifest(art)
    if not man["ok"]:
        raise PublicationError(f"manifest FAIL: {man}")

    # update pre_pack fields
    st_path = art / "status-contract.json"
    statuses = json.loads(st_path.read_text(encoding="utf-8"))
    statuses["pre_pack_manifest_status"] = "PASS"
    statuses["content_verification_status"] = "PASS"
    statuses["post_pack_publication_verification_status"] = "EXTERNAL_ATTESTATION_REQUIRED"
    statuses["PUBLICATION_INTEGRITY_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st_path.write_text(json.dumps(statuses, indent=2) + "\n")

    scope = art / "scope-and-claims.json"
    original = scope.read_bytes()
    scope.write_bytes(original + b"\n")
    failed = not verify_manifest(art)["ok"]
    # remanifest after status update first
    write_manifest(art)
    scope.write_bytes(original + b"\n")
    failed = not verify_manifest(art)["ok"]
    scope.write_bytes(original)
    write_manifest(art)
    restored = verify_manifest(art)["ok"]
    # re-do mutation proof cleanly
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
    for rel in (
        ARTIFACT_DIR,
        "src/human_simulator/intervention_association_v011",
        "src/human_simulator/intervention_association_v01/models.py",
        "src/human_simulator/core/simulation.py",
        "src/human_simulator/core/snapshot.py",
        "src/human_simulator/core/policy.py",
        "src/human_simulator/core/provenance.py",
    ):
        if (root / rel).is_dir():
            _add_tree(payloads, root, rel)
        elif (root / rel).is_file():
            payloads[rel] = (root / rel).read_bytes()

    for rel in (
        "src/human_simulator/__init__.py",
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

    scan = _scan(payloads)
    if not scan["ok"]:
        raise PublicationError(f"banned content: {scan['hits']}")

    with tempfile.TemporaryDirectory(prefix="uhbse-med-assoc-v011-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        pkg = staging / "src" / "human_simulator"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        # minimal core package init without heavy imports
        core = pkg / "core"
        core.mkdir(parents=True, exist_ok=True)
        if not (core / "__init__.py").is_file():
            (core / "__init__.py").write_text("", encoding="utf-8")
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        # unit suite for v011 only in clean room (v01 may need extra pkgs)
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest tests/test_intervention_association_v011_unit.py -q"
        )
        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
        )
        unit_out = (proc.stdout or "") + (proc.stderr or "")
        unit = {
            "exit_code": proc.returncode,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "output_tail": unit_out[-4000:],
            "literal_command": cmd,
        }
        m = re.search(r"(\d+)\s+passed", unit_out)
        unit["passed"] = int(m.group(1)) if m else None
        if unit["status"] != "PASS":
            raise PublicationError(f"clean-room FAIL: {unit}")

        # update clean_staging in statuses before packing — need refresh payloads
        statuses["clean_staging_test_status"] = "PASS"
        st_bytes = (json.dumps(statuses, indent=2) + "\n").encode()
        payloads[f"{ARTIFACT_DIR}/status-contract.json"] = st_bytes
        # remanifest bytes for packed art tree
        art_files = {
            k[len(ARTIFACT_DIR) + 1 :]: v
            for k, v in payloads.items()
            if k.startswith(ARTIFACT_DIR + "/") and not k.endswith("evidence-manifest.sha256")
        }
        man_lines = []
        for name in sorted(art_files):
            man_lines.append(f"{_sha_b(art_files[name])}  {name}")
        payloads[f"{ARTIFACT_DIR}/evidence-manifest.sha256"] = (
            "\n".join(man_lines) + "\n"
        ).encode()

        index_lines = [
            f"# REVIEW_INDEX — First Medication-Association Baseline v{VERSION}",
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
                info.date_time = (2026, 8, 19, 14, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 19, 14, 0, 0)
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
            # clean extraction pytest
            env2 = os.environ.copy()
            env2["UV_CACHE_DIR"] = str(Path(etmp) / "uv-cache")
            env2["UV_PROJECT_ENVIRONMENT"] = str(Path(etmp) / "venv")
            # copy extracted tree is already etmp contents
            proc2 = subprocess.run(
                "uv sync --frozen --extra dev && "
                "uv run --frozen pytest tests/test_intervention_association_v011_unit.py -q",
                cwd=etmp,
                env=env2,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc2.returncode != 0:
                raise PublicationError(
                    f"clean-extraction FAIL: {(proc2.stdout or '') + (proc2.stderr or '')}"[-2000:]
                )

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
        "bundle_kind": "first_medication_association_baseline_v011",
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
        "accepted_v01_sha256": ACCEPTED_V01_SHA256,
        "accepted_v01_zip": ACCEPTED_V01_ZIP,
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "clinical_validation_status": "NOT_STARTED",
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "causal_effect_status": "NOT_EVALUATED",
        "authoritative_comparison": "M1_vs_M2C",
        "row_level_episodes_in_zip": False,
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

    # workspace status remains EXTERNAL_ATTESTATION_REQUIRED (do not rewrite packed ZIP)
    statuses["clean_staging_test_status"] = "PASS"
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
        "internal_PUBLICATION_INTEGRITY_STATUS": statuses["PUBLICATION_INTEGRITY_STATUS"],
    }
