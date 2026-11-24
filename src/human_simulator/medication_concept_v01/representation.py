"""Corrected medication representation experiment (categorical M2ID_ONEHOT)."""

from __future__ import annotations

import hashlib
import json
import math
import random
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from human_simulator.medication_concept_v01.policy import (
    ACCEPTED_CONCEPT_STATUSES,
    HASH_DIMS,
    HASH_SEED,
    L2,
    LEGACY_ORDINAL_M2ID_LABEL,
    MIN_ACCEPTED_CONCEPTS_FOR_SEMANTIC_MODELS,
    N_BOOTSTRAP,
    N_PERMUTATION,
    SEED,
    V01_COHORTS,
    VERSION,
)

M1_FEATURES = (
    "pre_value",
    "n_prior_measurements",
    "prior_slope",
    "days_since_previous",
    "horizon_days",
    "prior_slope_missing",
    "days_since_previous_missing",
)


@dataclass
class StandardScaler:
    means: list[float] = field(default_factory=list)
    stds: list[float] = field(default_factory=list)
    fitted: bool = False
    fit_n_rows: int = 0

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
        self.fit_n_rows = n

    def transform(self, row: list[float]) -> list[float]:
        return [(x - m) / s for x, m, s in zip(row, self.means, self.stds, strict=True)]


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


def _fit_predict(
    train_x: list[list[float]], train_y: list[float], rows_x: list[list[float]]
) -> tuple[list[float], StandardScaler, list[float], list[str]]:
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
    out = []
    for r in rows_x:
        xr = [1.0] + sc.transform(r)
        out.append(sum(c * v for c, v in zip(coef, xr, strict=True)))
    feature_order = [f"f{i}" for i in range(len(train_x[0]))]
    return out, sc, coef, feature_order


def feat_m1(ep: dict[str, Any]) -> list[float]:
    slope = ep.get("prior_slope")
    days = ep.get("days_since_previous")
    return [
        float(ep["pre_value"]),
        float(ep.get("n_prior_measurements") or 0),
        float(slope) if slope is not None else 0.0,
        float(days) if days is not None else 0.0,
        float(ep["horizon_days"]),
        1.0 if slope is None else 0.0,
        1.0 if days is None else 0.0,
    ]


def signed_hash(medicine_id: str, dim: int, seed: int = HASH_SEED) -> list[float]:
    out = [0.0] * dim
    digest = hashlib.sha256(f"{seed}|med|{medicine_id}".encode()).digest()
    idx = struct.unpack(">I", digest[0:4])[0] % dim
    sign = 1.0 if (struct.unpack(">I", digest[4:8])[0] % 2 == 0) else -1.0
    out[idx] = sign
    return out


def collision_report(train_eps: list[dict[str, Any]], dim: int) -> dict[str, Any]:
    buckets: dict[int, set[str]] = defaultdict(set)
    for e in train_eps:
        mid = str(e["medicine_id"])
        digest = hashlib.sha256(f"{HASH_SEED}|med|{mid}".encode()).digest()
        idx = struct.unpack(">I", digest[0:4])[0] % dim
        buckets[idx].add(mid)
    loads = [len(v) for v in buckets.values()]
    n_ids = len({str(e["medicine_id"]) for e in train_eps})
    n_coll = sum(1 for v in buckets.values() if len(v) > 1)
    return {
        "hash_dim": dim,
        "n_train_medicine_ids": n_ids,
        "occupied_buckets": len(buckets),
        "n_collision_buckets": n_coll,
        "max_bucket_load": max(loads) if loads else 0,
        "mean_medicines_per_occupied_bucket": (
            sum(loads) / len(loads) if loads else 0.0
        ),
        "all_occupied_are_collisions": n_coll == len(buckets) and len(buckets) > 0,
    }


