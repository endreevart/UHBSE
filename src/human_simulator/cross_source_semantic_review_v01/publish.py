"""Publish refuse-if-exists review ZIP — semantic review v0.1 (no scientific PASS claim)."""

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

from human_simulator.cross_source_semantic_review_v01.policy import (
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_PRIVACY_XS_SHA256,
    ACCEPTED_PRIVACY_XS_ZIP,
    ARTIFACT_DIR,
    REVIEW_ZIP,
    VERSION,
)

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_cross_source_semantic_review_v01_unit.py",
    "tests/test_cross_source_semantic_review_v01_contracts.py",
)

PRIOR_IMMUTABLE_ZIPS = {
    "privacy_cross_source_v0.1": (ACCEPTED_PRIVACY_XS_ZIP, ACCEPTED_PRIVACY_XS_SHA256),
    "global_state_v0.1.1": (ACCEPTED_GS011_ZIP, ACCEPTED_GS011_SHA256),
}


class PublicationError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )


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
            ".html",
            ".csv",
        } or rel.startswith("artifacts/"):
            payloads[r] = path.read_bytes()


def scan_row_level(payloads: dict[str, bytes]) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    identity_keys = (
        "opaque_subject_key",
        "research_subject_id",
        "source_subject_id",
        "patient_id",
        "pair_id",
        "component_id",
        "observation_id",
    )
    for name, data in payloads.items():
        if not name.endswith((".json", ".html", ".csv", ".md")):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for key in identity_keys:
            if re.search(rf'"{re.escape(key)}"\s*:', text):
                hits.append({"member": name, "key": key, "kind": "identity_or_locator_key"})
        if "uhbse-research-hmac" in text or "UHBSE_RESEARCH_HMAC_KEY" in text:
            hits.append({"member": name, "key": "hmac", "kind": "secret_reference"})
    return {
        "ok": len(hits) == 0,
        "n_hits": len(hits),
        "hits": hits[:50],
        "row_level_data_in_zip": len(hits) != 0,
    }


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
        raise PublicationError("run cross-source-semantic-review run-v0.1 first")
    ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
    if not ver.get("ok"):
        raise PublicationError("refuse publish: verification.ok is false")

    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    required = {
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "MAPPING_UNIVERSE_ACCOUNTING_STATUS": "PASS",
        "DOMAIN_REVIEW_WORKBENCH_STATUS": "PASS",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "INDEPENDENCE_NOT_ESTABLISHED",
    }
    for k, exp in required.items():
        if st.get(k) != exp:
            raise PublicationError(f"refuse publish: {k}={st.get(k)} expected {exp}")

    pub_status = st.get("PUBLICATION_STATUS") or "REFUSED_DOMAIN_REVIEW_REQUIRED"
    if pub_status not in {
        "REFUSED_DOMAIN_REVIEW_REQUIRED",
        "READY_FOR_ACCEPTED_MAPPING_GATE_PACKET",
    }:
        raise PublicationError(f"unexpected PUBLICATION_STATUS={pub_status}")

    st["PUBLIC_DATA_MINIMIZATION_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["PUBLICATION_INTEGRITY_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["CONTENT_PREPACK_STATUS"] = "PASS"
    st["SCIENTIFIC_PASS"] = False
    (art / "status-contract.json").write_text(
        json.dumps(st, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce — Cross-Source Outcome Semantic Review v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_cross_source_semantic_review_v01*.py -q
uv run --frozen audit --root . cross-source-semantic-review verify-v0.1
```

Private domain-review pack: `private/cross-source-outcome-review-v01/`
Decision log is append-only. No classifier / zero-shot in this stage.
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Cross-Source Outcome Semantic Review v{VERSION}

This packet prepares typed domain decisions. It does **not** claim scientific PASS.
SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT may be 0 → DOMAIN_REVIEW_DECISION_REQUIRED.
Do not auto-accept from label/unit. T3 code 53 requires explicit domain review.
Security remains PAUSED_NOT_ACCEPTED_BY_OWNER.
""",
        encoding="utf-8",
    )

    write_manifest(art)
    if not verify_manifest(art)["ok"]:
        raise PublicationError("manifest FAIL")

    scope = art / "policy.json"
    original = scope.read_bytes()
    scope.write_bytes(original + b"\n")
    failed = not verify_manifest(art)["ok"]
    scope.write_bytes(original)
    restored = verify_manifest(art)["ok"]
    mutation = {
        "ok": failed and restored,
        "mutation_proof": "PASS" if (failed and restored) else "FAIL",
    }
    (art / "manifest-mutation-proof.json").write_text(
        json.dumps(mutation, indent=2) + "\n", encoding="utf-8"
    )
    write_manifest(art)

    payloads: dict[str, bytes] = {}
    _add_tree(payloads, root, ARTIFACT_DIR)
    _add_tree(payloads, root, "src/human_simulator")
    for rel in (
        "src/human_simulator/__init__.py",
        "src/human_simulator/cli.py",
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

    row_scan = scan_row_level(payloads)
    (art / "public-data-minimization-scan.json").write_text(
        json.dumps(row_scan, indent=2) + "\n", encoding="utf-8"
    )
    payloads[f"{ARTIFACT_DIR}/public-data-minimization-scan.json"] = (
        art / "public-data-minimization-scan.json"
    ).read_bytes()
    write_manifest(art)
    payloads[f"{ARTIFACT_DIR}/evidence-manifest.sha256"] = (
        art / "evidence-manifest.sha256"
    ).read_bytes()
    payloads[f"{ARTIFACT_DIR}/status-contract.json"] = (
        art / "status-contract.json"
    ).read_bytes()
    if not row_scan["ok"]:
        raise PublicationError(f"row-level keys: {row_scan['hits'][:10]}")

    with tempfile.TemporaryDirectory(prefix="uhbse-xs-semrev-v01-") as tmp:
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
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest tests/test_cross_source_semantic_review_v01*.py -q && "
            "uv run --frozen audit --root . cross-source-semantic-review verify-v0.1"
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
            "output_tail": unit_out[-6000:],
            "literal_command": cmd,
        }
        (staging / ARTIFACT_DIR / "tests.json").write_text(
            json.dumps(unit, indent=2) + "\n", encoding="utf-8"
        )
        if proc.returncode != 0:
            raise PublicationError(f"isolated tests FAIL: {unit_out[-2000:]}")

        members = sorted(
            p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()
        )
        index_body = [
            f"# REVIEW_INDEX — Cross-Source Outcome Semantic Review v{VERSION}",
            "",
            f"Members: {len(members)}",
            f"PUBLICATION_STATUS: {pub_status}",
            "SCIENTIFIC_PASS: false",
            "",
            "## Key artifacts",
            "",
            f"- `{ARTIFACT_DIR}/status-contract.json`",
            f"- `{ARTIFACT_DIR}/stage-report.md`",
            f"- `{ARTIFACT_DIR}/t3-domain-review-audit.json`",
            "",
            "Private decision log is **not** in this ZIP.",
            "",
        ]
        (staging / "REVIEW_INDEX.md").write_text("\n".join(index_body) + "\n", encoding="utf-8")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(staging.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(staging).as_posix())

    digest = _sha(zip_path)
    sidecar.write_text(f"{digest}  {ZIP_NAME}\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    indexed = len(names) - (1 if any(n.endswith("REVIEW_INDEX.md") for n in names) else 0)

    prior_after = {
        label: _sha(external / name) for label, (name, _) in PRIOR_IMMUTABLE_ZIPS.items()
    }
    if prior_after != prior_before:
        raise PublicationError("prior ZIP mutated during publish")

    att = {
        "version": VERSION,
        "zip": ZIP_NAME,
        "sha256": digest,
        "members": len(names),
        "indexed_members": indexed,
        "attestation_status": "PASS",
        "SCIENTIFIC_PASS": False,
        "PUBLICATION_STATUS": pub_status,
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": st.get(
            "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT"
        ),
        "prior_baselines_unchanged": prior_after,
        "created_at": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    att_path.write_text(json.dumps(att, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "zip": str(zip_path),
        "sha256": digest,
        "members": len(names),
        "indexed_members": indexed,
        "attestation": att,
        "SCIENTIFIC_PASS": False,
        "PUBLICATION_STATUS": pub_status,
    }
