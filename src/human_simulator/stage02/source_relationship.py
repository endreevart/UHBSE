"""Structural source relationship assessment from audit artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from human_simulator.classify.data_levels import data_levels_compatible
from human_simulator.stage02.relation_scope import (
    SOURCE_A_APPLICATION_SCHEMAS,
    SOURCE_B_APPLICATION_SCHEMAS,
    application_relations,
    shared_relation_names,
)


def assess_structural_relationship(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    stage01 = root / "artifacts" / "stage-01"
    stage02 = root / "artifacts" / "stage-02"

    profile_a = json.loads((stage01 / "schema-profile.json").read_text(encoding="utf-8"))
    profile_b = json.loads((stage02 / "schema-profile-kgz.json").read_text(encoding="utf-8"))
    crosswalk = yaml.safe_load((stage02 / "entity-crosswalk.yaml").read_text(encoding="utf-8"))
    schema_diff = yaml.safe_load((stage02 / "schema-diff.yaml").read_text(encoding="utf-8"))

    domain_overlap = _clinical_domain_overlap(crosswalk)
    structural = _structural_similarity(profile_a, profile_b, crosswalk)
    migration_signals = _migration_signals(profile_a, profile_b, schema_diff)
    unique_subsystems = _unique_subsystems(profile_a, profile_b)
    data_level_compat = _data_level_compatibility(crosswalk)
    mapping_kinds = _mapping_kind_summary(crosswalk)

    verdict = _relationship_verdict(
        domain_overlap=domain_overlap,
        structural=structural,
        migration_signals=migration_signals,
        identity_verdict=None,
    )

    return {
        "assessed_at": datetime.now(tz=UTC).isoformat(),
        "clinical_domain_overlap": domain_overlap,
        "structural_similarity": structural,
        "migration_signals": migration_signals,
        "unique_subsystems": unique_subsystems,
        "data_level_compatibility": data_level_compat,
        "mapping_kinds": mapping_kinds,
        "source_relationship_verdict": verdict,
        "notes": [
            "HYPOTHESIS mappings are not treated as proven structural equivalence.",
            "HEADER↔VALUE pairs use REPRESENTATION_TRANSFORM; EVENT↔EVENT use SEMANTIC_EQUIVALENCE_HYPOTHESIS.",
        ],
    }


def finalize_relationship_verdict(
    structural: dict[str, Any],
    *,
    identity_verdict: str,
    subject_root_a: str,
    subject_root_b: str,
) -> dict[str, Any]:
    verdict = dict(structural["source_relationship_verdict"])
    identity = identity_verdict

    if identity == "POTENTIAL_OVERLAP":
        verdict["supporting_evidence"].append(
            "Aggregate identity linkage verdict=POTENTIAL_OVERLAP without population extrapolation"
        )
    elif identity == "AGGREGATE_OVERLAP_CONFIRMED":
        verdict["supporting_evidence"].append(
            "Aggregate identity linkage verdict=AGGREGATE_OVERLAP_CONFIRMED without population extrapolation"
        )
    elif identity == "STRUCTURAL_ONLY":
        verdict["supporting_evidence"].append("Shared clinical domains without reliable aggregate patient overlap")

    if subject_root_b == "SUBJECT_ROOT_CANDIDATE":
        verdict["unresolved_questions"].append(
            "Source B patient root resolves via shared users table; staff/patient separation unclear"
        )

    verdict["prohibited_inferences"] = [
        "Patients are not assumed equal across sources.",
        "No permanent patient crosswalk created.",
        "Schema similarity does not prove shared deployment or migration.",
        "Infrastructure relation-name overlap is not evidence of system relationship.",
        "Observed unique-identifier overlap rates must not be extrapolated to full populations.",
    ]
    return verdict


def _clinical_domain_overlap(crosswalk: dict[str, Any]) -> dict[str, Any]:
    entity_types = crosswalk.get("entity_types", {})
    shared: list[str] = []
    a_only: list[str] = []
    b_only: list[str] = []
    for entity_type, block in entity_types.items():
        has_a = bool(block.get("source_a_candidates"))
        has_b = bool(block.get("source_b_candidates"))
        if has_a and has_b:
            shared.append(entity_type)
        elif has_a:
            a_only.append(entity_type)
        elif has_b:
            b_only.append(entity_type)
    return {
        "shared_domains": shared,
        "source_a_only_domains": a_only,
        "source_b_only_domains": b_only,
        "shared_domain_count": len(shared),
    }


def _structural_similarity(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
    crosswalk: dict[str, Any],
) -> dict[str, Any]:
    app_a = application_relations(profile_a, SOURCE_A_APPLICATION_SCHEMAS)
    app_b = application_relations(profile_b, SOURCE_B_APPLICATION_SCHEMAS)
    application_shared, infrastructure_shared, _ = shared_relation_names(profile_a, profile_b)

    hypothesis_mappings = 0
    unresolved = 0
    for block in crosswalk.get("entity_types", {}).values():
        for mapping in block.get("mappings", []):
            confidence = mapping.get("confidence", "UNKNOWN")
            if confidence == "HYPOTHESIS":
                hypothesis_mappings += 1
            if confidence in {"UNKNOWN", "HYPOTHESIS"}:
                unresolved += 1

    return {
        "source_a_application_relation_count": len(app_a),
        "source_b_application_relation_count": len(app_b),
        "application_shared_relation_name_count": len(application_shared),
        "application_shared_relation_names": application_shared[:20],
        "infrastructure_shared_relation_name_count": len(infrastructure_shared),
        "infrastructure_shared_relation_names": infrastructure_shared[:20],
        "hypothesis_mapping_count": hypothesis_mappings,
        "unresolved_mapping_count": unresolved,
        "patient_table_mapping_status": "UNRESOLVED",
        "visit_event_mapping_status": "HYPOTHESIS",
        "laboratory_mapping_status": "HYPOTHESIS",
    }


def _migration_signals(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
    schema_diff: dict[str, Any],
) -> dict[str, Any]:
    app_a = {r["name"] for r in application_relations(profile_a, SOURCE_A_APPLICATION_SCHEMAS)}
    app_b = {r["name"] for r in application_relations(profile_b, SOURCE_B_APPLICATION_SCHEMAS)}
    shared = app_a & app_b
    signals: list[str] = []
    if "consultations" in app_b and "appointment_appointment" in app_a:
        signals.append("parallel visit/appointment event tables with different naming")
    if "persons" in app_b and "account_patient" in app_a:
        signals.append("patient entity tables exist on both sides but are not cross-mapped")
    only_b = schema_diff.get("summary", {}).get("only_in_b") or []
    app_only_b = [item for item in only_b if "quest_digital" in str(item) or "profilaxys" in str(item)]
    if app_only_b:
        signals.append("Source B contains application schemas/tables absent from Source A (quest_digital, profilaxys_*)")

    return {
        "application_shared_table_names": sorted(shared)[:20],
        "signals": signals,
        "migration_hypothesis_strength": "weak",
        "note": "Infrastructure-only overlaps (PostGIS/extension metadata) are excluded from migration signals.",
    }


def _unique_subsystems(profile_a: dict[str, Any], profile_b: dict[str, Any]) -> dict[str, Any]:
    schemas_a = sorted({r["schema"] for r in profile_a.get("relations", [])})
    schemas_b = sorted({r["schema"] for r in profile_b.get("relations", [])})
    return {
        "source_a_schemas": schemas_a,
        "source_b_schemas": schemas_b,
        "source_a_unique": sorted(set(schemas_a) - set(schemas_b)),
        "source_b_unique": sorted(set(schemas_b) - set(schemas_a)),
    }


def _data_level_compatibility(crosswalk: dict[str, Any]) -> dict[str, Any]:
    compatible = 0
    incompatible = 0
    examples: list[str] = []
    for entity_type, block in crosswalk.get("entity_types", {}).items():
        for mapping in block.get("mappings", []):
            a_level = mapping.get("source_a_data_level")
            b_level = mapping.get("source_b_data_level")
            if a_level and b_level:
                if data_levels_compatible(a_level, b_level):
                    compatible += 1
                else:
                    incompatible += 1
                    examples.append(f"{entity_type}:{a_level}<->{b_level}")
    return {
        "compatible_mapping_count": compatible,
        "incompatible_mapping_count": incompatible,
        "incompatible_examples": examples[:10],
    }


def _mapping_kind_summary(crosswalk: dict[str, Any]) -> dict[str, Any]:
    representation_transform = 0
    semantic_hypothesis = 0
    for block in crosswalk.get("entity_types", {}).values():
        for mapping in block.get("mappings", []):
            a_level = mapping.get("source_a_data_level")
            b_level = mapping.get("source_b_data_level")
            if not a_level or not b_level:
                continue
            if _is_header_value_pair(a_level, b_level):
                representation_transform += 1
            elif a_level == "PATIENT_EVENT" and b_level == "PATIENT_EVENT":
                semantic_hypothesis += 1
    return {
        "REPRESENTATION_TRANSFORM": representation_transform,
        "SEMANTIC_EQUIVALENCE_HYPOTHESIS": semantic_hypothesis,
    }


def _is_header_value_pair(a_level: str, b_level: str) -> bool:
    pair = {a_level, b_level}
    return pair == {"OBSERVATION_HEADER", "OBSERVATION_VALUE"}


def _relationship_verdict(
    *,
    domain_overlap: dict[str, Any],
    structural: dict[str, Any],
    migration_signals: dict[str, Any],
    identity_verdict: str | None,
) -> dict[str, Any]:
    shared_count = domain_overlap["shared_domain_count"]
    supporting = [
        f"{shared_count} shared clinical entity domains in crosswalk",
        "Different application schemas and data models (magerya_api vs public/quest_digital)",
        "Structurally similar patient, visit/event, and laboratory concepts with unresolved mappings",
        f"{structural['application_shared_relation_name_count']} shared application relation names",
    ]
    contradicting = [
        "No EVIDENCE_BACKED entity mappings in crosswalk",
        "Source B public.persons is empty while Source A has populated account_patient",
    ]
    unresolved = [
        "Whether systems ever shared a deployment or data export path",
        "Exact laboratory result representation equivalence (header/value split differs)",
    ]

    if shared_count >= 4 and structural["unresolved_mapping_count"] > 10:
        code = "SAME_DOMAIN_DIFFERENT_SYSTEMS"
        confidence = "medium"
    elif migration_signals["signals"]:
        code = "STRUCTURALLY_RELATED"
        confidence = "low"
    elif shared_count == 0:
        code = "INDEPENDENT_SOURCES"
        confidence = "medium"
    else:
        code = "SAME_DOMAIN_DIFFERENT_SYSTEMS"
        confidence = "medium"

    return {
        "verdict": code,
        "supporting_evidence": supporting,
        "contradicting_evidence": contradicting,
        "unresolved_questions": unresolved,
        "confidence": confidence,
        "prohibited_inferences": [
            "Do not infer patient equality from structural similarity alone.",
            "Do not treat HYPOTHESIS crosswalk entries as confirmed mappings.",
        ],
    }


def render_source_relationship_markdown(payload: dict[str, Any]) -> str:
    verdict = payload["source_relationship_verdict"]
    lines = [
        "# Source relationship assessment",
        "",
        f"Assessed at: {payload['assessed_at']}",
        "",
        f"## Verdict: **{verdict['verdict']}** (confidence: {verdict['confidence']})",
        "",
        "### Supporting evidence",
        "",
    ]
    for item in verdict["supporting_evidence"]:
        lines.append(f"- {item}")
    lines.extend(["", "### Contradicting evidence", ""])
    for item in verdict["contradicting_evidence"]:
        lines.append(f"- {item}")
    lines.extend(["", "### Unresolved questions", ""])
    for item in verdict["unresolved_questions"]:
        lines.append(f"- {item}")
    lines.extend(["", "### Prohibited inferences", ""])
    for item in verdict["prohibited_inferences"]:
        lines.append(f"- {item}")

    domains = payload["clinical_domain_overlap"]
    lines.extend(
        [
            "",
            "## Clinical domain overlap",
            "",
            f"- Shared domains ({domains['shared_domain_count']}): {', '.join(domains['shared_domains'])}",
            f"- Source A only: {', '.join(domains['source_a_only_domains']) or 'none'}",
            f"- Source B only: {', '.join(domains['source_b_only_domains']) or 'none'}",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