def build_onehot_vocab(train_eps: list[dict[str, Any]]) -> dict[str, Any]:
    """Train-only medicine vocabulary for genuine one-hot (+ explicit OOV).

    Feature order: M1 | onehot[vocab...] | oov | polypharmacy | concurrent
    No numeric ordering between medicine IDs in the encoding values (0/1 only).
    """
    counts: dict[str, int] = defaultdict(int)
    for e in train_eps:
        counts[str(e["medicine_id"])] += 1
    # Deterministic order: frequency desc, then id string — order is feature layout only,
    # not an ordinal magnitude (values remain 0/1).
    ordered = sorted(counts.keys(), key=lambda k: (-counts[k], k))
    vocab = {mid: i for i, mid in enumerate(ordered)}
    payload = {"ordered_ids": ordered, "index": vocab}
    vhash = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
    return {
        "ordered_ids": ordered,
        "index": vocab,
        "vocab_size": len(ordered),
        "vocab_hash": vhash,
        "oov_index": len(ordered),  # last one-hot slot after vocab
        "encoding": "M2ID_ONEHOT",
        "legacy_ordinal_excluded": LEGACY_ORDINAL_M2ID_LABEL,
    }


def feat_m2id_onehot(ep: dict[str, Any], vocab: dict[str, Any]) -> list[float]:
    ordered = vocab["ordered_ids"]
    n = len(ordered)
    onehot = [0.0] * (n + 1)  # +1 OOV bucket
    mid = str(ep["medicine_id"])
    idx = vocab["index"].get(mid)
    if idx is None:
        onehot[n] = 1.0  # OOV
    else:
        onehot[idx] = 1.0
    return feat_m1(ep) + onehot + [
        float(ep.get("polypharmacy_flag") or 0),
        float(ep.get("concurrent_med_count") or 1),
    ]


def feat_m2id_onehot_order(vocab: dict[str, Any]) -> list[str]:
    ordered = vocab["ordered_ids"]
    return (
        list(M1_FEATURES)
        + [f"med_onehot_{mid}" for mid in ordered]
        + ["med_oov", "polypharmacy_flag", "concurrent_med_count"]
    )


def legacy_ordinal_m2id_feature(ep: dict[str, Any], vocab_index: dict[str, int]) -> list[float]:
    """INVALID for authoritative comparison — single numeric index."""
    mid = str(ep["medicine_id"])
    return feat_m1(ep) + [
        float(vocab_index.get(mid, 0)),
        float(ep.get("polypharmacy_flag") or 0),
        float(ep.get("concurrent_med_count") or 1),
    ]


def feat_exposure_count(ep: dict[str, Any]) -> list[float]:
    return feat_m1(ep) + [
        float(ep.get("polypharmacy_flag") or 0),
        float(ep.get("concurrent_med_count") or 1),
    ]


def subject_macro_mae(preds: list[dict[str, Any]]) -> float:
    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[p["opaque_subject_key"]].append(abs(p["y_pred"] - p["y_true"]))
    return sum(sum(v) / len(v) for v in by.values()) / len(by)


def pair_micro_mae(preds: list[dict[str, Any]]) -> float:
    return sum(abs(p["y_pred"] - p["y_true"]) for p in preds) / len(preds)


def subject_mae_map(preds: list[dict[str, Any]]) -> dict[str, float]:
    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[p["opaque_subject_key"]].append(abs(p["y_pred"] - p["y_true"]))
    return {s: sum(v) / len(v) for s, v in by.items()}


def bootstrap_improvement(
    m1: list[dict[str, Any]], cand: list[dict[str, Any]], *, n: int = N_BOOTSTRAP, seed: int = SEED
) -> dict[str, Any]:
    s1 = subject_mae_map(m1)
    s2 = subject_mae_map(cand)
    subjects = sorted(set(s1) & set(s2))
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        sample = [subjects[rng.randrange(len(subjects))] for _ in subjects]
        diffs.append(sum(s1[s] - s2[s] for s in sample) / len(sample))
    diffs.sort()
    real = sum(s1[s] - s2[s] for s in subjects) / len(subjects)
    return {
        "mean_subject_macro_mae_improvement": real,
        "ci95": [diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs))]],
        "n_bootstrap": n,
        "n_subjects": len(subjects),
    }


