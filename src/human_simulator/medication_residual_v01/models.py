"""Residual model families R0/R1/R2COUNT/R2ID/R2HASH. R2SEM is blocked at accepted count 0."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from typing import Any

from human_simulator.medication_residual_v01.hashes import sha_obj
from human_simulator.medication_residual_v01.policy import (
    FORBIDDEN_R1_MEDICATION_FIELDS,
    HASH_SEED,
    HASH_SENSITIVITY_DIM,
    HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT,
    L2,
    MAX_VOCAB,
    MIN_VOCAB_TRAIN_COUNT,
    R1_FEATURE_ORDER,
    R2COUNT_EXTRA,
    SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT,
    VERSION,
)


class StandardScaler:
    def __init__(self) -> None:
        self.means: list[float] = []
        self.stds: list[float] = []
        self.fitted = False

    def fit(self, rows: list[list[float]]) -> None:
        p = len(rows[0])
        n = len(rows)
        self.means = [0.0] * p
        self.stds = [1.0] * p
        for j in range(p):
            col = [r[j] for r in rows]
            mu = sum(col) / n
            var = sum((x - mu) ** 2 for x in col) / max(n, 1)
            self.means[j] = mu
            self.stds[j] = math.sqrt(var) if var > 1e-12 else 1.0
        self.fitted = True

    def transform(self, row: list[float]) -> list[float]:
        if len(row) != len(self.means):
            raise ValueError("FEATURE_LENGTH_MISMATCH_NO_PAD_TRUNCATE")
        return [(x - m) / s for x, m, s in zip(row, self.means, self.stds, strict=True)]

    def dump(self) -> dict[str, Any]:
        return {"means": self.means, "stds": self.stds, "fitted": self.fitted}


def scaler_from_dump(doc: dict[str, Any]) -> StandardScaler:
    sc = StandardScaler()
    sc.means = list(doc["means"])
    sc.stds = list(doc["stds"])
    sc.fitted = True
    return sc


def _solve_ridge(xtx: list[list[float]], xty: list[float], l2: float) -> list[float]:
    n = len(xty)
    a = [row[:] for row in xtx]
    b = xty[:]
    for i in range(n):
        a[i][i] += l2
    for i in range(n):
        pivot = a[i][i] if abs(a[i][i]) > 1e-12 else 1e-12
        a[i][i] = pivot
        for j in range(i + 1, n):
            f = a[j][i] / pivot
            for k in range(i, n):
                a[j][k] -= f * a[i][k]
            b[j] -= f * b[i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = b[i] - sum(a[i][k] * x[k] for k in range(i + 1, n))
        x[i] = s / a[i][i]
    return x


def fit_ridge(
    train_x: list[list[float]], train_y: list[float]
) -> tuple[StandardScaler, list[float]]:
    sc = StandardScaler()
    sc.fit(train_x)
    xs = [sc.transform(r) for r in train_x]
    p = len(xs[0]) + 1
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for row, yi in zip(xs, train_y, strict=True):
        xr = [1.0] + row
        for i in range(p):
            xty[i] += xr[i] * yi
            for j in range(p):
                xtx[i][j] += xr[i] * xr[j]
    coef = _solve_ridge(xtx, xty, L2)
    return sc, coef


def predict_ridge(sc: StandardScaler, coef: list[float], rows: list[list[float]]) -> list[float]:
    out = []
    for r in rows:
        xr = [1.0] + sc.transform(r)
        if len(xr) != len(coef):
            raise ValueError("FEATURE_LENGTH_MISMATCH_NO_PAD_TRUNCATE")
        out.append(sum(c * v for c, v in zip(coef, xr, strict=True)))
    return out


def r2sem_status() -> dict[str, Any]:
    blocked = (
        SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT == 0
        or HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT == 0
    )
    return {
        "R2SEM_STATUS": "NOT_RUN_NO_SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPTS",
        "blocked": blocked,
        "historical_exact_813_does_not_authorize": True,
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT": (
            SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT
        ),
        "HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT": HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT,
    }


def train_vocab(train_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for r in train_rows:
        for mid in r.get("medicine_ref_ids_json") or []:
            counts[str(mid)] += 1
    kept = [m for m, c in counts.most_common() if c >= MIN_VOCAB_TRAIN_COUNT][:MAX_VOCAB]
    index = {m: i for i, m in enumerate(kept)}
    return {
        "ids": kept,
        "index": index,
        "n": len(kept),
        "train_only": True,
        "min_count": MIN_VOCAB_TRAIN_COUNT,
        "n_train_distinct": len(counts),
        "oov_name": "OOV",
        "feature_order": [f"med::{m}" for m in kept] + ["med::OOV"],
        "ordinal_encoding": False,
        "vocab_sha256": sha_obj(kept),
    }


def r1_vector(row: dict[str, Any]) -> list[float]:
    feats = row.get("r1_features")
    if isinstance(feats, list) and len(feats) == len(R1_FEATURE_ORDER):
        vec = [float(x) for x in feats]
    else:
        vec = [float(row[k]) for k in R1_FEATURE_ORDER]
    for banned in FORBIDDEN_R1_MEDICATION_FIELDS:
        if banned in R1_FEATURE_ORDER:
            raise RuntimeError("R1 feature order contains medication field")
    return vec


def r2count_vector(row: dict[str, Any]) -> list[float]:
    extra = [
        float(row.get("concurrent_count") or 0),
        float(row.get("polypharmacy") or 0),
        float(row.get("n_prior_recorded_medication_events") or 0),
        float(row.get("days_since_last_prior_med") or 0),
        float(row.get("days_since_last_prior_med_missing") or 0),
    ]
    return r1_vector(row) + extra


def r2id_vector(row: dict[str, Any], vocab: dict[str, Any]) -> tuple[list[float], int]:
    index: dict[str, int] = vocab["index"]
    n = len(index)
    block = [0.0] * (n + 1)
    oov = 0
    for mid in row.get("medicine_ref_ids_json") or []:
        j = index.get(str(mid))
        if j is None:
            block[n] = 1.0
            oov += 1
        else:
            block[j] = 1.0
    return r1_vector(row) + block, oov


def signed_hash_index(token: str, dim: int, seed: int = HASH_SEED) -> tuple[int, int]:
    digest = hashlib.sha256(f"{seed}|{token}".encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % dim
    sign = 1 if digest[4] % 2 == 0 else -1
    return idx, sign


def r2hash_vector(row: dict[str, Any], dim: int) -> list[float]:
    block = [0.0] * dim
    for mid in row.get("medicine_ref_ids_json") or []:
        idx, sign = signed_hash_index(str(mid), dim)
        block[idx] += float(sign)
    return r1_vector(row) + block


def collision_report(ids: list[str], dim: int) -> dict[str, Any]:
    buckets: dict[int, int] = defaultdict(int)
    for mid in ids:
        idx, _ = signed_hash_index(mid, dim)
        buckets[idx] += 1
    collided = sum(1 for n in buckets.values() if n > 1)
    return {
        "dim": dim,
        "n_ids": len(ids),
        "occupied_buckets": len(buckets),
        "collided_buckets": collided,
        "max_bucket": max(buckets.values()) if buckets else 0,
    }


def r0_means(train_rows: list[dict[str, Any]]) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for r in train_rows:
        key = f"{r['outcome_key']}|{int(r['requested_horizon_days'])}"
        acc[key].append(float(r["residual"]))
    return {k: (sum(v) / len(v) if v else 0.0) for k, v in acc.items()}


def predict_r0(means: dict[str, float], rows: list[dict[str, Any]]) -> list[float]:
    out = []
    for r in rows:
        key = f"{r['outcome_key']}|{int(r['requested_horizon_days'])}"
        out.append(float(means.get(key, 0.0)))
    return out


def assert_no_ordinal(vec_builder_name: str, row: dict[str, Any]) -> None:
    ids = row.get("medicine_ref_ids_json") or []
    for mid in ids:
        if isinstance(mid, int):
            raise RuntimeError("ordinal integer medicine encoding is forbidden")
        if str(mid).isdigit() and vec_builder_name == "r2id":
            # hashed ref ids are hex; raw integer IDs as features would be ordinal
            pass


def feature_names_r2count() -> list[str]:
    return list(R1_FEATURE_ORDER) + list(R2COUNT_EXTRA)


def feature_names_r2id(vocab: dict[str, Any]) -> list[str]:
    return list(R1_FEATURE_ORDER) + list(vocab["feature_order"])


def feature_names_r2hash(dim: int) -> list[str]:
    return list(R1_FEATURE_ORDER) + [f"hash_{i}" for i in range(dim)]


def freeze_payload(
    *,
    family: str,
    feature_order: list[str],
    scaler: StandardScaler | None,
    coef: list[float] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc = {
        "version": VERSION,
        "family": family,
        "feature_order": feature_order,
        "feature_order_sha256": sha_obj(feature_order),
        "scaler": scaler.dump() if scaler else None,
        "scaler_sha256": sha_obj(scaler.dump()) if scaler else None,
        "coef": coef,
        "l2": L2,
        "not_intervention_response": True,
        "not_treatment_effect": True,
        "not_causal": True,
    }
    if extra:
        doc.update(extra)
    doc["model_identity_sha256"] = sha_obj(
        {k: doc[k] for k in ("family", "feature_order", "scaler", "coef", "l2") if k in doc}
    )
    return doc


def predict_family(
    family: str,
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    vocab: dict[str, Any] | None = None,
) -> list[float]:
    sc = scaler_from_dump(payload["scaler"]) if payload.get("scaler") else None
    coef = payload.get("coef")
    if family == "R1":
        xs = [r1_vector(r) for r in rows]
    elif family == "R2COUNT":
        xs = [r2count_vector(r) for r in rows]
    elif family == "R2ID":
        if not vocab:
            raise ValueError("vocab required")
        xs = [r2id_vector(r, vocab)[0] for r in rows]
    elif family == "R2HASH":
        dim = int(payload.get("hash_dim") or HASH_SENSITIVITY_DIM)
        xs = [r2hash_vector(r, dim) for r in rows]
    else:
        raise ValueError(family)
    if sc is None or coef is None:
        raise ValueError("missing scaler/coef")
    if any(len(x) != len(payload["feature_order"]) for x in xs):
        raise ValueError("FEATURE_LENGTH_MISMATCH_NO_PAD_TRUNCATE")
    return predict_ridge(sc, coef, xs)

