"""Source-stratified OOD with persisted identity. Test scoring happens only after freeze."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v0211.policy import (
    FEATURE_ORDER,
    LANDMARK_DIR,
    MODELS_DIR,
    OOD_MAX_VAL_FPR,
    RUNTIME_DIR,
    SEED,
    VERSION,
)


def _feats(r: dict[str, Any]) -> dict[str, float]:
    f = json.loads(r["features_json"])
    order = json.loads(r.get("feature_order_json") or "[]") or FEATURE_ORDER
    d = {order[i]: f[i] for i in range(min(len(order), len(f)))}
    dens = 1.0 - float(d.get("missingness_lab") or 0)
    return {
        "mask_proxy": dens,
        "n_obs_before": float(d.get("n_obs_before") or 0),
        "longitudinal_age_days": float(d.get("longitudinal_age_days") or 0),
        "days_since_last_event": float(d.get("days_since_last_event") or 0),
        "history_depth": float(r.get("history_depth") or d.get("n_obs_before") or 0),
    }


def _stratum(r: dict[str, Any]) -> str:
    f = _feats(r)
    miss = 0 if f["mask_proxy"] < 0.33 else (1 if f["mask_proxy"] < 0.66 else 2)
    hist = 0 if f["history_depth"] < 2 else (1 if f["history_depth"] < 8 else 2)
    return f"{r['source_system']}|m{miss}|h{hist}"


def _stratified(
    rows: list[dict[str, Any]],
    per_stratum: int,
    seed: int,
    *,
    expected_label: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    buckets: dict[str, list] = defaultdict(list)
    for r in rows:
        buckets[_stratum(r)].append(r)
    out = []
    accounting = {}
    for key in sorted(buckets):
        pool = sorted(buckets[key], key=lambda r: r["landmark_id"])
        rng.shuffle(pool)
        take = pool[:per_stratum]
        out.extend(take)
        accounting[key] = {
            "available": len(pool),
            "expected": min(per_stratum, len(pool)),
            "actual": len(take),
        }
    assert all(a["expected"] == a["actual"] for a in accounting.values())
    return out, {
        "label": expected_label,
        "per_stratum": per_stratum,
        "n": len(out),
        "strata": accounting,
        "stratified_by": ["source_system", "missingness_tertile", "history_depth_tertile"],
    }


def check_ood_integrity(
    detector: dict[str, Any] | None,
    source_system: str,
    *,
    expected_file_sha256: str | None = None,
    expected_identity_sha256: str | None = None,
    file_sha256: str | None = None,
) -> dict[str, Any]:
    if not detector:
        return {"ok": False, "error": "MISSING_OOD_REFERENCE", "hard_fail": True}
    ident = detector_identity_sha256(detector)
    stored = detector.get("detector_identity_sha256")
    if expected_identity_sha256 and ident != expected_identity_sha256:
        return {"ok": False, "error": "OOD_IDENTITY_MISMATCH", "hard_fail": True}
    if stored and ident != stored:
        return {"ok": False, "error": "OOD_IDENTITY_MISMATCH", "hard_fail": True}
    if expected_file_sha256 and file_sha256 and expected_file_sha256 != file_sha256:
        return {"ok": False, "error": "OOD_FILE_HASH_MISMATCH", "hard_fail": True}
    if detector.get("version") and detector.get("version") != VERSION:
        return {"ok": False, "error": "OOD_VERSION_INCOMPATIBLE", "hard_fail": True}
    label = "A" if source_system == "magerya_api" else "B"
    ref = (detector.get("ref") or {}).get(label)
    if not ref or not ref.get("ranges"):
        return {"ok": False, "error": "MISSING_SOURCE_SPECIFIC_OOD_STRATUM", "hard_fail": True}
    return {"ok": True, "identity_sha256": ident, "source": label}


def detector_identity_sha256(detector: dict[str, Any]) -> str:
    body = {
        "ref": detector.get("ref"),
        "features": detector.get("features"),
        "feature_order": detector.get("feature_order"),
        "version": detector.get("version"),
        "method": detector.get("method"),
    }
    return hashlib.sha256(
        json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def fit_ood_pretest(root: Path, parquet_name: str) -> dict[str, Any]:
    """Train-fit + validation FPR only. Does not open test."""
    root = Path(root).resolve()
    path = root / LANDMARK_DIR / parquet_name
    rows = pq.read_table(path).to_pylist() if path.is_file() else []
    train = [r for r in rows if r["split_role"] == "train"]
    val = [r for r in rows if r["split_role"] == "validation"]
    ref = {}
    train_sample, train_acc = _stratified(train, 40, SEED, expected_label="train_reference")
    by_src: dict[str, list] = defaultdict(list)
    for r in train_sample:
        by_src[r["source_system"]].append(r)
    for ss, label in (("magerya_api", "A"), ("kgz_raw", "B")):
        fs = [_feats(r) for r in by_src.get(ss, [])]
        if not fs:
            ref[label] = {"n": 0, "ranges": {}, "source_system": ss}
            continue
        ranges = {}
        for k in fs[0]:
            vals = [f[k] for f in fs]
            lo, hi = min(vals), max(vals)
            pad = 0.05 * (hi - lo if hi > lo else 1.0)
            ranges[k] = {"lo": lo - pad, "hi": hi + pad}
        ref[label] = {"n": len(fs), "ranges": ranges, "source_system": ss}

    def score(r):
        label = "A" if r["source_system"] == "magerya_api" else "B"
        f = _feats(r)
        reasons = []
        if f["history_depth"] < 1:
            reasons.append("insufficient_history")
        for k, rng in (ref[label].get("ranges") or {}).items():
            if f[k] < rng["lo"] or f[k] > rng["hi"]:
                reasons.append(f"feature_range:{k}")
        return {"in_support": len(reasons) == 0, "reasons": reasons, "source": label}

    val_sample, val_acc = _stratified(val, 25, SEED + 2, expected_label="validation_calibration")
    cal = [score(r) for r in val_sample]
    fpr = sum(1 for s in cal if not s["in_support"]) / max(len(cal), 1)
    detector = {
        "ref": ref,
        "features": "raw_source_aware",
        "feature_order": list(FEATURE_ORDER),
        "version": VERSION,
        "method": "source_stratified_range_detector",
        "CLINICAL_SAFETY": False,
        "not_safety_boundary": True,
    }
    ident = detector_identity_sha256(detector)
    detector["detector_identity_sha256"] = ident
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    path_det = root / MODELS_DIR / "ood-reference.json"
    path_det.write_text(json.dumps(detector, indent=2) + "\n", encoding="utf-8")
    file_sha = hashlib.sha256(path_det.read_bytes()).hexdigest()
    detector["file_sha256"] = file_sha
    path_det.write_text(json.dumps(detector, indent=2) + "\n", encoding="utf-8")
    file_sha = hashlib.sha256(path_det.read_bytes()).hexdigest()
    (root / MODELS_DIR / "ood-sampling-manifest.json").write_text(
        json.dumps(
            {
                "train": {**train_acc, "opaque_landmark_ids": [r["landmark_id"] for r in train_sample]},
                "validation": {
                    **val_acc,
                    "opaque_landmark_ids": [r["landmark_id"] for r in val_sample],
                },
                "test": {"opened": False},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    foundation = (
        "NOT_ACCEPTED_HIGH_FALSE_POSITIVE_RATE"
        if fpr > OOD_MAX_VAL_FPR
        else "TECHNICAL_EVALUATED"
    )
    doc = {
        "version": VERSION,
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": "TECHNICAL_EVALUATED",
        "APPLICABILITY_FOUNDATION_STATUS": foundation,
        "OOD_ARTIFACT_INTEGRITY_STATUS": "FROZEN",
        "not_safety_boundary": True,
        "validation_calibration_fpr": fpr,
        "ood_max_val_fpr_gate": OOD_MAX_VAL_FPR,
        "fpr_gate_passed": fpr <= OOD_MAX_VAL_FPR,
        "detector_identity_sha256": ident,
        "file_sha256": file_sha,
        "test_opened": False,
        "ok": True,
    }
    (root / RUNTIME_DIR / "applicability-ood.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc


def score_test_ood(root: Path, parquet_name: str) -> dict[str, Any]:
    root = Path(root).resolve()
    path_det = root / MODELS_DIR / "ood-reference.json"
    if not path_det.is_file():
        return {"ok": False, "error": "MISSING_OOD_REFERENCE"}
    detector = json.loads(path_det.read_text(encoding="utf-8"))
    file_sha = hashlib.sha256(path_det.read_bytes()).hexdigest()
    ident = detector_identity_sha256(detector)
    stored_ident = detector.get("detector_identity_sha256")
    if stored_ident and ident != stored_ident:
        return {"ok": False, "error": "OOD_IDENTITY_MISMATCH"}
    rows = pq.read_table(root / LANDMARK_DIR / parquet_name).to_pylist()
    test = [r for r in rows if r["split_role"] == "test"]
    test_sample, test_acc = _stratified(test, 30, SEED + 9, expected_label="test_after_freeze")

    def score(r):
        label = "A" if r["source_system"] == "magerya_api" else "B"
        if not (detector.get("ref") or {}).get(label):
            return {"in_support": False, "reasons": ["missing_source_stratum"]}
        f = _feats(r)
        reasons = []
        if f["history_depth"] < 1:
            reasons.append("insufficient_history")
        for k, rng in ((detector["ref"][label].get("ranges")) or {}).items():
            if f[k] < rng["lo"] or f[k] > rng["hi"]:
                reasons.append(f"feature_range:{k}")
        return {"in_support": len(reasons) == 0, "reasons": reasons}

    scored = [score(r) for r in test_sample]
    man_path = root / MODELS_DIR / "ood-sampling-manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.is_file() else {}
    man["test"] = {
        **test_acc,
        "opaque_landmark_ids": [r["landmark_id"] for r in test_sample],
        "opened": True,
    }
    man_path.write_text(json.dumps(man, indent=2) + "\n", encoding="utf-8")
    pretest = json.loads((root / RUNTIME_DIR / "applicability-ood.json").read_text(encoding="utf-8"))
    pretest["test_n_scored"] = len(scored)
    pretest["test_ood_fraction"] = sum(1 for s in scored if not s["in_support"]) / max(len(scored), 1)
    pretest["test_opened"] = True
    pretest["file_sha256_after_test_detector"] = file_sha
    (root / RUNTIME_DIR / "applicability-ood.json").write_text(
        json.dumps(pretest, indent=2) + "\n", encoding="utf-8"
    )
    return pretest