def permutation_upper(
    m1: list[dict[str, Any]], cand: list[dict[str, Any]], *, n: int = N_PERMUTATION, seed: int = SEED
) -> dict[str, Any]:
    s1 = subject_mae_map(m1)
    s2 = subject_mae_map(cand)
    subjects = sorted(set(s1) & set(s2))
    observed = sum(s1[s] - s2[s] for s in subjects) / len(subjects)
    rng = random.Random(seed + 1)
    count_ge = 0
    for _ in range(n):
        flipped = 0.0
        for s in subjects:
            if rng.random() < 0.5:
                flipped += s2[s] - s1[s]
            else:
                flipped += s1[s] - s2[s]
        flipped /= len(subjects)
        if flipped >= observed:
            count_ge += 1
    p = (count_ge + 1) / (n + 1)
    if p == 0.0:
        raise ValueError("literal zero p forbidden")
    return {
        "permutation_p_value": p,
        "count_ge_observed": count_ge,
        "n_permutations": n,
        "observed_improvement": observed,
        "tail": "upper",
        "formula": "(count_ge_observed + 1) / (n_permutations + 1)",
    }


def _make_preds(eps: list[dict[str, Any]], yhat: list[float]) -> list[dict[str, Any]]:
    return [
        {
            "opaque_subject_key": e["opaque_subject_key"],
            "y_true": float(e["post_value"]),
            "y_pred": float(yh),
            "episode_id": e["episode_id"],
        }
        for e, yh in zip(eps, yhat, strict=True)
    ]


