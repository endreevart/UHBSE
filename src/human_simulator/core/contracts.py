"""Accepted design-contract verification for Core Vertical Slice review bundles."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from human_simulator.core.policy import DESIGN_CONTENT_MANIFEST, REQUIRED_DESIGN_CONTRACTS
from human_simulator.core.provenance import COMPUTED_FORBIDDEN, COMPUTED_REQUIRED


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_design_manifest(manifest_path: Path) -> dict[str, str]:
    """Parse design-content-manifest.sha256 → {filename: digest}. Refuses self-hash."""
    mapping: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        name = name.strip()
        if name in {"manifest.sha256", "design-content-manifest.sha256"}:
            raise ValueError("design manifest must not hash itself")
        mapping[name] = digest.strip()
    return mapping


def _computed_required_from_contract(repo_root: Path) -> tuple[set[str], str | None]:
    try:
        import yaml  # type: ignore

        path = repo_root / "artifacts/stage-03/provenance-contract.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        computed = ((doc or {}).get("profiles") or {}).get("COMPUTED") or {}
        required = computed.get("required_fields")
        if required is None:
            return set(), "COMPUTED.required_fields missing"
        return set(required), None
    except Exception as exc:  # noqa: BLE001
        return set(), f"{type(exc).__name__}: {exc}"


def verify_accepted_design_contracts(
    repo_root: Path,
    *,
    contracts_root: Path | None = None,
    manifest_path: Path | None = None,
    validator_required: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Confirm required contracts exist and match design-content-manifest.sha256."""
    manifest_rel = DESIGN_CONTENT_MANIFEST
    mpath = manifest_path or (repo_root / manifest_rel)
    croots = contracts_root or (repo_root / "artifacts" / "stage-03")
    if not mpath.is_file():
        return {
            "ok": False,
            "status": "FAIL",
            "detail": f"missing accepted design manifest: {manifest_rel}",
            "contracts": {},
            "check_name": "accepted_design_contracts_present_and_verified",
        }
    try:
        accepted = parse_design_manifest(mpath)
    except ValueError as exc:
        return {
            "ok": False,
            "status": "FAIL",
            "detail": str(exc),
            "contracts": {},
            "check_name": "accepted_design_contracts_present_and_verified",
        }

    contracts: dict[str, Any] = {}
    all_ok = True
    for name in REQUIRED_DESIGN_CONTRACTS:
        path = croots / name
        expected = accepted.get(name)
        entry: dict[str, Any] = {
            "path": f"artifacts/stage-03/{name}",
            "present": path.is_file(),
            "expected_sha256": expected,
            "computed_sha256": None,
            "matches_manifest": False,
        }
        if expected is None:
            entry["detail"] = "not listed in accepted design manifest"
            all_ok = False
        elif not path.is_file():
            entry["detail"] = "file missing"
            all_ok = False
        else:
            computed = _sha256_file(path)
            entry["computed_sha256"] = computed
            entry["matches_manifest"] = computed == expected
            if not entry["matches_manifest"]:
                entry["detail"] = "sha256 mismatch vs accepted design manifest"
                all_ok = False
        contracts[name] = entry
        if not entry.get("matches_manifest"):
            all_ok = False

    yaml_required, yaml_error = _computed_required_from_contract(repo_root)
    py_required = set(validator_required if validator_required is not None else COMPUTED_REQUIRED)
    weakened = bool(yaml_required) and not (py_required >= yaml_required)
    covers = (py_required >= yaml_required) if yaml_required else yaml_error is None
    if weakened or yaml_error:
        all_ok = False

    return {
        "ok": all_ok and not weakened and yaml_error is None,
        "status": "PASS" if all_ok and not weakened and yaml_error is None else "FAIL",
        "manifest_path": manifest_rel,
        "manifest_sha256": _sha256_file(mpath),
        "manifest_self_hash_absent": True,
        "contracts": contracts,
        "validator_computed_required_fields": sorted(py_required),
        "contract_computed_required_fields": sorted(yaml_required),
        "validator_covers_contract_required_fields": covers,
        "validator_weakened_vs_contract": weakened,
        "validator_forbidden_fields": list(COMPUTED_FORBIDDEN),
        "yaml_parse_error": yaml_error,
        "check_name": "accepted_design_contracts_present_and_verified",
    }
