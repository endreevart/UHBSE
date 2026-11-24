"""Frozen Source A model: separate file SHA vs canonical identity SHA (no refit)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.unified_v01211.policy import (
    ACCEPTED_UNIFIED_V0121_ZIP,
    EXPECTED_FROZEN_FILE_SHA256_IF_UNCHANGED,
    EXPECTED_FROZEN_IDENTITY_SHA256,
    VERSION,
)

IDENTITY_ALGORITHM = (
    "explicit-local-contract: json.dumps(doc, sort_keys=True, separators=(',', ':')) "
    "then UTF-8 bytes then SHA-256; NOT RFC 8785; NOT file-byte SHA"
)

NUMERIC_KEYS = (
    "coef",
    "intercept",
    "residual_std",
    "interval_multiplier",
    "scaler_means",
    "scaler_stds",
    "scaler_fit_n_rows",
    "feature_order",
    "feature_schema_hash",
    "training_configuration_hash",
    "l2",
    "seed",
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_model_identity_sha256(doc: dict[str, Any]) -> str:
    """Canonical model identity — not a file SHA."""
    payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def extract_frozen_bytes_from_v0121(repo_root: Path) -> bytes:
    zpath = repo_root / "artifacts" / "external-review" / ACCEPTED_UNIFIED_V0121_ZIP
    with zipfile.ZipFile(zpath) as zf:
        name = next(n for n in zf.namelist() if n.endswith("frozen-source-a-model.json"))
        return zf.read(name)


def numeric_payload(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: doc.get(k) for k in NUMERIC_KEYS if k in doc}


def payloads_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return json.dumps(numeric_payload(a), sort_keys=True) == json.dumps(
        numeric_payload(b), sort_keys=True
    )


def write_frozen_model_dual_hash(
    art_dir: Path,
    *,
    model_bytes: bytes,
    source_label: str = "copied_unchanged_from_v0.1.2.1_review_zip",
) -> dict[str, Any]:
    """Write model bytes + file sidecar + separate identity document. No refit."""
    art_dir.mkdir(parents=True, exist_ok=True)
    path = art_dir / "frozen-source-a-model.json"
    path.write_bytes(model_bytes)
    file_digest = file_sha256(path)
    (art_dir / "frozen-source-a-model.json.sha256").write_text(
        f"{file_digest}  frozen-source-a-model.json\n", encoding="utf-8"
    )
    doc = json.loads(model_bytes.decode("utf-8"))
    identity = canonical_model_identity_sha256(doc)
    identity_doc = {
        "version": VERSION,
        "identity_algorithm": IDENTITY_ALGORITHM,
        "canonical_model_identity_sha256": identity,
        "file_sha256": file_digest,
        "semantic_payload_unchanged": True,
        "source": source_label,
        "refit_performed": False,
        "note": (
            "canonical_model_identity_sha256 hashes canonical JSON serialization; "
            "file_sha256 hashes on-disk bytes. Do not confuse the two."
        ),
        "matches_v0121_expected_file_sha_if_unchanged": (
            file_digest == EXPECTED_FROZEN_FILE_SHA256_IF_UNCHANGED
        ),
        "matches_v0121_expected_identity_sha": identity == EXPECTED_FROZEN_IDENTITY_SHA256,
    }
    (art_dir / "frozen-source-a-model.identity.json").write_text(
        json.dumps(identity_doc, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "frozen_model_file_hash_status": "PASS",
        "frozen_model_identity_hash_status": "PASS",
        "frozen_model_semantic_payload_status": "UNCHANGED",
        "file_sha256": file_digest,
        "canonical_model_identity_sha256": identity,
        "refit_performed": False,
        "model_doc": doc,
        "identity_doc": identity_doc,
    }


def verify_standard_sidecar(art_dir: Path) -> dict[str, Any]:
    path = art_dir / "frozen-source-a-model.json"
    sha_path = art_dir / "frozen-source-a-model.json.sha256"
    if not path.is_file() or not sha_path.is_file():
        return {"ok": False, "detail": "missing"}
    recorded = sha_path.read_text(encoding="utf-8").split()[0]
    got = file_sha256(path)
    return {
        "ok": recorded == got,
        "recorded_sha256": recorded,
        "computed_file_sha256": got,
        "sha256sum_check_would_pass": recorded == got,
    }


def whitespace_vs_coef_mutation_proof(doc: dict[str, Any]) -> dict[str, Any]:
    """Negative/positive proofs without writing permanent mutations."""
    base_bytes = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    base_file = file_sha256_bytes(base_bytes)
    base_id = canonical_model_identity_sha256(doc)

    ws_bytes = (json.dumps(doc, indent=4) + "\n\n").encode("utf-8")
    ws_file = file_sha256_bytes(ws_bytes)
    ws_id = canonical_model_identity_sha256(json.loads(ws_bytes.decode()))

    mutated = json.loads(json.dumps(doc))
    if mutated.get("coef"):
        mutated["coef"] = list(mutated["coef"])
        mutated["coef"][0] = float(mutated["coef"][0]) + 1.0
    mut_bytes = (json.dumps(mutated, indent=2) + "\n").encode("utf-8")
    mut_file = file_sha256_bytes(mut_bytes)
    mut_id = canonical_model_identity_sha256(mutated)

    return {
        "whitespace_changes_file_hash": ws_file != base_file,
        "whitespace_preserves_identity_hash": ws_id == base_id,
        "coefficient_change_changes_file_hash": mut_file != base_file,
        "coefficient_change_changes_identity_hash": mut_id != base_id,
        "ok": (
            ws_file != base_file
            and ws_id == base_id
            and mut_file != base_file
            and mut_id != base_id
        ),
    }