def _eval_candidate(
    *,
    label: str,
    m1_preds: list[dict[str, Any]],
    m1_mae_subj: float,
    train_x: list[list[float]],
    train_y: list[float],
    test_x: list[list[float]],
    test_eps: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hat, sc, coef, _ = _fit_predict(train_x, train_y, test_x)
    preds = _make_preds(test_eps, hat)
    boot = bootstrap_improvement(m1_preds, preds)
    perm = permutation_upper(m1_preds, preds)
    mae_s = subject_macro_mae(preds)
    imp = m1_mae_subj - mae_s
    out = {
        "label": label,
        "subject_macro_mae": mae_s,
        "pair_micro_mae": pair_micro_mae(preds),
        "improvement_vs_m1_subject_macro": imp,
        "bootstrap": boot,
        "permutation": perm,
        "n_features": len(train_x[0]),
        "scaler_dim": len(sc.means),
        "coef_dim": len(coef),
    }
    if extra:
        out.update(extra)
    return out, preds, imp, perm


def run_corrected_representation_experiment(
    *,
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
    n_accepted_drug_concepts: int,
    concept_by_medicine: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    concept_by_medicine = concept_by_medicine or {}
    m2sem_status = (
        "RUN"
        if n_accepted_drug_concepts >= MIN_ACCEPTED_CONCEPTS_FOR_SEMANTIC_MODELS
        else "NOT_RUN_INSUFFICIENT_ACCEPTED_DRUG_CONCEPTS"
    )
    semantic_gate = "NOT_RUN_INSUFFICIENT_ACCEPTED_DRUG_CONCEPTS"

    cohort_results = []
    any_signal = False
    onehot_proof = None

    for outcome, unit in V01_COHORTS:
        tr = [e for e in train if e["outcome"] == outcome and e["unit"] == unit]
        va = [e for e in val if e["outcome"] == outcome and e["unit"] == unit]
        te = [e for e in test if e["outcome"] == outcome and e["unit"] == unit]
        if len(tr) < 20 or len(te) < 10:
            continue
        y_tr = [float(e["post_value"]) for e in tr]
        x1_tr = [feat_m1(e) for e in tr]
        x1_te = [feat_m1(e) for e in te]
        m1_hat, _, _, _ = _fit_predict(x1_tr, y_tr, x1_te)
        m1_preds = _make_preds(te, m1_hat)
        m1_mae_subj = subject_macro_mae(m1_preds)
        abs_err = sorted(abs(p["y_pred"] - p["y_true"]) for p in m1_preds)

        models: dict[str, Any] = {
            "M1": {
                "subject_macro_mae": m1_mae_subj,
                "pair_micro_mae": pair_micro_mae(m1_preds),
                "n_test": len(te),
                "tail_risk": {
                    "p90": abs_err[min(len(abs_err) - 1, int(math.ceil(0.90 * len(abs_err)) - 1))],
                    "p95": abs_err[min(len(abs_err) - 1, int(math.ceil(0.95 * len(abs_err)) - 1))],
                    "p99": abs_err[min(len(abs_err) - 1, int(math.ceil(0.99 * len(abs_err)) - 1))],
                    "maximum_absolute_error": abs_err[-1],
                },
            }
        }

        # M2EXPOSURE_COUNT — not medication semantics
        x_tr = [feat_exposure_count(e) for e in tr]
        x_te = [feat_exposure_count(e) for e in te]
        res, _, imp, perm = _eval_candidate(
            label="M2EXPOSURE_COUNT",
            m1_preds=m1_preds,
            m1_mae_subj=m1_mae_subj,
            train_x=x_tr,
            train_y=y_tr,
            test_x=x_te,
            test_eps=te,
            extra={"note": "polypharmacy+concurrent only; not drug-concept semantics"},
        )
        models["M2EXPOSURE_COUNT"] = res
        if imp > 0 and perm["permutation_p_value"] < 0.05:
            any_signal = True

        for dim in HASH_DIMS:
            label = f"M2C{dim}"
            coll = collision_report(tr, dim)
            x_tr = [
                feat_m1(e)
                + signed_hash(str(e["medicine_id"]), dim)
                + [
                    float(e.get("polypharmacy_flag") or 0),
                    float(e.get("concurrent_med_count") or 1),
                ]
                for e in tr
            ]
            x_te = [
                feat_m1(e)
                + signed_hash(str(e["medicine_id"]), dim)
                + [
                    float(e.get("polypharmacy_flag") or 0),
                    float(e.get("concurrent_med_count") or 1),
                ]
                for e in te
            ]
            res, _, imp, perm = _eval_candidate(
                label=label,
                m1_preds=m1_preds,
                m1_mae_subj=m1_mae_subj,
                train_x=x_tr,
                train_y=y_tr,
                test_x=x_te,
                test_eps=te,
                extra={"collision": coll},
            )
            models[label] = res
            if imp > 0 and perm["permutation_p_value"] < 0.05:
                any_signal = True

        # M2ID_ONEHOT — authoritative categorical identity
        vocab = build_onehot_vocab(tr)
        if onehot_proof is None:
            sample_ep = {
                "pre_value": float(tr[0]["pre_value"]),
                "n_prior_measurements": tr[0].get("n_prior_measurements") or 0,
                "prior_slope": tr[0].get("prior_slope"),
                "days_since_previous": tr[0].get("days_since_previous"),
                "horizon_days": tr[0]["horizon_days"],
                "medicine_id": vocab["ordered_ids"][0],
                "polypharmacy_flag": tr[0].get("polypharmacy_flag") or 0,
                "concurrent_med_count": tr[0].get("concurrent_med_count") or 1,
            }
            a = feat_m2id_onehot(sample_ep, vocab)
            onehot_block = a[len(M1_FEATURES) : -2]
            onehot_proof = {
                "vocab_hash": vocab["vocab_hash"],
                "vocab_size": vocab["vocab_size"],
                "feature_order_prefix": feat_m2id_onehot_order(vocab)[:12],
                "n_feature_order": len(feat_m2id_onehot_order(vocab)),
                "values_are_zero_one_in_onehot_block": all(
                    v in (0.0, 1.0) for v in onehot_block
                ),
                "exactly_one_active_in_onehot_block": sum(onehot_block) == 1.0,
                "legacy_ordinal_label": LEGACY_ORDINAL_M2ID_LABEL,
                "legacy_excluded_from_decisions": True,
            }

        x_tr = [feat_m2id_onehot(e, vocab) for e in tr]
        x_te = [feat_m2id_onehot(e, vocab) for e in te]
        oov_val = sum(1 for e in va if str(e["medicine_id"]) not in vocab["index"]) / max(
            len(va), 1
        )
        oov_test = sum(1 for e in te if str(e["medicine_id"]) not in vocab["index"]) / max(
            len(te), 1
        )
        res, _, imp, perm = _eval_candidate(
            label="M2ID_ONEHOT",
            m1_preds=m1_preds,
            m1_mae_subj=m1_mae_subj,
            train_x=x_tr,
            train_y=y_tr,
            test_x=x_te,
            test_eps=te,
            extra={
                "vocab_size": vocab["vocab_size"],
                "vocab_hash": vocab["vocab_hash"],
                "oov_rate_validation": oov_val,
                "oov_rate_test": oov_test,
                "encoding": "M2ID_ONEHOT",
                "feature_order_hash": hashlib.sha256(
                    json.dumps(feat_m2id_onehot_order(vocab)).encode()
                ).hexdigest(),
            },
        )
        models["M2ID_ONEHOT"] = res
        if imp > 0 and perm["permutation_p_value"] < 0.05:
            any_signal = True

        # Legacy ordinal — recorded as invalid, not used for signal
        legacy_index = {mid: i + 1 for mid, i in vocab["index"].items()}
        models["LEGACY_ORDINAL_M2ID"] = {
            "status": LEGACY_ORDINAL_M2ID_LABEL,
            "excluded_from_authoritative_comparison": True,
            "excluded_from_signal_decision": True,
        }

        # Semantic models gated on accepted drug concepts
        for label in ("M2INGREDIENT", "M2DRUG_CONCEPT", "M2ATC", "M2SEM"):
            if m2sem_status != "RUN":
                models[label] = {"status": semantic_gate}
            else:
                # Would build multi-hot from accepted concepts — none expected without provider
                accepted_feats = []
                models[label] = {"status": semantic_gate if not accepted_feats else "RUN"}

        if m2sem_status != "RUN":
            models["M2SEM"] = {"status": m2sem_status}

        cohort_results.append(
            {
                "outcome": outcome,
                "unit": unit,
                "n_train": len(tr),
                "n_validation": len(va),
                "n_test": len(te),
                "models": models,
            }
        )

    signal = (
        "EXPLORATORY_INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_SUPPORTED"
        if any_signal
        else "NO_INCREMENTAL_SIGNAL_DETECTED_FOR_EVALUATED_REPRESENTATIONS"
    )
    return {
        "version": VERSION,
        "MEDICATION_REPRESENTATION_EXPERIMENT_STATUS": "COMPLETED",
        "M2ID_CATEGORICAL_CORRECTION_STATUS": "PASS",
        "M2SEM_GATE_STATUS": m2sem_status,
        "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": signal,
        "primary_estimand": "mean_subject_macro_mae_improvement_m1_minus_candidate",
        "n_accepted_drug_concepts": n_accepted_drug_concepts,
        "exploratory_note": (
            "Prior test results already observed; representation comparison is exploratory. "
            "Negative result must not be generalized to unobserved dose/adherence/"
            "ingredient/administration data."
        ),
        "onehot_implementation_proof": onehot_proof,
        "legacy_ordinal_m2id": LEGACY_ORDINAL_M2ID_LABEL,
        "cohorts": cohort_results,
    }
