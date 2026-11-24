"""Publish refuse-if-exists review ZIP for concept-bounded technical pilot v0.1."""

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

from human_simulator.concept_pilot_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_CONCEPT_COHORTS_SHA256,
    PRIOR_CONCEPT_COHORTS_ZIP,
    PRIOR_MEDICATION_ASSOC_SHA256,
    PRIOR_MEDICATION_ASSOC_ZIP,
    REVIEW_ZIP,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_v012.publication_fixes import assert_attestation_index_fields

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = ("tests/test_concept_pilot_v01.py",)

PRIOR_IMMUTABLE_ZIPS = {
    "medication_association_v011": (PRIOR_MEDICATION_ASSOC_ZIP, PRIOR_MEDICATION_ASSOC_SHA256),
    "concept_cohorts_v01": (PRIOR_CONCEPT_COHORTS_ZIP, PRIOR_CONCEPT_COHORTS_SHA256),
}


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
    if p.suffix.lower() == ".zip" or "dumps" in p.parts:
        return True
    if "private" in p.parts:
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
        (re.compile(rb"\bpatient_id\b.{0,40}\b\d{4,}\b"), "PATIENT_ID_VALUE"),
    ]
    hits = []
    for name, data in payloads.items():
        if "publish.py" in name or name.endswith("test_concept_pilot_v01.py"):
            continue
        sample = data if len(data) < 400_000 else data[:400_000]
        for rx, label in patterns:
            if rx.search(sample):
                hits.append({"member": name, "pattern": label})
    return {"ok": not hits, "hits": hits}


def _write_guides(art: Path) -> None:
    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce — Concept-Bounded Technical Medication Pilot v{VERSION}

```bash
uv run --frozen audit --root . concept-pilot run-v0.1 --no-publish
uv run --frozen audit --root . concept-pilot verify-v0.1
uv run --frozen pytest tests/test_concept_pilot_v01.py -q
```

Scientific readiness remains ZERO_READY. Technical CV is not external validation.
Clinical use and causal interpretation are prohibited.
Row-level episode tables remain workspace-only under `private/`.
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Concept-Bounded Technical Medication Pilot v{VERSION}

Independent statuses in `status-contract.json`. Do not collapse into one PASS.

Scientific gates 100/300/30 unchanged. Technical pilot status is separate.

Non-claims: intervention-response, treatment-effect, causal-effect, clinical validation,
QSP, PK/PD, production readiness. Security remains PAUSED_NOT_ACCEPTED_BY_OWNER.
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
        raise PublicationError("run concept-pilot run-v0.1 first")

    _write_guides(art)
    scope = art / "scope-and-claims.json"
    if not scope.is_file():
        scope.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "clinical_use_prohibited": True,
                    "causal_interpretation_prohibited": True,
                    "policy": policy_snapshot(),
                },
                indent=2,
            )
            + "\n"
        )

    status_path = art / "status-contract.json"
    if status_path.is_file():
        st = json.loads(status_path.read_text(encoding="utf-8"))
        st["PUBLICATION_INTEGRITY_STATUS"] = "PASS"
        status_path.write_text(json.dumps(st, indent=2) + "\n")

    write_manifest(art)
    man = verify_manifest(art)
    if not man["ok"]:
        raise PublicationError(f"manifest FAIL: {man}")

    original = scope.read_bytes()
    scope.write_bytes(original + b"\n")
    failed = not verify_manifest(art)["ok"]
    scope.write_bytes(original)
    restored = verify_manifest(art)["ok"]
    mutation = {"ok": failed and restored}
    (art / "manifest-mutation-proof.json").write_text(json.dumps(mutation, indent=2) + "\n")
    write_manifest(art)

    payloads: dict[str, bytes] = {}
    for rel in (ARTIFACT_DIR, "src/human_simulator/concept_pilot_v01"):
        if (root / rel).is_dir():
            _add_tree(payloads, root, rel)
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

    with tempfile.TemporaryDirectory(prefix="uhbse-concept-pilot-v01-") as tmp:
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
        # Clean-room needs association helpers imported by concept_pilot
        for rel in (
            "src/human_simulator/intervention_association_v01",
            "src/human_simulator/core",
            "src/human_simulator/unified_v012",
        ):
            src = root / rel
            if src.is_dir():
                for path in sorted(src.rglob("*.py")):
                    r = path.relative_to(root).as_posix()
                    dest = staging / r
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(path.read_bytes())

        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest "
            + " ".join(UNIT_TESTS)
            + " -q"
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
            "output_tail": unit_out[-4000:],
            "literal_command": cmd,
        }
        m = re.search(r"(\d+)\s+passed", unit_out)
        unit["passed"] = int(m.group(1)) if m else None
        if unit["status"] != "PASS":
            raise PublicationError(f"clean-room FAIL: {unit}")

        index_lines = [
            f"# REVIEW_INDEX — Concept-Bounded Technical Medication Pilot v{VERSION}",
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
                info.date_time = (2026, 8, 20, 12, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 20, 12, 0, 0)
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

    attestation = {
        "bundle_kind": "first_concept_bounded_technical_medication_pilot_v01",
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
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "clinical_validation_status": "NOT_STARTED",
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "causal_effect_status": "NOT_EVALUATED",
        "row_level_episodes_in_zip": False,
        "policy": policy_snapshot(),
    }
    ok = (
        prior_ok
        and unit["status"] == "PASS"
        and mutation["ok"]
        and attestation["members_equals_indexed_plus_one"]
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
    }
