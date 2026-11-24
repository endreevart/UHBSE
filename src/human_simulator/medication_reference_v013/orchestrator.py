"""Orchestrator — Acceptance Semantics v0.1.3 (evidence packet only)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v013.acceptance import (
    exact_813_eligibility,
    historical_authoritative_accepted,
    load_jsonl,
    scientifically_usable_accepted,
    write_acceptance_semantics_doc,
)
from human_simulator.medication_reference_v013.concepts import write_omega3_concept_hierarchy
from human_simulator.medication_reference_v013.omega3_evidence import (
    build_omacor_provider_card,
    build_omega3_source_card,
)
from human_simulator.medication_reference_v013.packets import (
    write_813_card,
    write_omega3_packet,
    write_reviewer_instructions,
)
from human_simulator.medication_reference_v013.policy import (
    ARTIFACT_DIR,
    EXACT_REVIEW_ID,
    OMACOR_ESKLP_ID,
    OMEGA3_PRIORITY_IDS,
    RUNTIME_DIR,
    V011_MAPPING,
    V012_MAPPING,
    V012_PROFILES,
    VERSION,
    policy_snapshot,
)
from human_simulator.medication_reference_v013.readiness import run_acceptance_readiness
from human_simulator.medication_reference_v013.verify import verify_baseline


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def _load_omacor(root: Path) -> dict[str, Any]:
    index = (
        root
        / "private/medication-reference-v011/provider-snapshots/esklp/index"
        / "provider-index.jsonl"
    )
    with index.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("provider_concept_id") == OMACOR_ESKLP_ID:
                return row
    return {
        "provider_concept_id": OMACOR_ESKLP_ID,
        "trade_name": "Омакор",
        "strength": "1000 мг",
        "form": "КАПСУЛЫ",
    }


def _build_813_review_card(root: Path) -> dict[str, Any]:
    elig = exact_813_eligibility(root)
    row = next(
        (
            r
            for r in load_jsonl(root / V011_MAPPING)
            if str(r.get("source_medicine_id")) == EXACT_REVIEW_ID
        ),
        {},
    )
    cand = (row.get("candidates") or [{}])[0]
    source = {
        "source_medicine_id": EXACT_REVIEW_ID,
        "full_name": row.get("original_name"),
        "trade_name_source": "Фурациллин (in parentheses)",
        "active_ingredient": "nitrofural / НИТРОФУРАЛ",
        "salt_chemical_form": "unspecified_beyond_inn",
        "strength": "20 мг",
        "dosage_form": "таблетки для приготовления раствора для местного и наружного применения",
        "route": "topical / local external",
        "manufacturer": None,
        "description": row.get("original_description"),
        "source_text_hash": row.get("source_text_hash") or row.get("source_medication_hash"),
    }
    provider = {
        "esklp_product_identifier": row.get("provider_concept_id"),
        "trade_name": cand.get("trade_name") or "",
        "active_ingredient": cand.get("inn") or row.get("inn"),
        "strength": cand.get("strength") or row.get("strength"),
        "dosage_form": cand.get("form") or row.get("form"),
        "route": "inferred topical-capable (effervescent tablets often dissolved for local use)",
        "manufacturer": None,
        "provider_evidence_hash": row.get("provider_evidence_hash"),
        "provider_snapshot_hash": row.get("provider_snapshot_hash"),
        "source_file": cand.get("source_file"),
    }
    matches = [
        "active_ingredient_nitrofural",
        "strength_20_mg",
        "topical_or_local_use_compatible",
    ]
    diffs = list(elig.get("doubts") or [])
    return {
        **elig,
        "source": source,
        "provider": provider,
        "matches": matches,
        "diffs": diffs,
        "audit_result": "PRODUCT_IDENTITY_REVIEW_REQUIRED",
    }


def run_acceptance_semantics_v013(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    baseline = verify_baseline(root)
    if not baseline.get("snapshot_ok") or not baseline.get("accounting_ok"):
        raise RuntimeError("baseline_verification_failed")
    if not baseline.get("decision_log_ok"):
        raise RuntimeError("decision_log_regression_failed")

    profiles = {
        str(p["source_medicine_id"]): p for p in load_jsonl(root / V012_PROFILES)
    }
    mappings = {
        str(m["source_medicine_id"]): m for m in load_jsonl(root / V012_MAPPING)
    }
    omacor = _load_omacor(root)
    omacor_card = build_omacor_provider_card(omacor)

    omega_cards = []
    for mid in OMEGA3_PRIORITY_IDS:
        p = profiles.get(mid)
        if not p:
            raise RuntimeError(f"missing_profile:{mid}")
        omega_cards.append(
            build_omega3_source_card(p, mappings.get(mid), omacor=omacor)
        )

    card_813 = _build_813_review_card(root)
    write_813_card(root, card_813)
    write_omega3_packet(root, omega_cards, omacor_card)
    write_omega3_concept_hierarchy(root, omega_cards, omacor_card)
    write_acceptance_semantics_doc(root)

    readiness = run_acceptance_readiness(root, omega3_cards=omega_cards)
    write_reviewer_instructions(
        root,
        status=str(readiness.get("OVERALL_STATUS")),
        min_decisions=readiness.get("minimum_human_decisions"),
    )

    hist = historical_authoritative_accepted(root)
    usable = scientifically_usable_accepted(root)

    # Classification counts for report
    product_ids = [
        c["source_medicine_id"]
        for c in omega_cards
        if c.get("eligibility", {}).get("PRODUCT_IDENTITY_ACCEPTED")
    ]
    ing_set_ids = [
        c["source_medicine_id"]
        for c in omega_cards
        if c.get("eligibility", {}).get("INGREDIENT_SET_ACCEPTED")
        or c.get("eligibility", {}).get("PRODUCT_IDENTITY_ACCEPTED")
    ]
    ifr_ids = [
        c["source_medicine_id"]
        for c in omega_cards
        if c.get("eligibility", {}).get("INGREDIENT_FORM_ROUTE_ACCEPTED")
        or c.get("eligibility", {}).get("PRODUCT_IDENTITY_ACCEPTED")
    ]
    family_ids = [
        c["source_medicine_id"]
        for c in omega_cards
        if c.get("eligibility", {}).get("INGREDIENT_FAMILY_ONLY")
        or c.get("eligibility", {}).get("forbidden_product_identity_as_omacor")
    ]

    gaps = [
        {
            "source_medicine_id": c["source_medicine_id"],
            "gap": c.get("provider_neutral_concept"),
            "strength": c.get("strength_comparability_vs_omacor"),
            "chemical_form": c.get("chemical_form"),
        }
        for c in omega_cards
        if c.get("suggested_review_action")
        in {"INGREDIENT_FAMILY_ONLY", "INSUFFICIENT_SOURCE_EVIDENCE"}
    ]

    pack = root / RUNTIME_DIR / "review-pack"
    public = {
        "version": VERSION,
        "generated_at": _now(),
        "OVERALL_STATUS": readiness.get("OVERALL_STATUS"),
        "HISTORICAL_AUTHORITATIVE_ACCEPTED_COUNT": hist.get(
            "HISTORICAL_AUTHORITATIVE_ACCEPTED_COUNT"
        ),
        "SCIENTIFICALLY_USABLE_ACCEPTED_COUNT": usable.get(
            "SCIENTIFICALLY_USABLE_ACCEPTED_COUNT"
        ),
        "AUTOMATIC_EXACT_813_AUDIT": card_813.get("audit_result"),
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": readiness.get(
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS"
        ),
        "product_identity_candidate_ids": product_ids,
        "ingredient_set_candidate_ids": ing_set_ids,
        "ingredient_form_route_candidate_ids": ifr_ids,
        "ingredient_family_only_ids": family_ids,
        "n_omega3_cards": len(omega_cards),
        "authoritative_product_ready": any(
            x.get("READY") for x in readiness.get("A_product_level") or []
        ),
        "authoritative_ingredient_form_ready": any(
            x.get("READY") for x in readiness.get("B_ingredient_form_level") or []
        ),
        "family_exploratory_ready_forbidden": True,
        "provisional_any_READY": False,
        "minimum_human_decisions": readiness.get("minimum_human_decisions"),
        "provider_gaps_n": len(gaps),
        "private_review_pack": str(pack.relative_to(root)),
        "no_model_training": True,
        "no_zip_published": True,
        "no_automatic_human_accepted": True,
        "v011_decision_log_unchanged": True,
        **policy_snapshot(),
    }
    _write(root / ARTIFACT_DIR / "acceptance-semantics-summary.json", public)
    _write(root / RUNTIME_DIR / "diagnostics" / "baseline.json", baseline)
    _write(root / RUNTIME_DIR / "diagnostics" / "omega3-cards.private.json", omega_cards)
    _write(root / RUNTIME_DIR / "diagnostics" / "813-card.private.json", card_813)
    _write(root / RUNTIME_DIR / "diagnostics" / "provider-gaps.private.json", gaps)

    return {
        "ok": True,
        "baseline": baseline,
        "public": public,
        "omega_cards": omega_cards,
        "card_813": card_813,
        "readiness": readiness,
        "usable": usable,
        "gaps": gaps,
    }
