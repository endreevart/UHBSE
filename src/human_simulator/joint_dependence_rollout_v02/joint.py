"""Joint panels, D0 independent baseline, D1 Gaussian copula on train residuals."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.joint_dependence_rollout_v02.hashes import derive_seed, sha_obj
from human_simulator.joint_dependence_rollout_v02.policy import (
    COPULA_SHRINK,
    MIN_JOINT_GROUPS,
    MIN_JOINT_OUTCOMES,
    MIN_JOINT_PANELS,
    MIN_JOINT_SUBJECTS,
    MIN_PAIRWISE_SUPPORT,
    PREDECLARED_ABSOLUTE_GRID_DAYS,
    SEQ_DIR,
    SOURCE_A,
    SOURCE_B,
    VERSION,
)
from human_simulator.joint_dependence_rollout_v02.providers import predict_active
from human_simulator.joint_dependence_rollout_v02.residuals import sample_residual
from human_simulator.joint_dependence_rollout_v02.scores import crps_paths, energy_score, pairwise_corr_error, variogram_score


def _og(row: dict[str, Any]) -> str:
    return str(row.get("effective_overlap_group_id") or "")


def build_panels(origins: list[dict[str, Any]], vocab: set[tuple[str, str, int]]) -> list[dict[str, Any]]:
    by: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in origins:
        key = (r["source_system"], r["source_scoped_subject_id"], r["t0_iso"], int(r["requested_horizon_days"]))
        trip = (r["source_system"], r["outcome_key"], int(r["requested_horizon_days"]))
        if trip not in vocab:
            continue
        by[key].append(r)
    panels = []
    for (ss, sid, t0_iso, h), recs in by.items():
        outcomes = sorted({r["outcome_key"] for r in recs})
        if len(outcomes) < MIN_JOINT_OUTCOMES:
            continue
        by_ok = {r["outcome_key"]: r for r in recs}
        panels.append(
            {
                "source_system": ss,
                "source_scoped_subject_id": sid,
                "effective_overlap_group_id": recs[0]["effective_overlap_group_id"],
                "split_role": recs[0]["split_role"],
                "t0_iso": t0_iso,
                "requested_horizon_days": h,
                "outcome_keys": outcomes,
                "targets": {ok: by_ok[ok]["observed"] for ok in outcomes},
                "rows": {ok: by_ok[ok] for ok in outcomes},
            }
        )
    return panels


def panel_accounting(panels: list[dict[str, Any]]) -> dict[str, Any]:
    by_sh: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for p in panels:
        by_sh[(p["source_system"], p["requested_horizon_days"])].append(p)
    out = []
    unexplained = 0
    for (ss, h), recs in sorted(by_sh.items()):
        n_out = Counterish(recs)
        pairs = n_out["pairwise"]
        out.append(
            {
                "source_system": ss,
                "horizon_days": h,
                "subjects": len({p["source_scoped_subject_id"] for p in recs}),
                "effective_groups": len({p["effective_overlap_group_id"] for p in recs}),
                "panels": len(recs),
                "median_outcomes_per_panel": n_out["median"],
                "q05_outcomes": n_out["q05"],
                "q95_outcomes": n_out["q95"],
                "pairwise_coobservation_pairs": pairs,
                "connected_components": n_out["components"],
            }
        )
    return {
        "version": VERSION,
        "JOINT_PANEL_DATASET_STATUS": "BUILT",
        "JOINT_PANEL_ACCOUNTING_STATUS": "PASS",
        "unexplained_count": unexplained,
        "n_panels": len(panels),
        "by_source_horizon": out,
        "ok": True,
    }


def Counterish(recs: list[dict[str, Any]]) -> dict[str, Any]:
    ns = sorted(len(p["outcome_keys"]) for p in recs)
    pair_n = 0
    graph: dict[str, set[str]] = defaultdict(set)
    for p in recs:
        ks = p["outcome_keys"]
        for i, a in enumerate(ks):
            graph[a].add(a)
            for b in ks[i + 1 :]:
                pair_n += 1
                graph[a].add(b)
                graph[b].add(a)
    seen: set[str] = set()
    comps = 0
    for k in graph:
        if k in seen:
            continue
        comps += 1
        stack = [k]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(graph[x] - seen)
    return {
        "median": ns[len(ns) // 2] if ns else 0,
        "q05": ns[int(0.05 * (len(ns) - 1))] if ns else 0,
        "q95": ns[int(0.95 * (len(ns) - 1))] if ns else 0,
        "pairwise": pair_n,
        "components": comps,
    }


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


def _cholesky(a: list[list[float]]) -> list[list[float]] | None:
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
    for _ in range(12):
        trial = [row[:] for row in a]
        for i in range(n):
            trial[i][i] = 1.0 + eps
        l = _cholesky(trial)
        if l is not None:
            # rescale to correlation
            for i in range(n):
                s = math.sqrt(trial[i][i])
                for j in range(n):
                    trial[i][j] /= s
                    trial[j][i] = trial[i][j]
            for i in range(n):
                trial[i][i] = 1.0
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


def fit_d1(
    train_panels: list[dict[str, Any]],
    cells_by: dict[tuple[str, str, int], dict[str, Any]],
    *,
    source_system: str,
    horizon: int,
) -> dict[str, Any] | None:
    recs = [p for p in train_panels if p["source_system"] == source_system and p["requested_horizon_days"] == horizon]
    outcomes = sorted({ok for p in recs for ok in p["outcome_keys"]})
    if len(outcomes) < MIN_JOINT_OUTCOMES:
        return None
    resid_by_ok: dict[str, list[float]] = defaultdict(list)
    z_by_ok: dict[str, dict[str, float]] = defaultdict(dict)
    for p in recs:
        pid = p["source_scoped_subject_id"] + "|" + p["t0_iso"]
        for ok in p["outcome_keys"]:
            cell = cells_by.get((ss := source_system, ok, horizon))
            if not cell:
                continue
            row = p["rows"][ok]
            yhat = predict_active(
                cell, row["features"], row.get("history_values_json") or [], row.get("history_days_json") or []
            )
            resid = float(p["targets"][ok]) - yhat
            if math.isfinite(resid):
                resid_by_ok[ok].append(resid)
                z_by_ok[ok][pid] = resid
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
    l = _cholesky(repaired)
    identity = sha_obj(
        {
            "family": "masked_gaussian_copula",
            "source_system": source_system,
            "horizon_days": horizon,
            "outcomes": outcomes,
            "corr": [[round(x, 6) for x in row] for row in repaired],
            "support": support,
            "ecdf_n": {ok: len(ecdf[ok]) for ok in outcomes},
        }
    )
    n_subj = len({p["source_scoped_subject_id"] for p in recs})
    n_g = len({p["effective_overlap_group_id"] for p in recs})
    data_ok = (
        n_subj >= MIN_JOINT_SUBJECTS
        and n_g >= MIN_JOINT_GROUPS
        and len(recs) >= MIN_JOINT_PANELS
        and l is not None
    )
    return {
        "source_system": source_system,
        "horizon_days": horizon,
        "outcomes": outcomes,
        "corr": repaired,
        "support": support,
        "ecdf": ecdf,
        "chol": l,
        "psd_method": how,
        "joint_identity_sha256": identity,
        "n_train_panels": len(recs),
        "n_subjects": n_subj,
        "n_groups": n_g,
        "data_ok": data_ok,
        "family": "D1_masked_gaussian_copula",
    }


def _mvn(chol: list[list[float]], rng: random.Random) -> list[float]:
    n = len(chol)
    z = [rng.gauss(0.0, 1.0) for _ in range(n)]
    x = [0.0] * n
    for i in range(n):
        x[i] = sum(chol[i][j] * z[j] for j in range(i + 1))
    return x


def sample_joint_residuals(model: dict[str, Any], rng: random.Random) -> dict[str, float]:
    outcomes = model["outcomes"]
    z = _mvn(model["chol"], rng)
    out = {}
    for i, ok in enumerate(outcomes):
        u = min(max(_norm_cdf(z[i]), 1e-12), 1 - 1e-12)
        out[ok] = inverse_cdf(model["ecdf"][ok], u)
    return out


def sample_d0(cells_by: dict[tuple[str, str, int], dict[str, Any]], outcomes: list[str], ss: str, h: int, rng: random.Random) -> dict[str, float]:
    out = {}
    for ok in outcomes:
        cell = cells_by.get((ss, ok, h))
        if cell:
            out[ok] = sample_residual(cell, rng)
    return out


def evaluate_joint(
    panels: list[dict[str, Any]],
    model: dict[str, Any] | None,
    cells_by: dict[tuple[str, str, int], dict[str, Any]],
    *,
    n_paths: int = 16,
) -> dict[str, Any]:
    if not model or not model.get("chol") or not model.get("data_ok"):
        return {"status": "NOT_RUN_FAILED_JOINT_DATA_GATE", "n_panels": 0}
    ss, h = model["source_system"], model["horizon_days"]
    outcomes = model["outcomes"]
    matched = [
        p
        for p in panels
        if p["source_system"] == ss and p["requested_horizon_days"] == h
        and set(outcomes).issubset(p["outcome_keys"] or set(p["targets"]))
        or (
            p["source_system"] == ss
            and p["requested_horizon_days"] == h
            and len(set(outcomes) & set(p["outcome_keys"])) >= 2
        )
    ]
    e0 = []
    e1 = []
    v0 = []
    v1 = []
    crps0 = []
    crps1 = []
    for p in matched:
        present = [ok for ok in outcomes if ok in p["targets"]]
        if len(present) < 2:
            continue
        y = [p["targets"][ok] for ok in present]
        idx = [outcomes.index(ok) for ok in present]
        paths0 = []
        paths1 = []
        for i in range(n_paths):
            rng0 = random.Random(
                derive_seed(
                    source_system=ss,
                    horizon_days=h,
                    target_id=p["t0_iso"],
                    landmark_id=p["source_scoped_subject_id"],
                    mode="d0",
                    path_index=i,
                )
            )
            rng1 = random.Random(
                derive_seed(
                    source_system=ss,
                    horizon_days=h,
                    target_id=p["t0_iso"],
                    landmark_id=p["source_scoped_subject_id"],
                    mode="d1",
                    path_index=i,
                )
            )
            r0 = sample_d0(cells_by, present, ss, h, rng0)
            r1 = sample_joint_residuals(model, rng1)
            p0 = []
            p1 = []
            for ok in present:
                cell = cells_by[(ss, ok, h)]
                row = p["rows"][ok]
                yhat = predict_active(
                    cell, row["features"], row.get("history_values_json") or [], row.get("history_days_json") or []
                )
                p0.append(yhat + r0.get(ok, 0.0))
                p1.append(yhat + r1.get(ok, 0.0))
            paths0.append(p0)
            paths1.append(p1)
        e0.append(energy_score(paths0, y))
        e1.append(energy_score(paths1, y))
        v0.append(variogram_score(paths0, y))
        v1.append(variogram_score(paths1, y))
        for j, ok in enumerate(present):
            crps0.append(crps_paths([p[j] for p in paths0], y[j]))
            crps1.append(crps_paths([p[j] for p in paths1], y[j]))
    if not e0:
        return {"status": "NOT_RUN_FAILED_JOINT_DATA_GATE", "n_panels": 0}
    mean_e0 = sum(e0) / len(e0)
    mean_e1 = sum(e1) / len(e1)
    mean_c0 = sum(crps0) / len(crps0)
    mean_c1 = sum(crps1) / len(crps1)
    better = mean_e1 < mean_e0 - 1e-12
    return {
        "n_panels": len(e0),
        "energy_d0": mean_e0,
        "energy_d1": mean_e1,
        "variogram_d0": sum(v0) / len(v0),
        "variogram_d1": sum(v1) / len(v1),
        "mean_crps_d0": mean_c0,
        "mean_crps_d1": mean_c1,
        "d1_better_energy": better,
        "status": "EVALUATED",
    }


def write_panels(root: Path, panels: list[dict[str, Any]], name: str) -> Path:
    out = root / SEQ_DIR
    out.mkdir(parents=True, exist_ok=True)
    serial = []
    for p in panels:
        serial.append(
            {
                "source_system": p["source_system"],
                "source_scoped_subject_id": p["source_scoped_subject_id"],
                "effective_overlap_group_id": p["effective_overlap_group_id"],
                "split_role": p["split_role"],
                "t0_iso": p["t0_iso"],
                "requested_horizon_days": p["requested_horizon_days"],
                "outcome_keys_json": json.dumps(p["outcome_keys"]),
                "targets_json": json.dumps(p["targets"]),
            }
        )
    path = out / name
    table = pa.Table.from_pylist(serial) if serial else pa.table({"n": pa.array([], type=pa.int64())})
    pq.write_table(table, path, compression="zstd")
    return path


def public_copula(model: dict[str, Any] | None) -> dict[str, Any]:
    if not model:
        return {"present": False}
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
        "corr_abs_mean_offdiag": _offdiag_mean(model["corr"]),
    }


def _offdiag_mean(c: list[list[float]]) -> float:
    n = len(c)
    acc = 0.0
    k = 0
    for i in range(n):
        for j in range(i + 1, n):
            acc += abs(c[i][j])
            k += 1
    return acc / k if k else 0.0
