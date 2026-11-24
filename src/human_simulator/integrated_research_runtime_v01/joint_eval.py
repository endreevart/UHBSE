"""Corrected joint evaluation: normalized scores, paired group bootstrap, no test-driven gates."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.integrated_research_runtime_v01.hashes import derive_seed
from human_simulator.integrated_research_runtime_v01.joint_model import sample_d0_residuals, sample_d1_residuals
from human_simulator.integrated_research_runtime_v01.joint_normalize import scale_value
from human_simulator.integrated_research_runtime_v01.policy import (
    COVERAGE_HI,
    COVERAGE_LO,
    MARGINAL_CRPS_TOL,
    N_BOOTSTRAP,
    N_PATHS_DEFAULT,
    PI_HI,
    PI_LO,
    SEED,
    STABILITY_PATH_COUNTS,
    STABILITY_SEEDS,
    VERSION,
)
from human_simulator.integrated_research_runtime_v01.scores import crps_paths, energy_score, pairwise_corr_error, variogram_score


def _scale_resid(scales: dict[str, Any], ss: str, ok: str, resid: float) -> float:
    return scale_value(scales, ss, ok, resid)


def panel_paths(
    panel: dict[str, Any],
    model: dict[str, Any],
    *,
    family: str,
    n_paths: int,
    seed_extra: str,
) -> tuple[list[list[float]], list[float], list[str]]:
    present = [ok for ok in model["outcomes"] if ok in panel["targets"] and "oof_residual" in panel["rows"].get(ok, {})]
    if family == "D1":
        present = [ok for ok in present if ok in (model.get("ecdf") or {})]
    if len(present) < 2:
        return [], [], []
    ss = panel["source_system"]
    y_norm = []
    for ok in present:
        y_norm.append(_scale_resid(model, ss, ok, float(panel["rows"][ok]["oof_residual"])))
    paths = []
    for i in range(n_paths):
        rng = random.Random(
            derive_seed(
                source_system=ss,
                horizon_days=int(panel["requested_horizon_days"]),
                target_id=panel["t0_iso"],
                landmark_id=panel["source_scoped_subject_id"],
                mode=family.lower(),
                path_index=i,
                extra=seed_extra,
            )
        )
        if family == "D1":
            resid = sample_d1_residuals(model, rng, present)
        else:
            resid = sample_d0_residuals(model, rng, present)
        paths.append([_scale_resid(model, ss, ok, resid[ok]) for ok in present])
    return paths, y_norm, present


def _corr_from_vectors(vecs: list[list[float]]) -> list[list[float]]:
    d = len(vecs[0]) if vecs else 0
    corr = [[0.0] * d for _ in range(d)]
    for i in range(d):
        corr[i][i] = 1.0
        xs = [v[i] for v in vecs]
        for j in range(i + 1, d):
            ys = [v[j] for v in vecs]
            mx = sum(xs) / len(xs)
            my = sum(ys) / len(ys)
            num = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
            vx = sum((a - mx) ** 2 for a in xs)
            vy = sum((b - my) ** 2 for b in ys)
            den = math.sqrt(vx * vy)
            r = 0.0 if den < 1e-12 else num / den
            corr[i][j] = corr[j][i] = r
    return corr


def evaluate_route(
    panels: list[dict[str, Any]],
    model: dict[str, Any] | None,
    *,
    n_paths: int = N_PATHS_DEFAULT,
    seed: int = SEED,
    require_ci: bool = True,
) -> dict[str, Any]:
    if not model or not model.get("chol") or not model.get("data_ok"):
        return {
            "status": "NOT_RUN_FAILED_JOINT_DATA_GATE",
            "n_panels": 0,
            "accepted": False,
        }
    matched = [
        p
        for p in panels
        if p["source_system"] == model["source_system"]
        and p["requested_horizon_days"] == model["horizon_days"]
        and p.get("panel_contract") == "STRICT_COOBSERVED_TARGET_PANEL"
    ]
    per_panel: list[dict[str, Any]] = []
    for p in matched:
        p0, y, present = panel_paths(p, model, family="D0", n_paths=n_paths, seed_extra=str(seed))
        p1, _, _ = panel_paths(p, model, family="D1", n_paths=n_paths, seed_extra=str(seed))
        if not p0 or not p1 or not y:
            continue
        e0 = energy_score(p0, y, normalized=True)
        e1 = energy_score(p1, y, normalized=True)
        v0 = variogram_score(p0, y, normalized=True)
        v1 = variogram_score(p1, y, normalized=True)
        crps0 = [crps_paths([row[j] for row in p0], y[j]) for j in range(len(y))]
        crps1 = [crps_paths([row[j] for row in p1], y[j]) for j in range(len(y))]
        cov0 = 0
        cov1 = 0
        for j in range(len(y)):
            col0 = sorted(row[j] for row in p0)
            col1 = sorted(row[j] for row in p1)
            lo0, hi0 = col0[int(PI_LO * (len(col0) - 1))], col0[int(PI_HI * (len(col0) - 1))]
            lo1, hi1 = col1[int(PI_LO * (len(col1) - 1))], col1[int(PI_HI * (len(col1) - 1))]
            cov0 += int(lo0 <= y[j] <= hi0)
            cov1 += int(lo1 <= y[j] <= hi1)
        per_panel.append(
            {
                "group": p["effective_overlap_group_id"],
                "subject": p["source_scoped_subject_id"],
                "energy_d0": e0,
                "energy_d1": e1,
                "variogram_d0": v0,
                "variogram_d1": v1,
                "mean_crps_d0": sum(crps0) / len(crps0),
                "mean_crps_d1": sum(crps1) / len(crps1),
                "cov_d0": cov0 / len(y),
                "cov_d1": cov1 / len(y),
                "y": y,
                "paths_d0": p0,
                "paths_d1": p1,
            }
        )
    if not per_panel:
        return {"status": "NOT_RUN_FAILED_JOINT_DATA_GATE", "n_panels": 0, "accepted": False}
    mean = lambda key: sum(p[key] for p in per_panel) / len(per_panel)
    d = len(model["outcomes"])
    full = [p for p in per_panel if len(p["y"]) == d]
    emp0 = _corr_from_vectors([p["y"] for p in full]) if full else []
    gen0 = _corr_from_vectors([p["paths_d0"][0] for p in full if p["paths_d0"]]) if full else []
    gen1 = _corr_from_vectors([p["paths_d1"][0] for p in full if p["paths_d1"]]) if full else []
    corr_err0 = pairwise_corr_error(gen0, emp0) if emp0 else float("nan")
    corr_err1 = pairwise_corr_error(gen1, emp0) if emp0 else float("nan")
    for p in per_panel:
        p.pop("paths_d0", None)
        p.pop("paths_d1", None)
        p.pop("y", None)
    boot = paired_group_bootstrap(per_panel, seed=seed)
    crps_ok = mean("mean_crps_d1") <= mean("mean_crps_d0") * MARGINAL_CRPS_TOL + 1e-12
    cov_ok = COVERAGE_LO <= mean("cov_d1") <= COVERAGE_HI
    corr_ok = math.isfinite(corr_err1) and math.isfinite(corr_err0) and corr_err1 <= corr_err0 + 1e-12
    ci_ok = boot.get("hi") is not None and boot["hi"] < 0
    accepted = False
    status = "EVALUATED_NOT_ACCEPTED"
    if not require_ci:
        status = "EVALUATED_NO_CI_CANNOT_ACCEPT"
    elif not model.get("data_ok"):
        status = "NOT_RUN_FAILED_JOINT_DATA_GATE"
    elif ci_ok and crps_ok and corr_ok and cov_ok:
        accepted = True
        status = "JOINT_DEPENDENCE_CELL_ACCEPTED"
    return {
        "version": VERSION,
        "source_system": model["source_system"],
        "horizon_days": model["horizon_days"],
        "n_panels": len(per_panel),
        "n_subjects": len({p["subject"] for p in per_panel}),
        "n_groups": len({p["group"] for p in per_panel}),
        "energy_d0": mean("energy_d0"),
        "energy_d1": mean("energy_d1"),
        "energy_delta": mean("energy_d1") - mean("energy_d0"),
        "variogram_d0": mean("variogram_d0"),
        "variogram_d1": mean("variogram_d1"),
        "mean_crps_d0": mean("mean_crps_d0"),
        "mean_crps_d1": mean("mean_crps_d1"),
        "coverage_d0": mean("cov_d0"),
        "coverage_d1": mean("cov_d1"),
        "pairwise_corr_error_d0": corr_err0,
        "pairwise_corr_error_d1": corr_err1,
        "bootstrap": {k: v for k, v in boot.items() if k != "draws"},
        "crps_ok": crps_ok,
        "coverage_ok": cov_ok,
        "corr_ok": corr_ok,
        "ci_ok": ci_ok,
        "accepted": accepted,
        "status": status,
        "MULTIVARIATE_PROPER_SCORE_STATUS": "NORMALIZED_ENERGY_AND_VARIOGRAM",
        "JOINT_PAIRED_BOOTSTRAP_STATUS": "PASS" if boot.get("hi") is not None else "FAIL",
        "raw_unit_pooled": False,
    }


def paired_group_bootstrap(per_panel: list[dict[str, Any]], *, seed: int = SEED) -> dict[str, Any]:
    by: dict[str, list[float]] = defaultdict(list)
    for p in per_panel:
        by[p["group"]].append(p["energy_d1"] - p["energy_d0"])
    keys = list(by)
    if not keys:
        return {"lo": None, "hi": None, "grouping": "effective_overlap_group", "estimand": "group_macro"}
    rng = random.Random(seed)
    stats = []
    for _ in range(N_BOOTSTRAP):
        draw = [keys[rng.randrange(len(keys))] for _ in keys]
        group_means = [sum(by[k]) / len(by[k]) for k in draw]
        stats.append(sum(group_means) / len(group_means))
    stats.sort()
    return {
        "lo": stats[int(0.025 * (len(stats) - 1))],
        "hi": stats[int(0.975 * (len(stats) - 1))],
        "mean": sum(stats) / len(stats),
        "grouping": "effective_overlap_group",
        "estimand": "group_macro_delta_energy_d1_minus_d0",
        "n_groups": len(keys),
        "n_boot": N_BOOTSTRAP,
        "row_weighted": False,
    }


def subject_macro(per_panel: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[float]] = defaultdict(list)
    for p in per_panel:
        by[p["subject"]].append(p["energy_d1"] - p["energy_d0"])
    if not by:
        return {"mean": float("nan")}
    return {"mean": sum(sum(v) / len(v) for v in by.values()) / len(by), "n_subjects": len(by)}


def stability_check(panels: list[dict[str, Any]], model: dict[str, Any] | None) -> dict[str, Any]:
    if not model:
        return {"status": "NOT_RUN", "ok": False}
    deltas = []
    for seed in STABILITY_SEEDS:
        for n_paths in STABILITY_PATH_COUNTS:
            ev = evaluate_route(panels, model, n_paths=n_paths, seed=seed, require_ci=True)
            if ev.get("n_panels"):
                deltas.append(ev["energy_delta"])
    if not deltas:
        return {"status": "NOT_RUN", "ok": False}
    sign_stable = all(d < 0 for d in deltas) or all(d >= 0 for d in deltas)
    return {
        "status": "SEED_AND_PATH_COUNT_SENSITIVITY",
        "deltas": deltas,
        "sign_stable": sign_stable,
        "ok": True,
    }
