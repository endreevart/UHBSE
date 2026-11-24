"""D0 independent normalized residuals; D1 source-specific masked Gaussian copula."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.integrated_research_runtime_v01.hashes import sha_obj
from human_simulator.integrated_research_runtime_v01.policy import (
    CODE_VERSION,
    COPULA_SHRINK,
    MIN_JOINT_GROUPS,
    MIN_JOINT_OUTCOMES,
    MIN_JOINT_PANELS,
    MIN_JOINT_SUBJECTS,
    MIN_PAIRWISE_SUPPORT,
    VERSION,
)


def _norm_ppf(p: float) -> float:
    p = min(max(p, 1e-12), 1 - 1e-12)
    x = 0.0
    for _ in range(25):
        cdf = 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
        pdf = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
        x -= (cdf - p) / max(pdf, 1e-12)
    return x


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def cholesky(a: list[list[float]]) -> list[list[float]] | None:
    n = len(a)
    l = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(l[i][k] * l[j][k] for k in range(j))
            diff = a[i][j] - s
            if i == j:
                if diff <= 1e-12:
                    return None
                l[i][j] = math.sqrt(diff)
            else:
                l[i][j] = diff / l[j][j]
    return l


def psd_repair(corr: list[list[float]]) -> tuple[list[list[float]], str]:
    n = len(corr)
    a = [[0.5 * (corr[i][j] + corr[j][i]) for j in range(n)] for i in range(n)]
    for i in range(n):
        a[i][i] = 1.0
    eps = 0.0
    for _ in range(16):
        trial = [row[:] for row in a]
        for i in range(n):
            trial[i][i] = 1.0 + eps
        l = cholesky(trial)
        if l is not None:
            d = [math.sqrt(trial[i][i]) for i in range(n)]
            for i in range(n):
                for j in range(n):
                    trial[i][j] /= d[i] * d[j]
            for i in range(n):
                trial[i][i] = 1.0
            if cholesky(trial) is None:
                eps = 1e-6 if eps == 0 else eps * 10
                continue
            return trial, "RIDGE_UNTIL_CHOLESKY" if eps > 0 else "ALREADY_PD"
        eps = 1e-6 if eps == 0 else eps * 10
    return a, "FAIL"


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    den = math.sqrt(vx * vy)
    if den < 1e-12:
        return 0.0
    return max(-0.999, min(0.999, num / den))


def empirical_cdf_value(sorted_xs: list[float], x: float) -> float:
    if not sorted_xs:
        return 0.5
    n = len(sorted_xs)
    i = 0
    while i < n and sorted_xs[i] <= x:
        i += 1
    return (i + 0.5) / (n + 1)


def inverse_cdf(sorted_xs: list[float], u: float) -> float:
    if not sorted_xs:
        return 0.0
    n = len(sorted_xs)
    pos = min(n - 1, max(0, int(u * n)))
    return sorted_xs[pos]


def composite_identity(payload: dict[str, Any]) -> str:
    return sha_obj(
        {
            "family": payload.get("family"),
            "source_system": payload.get("source_system"),
            "horizon_days": payload.get("horizon_days"),
            "outcomes": payload.get("outcomes"),
            "train_scales": payload.get("train_scales"),
            "ecdf": payload.get("ecdf"),
            "support": payload.get("support"),
            "corr": payload.get("corr"),
            "psd_method": payload.get("psd_method"),
            "marginal_provider_identities": payload.get("marginal_provider_identities"),
            "panel_contract": payload.get("panel_contract"),
            "rng_contract": payload.get("rng_contract"),
            "code_version": payload.get("code_version"),
            "residual_block_identity_sha256": payload.get("residual_block_identity_sha256"),
        }
    )


def fit_d1(
    train_panels: list[dict[str, Any]],
    cells_by: dict[tuple[str, str, int], dict[str, Any]],
    scales: dict[str, Any],
    *,
    source_system: str,
    horizon: int,
    residual_block_identity_sha256: str,
) -> dict[str, Any] | None:
    recs = [
        p
        for p in train_panels
        if p["source_system"] == source_system
        and p["requested_horizon_days"] == horizon
        and p.get("panel_contract") == "STRICT_COOBSERVED_TARGET_PANEL"
    ]
    outcomes = sorted({ok for p in recs for ok in p["outcome_keys"]})
    if len(outcomes) < MIN_JOINT_OUTCOMES:
        return None
    resid_by_ok: dict[str, list[float]] = defaultdict(list)
    z_by_ok: dict[str, dict[str, float]] = defaultdict(dict)
    for p in recs:
        pid = p["source_scoped_subject_id"] + "|" + p["t0_iso"]
        for ok in p["outcome_keys"]:
            row = p["rows"][ok]
            resid = row.get("oof_residual")
            if resid is None or not math.isfinite(float(resid)):
                continue
            resid_by_ok[ok].append(float(resid))
            z_by_ok[ok][pid] = float(resid)
    ecdf = {ok: sorted(xs) for ok, xs in resid_by_ok.items() if xs}
    outcomes = [ok for ok in outcomes if ok in ecdf]
    if len(outcomes) < MIN_JOINT_OUTCOMES:
        return None
    n = len(outcomes)
    corr = [[0.0] * n for _ in range(n)]
    support = [[0] * n for _ in range(n)]
    for i, a in enumerate(outcomes):
        corr[i][i] = 1.0
        for j, b in enumerate(outcomes):
            if j <= i:
                continue
            keys = set(z_by_ok[a]) & set(z_by_ok[b])
            support[i][j] = support[j][i] = len(keys)
            if len(keys) < MIN_PAIRWISE_SUPPORT:
                r = 0.0
            else:
                za = [_norm_ppf(empirical_cdf_value(ecdf[a], z_by_ok[a][k])) for k in keys]
                zb = [_norm_ppf(empirical_cdf_value(ecdf[b], z_by_ok[b][k])) for k in keys]
                r_raw = _pearson(za, zb)
                r = r_raw * (len(keys) / (len(keys) + COPULA_SHRINK))
            corr[i][j] = corr[j][i] = r
    repaired, how = psd_repair(corr)
    l = cholesky(repaired)
    marginal_ids = {}
    for ok in outcomes:
        cell = cells_by.get((source_system, ok, horizon))
        if cell:
            marginal_ids[ok] = cell.get("active_payload_sha256")
    scale_subset = {
        k: v
        for k, v in (scales.get("scales") or {}).items()
        if k.startswith(f"{source_system}|") and any(k.split("|")[1] == ok for ok in outcomes)
    }
    payload = {
        "family": "SOURCE_SPECIFIC_MASKED_GAUSSIAN_COPULA",
        "source_system": source_system,
        "horizon_days": horizon,
        "outcomes": outcomes,
        "corr": repaired,
        "support": support,
        "ecdf": ecdf,
        "chol": l,
        "psd_method": how,
        "train_scales": scale_subset,
        "marginal_provider_identities": marginal_ids,
        "panel_contract": "STRICT_COOBSERVED_TARGET_PANEL",
        "rng_contract": "sha256_namespace_seed",
        "code_version": CODE_VERSION,
        "residual_block_identity_sha256": residual_block_identity_sha256,
        "n_train_panels": len(recs),
        "n_subjects": len({p["source_scoped_subject_id"] for p in recs}),
        "n_groups": len({p["effective_overlap_group_id"] for p in recs}),
        "missing_filled_with_zero": False,
    }
    payload["joint_identity_sha256"] = composite_identity(payload)
    payload["data_ok"] = (
        payload["n_subjects"] >= MIN_JOINT_SUBJECTS
        and payload["n_groups"] >= MIN_JOINT_GROUPS
        and len(recs) >= MIN_JOINT_PANELS
        and l is not None
        and how != "FAIL"
    )
    payload["DEPENDENCE_MATRIX_PSD_STATUS"] = "PASS" if l is not None and how != "FAIL" else "FAIL"
    return payload


def _mvn(chol: list[list[float]], rng: random.Random) -> list[float]:
    n = len(chol)
    z = [rng.gauss(0.0, 1.0) for _ in range(n)]
    x = [0.0] * n
    for i in range(n):
        x[i] = sum(chol[i][j] * z[j] for j in range(i + 1))
    return x


def sample_d1_residuals(model: dict[str, Any], rng: random.Random, present: list[str]) -> dict[str, float]:
    outcomes = model["outcomes"]
    z = _mvn(model["chol"], rng)
    out: dict[str, float] = {}
    for i, ok in enumerate(outcomes):
        if ok not in present:
            continue
        u = min(max(_norm_cdf(z[i]), 1e-12), 1 - 1e-12)
        out[ok] = inverse_cdf(model["ecdf"][ok], u)
    return out


def sample_d0_residuals(
    model: dict[str, Any],
    rng: random.Random,
    present: list[str],
) -> dict[str, float]:
    out = {}
    for ok in present:
        xs = model["ecdf"].get(ok) or [0.0]
        out[ok] = float(xs[rng.randrange(len(xs))])
    return out


def public_payload(model: dict[str, Any] | None) -> dict[str, Any]:
    if not model:
        return {}
    return {
        "source_system": model["source_system"],
        "horizon_days": model["horizon_days"],
        "n_outcomes": len(model["outcomes"]),
        "n_train_panels": model["n_train_panels"],
        "n_subjects": model["n_subjects"],
        "n_groups": model["n_groups"],
        "psd_method": model["psd_method"],
        "joint_identity_sha256": model["joint_identity_sha256"],
        "data_ok": model["data_ok"],
        "family": model["family"],
        "panel_contract": model["panel_contract"],
        "DEPENDENCE_MATRIX_PSD_STATUS": model["DEPENDENCE_MATRIX_PSD_STATUS"],
    }


def synthetic_fixture_model() -> dict[str, Any]:
    outcomes = ["SYN::alpha::au", "SYN::beta::au"]
    ecdf = {"SYN::alpha::au": [-1.0, -0.5, 0.0, 0.5, 1.0], "SYN::beta::au": [-1.0, -0.2, 0.0, 0.2, 1.0]}
    corr = [[1.0, 0.4], [0.4, 1.0]]
    repaired, how = psd_repair(corr)
    l = cholesky(repaired)
    scales = {
        "synthetic|SYN::alpha::au|au": {"source_system": "synthetic", "outcome_key": "SYN::alpha::au", "unit": "au", "median": 0.0, "scale": 1.0},
        "synthetic|SYN::beta::au|au": {"source_system": "synthetic", "outcome_key": "SYN::beta::au", "unit": "au", "median": 0.0, "scale": 1.0},
    }
    payload = {
        "family": "SOURCE_SPECIFIC_MASKED_GAUSSIAN_COPULA",
        "source_system": "synthetic",
        "horizon_days": 90,
        "outcomes": outcomes,
        "corr": repaired,
        "support": [[5, 5], [5, 5]],
        "ecdf": ecdf,
        "chol": l,
        "psd_method": how,
        "train_scales": scales,
        "marginal_provider_identities": {"SYN::alpha::au": "fixture", "SYN::beta::au": "fixture"},
        "panel_contract": "STRICT_COOBSERVED_TARGET_PANEL",
        "rng_contract": "sha256_namespace_seed",
        "code_version": CODE_VERSION,
        "residual_block_identity_sha256": "fixture",
        "n_train_panels": 80,
        "n_subjects": 50,
        "n_groups": 50,
        "missing_filled_with_zero": False,
        "validation_accepted": False,
        "synthetic_fixture": True,
    }
    payload["joint_identity_sha256"] = composite_identity(payload)
    payload["data_ok"] = True
    payload["DEPENDENCE_MATRIX_PSD_STATUS"] = "PASS"
    return payload
