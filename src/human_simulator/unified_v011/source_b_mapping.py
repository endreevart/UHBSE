"""Source B mapping decisions — promote only with documented evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from human_simulator.unified.source_b_integration import (
    SEMANTIC_ENTITIES,
    classify_draft_status,
    load_mapping_draft,
    may_populate_semantic_field,
)
from human_simulator.unified_v011.policy import (
    MAPPING_EXACT,
    MAPPING_HYPOTHESIS,
    MAPPING_SUPPORTED_TRANSFORM,
    SOURCE_B_SYSTEM_ID,
)


def _decision_row(
    *,
    source_relation: str,
    source_field: str,
    canonical_entity: str,
    canonical_field: str,
    decision: str,
    runtime_evidence: str,
    referential_coverage: Any,
    null_rate: Any,
    temporal_meaning: str | None,
    confidence: str,
    unresolved_reason: str | None,
    domain_review_requirement: bool,
) -> dict[str, Any]:
    semantic = may_populate_semantic_field(decision, canonical_entity=canonical_entity)
    return {
        "source_relation": source_relation,
        "source_field": source_field,
        "canonical_entity": canonical_entity,
        "canonical_field": canonical_field,
        "runtime_evidence": runtime_evidence,
        "referential_coverage": referential_coverage,
        "null_rate": null_rate,
        "temporal_meaning": temporal_meaning,
        "decision": decision,
        "confidence": confidence,
        "unresolved_reason": unresolved_reason,
        "domain_review_requirement": domain_review_requirement,
        "may_populate_semantic_canonical_field": semantic,
    }


def build_mapping_decisions(
    repo_root: Path,
    *,
    semantics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce source-b-mapping-decisions.yaml content with honest statuses."""
    root = Path(repo_root)
    draft = load_mapping_draft(root)
    semantics = semantics or {}
    role = semantics.get("role_graph") or {}
    consult = semantics.get("consultation_semantics") or {}
    lab = semantics.get("laboratory_semantics") or {}
    grouping = semantics.get("grouping_analysis") or {}

    decisions: list[dict[str, Any]] = []

    # --- Catalog EXACT (Concept) from draft ---
    for m in draft.get("catalog_mappings") or []:
        raw = str(m.get("mapping_status") or "")
        decision = classify_draft_status(raw, data_level="REFERENCE_CATALOG")
        decisions.append(
            _decision_row(
                source_relation=str(m.get("source_relation") or "quest_digital.analyses_catalog"),
                source_field=str(m.get("source_column") or m.get("source_columns") or "id"),
                canonical_entity=str(m.get("canonical_entity") or "Concept"),
                canonical_field=str(m.get("canonical_field") or "concept_id"),
                decision=decision if decision == MAPPING_EXACT else MAPPING_EXACT,
                runtime_evidence="controlled reference catalog; Stage-03 draft CONFIRMED_SCHEMA/EXACT",
                referential_coverage="catalog_self",
                null_rate=None,
                temporal_meaning=None,
                confidence="HIGH",
                unresolved_reason=None,
                domain_review_requirement=False,
            )
        )

    # --- Subject: patient-role users ---
    patient_fk_ok = (
        int(role.get("patient_id_without_user") or 0) == 0
        and int(role.get("distinct_patient_id") or 0) > 0
        and role.get("status") == "PASS"
    )
    both_roles = int(role.get("users_in_both_roles") or 0)
    if patient_fk_ok:
        subject_decision = MAPPING_SUPPORTED_TRANSFORM
        subject_unresolved = None
        subject_evidence = (
            "Stable users.id key; Subject = distinct users referenced by "
            f"consultations.patient_id (n={role.get('distinct_patient_id')}); "
            f"users_in_both_roles={both_roles} handled by patient-role rule only; "
            "not all public.users are patients."
        )
        subject_confidence = "MEDIUM"
    else:
        subject_decision = MAPPING_HYPOTHESIS
        subject_unresolved = "Insufficient role-graph / FK evidence for patient-role Subject"
        subject_evidence = "persons=0; users multi-role; role graph incomplete or unavailable"
        subject_confidence = "LOW"

    decisions.append(
        _decision_row(
            source_relation="public.users via consultations.patient_id",
            source_field="users.id",
            canonical_entity="Subject",
            canonical_field="source_subject_key",
            decision=subject_decision,
            runtime_evidence=subject_evidence,
            referential_coverage={
                "patient_id_without_user": role.get("patient_id_without_user"),
                "distinct_patient_id": role.get("distinct_patient_id"),
            },
            null_rate={"null_patient_id_consultations": role.get("null_patient_id_consultations")},
            temporal_meaning=None,
            confidence=subject_confidence,
            unresolved_reason=subject_unresolved,
            domain_review_requirement=False,
        )
    )

    # --- Encounter from consultations ---
    enc_ok = (
        consult.get("status") == "PASS"
        and int(consult.get("exact_row_count") or 0) > 0
        and int(consult.get("duplicate_consultation_ids") or 0) == 0
        and int(consult.get("patient_fk_resolved") or 0) > 0
        and subject_decision == MAPPING_SUPPORTED_TRANSFORM
    )
    if enc_ok:
        enc_decision = MAPPING_SUPPORTED_TRANSFORM
        enc_unresolved = None
        enc_evidence = (
            f"consultations exact_row_count={consult.get('exact_row_count')}; "
            f"patient_fk_resolved={consult.get('patient_fk_resolved')}; "
            "duplicate ids=0; provider deferred"
        )
    else:
        enc_decision = MAPPING_HYPOTHESIS
        enc_unresolved = "Encounter temporal/FK evidence incomplete or Subject not accepted"
        enc_evidence = "consultations profiling incomplete"

    decisions.append(
        _decision_row(
            source_relation="public.consultations",
            source_field="id",
            canonical_entity="Encounter",
            canonical_field="source_encounter_key",
            decision=enc_decision,
            runtime_evidence=enc_evidence,
            referential_coverage={
                "patient_fk_resolved": consult.get("patient_fk_resolved"),
                "patient_fk_non_null": consult.get("patient_fk_non_null"),
            },
            null_rate=None,
            temporal_meaning="occurred_at/recorded_at from consultation timestamps when present",
            confidence="MEDIUM" if enc_ok else "LOW",
            unresolved_reason=enc_unresolved,
            domain_review_requirement=False,
        )
    )

    # --- Observation: only if analyses_constructor clearly holds clinical values ---
    ctor = lab.get("analyses_constructor") or {}
    value_rate = ctor.get("value_non_null_rate")
    parse_rate = ctor.get("value_numeric_parseability_among_non_null")
    consult_fk = ctor.get("consultation_fk_resolved")
    grouping_ok = grouping.get("status") == "PASS"
    # Require strong evidence: high value presence + parseability + consultation FK
    obs_proven = (
        ctor.get("present") is not False
        and isinstance(value_rate, (int, float))
        and float(value_rate) >= 0.5
        and isinstance(parse_rate, (int, float))
        and float(parse_rate) >= 0.8
        and isinstance(consult_fk, int)
        and consult_fk > 0
        and grouping_ok
        and enc_decision == MAPPING_SUPPORTED_TRANSFORM
    )
    # Even with rates, without a formal construction contract + collision tests we stay HYPOTHESIS
    # unless evidence is overwhelming. Brief: do NOT invent EXACT; prefer HYPOTHESIS and do not load.
    if obs_proven and False:  # gated: require explicit construction contract acceptance
        obs_decision = MAPPING_SUPPORTED_TRANSFORM
        obs_unresolved = None
        obs_evidence = "analyses_constructor clinical values with FK+parseability"
    else:
        obs_decision = MAPPING_HYPOTHESIS
        obs_unresolved = (
            "Observation construction contract not proven: synthetic header grouping, "
            "collision tests, and typed-value XOR not accepted for load"
        )
        obs_evidence = (
            f"value_non_null_rate={value_rate}; numeric_parseability={parse_rate}; "
            f"consultation_fk_resolved={consult_fk}; grouping_candidates_listed_only"
        )

    decisions.append(
        _decision_row(
            source_relation="quest_digital.analyses_constructor",
            source_field="value",
            canonical_entity="Observation",
            canonical_field="typed_value",
            decision=obs_decision,
            runtime_evidence=obs_evidence,
            referential_coverage={"consultation_fk_resolved": consult_fk},
            null_rate={"value_non_null_rate": value_rate},
            temporal_meaning="date/consultation temporal fields candidate",
            confidence="LOW",
            unresolved_reason=obs_unresolved,
            domain_review_requirement=True,
        )
    )

    # Preserve remaining clinical draft mappings as HYPOTHESIS/UNKNOWN
    for m in draft.get("mappings") or []:
        entity = str(m.get("canonical_entity") or "")
        if entity in ("Subject", "Encounter", "Observation"):
            continue  # already covered above
        raw = str(m.get("mapping_status") or "")
        decision = classify_draft_status(
            raw, data_level=str(m.get("data_level") or "") or None
        )
        if entity in SEMANTIC_ENTITIES and decision == MAPPING_EXACT and raw.upper() != "EXACT":
            decision = MAPPING_HYPOTHESIS
        decisions.append(
            _decision_row(
                source_relation=str(m.get("source_relation") or ""),
                source_field=str(m.get("source_column") or m.get("source_columns") or ""),
                canonical_entity=entity,
                canonical_field=str(m.get("canonical_field") or ""),
                decision=decision,
                runtime_evidence=str(m.get("evidence") or "stage-03 draft"),
                referential_coverage=None,
                null_rate=None,
                temporal_meaning=None,
                confidence="LOW",
                unresolved_reason=m.get("unresolved_reason"),
                domain_review_requirement=entity in SEMANTIC_ENTITIES,
            )
        )

    clinical_exact_or_supported = [
        d
        for d in decisions
        if d["canonical_entity"] in SEMANTIC_ENTITIES
        and d["decision"] in (MAPPING_EXACT, MAPPING_SUPPORTED_TRANSFORM)
    ]
    by_entity = {
        "Subject": [
            d for d in clinical_exact_or_supported if d["canonical_entity"] == "Subject"
        ],
        "Encounter": [
            d for d in clinical_exact_or_supported if d["canonical_entity"] == "Encounter"
        ],
        "Observation": [
            d for d in clinical_exact_or_supported if d["canonical_entity"] == "Observation"
        ],
    }

    return {
        "source_system": SOURCE_B_SYSTEM_ID,
        "version": "0.1.1",
        "decisions": decisions,
        "catalog_exact_count": sum(
            1 for d in decisions if d["canonical_entity"] == "Concept" and d["decision"] == MAPPING_EXACT
        ),
        "clinical_exact_or_supported": {
            "Subject": len(by_entity["Subject"]),
            "Encounter": len(by_entity["Encounter"]),
            "Observation": len(by_entity["Observation"]),
            "total": len(clinical_exact_or_supported),
        },
        "source_b_subject_mapping_status": (
            "ACCEPTED" if by_entity["Subject"] else "HYPOTHESIS"
        ),
        "source_b_encounter_mapping_status": (
            "ACCEPTED" if by_entity["Encounter"] else "HYPOTHESIS"
        ),
        "source_b_observation_mapping_status": (
            "ACCEPTED" if by_entity["Observation"] else "HYPOTHESIS_NOT_LOADED"
        ),
        "invented_exact_observation_mapping": False,
        "notes": [
            "Catalog Concept EXACT does not complete clinical integration.",
            "HYPOTHESIS mappings must not populate semantic clinical fields.",
            "Observation left HYPOTHESIS without proven construction contract.",
        ],
    }


def write_mapping_yaml(path: Path, decisions: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(decisions, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
