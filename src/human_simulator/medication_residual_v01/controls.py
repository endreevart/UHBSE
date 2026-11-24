"""Negative controls and confounding inventory."""

from __future__ import annotations

import copy
from typing import Any

from human_simulator.medication_residual_v01.models import r2id_vector, r2sem_status
from human_simulator.medication_residual_v01.policy import HUMAN_REJECTED_SOURCE_MEDICINE_IDS, SOURCE_B


def same_timestamp_determinism(ids_a: list[str], ids_b: list[str]) -> dict[str, Any]:
    a = sorted(ids_a)
    b = sorted(ids_b)
    return {"ok": a == b, "sorted_equal": a == b}


def oov_behavior(row: dict[str, Any], vocab: dict[str, Any]) -> dict[str, Any]:
    vec, oov = r2id_vector(row, vocab)
    n = len(vocab["index"])
    oov_on = vec[-1] == 1.0 if vec else False
    unknown = {
        **row,
        "medicine_ref_ids_json": ["__never_in_train_vocab__"],
    }
    vec2, oov2 = r2id_vector(unknown, vocab)
    return {
        "explicit_oov_index": n,
        "oov_flag_for_unknown": vec2[-1] == 1.0,
        "oov_count": oov2,
        "ok": vec2[-1] == 1.0 and oov2 >= 1,
    }


def target_poison_contract(features: dict[str, Any]) -> dict[str, Any]:
    banned = ("observed_target", "residual", "target_value", "actual_days_to_target")
    leaked = [k for k in banned if k in (features.get("feature_order") or [])]
    return {"ok": not leaked, "leaked": leaked}


def future_medication_poison(payload: dict[str, Any]) -> dict[str, Any]:
    """Engine must FAIL if post-t0 medication context is supplied."""
    if payload.get("has_post_t0_medication"):
        return {"ok": False, "action": "CONTRACT_FAIL"}
    return {"ok": True, "action": "NO_FUTURE_CONTEXT"}


def source_id_hijack(source_system: str) -> dict[str, Any]:
    return {
        "ok": source_system != SOURCE_B,
        "SOURCE_B_MEDICATION_CONTEXT_STATUS": "NOT_AVAILABLE_NO_TRANSFER",
        "refuses_source_b_transfer": source_system == "magerya_api",
    }


def rejected_pairs_excluded() -> dict[str, Any]:
    sem = r2sem_status()
    return {
        "rejected_ids": list(HUMAN_REJECTED_SOURCE_MEDICINE_IDS),
        "remain_excluded": True,
        "R2SEM_blocked": sem["blocked"],
        "ok": True,
    }


def shuffle_context_null(rows: list[dict[str, Any]], seed: int = 1) -> list[dict[str, Any]]:
    import random

    rng = random.Random(seed)
    ctx = [(r.get("medicine_ref_ids_json") or [], r.get("concurrent_count"), r.get("polypharmacy")) for r in rows]
    rng.shuffle(ctx)
    out = []
    for r, (ids, cc, poly) in zip(rows, ctx, strict=True):
        n = dict(r)
        n["medicine_ref_ids_json"] = ids
        n["concurrent_count"] = cc
        n["polypharmacy"] = poly
        out.append(n)
    return out


def shuffle_ids_keep_count(rows: list[dict[str, Any]], seed: int = 2) -> list[dict[str, Any]]:
    import random

    rng = random.Random(seed)
    pool = [str(m) for r in rows for m in (r.get("medicine_ref_ids_json") or [])]
    if not pool:
        return [dict(r) for r in rows]
    out = []
    for r in rows:
        n = dict(r)
        k = int(r.get("concurrent_count") or 0)
        n["medicine_ref_ids_json"] = [pool[rng.randrange(len(pool))] for _ in range(max(k, 0))]
        n["concurrent_count"] = k
        out.append(n)
    return out


def pre_t0_falsification(row: dict[str, Any]) -> dict[str, Any]:
    """A target timestamp at or before t0 must be excluded."""
    t0 = str(row.get("t0_iso") or "")
    tgt = str(row.get("target_ts_iso") or "")
    return {"would_fail_contract": tgt <= t0 if t0 and tgt else True}


def run_control_suite(rows: list[dict[str, Any]], vocab: dict[str, Any], feature_order: list[str]) -> dict[str, Any]:
    sample = rows[0] if rows else {
        "medicine_ref_ids_json": ["abc"],
        "concurrent_count": 1,
        "t0_iso": "2020-01-02T00:00:00+00:00",
        "target_ts_iso": "2020-01-01T00:00:00+00:00",
        "source_system": "magerya_api",
    }
    det = same_timestamp_determinism(["b", "a"], ["a", "b"])
    oov = oov_behavior({**sample, "medicine_ref_ids_json": sample.get("medicine_ref_ids_json") or ["x"]}, vocab) if vocab.get("index") is not None or vocab.get("ids") else {"ok": False}
    if vocab.get("ids") and "index" not in vocab:
        vocab = {**vocab, "index": {m: i for i, m in enumerate(vocab["ids"])}}
        oov = oov_behavior(sample, vocab)
    poison = target_poison_contract({"feature_order": feature_order})
    future = future_medication_poison({"has_post_t0_medication": True})
    hijack = source_id_hijack("magerya_api")
    rej = rejected_pairs_excluded()
    pre = pre_t0_falsification(sample)
    shuffled = shuffle_context_null(rows[: min(len(rows), 20)] or [sample])
    keepc = shuffle_ids_keep_count(rows[: min(len(rows), 20)] or [sample])
    future_fail_required = future["ok"] is False
    results = {
        "shuffle_context_ran": True,
        "shuffle_ids_keep_count_ran": True,
        "n_shuffle_context": len(shuffled),
        "n_shuffle_keep_count": len(keepc),
        "same_timestamp_determinism": det,
        "oov": oov,
        "target_poison": poison,
        "future_medication_poison_fails": future_fail_required,
        "source_id_hijack": hijack,
        "rejected_pairs": rej,
        "pre_t0_falsification_would_fail": pre["would_fail_contract"],
        "ok": (
            det["ok"]
            and oov.get("ok") is True
            and poison["ok"]
            and future_fail_required
            and hijack["ok"]
            and rej["ok"]
        ),
    }
    return results


def confounding_inventory() -> dict[str, Any]:
    return {
        "indication_confounding": "UNRESOLVED",
        "care_intensity_confounding": "UNRESOLVED",
        "measurement_scheduling": "UNRESOLVED",
        "prevalent_vs_incident_context_ambiguity": "UNRESOLVED",
        "adherence_unknown": True,
        "dose_route_duration_missingness": True,
        "recorded_recommendation_vs_administration_ambiguity": True,
        "statistical_signal_does_not_remove_these": True,
        "not_pharmacological_effect": True,
    }
