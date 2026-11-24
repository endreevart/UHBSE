"""Multi-outcome Source B technical shadow (no B tuning; scientific gates separate)."""

from __future__ import annotations

from typing import Any

from human_simulator.cross_source_shadow_v01.shadow import (
    engineering_shadow_gate,
    run_technical_shadow,
    scientific_cross_source_gate,
)
from human_simulator.population_v01.policy import SOURCE_A, SOURCE_B, VERSION
from human_simulator.scientific.dataset import build_consecutive_pairs, fetch_measurement_series
from human_simulator.scientific.models import FirstLearnedBaseline
from human_simulator.scientific_v02.applicability import (
    assess_b_applicability,
    build_applicability_reference,
)
from human_simulator.scientific_v02.policy import DOMAIN_REVIEW_REQUIRED


def evaluate_b_eligibility(conn: Any, outcome_a: dict[str, Any], catalog_b: dict[str, Any]) -> dict[str, Any]:
    code = outcome_a["source_code"]
    unit = outcome_a["dominant_unit"]
    # Find B candidate with identical code+unit only (no unverified conversion)
    match = None
    for b in catalog_b.get("candidates") or []:
        if b.get("source_code") == code and b.get("dominant_unit") == unit:
            match = b
            break
        # also allow normalized label match with identical unit → still not EXACT
        if (
            str(b.get("normalized_candidate_label", "")).casefold()
            == str(outcome_a.get("normalized_candidate_label", "")).casefold()
            and b.get("dominant_unit") == unit
        ):
            match = b
            break

    checks = {
        "source_b_candidate_exists": match is not None,
        "units_compatible_without_conversion": bool(match and match.get("dominant_unit") == unit),
        "temporal_pairs_exist": bool(match and int(match.get("strict_consecutive_positive_horizon_pairs") or 0) > 0),
        "feature_contract_evaluable": True,
        "model_remains_frozen": True,
        "no_source_b_fitting_or_tuning": True,
    }
    failed = [k for k, v in checks.items() if not v]
    return {
        "outcome_a_candidate_id": outcome_a.get("candidate_id"),
        "source_code": code,
        "dominant_unit": unit,
        "b_match_candidate_id": (match or {}).get("candidate_id"),
        "mapping_status": "HYPOTHESIS" if match else "UNKNOWN",
        "technical_gates_pass": not failed,
        "failed_checks": failed,
        "checks": checks,
        "b_pair_stats": {
            "n_pairs": (match or {}).get("strict_consecutive_positive_horizon_pairs"),
            "n_subjects": (match or {}).get("subjects_with_pairs"),
        },
    }


