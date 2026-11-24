"""Pack and verify aggregate-only upstream evidence snapshots."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.intervention_response_readiness_v01.hashes import sha256_bytes, sha256_file
from human_simulator.intervention_response_readiness_v011.policy import (
    ARTIFACT_DIR,
    BUNDLE_MEMBER_BOOKKEEPING_KEYS,
    EVIDENCE_CATALOG,
    SNAPSHOT_DIRNAME,
    VERSION,
)


class SnapshotError(RuntimeError):
    pass


def artifact_dir(root: Path) -> Path:
    return root / ARTIFACT_DIR


def manifest_path(root: Path) -> Path:
    return artifact_dir(root) / "upstream-evidence-manifest.json"


def snapshot_dir(root: Path) -> Path:
    return artifact_dir(root) / SNAPSHOT_DIRNAME


def _sha_file(path: Path) -> str:
    return sha256_file(path)


def _json_keys_diverged(left: bytes, right: bytes) -> list[str] | None:
    try:
        a = json.loads(left)
        b = json.loads(right)
    except json.JSONDecodeError:
        return None
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    keys = sorted(set(a) | set(b))
    return [key for key in keys if a.get(key) != b.get(key)]


def _bundle_member(root: Path, bundle_name: str, member: str) -> tuple[bytes | None, str | None, str]:
    path = root / "artifacts" / "external-review" / bundle_name
    if not path.is_file():
        return None, None, "NOT_RUN_BUNDLE_NOT_IN_TREE"
    digest = _sha_file(path)
    with zipfile.ZipFile(path) as zf:
        try:
            payload = zf.read(member)
        except KeyError:
            return None, digest, "BUNDLE_MEMBER_MISSING"
    return payload, digest, "PRESENT"


def build_snapshots(root: Path, *, catalog: tuple[dict[str, str], ...] | None = None) -> dict[str, Any]:
    """Copy canonical source bytes into the stage snapshot directory.

    Does not reserialize JSON. Snapshot bytes are the source bytes.
    """
    root = root.resolve()
    catalog = catalog or EVIDENCE_CATALOG
    dest_dir = snapshot_dir(root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for spec in catalog:
        rel = spec["canonical_source_path"]
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise SnapshotError(f"substituted evidence path: {rel}")
        source = root / rel
        if not source.is_file():
            raise SnapshotError(f"canonical source missing: {rel}")
        if source.suffix.lower() == ".parquet":
            raise SnapshotError("parquet evidence is forbidden")
        source_bytes = source.read_bytes()
        source_sha = sha256_bytes(source_bytes)
        member, bundle_sha, bundle_state = _bundle_member(root, spec["originating_bundle_name"], rel)
        expected_bundle = spec["originating_bundle_sha256"]
        divergence: list[str] = []
        member_sha = None
        equal_member = False
        if bundle_state == "PRESENT":
            if bundle_sha != expected_bundle:
                raise SnapshotError(f"originating bundle sha mismatch: {spec['originating_bundle_name']}")
            member_sha = sha256_bytes(member or b"")
            equal_member = member == source_bytes
            if not equal_member:
                divergence = _json_keys_diverged(source_bytes, member or b"") or ["NON_JSON_OR_UNEQUAL"]
                allowed = BUNDLE_MEMBER_BOOKKEEPING_KEYS.get(spec["key"], frozenset())
                if not divergence or any(key not in allowed for key in divergence):
                    raise SnapshotError(
                        f"scientific bytes diverged from originating bundle for {spec['key']}: {divergence}"
                    )
        elif bundle_state == "BUNDLE_MEMBER_MISSING":
            raise SnapshotError(f"bundle member missing: {rel}")
        else:
            raise SnapshotError(f"originating bundle unavailable while building snapshots: {spec['key']}")
        snap_rel = f"{SNAPSHOT_DIRNAME}/{spec['key']}.json"
        snap_path = artifact_dir(root) / snap_rel
        snap_path.write_bytes(source_bytes)
        if sha256_bytes(snap_path.read_bytes()) != source_sha:
            raise SnapshotError(f"snapshot write mismatch: {spec['key']}")
        entries.append(
            {
                "key": spec["key"],
                "canonical_source_path": rel,
                "source_sha256": source_sha,
                "originating_bundle_name": spec["originating_bundle_name"],
                "originating_bundle_sha256": expected_bundle,
                "originating_bundle_member_sha256": member_sha,
                "source_bytes_equal_originating_bundle_member": equal_member,
                "bundle_member_divergence_keys": divergence,
                "evidence_role": spec["evidence_role"],
                "privacy_classification": spec["privacy_classification"],
                "snapshot_relpath": snap_rel,
                "snapshot_sha256": source_sha,
                "source_bytes_equal_snapshot": True,
            }
        )
    document = {
        "version": VERSION,
        "snapshot_count": len(entries),
        "expected_count": len(catalog),
        "built_with_originating_bundles_present": True,
        "patient_rows_included": False,
        "parquet_included": False,
        "raw_db_exports_included": False,
        "snapshots": entries,
    }
    manifest_path(root).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def verify_snapshots(root: Path, *, catalog: tuple[dict[str, str], ...] | None = None) -> dict[str, Any]:
    root = root.resolve()
    catalog = catalog or EVIDENCE_CATALOG
    catalog_by_key = {item["key"]: item for item in catalog}
    path = manifest_path(root)
    problems: list[dict[str, str]] = []
    if not path.is_file():
        return _verification(False, problems + [{"key": "*", "reason": "MANIFEST_MISSING"}], 0, catalog)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _verification(False, [{"key": "*", "reason": "MANIFEST_NOT_JSON"}], 0, catalog)
    entries = manifest.get("snapshots") or []
    if not isinstance(entries, list):
        problems.append({"key": "*", "reason": "MANIFEST_SNAPSHOTS_NOT_A_LIST"})
        entries = []
    seen: set[str] = set()
    checked = 0
    bundle_recheck = "NOT_RUN_BUNDLE_NOT_IN_TREE"
    bundles_seen = False
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append({"key": "?", "reason": "ENTRY_NOT_OBJECT"})
            continue
        key = str(entry.get("key") or "")
        spec = catalog_by_key.get(key)
        if spec is None:
            problems.append({"key": key, "reason": "UNKNOWN_EVIDENCE_KEY"})
            continue
        seen.add(key)
        canonical = str(entry.get("canonical_source_path") or "")
        if canonical != spec["canonical_source_path"] or ".." in Path(canonical).parts or Path(canonical).is_absolute():
            problems.append({"key": key, "reason": "SUBSTITUTED_EVIDENCE_PATH"})
        if entry.get("originating_bundle_name") != spec["originating_bundle_name"]:
            problems.append({"key": key, "reason": "SUBSTITUTED_ORIGINATING_BUNDLE"})
        if entry.get("originating_bundle_sha256") != spec["originating_bundle_sha256"]:
            problems.append({"key": key, "reason": "ORIGINATING_BUNDLE_SHA_MISMATCH"})
        if entry.get("evidence_role") != spec["evidence_role"]:
            problems.append({"key": key, "reason": "EVIDENCE_ROLE_MISMATCH"})
        if entry.get("privacy_classification") != spec["privacy_classification"]:
            problems.append({"key": key, "reason": "PRIVACY_CLASSIFICATION_MISMATCH"})
        snap_rel = str(entry.get("snapshot_relpath") or "")
        expected_rel = f"{SNAPSHOT_DIRNAME}/{key}.json"
        if snap_rel != expected_rel or ".." in Path(snap_rel).parts:
            problems.append({"key": key, "reason": "SUBSTITUTED_SNAPSHOT_PATH"})
            continue
        snap = artifact_dir(root) / snap_rel
        if not snap.is_file():
            problems.append({"key": key, "reason": "SNAPSHOT_DELETED"})
            continue
        payload = snap.read_bytes()
        digest = sha256_bytes(payload)
        source_sha = str(entry.get("source_sha256") or "")
        snap_sha = str(entry.get("snapshot_sha256") or "")
        if digest != snap_sha or digest != source_sha or snap_sha != source_sha:
            problems.append({"key": key, "reason": "SNAPSHOT_HASH_MISMATCH"})
        if entry.get("source_bytes_equal_snapshot") is not True:
            problems.append({"key": key, "reason": "SOURCE_SNAPSHOT_EQUALITY_NOT_RECORDED"})
        checked += 1
        canonical_path = root / canonical
        if canonical_path.is_file() and sha256_bytes(canonical_path.read_bytes()) != source_sha:
            problems.append({"key": key, "reason": "CANONICAL_SOURCE_HASH_MISMATCH"})
        member, bundle_sha, state = _bundle_member(root, spec["originating_bundle_name"], canonical)
        if state == "PRESENT":
            bundles_seen = True
            if bundle_sha != spec["originating_bundle_sha256"]:
                problems.append({"key": key, "reason": "ORIGINATING_BUNDLE_FILE_HASH_MISMATCH"})
            if sha256_bytes(member or b"") != entry.get("originating_bundle_member_sha256"):
                problems.append({"key": key, "reason": "BUNDLE_MEMBER_HASH_MISMATCH"})
        elif state == "BUNDLE_MEMBER_MISSING":
            problems.append({"key": key, "reason": "BUNDLE_MEMBER_MISSING"})
    if bundles_seen:
        bundle_recheck = "CHECKED_PUBLISHER_WORKSPACE"
    missing_keys = sorted(set(catalog_by_key) - seen)
    for key in missing_keys:
        problems.append({"key": key, "reason": "CATALOG_ENTRY_ABSENT"})
    extra = sorted(seen - set(catalog_by_key))
    for key in extra:
        problems.append({"key": key, "reason": "EXTRA_SNAPSHOT"})
    ok = not problems and checked == len(catalog) and len(entries) == len(catalog)
    result = _verification(ok, problems, checked, catalog)
    result["originating_bundle_recheck"] = bundle_recheck
    result["originating_bundle_recheck_note"] = (
        "Bundle file bytes are rehashed only when the originating ZIP is in this tree. "
        "A clean extraction does not carry those ZIPs; snapshot equality is checked against the manifest."
    )
    return result


def _verification(ok: bool, problems: list[dict[str, str]], checked: int, catalog: tuple[dict[str, str], ...]) -> dict[str, Any]:
    by_key = {spec["key"]: spec["canonical_source_path"] for spec in catalog}
    reasons = {
        "SNAPSHOT_DELETED",
        "MANIFEST_MISSING",
        "CATALOG_ENTRY_ABSENT",
        "SNAPSHOT_HASH_MISMATCH",
        "CANONICAL_SOURCE_HASH_MISMATCH",
        "SUBSTITUTED_EVIDENCE_PATH",
    }
    if any(item.get("reason") == "MANIFEST_MISSING" for item in problems):
        missing = [spec["canonical_source_path"] for spec in catalog]
    else:
        missing = []
        for item in problems:
            if item.get("reason") not in reasons:
                continue
            path = by_key.get(str(item.get("key") or ""))
            if path and path not in missing:
                missing.append(path)
    return {
        "ok": ok,
        "UPSTREAM_EVIDENCE_SNAPSHOT_STATUS": "PASS" if ok else "FAIL",
        "snapshot_count": checked,
        "expected_count": len(catalog),
        "snapshot_count_label": f"{checked}/{len(catalog)}",
        "problems": problems,
        "evidence_files_missing": missing,
        "version": VERSION,
    }


def load_snapshot_documents(root: Path, verification: dict[str, Any]) -> dict[str, Any]:
    """Load snapshot JSON only after verification. Missing docs are marked, not invented."""
    loaded: dict[str, Any] = {}
    if not verification.get("ok"):
        for spec in EVIDENCE_CATALOG:
            loaded[spec["key"]] = {"_missing": True, "path": spec["canonical_source_path"], "_verified": False}
        return loaded
    manifest = json.loads(manifest_path(root).read_text(encoding="utf-8"))
    for entry in manifest["snapshots"]:
        snap = artifact_dir(root) / entry["snapshot_relpath"]
        document = json.loads(snap.read_text(encoding="utf-8"))
        if isinstance(document, dict):
            document = dict(document)
            document["_source_key"] = entry["key"]
            document["_verified"] = True
            document["_source_sha256"] = entry["source_sha256"]
        loaded[entry["key"]] = document
    return loaded
