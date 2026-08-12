"""Where the relationship manifest drift came from, established from evidence.

The manifest records a hash for eight artifacts. Two of them no longer match. The tempting
repair — recompute the manifest over whatever is on disk — would convert an unexplained
difference into a signed statement that the current bytes are correct, which is exactly the
claim that has not been established. So provenance is established first:

1. hash the eight artifacts and the manifest as they are;
2. find every copy of each artifact in every published review bundle, and hash those too;
3. reproduce the assessment read-only in a throwaway workspace;
4. compare bodies with the volatile fields removed, so a difference in a verdict, an aggregate,
   a denominator or a conflict definition is distinguishable from a difference in a timestamp.

Only after all four does a repair have a defensible basis. Nothing here writes into
``artifacts/stage-02/``.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
)
from human_simulator.stage02_maintenance.constants import (
    EXTERNAL_REVIEW_DIR,
    SEMANTIC_FIELDS,
    STAGE_02_DIR,
    VOLATILE_FIELDS,
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


@dataclass(frozen=True)
class BundleCopy:
    """One published copy of one relationship artifact."""

    bundle: str
    member: str
    sha256: str
    assessed_at: str | None


@dataclass(frozen=True)
class ArtifactDrift:
    name: str
    current_sha256: str
    manifest_sha256: str | None
    matches_manifest: bool
    published_copies: tuple[BundleCopy, ...] = ()
    current_bytes_published_in: tuple[str, ...] = ()
    manifest_bytes_published_in: tuple[str, ...] = ()

    @property
    def manifest_bytes_are_unattested(self) -> bool:
        """Does any published release carry the bytes the manifest expects?"""
        return not self.manifest_bytes_published_in

    def document(self) -> dict[str, Any]:
        return {
            "artifact": self.name,
            "current_sha256": self.current_sha256,
            "manifest_records_sha256": self.manifest_sha256,
            "matches_manifest": self.matches_manifest,
            "distinct_published_hashes": len({copy.sha256 for copy in self.published_copies}),
            "current_bytes_published_in": list(self.current_bytes_published_in),
            "manifest_bytes_published_in": list(self.manifest_bytes_published_in),
            "manifest_bytes_are_unattested": self.manifest_bytes_are_unattested,
            "published_copies": [
                {
                    "bundle": copy.bundle,
                    "member": copy.member,
                    "sha256": copy.sha256,
                    "assessed_at": copy.assessed_at,
                }
                for copy in self.published_copies
            ],
        }


def read_manifest(repo_root: Path) -> dict[str, str]:
    """The hashes the manifest records, by artifact name. Never rewritten."""
    path = repo_root / STAGE_02_DIR / MANIFEST_NAME
    if not path.is_file():
        return {}
    recorded: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            recorded[parts[1].strip()] = parts[0]
    return recorded


def _assessed_at(payload: bytes, name: str) -> str | None:
    if not name.endswith(".json"):
        return None
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return document.get("assessed_at") if isinstance(document, dict) else None


def collect_published_copies(repo_root: Path) -> dict[str, list[BundleCopy]]:
    """Every copy of every relationship artifact in every published review bundle.

    Bundles are the only durable record of what an accepted release actually contained, so they
    are the evidence base for deciding which bytes are authoritative.
    """
    copies: dict[str, list[BundleCopy]] = {name: [] for name in RELATIONSHIP_MANIFEST_ARTIFACTS}
    copies[MANIFEST_NAME] = []
    wanted = set(copies)

    directory = repo_root / EXTERNAL_REVIEW_DIR
    if not directory.is_dir():
        return copies

    for archive in sorted(directory.glob("*.zip")):
        try:
            bundle = zipfile.ZipFile(archive)
        except zipfile.BadZipFile:
            continue
        for member in bundle.namelist():
            base = Path(member).name
            if base not in wanted or "/stage-02/" not in member:
                continue
            payload = bundle.read(member)
            copies[base].append(
                BundleCopy(
                    bundle=archive.name,
                    member=member,
                    sha256=sha256_bytes(payload),
                    assessed_at=_assessed_at(payload, base),
                )
            )
    return copies


def evaluate_drift(repo_root: Path) -> list[ArtifactDrift]:
    """Per-artifact drift, with the published provenance of both the current and expected bytes."""
    recorded = read_manifest(repo_root)
    published = collect_published_copies(repo_root)
    directory = repo_root / STAGE_02_DIR

    results: list[ArtifactDrift] = []
    for name in RELATIONSHIP_MANIFEST_ARTIFACTS:
        path = directory / name
        current = sha256_file(path) if path.is_file() else ""
        expected = recorded.get(name)
        copies = tuple(published.get(name, ()))
        results.append(
            ArtifactDrift(
                name=name,
                current_sha256=current,
                manifest_sha256=expected,
                matches_manifest=bool(expected) and expected == current,
                published_copies=copies,
                current_bytes_published_in=tuple(
                    sorted({copy.bundle for copy in copies if copy.sha256 == current})
                ),
                manifest_bytes_published_in=tuple(
                    sorted({copy.bundle for copy in copies if expected and copy.sha256 == expected})
                ),
            )
        )
    return results


# ---------------------------------------------------------------------------------------
# Semantic comparison
# ---------------------------------------------------------------------------------------


def strip_volatile(document: Any) -> Any:
    """The document without the fields allowed to move between runs."""
    if not isinstance(document, dict):
        return document
    return {key: value for key, value in document.items() if key not in VOLATILE_FIELDS}


def semantic_digest(payload: bytes) -> str | None:
    """A hash of the meaning: the document minus volatile fields, canonically serialised."""
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return sha256_bytes(
        json.dumps(strip_volatile(document), sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


@dataclass
class SemanticComparison:
    """Whether two byte-different copies of one artifact say the same thing."""

    artifact: str
    reference_label: str
    other_label: str
    bytes_identical: bool
    semantically_identical: bool
    volatile_differences: dict[str, list[Any]] = field(default_factory=dict)
    semantic_differences: list[str] = field(default_factory=list)
    compared_fields: tuple[str, ...] = ()

    def document(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "reference": self.reference_label,
            "other": self.other_label,
            "bytes_identical": self.bytes_identical,
            "semantically_identical": self.semantically_identical,
            "volatile_differences": self.volatile_differences,
            "semantic_differences": self.semantic_differences,
            "compared_fields": list(self.compared_fields),
        }


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            flat.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flat.update(_flatten(item, f"{prefix}[{index}]"))
    else:
        flat[prefix] = value
    return flat


MARKDOWN_TIMESTAMP = re.compile(r"^Assessed at:\s*(\S+)\s*$", re.MULTILINE)


def timestamp_split(repo_root: Path, artifact: str) -> dict[str, Any]:
    """Compare a JSON artifact's ``assessed_at`` with the one its markdown sibling reports.

    A regeneration writes both at once, so they agree. A targeted restore of one file leaves
    them disagreeing, which is what distinguishes the two explanations for the drift.
    """
    directory = repo_root / STAGE_02_DIR
    json_path = directory / artifact
    markdown_path = directory / f"{Path(artifact).stem}.md"

    json_stamp: str | None = None
    if json_path.is_file():
        try:
            document = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            document = {}
        json_stamp = document.get("assessed_at") if isinstance(document, dict) else None

    markdown_stamp: str | None = None
    if markdown_path.is_file():
        match = MARKDOWN_TIMESTAMP.search(markdown_path.read_text(encoding="utf-8"))
        markdown_stamp = match.group(1) if match else None

    return {
        "json_artifact": artifact,
        "markdown_artifact": markdown_path.name,
        "json_assessed_at": json_stamp,
        "markdown_assessed_at": markdown_stamp,
        "siblings_disagree": bool(json_stamp and markdown_stamp and json_stamp != markdown_stamp),
    }


def compare_semantics(
    artifact: str,
    reference: bytes,
    other: bytes,
    *,
    reference_label: str,
    other_label: str,
) -> SemanticComparison:
    """Compare two copies field by field, separating volatile drift from meaning."""
    identical = reference == other
    if not artifact.endswith(".json"):
        return SemanticComparison(
            artifact=artifact,
            reference_label=reference_label,
            other_label=other_label,
            bytes_identical=identical,
            semantically_identical=identical,
            semantic_differences=[] if identical else ["non-JSON artifact differs byte for byte"],
        )

    left = json.loads(reference)
    right = json.loads(other)

    volatile: dict[str, list[Any]] = {
        name: [left.get(name), right.get(name)]
        for name in VOLATILE_FIELDS
        if left.get(name) != right.get(name)
    }

    flat_left = _flatten(strip_volatile(left))
    flat_right = _flatten(strip_volatile(right))
    differences = sorted(
        set(flat_left) ^ set(flat_right)
        | {key for key in set(flat_left) & set(flat_right) if flat_left[key] != flat_right[key]}
    )

    return SemanticComparison(
        artifact=artifact,
        reference_label=reference_label,
        other_label=other_label,
        bytes_identical=identical,
        semantically_identical=not differences,
        volatile_differences=volatile,
        semantic_differences=differences,
        compared_fields=SEMANTIC_FIELDS.get(artifact, tuple(sorted(strip_volatile(left)))),
    )