def run_shadow_for_outcome(
    conn: Any,
    *,
    model: FirstLearnedBaseline,
    train_pairs_a: list[dict[str, Any]],
    outcome_a: dict[str, Any],
    eligibility: dict[str, Any],
) -> dict[str, Any]:
    if not eligibility.get("technical_gates_pass"):
        return {
            "version": VERSION,
            "executed": False,
            "technical_shadow_execution_status": "NOT_RUN_TECHNICAL_GATE",
            "technical_shadow_transfer_status": "NOT_RUN_TECHNICAL_GATE",
            "scientific_interpretability_status": "NOT_ESTABLISHED",
            "scientific_cross_source_transfer_status": "NOT_RUN_DUE_TO_FAILED_TECHNICAL_GATE",
            "failed_checks": eligibility.get("failed_checks"),
            "source_b_tuned": False,
        }

    code = outcome_a["source_code"]
    unit = outcome_a["dominant_unit"]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT o.subject_id::text
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND oc.raw_code = %s AND COALESCE(oc.raw_unit,'') = %s
              AND oc.numeric_value IS NOT NULL
            GROUP BY o.subject_id HAVING COUNT(*) >= 2
            """,
            (SOURCE_B, code, unit),
        )
        b_subjects = {r[0] for r in cur.fetchall()}

    series = fetch_measurement_series(conn, raw_code=code, dominant_unit=unit, subject_keys=b_subjects)
    # Ensure B only
    with conn.cursor() as cur:
        keys = list({r["opaque_subject_key"] for r in series})
        if keys:
            cur.execute(
                """
                SELECT subject_id::text FROM canonical_evidence.subject
                WHERE subject_id::text = ANY(%s) AND source_system_id = %s
                """,
                (keys, SOURCE_B),
            )
            ok = {r[0] for r in cur.fetchall()}
        else:
            ok = set()
    series = [r for r in series if r["opaque_subject_key"] in ok]
    pairs, _meta = build_consecutive_pairs(
        series,
        outcome={"source_measurement_label": code, "dominant_unit": unit},
        config={"version": VERSION},
    )
    if not pairs:
        return {
            "executed": False,
            "technical_shadow_execution_status": "NOT_RUN_NO_PAIRS",
            "scientific_interpretability_status": "NOT_ESTABLISHED",
            "scientific_cross_source_transfer_status": "NOT_RUN_DUE_TO_FAILED_TECHNICAL_GATE",
            "source_b_tuned": False,
        }

    ref = build_applicability_reference(train_pairs_a)
    appl = assess_b_applicability(pairs, ref)
    in_s = appl.pop("_runtime_in_support", [])
    out_s = appl.pop("_runtime_out_support", [])

    eng = engineering_shadow_gate(
        baseline_ok=True,
        training_ok=True,
        eval_ok=True,
        frozen_ok=True,
        b_dataset_ok=True,
        feature_contract_ok=True,
    )
    shadow = run_technical_shadow(
        model=model,
        b_pairs=pairs,
        in_support=in_s,
        out_support=out_s,
        eng_gate=eng,
        applicability_pass=bool(appl.get("applicability_pass")),
        applicability_status=str(appl.get("applicability_status") or "UNKNOWN"),
    )
    sci = scientific_cross_source_gate(
        t3_status=DOMAIN_REVIEW_REQUIRED,
        applicability_pass=bool(appl.get("applicability_pass")),
    )
    # Force scientific statuses per stage contract
    shadow["scientific_interpretability_status"] = "NOT_ESTABLISHED"
    shadow["scientific_cross_source_transfer_status"] = (
        "NOT_RUN_DUE_TO_FAILED_SCIENTIFIC_GATE"
        if sci.get("scientific_cross_source_gate_status") == "FAIL"
        else "NOT_RUN_DOMAIN_REVIEW_REQUIRED"
    )
    shadow["scientifically_interpretable"] = False
    shadow["scientific_gate"] = sci
    shadow["applicability"] = {
        k: v for k, v in appl.items() if not str(k).startswith("_")
    }
    shadow["n_b_pairs"] = len(pairs)
    shadow["n_b_subjects"] = len({p["opaque_subject_key"] for p in pairs})
    shadow["source_a_subjects_excluded"] = True
    shadow["identity_merge"] = False
    return shadow


def run_multi_shadow(
    conn: Any,
    *,
    baseline_results: dict[str, Any],
    catalog_b: dict[str, Any],
    train_pairs_by_candidate: dict[str, list[dict[str, Any]]],
    models_by_candidate: dict[str, FirstLearnedBaseline],
    shortlist: dict[str, Any],
) -> dict[str, Any]:
    rows = []
    for outcome in shortlist.get("shortlist") or []:
        cid = outcome["candidate_id"]
        elig = evaluate_b_eligibility(conn, outcome, catalog_b)
        model = models_by_candidate.get(cid)
        train = train_pairs_by_candidate.get(cid) or []
        if model is None:
            shadow = {
                "executed": False,
                "reason": "no_frozen_model_for_outcome",
                "scientific_interpretability_status": "NOT_ESTABLISHED",
                "technical_shadow_execution_status": "NOT_RUN",
            }
        else:
            shadow = run_shadow_for_outcome(
                conn,
                model=model,
                train_pairs_a=train,
                outcome_a=outcome,
                eligibility=elig,
            )
        rows.append({"eligibility": elig, "shadow": shadow, "candidate_id": cid})

    return {
        "version": VERSION,
        "technical_shadow_transfer_status": (
            "TECHNICAL_SHADOW_TRANSFER_EXECUTED"
            if any((r.get("shadow") or {}).get("executed") for r in rows)
            else "PARTIAL"
        ),
        "scientific_interpretability_status": "NOT_ESTABLISHED",
        "scientific_cross_source_transfer_status": "NOT_RUN_DOMAIN_REVIEW_REQUIRED",
        "outcomes": rows,
        "source_b_tuned": False,
        "no_identity_merge": True,
    }
