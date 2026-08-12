"""Compare Stage 01 (source A) and Stage 02 (source B) audit artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from human_simulator.audit.report import REPORT_STATUS_FINAL, read_report_status
from human_simulator.classify.data_levels import data_levels_compatible
from human_simulator.classify.entities import ENTITY_TYPES
from human_simulator.stage01.manifest import MANIFEST_NAME as STAGE01_MANIFEST_NAME
from human_simulator.stage01.manifest import verify_manifest as verify_stage01_manifest
from human_simulator.stage02.classify_second_source import (
    MANIFEST_NAME,
    verify_manifest,
    _sha256_file,
)

SOURCE_A_AUDIT = "source-audit.json"
SOURCE_A_MANIFEST = STAGE01_MANIFEST_NAME
PRELIMINARY_STATUS = "PRELIMINARY_SCHEMA_ONLY"
LIVE_EXTRACTION_METHOD = "live_readonly_profile"
LIVE_AUDIT_USER = "mg_audit_ro"

SOURCE_A_ARTIFACTS: tuple[str, ...] = (
    "schema-profile.json",
    "entity-candidates.yaml",
    "relation-graph.md",
    "unknown-semantics.md",
    "stage-01-report.md",
)

SOURCE_B_PROFILE = "schema-profile-kgz.json"
SOURCE_B_CANDIDATES = "entity-candidates-kgz.yaml"
SOURCE_B_AUDIT = "source-b-audit.json"

CONFIDENCE_LEVELS: tuple[str, ...] = (
    "UNKNOWN",
    "NAME_MATCH",
    "STRUCTURAL_MATCH",
    "HYPOTHESIS",
    "EVIDENCE_BACKED",
)

# Recorded structural proofs required for EVIDENCE_BACKED (not inferred heuristics).
STRUCTURAL_EVIDENCE_CROSSWALK: dict[tuple[str, str, str], list[str]] = {}

CURATED_CROSSWALK: dict[tuple[str, str, str], str] = {
    ("visits", "magerya_api.appointment_appointment", "public.consultations"): "HYPOTHESIS",
    ("appointments", "magerya_api.appointment_appointment", "public.consultations"): "HYPOTHESIS",
    ("doctors", "magerya_api.account_doctor", "public.users"): "HYPOTHESIS",
    (
        "laboratory_results",
        "magerya_api.document_analysisresult",
        "quest_digital.analyses_constructor",
    ): "HYPOTHESIS",
}

SOURCE_A_APPLICATION_SCHEMAS: frozenset[str] = frozenset({"magerya_api"})
SOURCE_B_APPLICATION_SCHEMAS: frozenset[str] = frozenset({"public", "quest_digital"})

_INFRASTRUCTURE_SCHEMAS = frozenset({"tiger", "tiger_data", "topology", "pg_catalog", "information_schema"})
_INFRASTRUCTURE_RELATIONS = frozenset({("public", "spatial_ref_sys")})

_COLUMN_ALIASES: dict[str, str] = {
    "date_birth": "birthdate",
    "birth_date": "birthdate",
    "modified": "updated_at",
    "created": "created_at",
    "doctor_id": "doctor_id",
    "patient_id": "patient_id",
}

_ENTITY_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "patients": ("patient", "person", "persons"),
    "visits": ("visit", "consultation", "appointment", "encounter"),
    "doctors": ("doctor", "physician", "user"),
    "laboratory_results": ("analysis", "analyses", "lab_result", "analysisresult"),
    "measurements": ("profile", "measurement", "metric"),
    "appointments": ("appointment", "schedule", "booking"),
}


class CompareSourceAuditsError(RuntimeError):
    """Raised when comparison prerequisites fail or inputs are invalid."""


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    detail: str


def compare_source_audits(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    stage01_dir = root / "artifacts" / "stage-01"
    stage02_dir = root / "artifacts" / "stage-02"

    gates = _run_gates(stage01_dir, stage02_dir)
    failed = [gate for gate in gates if gate.status != "PASS"]
    if failed:
        raise CompareSourceAuditsError(
            "compare-source-audits prerequisites failed: "
            + "; ".join(f"{gate.name}={gate.detail}" for gate in failed)
        )

    profile_a = _load_json(stage01_dir / "schema-profile.json")
    profile_b = _load_json(stage02_dir / SOURCE_B_PROFILE)
    candidates_a = _load_yaml(stage01_dir / "entity-candidates.yaml")
    candidates_b = _load_yaml(stage02_dir / SOURCE_B_CANDIDATES)
    audit_b = _load_json(stage02_dir / SOURCE_B_AUDIT)

    schema_diff = _build_schema_diff(profile_a, profile_b, stage01_dir, stage02_dir)
    crosswalk = _build_entity_crosswalk(candidates_a, candidates_b, profile_a, profile_b)

    compared_at = datetime.now(UTC).isoformat()
    stage02_dir.mkdir(parents=True, exist_ok=True)
    schema_diff_path = stage02_dir / "schema-diff.yaml"
    crosswalk_path = stage02_dir / "entity-crosswalk.yaml"
    report_path = stage02_dir / "compare-verification-report.json"

    schema_diff["compared_at"] = compared_at
    crosswalk["compared_at"] = compared_at

    schema_diff_path.write_text(
        yaml.safe_dump(schema_diff, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    crosswalk_path.write_text(
        yaml.safe_dump(crosswalk, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    graph_nodes_b = _count_relation_graph_nodes(stage02_dir / "relation-graph-kgz.md")
    entity_candidates_b = _count_entity_candidates(candidates_b)
    audit_a = _load_json(stage01_dir / SOURCE_A_AUDIT)
    verification = _build_verification_report(
        compared_at=compared_at,
        gates=gates,
        schema_diff_path=schema_diff_path,
        crosswalk_path=crosswalk_path,
        crosswalk=crosswalk,
        audit_a=audit_a,
        audit_b=audit_b,
        stage01_dir=stage01_dir,
        stage02_dir=stage02_dir,
        graph_nodes_b=graph_nodes_b,
        entity_candidates_b=entity_candidates_b,
    )
    report_path.write_text(json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "status": verification["status"],
        "compared_at": compared_at,
        "unresolved_mappings": verification["summary"]["unresolved_mappings"],
        "artifacts": [
            str(schema_diff_path),
            str(crosswalk_path),
            str(report_path),
        ],
    }


def _run_gates(stage01_dir: Path, stage02_dir: Path) -> list[GateResult]:
    gates: list[GateResult] = []

    report_status = read_report_status(stage01_dir)
    gates.append(
        GateResult(
            "source_a_report_status",
            "PASS" if report_status == REPORT_STATUS_FINAL else "FAIL",
            f"stage-01-report status={report_status!r}, expected FINAL",
        )
    )

    missing_a = [name for name in SOURCE_A_ARTIFACTS if not (stage01_dir / name).exists()]
    gates.append(
        GateResult(
            "stage_01_artifacts",
            "PASS" if not missing_a else "FAIL",
            "missing: " + ", ".join(missing_a) if missing_a else "all present",
        )
    )

    audit_a_path = stage01_dir / SOURCE_A_AUDIT
    audit_a = _load_json(audit_a_path) if audit_a_path.exists() else None
    gates.append(
        GateResult(
            "source_a_live_extraction",
            "PASS"
            if audit_a and audit_a.get("extraction_method") == LIVE_EXTRACTION_METHOD
            else "FAIL",
            f"extraction_method={audit_a.get('extraction_method') if audit_a else 'missing'}",
        )
    )
    gates.append(
        GateResult(
            "source_a_audit_user",
            "PASS" if audit_a and audit_a.get("connection_user") == LIVE_AUDIT_USER else "FAIL",
            f"connection_user={audit_a.get('connection_user') if audit_a else 'missing'}",
        )
    )
    gates.append(
        GateResult(
            "source_a_reachable",
            "PASS" if audit_a and audit_a.get("reachable") is True else "FAIL",
            f"reachable={audit_a.get('reachable') if audit_a else 'missing'}",
        )
    )

    profile_a = _load_json(stage01_dir / "schema-profile.json") if (stage01_dir / "schema-profile.json").exists() else None
    readonly_ok = bool(profile_a and profile_a.get("readonly_validation", {}).get("safe"))
    gates.append(
        GateResult(
            "source_a_readonly_validation",
            "PASS" if readonly_ok else "FAIL",
            "readonly_validation.safe=true" if readonly_ok else "readonly validation missing or unsafe",
        )
    )

    fingerprint_match = bool(
        audit_a
        and audit_a.get("schema_fingerprint_check", {}).get("fingerprints_match") is True
    )
    gates.append(
        GateResult(
            "source_a_fingerprint_match",
            "PASS" if fingerprint_match else "FAIL",
            f"fingerprints_match={audit_a.get('schema_fingerprint_check', {}).get('fingerprints_match') if audit_a else 'missing'}",
        )
    )

    stage01_manifest_ok, stage01_manifest_detail = (
        verify_stage01_manifest(stage01_dir)
        if (stage01_dir / SOURCE_A_MANIFEST).exists()
        else (False, f"missing {SOURCE_A_MANIFEST}")
    )
    gates.append(
        GateResult(
            "source_a_manifest",
            "PASS" if stage01_manifest_ok else "FAIL",
            stage01_manifest_detail,
        )
    )

    prelim_audit = stage01_dir.parent / "stage-01-preliminary" / SOURCE_A_AUDIT
    prelim_used = False
    if audit_a and audit_a.get("status") == PRELIMINARY_STATUS:
        prelim_used = True
    if prelim_audit.exists():
        prelim_data = _load_json(prelim_audit)
        if prelim_data.get("status") == PRELIMINARY_STATUS and audit_a == prelim_data:
            prelim_used = True
    gates.append(
        GateResult(
            "source_a_not_preliminary",
            "PASS" if not prelim_used and report_status == REPORT_STATUS_FINAL else "FAIL",
            "preliminary Stage 01 artifacts must not gate compare",
        )
    )

    audit_path = stage02_dir / SOURCE_B_AUDIT
    audit_b = _load_json(audit_path) if audit_path.exists() else None
    gates.append(
        GateResult(
            "source_b_pass",
            "PASS" if audit_b and audit_b.get("status") == "PASS" else "FAIL",
            f"source-b-audit status={audit_b.get('status') if audit_b else 'missing'}",
        )
    )

    manifest_ok, manifest_detail = verify_manifest(stage02_dir) if (stage02_dir / MANIFEST_NAME).exists() else (False, "missing manifest.sha256")
    gates.append(
        GateResult(
            "source_b_manifest",
            "PASS" if manifest_ok else "FAIL",
            manifest_detail,
        )
    )

    for name in (SOURCE_B_PROFILE, SOURCE_B_CANDIDATES):
        gates.append(
            GateResult(
                f"source_b_{name}",
                "PASS" if (stage02_dir / name).exists() else "FAIL",
                "present" if (stage02_dir / name).exists() else "missing",
            )
        )

    graph_path = stage02_dir / "relation-graph-kgz.md"
    graph_nodes = _count_relation_graph_nodes(graph_path)
    candidates_b = _load_yaml(stage02_dir / SOURCE_B_CANDIDATES) if (stage02_dir / SOURCE_B_CANDIDATES).exists() else {}
    unique_candidates_b = _count_unique_candidate_relations(candidates_b)
    gates.append(
        GateResult(
            "source_b_relation_graph_nodes",
            "PASS" if graph_nodes == unique_candidates_b else "FAIL",
            f"graph_nodes={graph_nodes}, unique_candidate_relations={unique_candidates_b}",
        )
    )

    return gates


def _build_schema_diff(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
    stage01_dir: Path,
    stage02_dir: Path,
) -> dict[str, Any]:
    rel_a = _application_relations(profile_a, SOURCE_A_APPLICATION_SCHEMAS)
    rel_b = _application_relations(profile_b, SOURCE_B_APPLICATION_SCHEMAS)

    keys_a = {_relation_key(item) for item in rel_a}
    keys_b = {_relation_key(item) for item in rel_b}

    normalized_a = {_normalize_relation_name(item["name"]): _relation_key(item) for item in rel_a}
    normalized_b = {_normalize_relation_name(item["name"]): _relation_key(item) for item in rel_b}

    shared_normalized = sorted(set(normalized_a) & set(normalized_b))
    a_only = sorted(keys_a - keys_b)
    b_only = sorted(keys_b - keys_a)

    shared_details: list[dict[str, Any]] = []
    rename_hypotheses: list[dict[str, Any]] = []

    for norm in shared_normalized:
        key_a = normalized_a[norm]
        key_b = normalized_b[norm]
        if key_a == key_b:
            continue
        rename_hypotheses.append(
            {
                "source_a": _format_key(key_a),
                "source_b": _format_key(key_b),
                "confidence": "NAME_MATCH",
                "hypothesis_only": True,
                "evidence_refs": [f"normalized_name:{norm}"],
            }
        )

    for norm in shared_normalized:
        key_a = normalized_a[norm]
        key_b = normalized_b[norm]
        column_diffs = _column_diffs(profile_a, profile_b, key_a, key_b)
        if column_diffs:
            shared_details.append(
                {
                    "source_a": _format_key(key_a),
                    "source_b": _format_key(key_b),
                    "normalized_name": norm,
                    "column_diffs": column_diffs,
                }
            )

    for key_a in a_only:
        for key_b in b_only:
            score = SequenceMatcher(None, _normalize_relation_name(key_a[1]), _normalize_relation_name(key_b[1])).ratio()
            if score < 0.72:
                continue
            rename_hypotheses.append(
                {
                    "source_a": _format_key(key_a),
                    "source_b": _format_key(key_b),
                    "confidence": "NAME_MATCH",
                    "hypothesis_only": True,
                    "similarity": round(score, 3),
                    "evidence_refs": ["name_similarity_heuristic"],
                }
            )

    return {
        "source_a": {
            "artifact": str(stage01_dir / "schema-profile.json"),
            "sha256": _sha256_file(stage01_dir / "schema-profile.json"),
            "application_schemas": sorted(SOURCE_A_APPLICATION_SCHEMAS),
            "relation_count": len(rel_a),
        },
        "source_b": {
            "artifact": str(stage02_dir / SOURCE_B_PROFILE),
            "sha256": _sha256_file(stage02_dir / SOURCE_B_PROFILE),
            "application_schemas": sorted(SOURCE_B_APPLICATION_SCHEMAS),
            "relation_count": len(rel_b),
        },
        "notes": [
            "Structural diff uses application schemas only; infrastructure/extension objects excluded.",
            "Missing dedicated table in one source does not imply missing clinical data; values may live in JSON, documents, or text fields.",
            "Rename hypotheses are not confirmed migrations.",
        ],
        "relations": {
            "a_only": [_format_key(key) for key in a_only],
            "b_only": [_format_key(key) for key in b_only],
            "shared_by_normalized_name": shared_normalized,
        },
        "shared_relation_details": shared_details,
        "rename_hypotheses": _dedupe_hypotheses(rename_hypotheses),
        "constraints": {
            "primary_keys_a": len(profile_a.get("primary_keys") or []),
            "primary_keys_b": len(profile_b.get("primary_keys") or []),
            "foreign_keys_a": len(profile_a.get("foreign_keys") or []),
            "foreign_keys_b": len(profile_b.get("foreign_keys") or []),
            "indexes_a": len(profile_a.get("indexes") or []),
            "indexes_b": len(profile_b.get("indexes") or []),
        },
    }


def _build_entity_crosswalk(
    candidates_a: dict[str, Any],
    candidates_b: dict[str, Any],
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
) -> dict[str, Any]:
    entity_types: dict[str, Any] = {}
    unresolved: list[str] = []

    for entity_type in ENTITY_TYPES:
        items_a = candidates_a.get("entity_types", {}).get(entity_type, [])
        items_b = candidates_b.get("entity_types", {}).get(entity_type, [])
        mappings = _propose_mappings(entity_type, items_a, items_b, profile_a, profile_b)
        for mapping in mappings:
            if mapping["confidence"] in {"UNKNOWN", "HYPOTHESIS"}:
                unresolved.append(f"{entity_type}:{mapping['source_a']}->{mapping['source_b']}")
        entity_types[entity_type] = {
            "source_a_candidates": [_candidate_ref(item) for item in items_a],
            "source_b_candidates": [_candidate_ref(item) for item in items_b],
            "mappings": mappings,
        }

    return {
        "rules": [
            "CANDIDATE status is never upgraded to CONFIRMED during crosswalk.",
            "Curated rules emit HYPOTHESIS only; EVIDENCE_BACKED requires recorded structural proofs.",
            "Mappings require compatible data_level on both sides.",
            "No cross-source patient identity linkage is attempted.",
            "Absence of a mapped table does not imply absence of entity data in other storage forms.",
        ],
        "entity_types": entity_types,
        "unresolved_mappings": unresolved,
    }


def _propose_mappings(
    entity_type: str,
    items_a: list[dict[str, Any]],
    items_b: list[dict[str, Any]],
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    used_b: set[tuple[str, str]] = set()

    for item_a in items_a:
        key_a = (item_a["schema"], item_a["relation"])
        best: dict[str, Any] | None = None
        best_score = 0.0
        best_key_b: tuple[str, str] | None = None
        for item_b in items_b:
            key_b = (item_b["schema"], item_b["relation"])
            if key_b in used_b:
                continue
            ref_a = _format_key(key_a)
            ref_b = _format_key(key_b)
            level_a = item_a.get("data_level", "UNKNOWN")
            level_b = item_b.get("data_level", "UNKNOWN")
            if not data_levels_compatible(level_a, level_b):
                continue
            curated = CURATED_CROSSWALK.get((entity_type, ref_a, ref_b))
            if curated:
                best = {
                    "source_a": ref_a,
                    "source_b": ref_b,
                    "confidence": curated,
                    "candidate_status": "CANDIDATE",
                    "source_a_data_level": level_a,
                    "source_b_data_level": level_b,
                    "evidence_refs": ["curated_crosswalk_hypothesis"],
                }
                best_score = 999.0
                best_key_b = key_b
                break
            confidence, score, evidence = _mapping_confidence(
                entity_type,
                item_a,
                item_b,
                profile_a,
                profile_b,
            )
            if score > best_score:
                best_score = score
                best_key_b = key_b
                best = {
                    "source_a": _format_key(key_a),
                    "source_b": _format_key(key_b),
                    "confidence": confidence,
                    "candidate_status": "CANDIDATE",
                    "source_a_data_level": level_a,
                    "source_b_data_level": level_b,
                    "evidence_refs": evidence,
                }
        if best and best["confidence"] != "UNKNOWN":
            if best_key_b is not None:
                used_b.add(best_key_b)
            structural_key = (entity_type, best["source_a"], best["source_b"])
            proofs = STRUCTURAL_EVIDENCE_CROSSWALK.get(structural_key, [])
            if proofs:
                best["confidence"] = "EVIDENCE_BACKED"
                best["evidence_refs"] = list(best["evidence_refs"]) + proofs
            mappings.append(best)
        else:
            mappings.append(
                {
                    "source_a": _format_key(key_a),
                    "source_b": None,
                    "confidence": "UNKNOWN",
                    "candidate_status": "CANDIDATE",
                    "source_a_data_level": item_a.get("data_level", "UNKNOWN"),
                    "source_b_data_level": None,
                    "evidence_refs": ["no_structural_or_name_match"],
                }
            )

    for item_b in items_b:
        key_b = (item_b["schema"], item_b["relation"])
        if any(mapping.get("source_b") == _format_key(key_b) for mapping in mappings):
            continue
        mappings.append(
            {
                "source_a": None,
                "source_b": _format_key(key_b),
                "confidence": "UNKNOWN",
                "candidate_status": "CANDIDATE",
                "source_a_data_level": None,
                "source_b_data_level": item_b.get("data_level", "UNKNOWN"),
                "evidence_refs": ["no_source_a_candidate_match"],
            }
        )

    return mappings


def _mapping_confidence(
    entity_type: str,
    item_a: dict[str, Any],
    item_b: dict[str, Any],
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
) -> tuple[str, float, list[str]]:
    key_a = (item_a["schema"], item_a["relation"])
    key_b = (item_b["schema"], item_b["relation"])
    evidence: list[str] = []

    norm_a = _normalize_relation_name(item_a["relation"])
    norm_b = _normalize_relation_name(item_b["relation"])
    name_score = SequenceMatcher(None, norm_a, norm_b).ratio()
    hints = _ENTITY_NAME_HINTS.get(entity_type, ())
    hint_match = any(hint in norm_a and hint in norm_b for hint in hints)

    structural = _structural_overlap(profile_a, profile_b, key_a, key_b)
    if structural["shared_columns"]:
        evidence.append(f"shared_columns:{','.join(structural['shared_columns'][:5])}")
    if structural["shared_column_ratio"] >= 0.45:
        evidence.append(f"shared_column_ratio:{structural['shared_column_ratio']:.2f}")

    if name_score >= 0.9 or (hint_match and name_score >= 0.55):
        confidence = "NAME_MATCH"
        score = name_score + (0.1 if hint_match else 0)
        evidence.append("name_pattern")
    elif structural["shared_column_ratio"] >= 0.45:
        confidence = "STRUCTURAL_MATCH"
        score = structural["shared_column_ratio"]
    else:
        return "UNKNOWN", 0.0, ["insufficient_name_and_structure_evidence"]

    return confidence, score, evidence


def _structural_overlap(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
    key_a: tuple[str, str],
    key_b: tuple[str, str],
) -> dict[str, Any]:
    cols_a = {
        _normalize_column(col["name"])
        for col in profile_a.get("columns", [])
        if col.get("schema") == key_a[0] and col.get("relation") == key_a[1]
    }
    cols_b = {
        _normalize_column(col["name"])
        for col in profile_b.get("columns", [])
        if col.get("schema") == key_b[0] and col.get("relation") == key_b[1]
    }
    shared = sorted(cols_a & cols_b)
    ratio = len(shared) / max(len(cols_a | cols_b), 1)
    return {"shared_columns": shared, "shared_column_ratio": ratio}


def _build_verification_report(
    *,
    compared_at: str,
    gates: list[GateResult],
    schema_diff_path: Path,
    crosswalk_path: Path,
    crosswalk: dict[str, Any],
    audit_a: dict[str, Any],
    audit_b: dict[str, Any],
    stage01_dir: Path,
    stage02_dir: Path,
    graph_nodes_b: int,
    entity_candidates_b: int,
) -> dict[str, Any]:
    unresolved = crosswalk.get("unresolved_mappings") or []
    checks = [{"name": gate.name, "status": gate.status, "detail": gate.detail} for gate in gates]
    checks.extend(
        [
            {
                "name": "schema_diff_written",
                "status": "PASS" if schema_diff_path.exists() else "FAIL",
                "detail": str(schema_diff_path),
            },
            {
                "name": "entity_crosswalk_written",
                "status": "PASS" if crosswalk_path.exists() else "FAIL",
                "detail": str(crosswalk_path),
            },
            {
                "name": "no_confirmed_crosswalk",
                "status": "PASS",
                "detail": "crosswalk preserves CANDIDATE status only",
            },
        ]
    )
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"

    source_a_hashes = _artifact_hashes(stage01_dir, SOURCE_A_ARTIFACTS)
    source_b_hashes = dict(audit_b.get("artifact_hashes") or {})
    for name in (SOURCE_B_PROFILE, SOURCE_B_CANDIDATES, "relation-graph-kgz.md", "unknown-semantics-kgz.md"):
        path = stage02_dir / name
        if path.exists():
            source_b_hashes.setdefault(name, _sha256_file(path))

    unique_candidates_b = _count_unique_candidate_relations(
        _load_yaml(stage02_dir / SOURCE_B_CANDIDATES)
        if (stage02_dir / SOURCE_B_CANDIDATES).exists()
        else {}
    )

    return {
        "compared_at": compared_at,
        "status": status,
        "source_a_report_status": read_report_status(stage01_dir),
        "source_a_audit": {
            "extraction_method": audit_a.get("extraction_method"),
            "connection_user": audit_a.get("connection_user"),
            "readonly_user_only": audit_a.get("readonly_user_only"),
            "fingerprints_match": audit_a.get("schema_fingerprint_check", {}).get("fingerprints_match"),
        },
        "source_b_audit_status": audit_b.get("status"),
        "artifact_hashes": {
            "source_a": source_a_hashes,
            "source_b": source_b_hashes,
        },
        "source_a_manifest": SOURCE_A_MANIFEST,
        "source_b_manifest": audit_b.get("manifest"),
        "checks": checks,
        "summary": {
            "unresolved_mappings": len(unresolved),
            "unresolved_examples": unresolved[:10],
            "relation_graph_nodes_b": graph_nodes_b,
            "unique_candidate_relations_b": unique_candidates_b,
            "entity_candidate_entries_b": entity_candidates_b,
        },
        "notes": [
            "Comparison uses artifact metadata only; no row-level patient reads.",
            "No canonical database or cross-source patient merge performed.",
            "relation_graph_nodes_b counts graph nodes; entity_candidate_entries_b counts typed candidate rows.",
        ],
    }


def _application_relations(profile: dict[str, Any], schemas: frozenset[str]) -> list[dict[str, Any]]:
    relations = []
    for relation in profile.get("relations") or []:
        if relation.get("kind") not in {"table", "materialized_view"}:
            continue
        schema = relation["schema"]
        name = relation["name"]
        if schema in _INFRASTRUCTURE_SCHEMAS or schema.startswith("pg_"):
            continue
        if (schema, name) in _INFRASTRUCTURE_RELATIONS:
            continue
        if schema in schemas:
            relations.append(relation)
    return relations


def _column_diffs(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
    key_a: tuple[str, str],
    key_b: tuple[str, str],
) -> list[dict[str, Any]]:
    cols_a = {
        col["name"]: col
        for col in profile_a.get("columns", [])
        if col.get("schema") == key_a[0] and col.get("relation") == key_a[1]
    }
    cols_b = {
        col["name"]: col
        for col in profile_b.get("columns", [])
        if col.get("schema") == key_b[0] and col.get("relation") == key_b[1]
    }
    diffs: list[dict[str, Any]] = []
    for name in sorted(set(cols_a) | set(cols_b)):
        if name not in cols_a:
            diffs.append({"column": name, "issue": "missing_in_a"})
            continue
        if name not in cols_b:
            diffs.append({"column": name, "issue": "missing_in_b"})
            continue
        type_a = cols_a[name].get("data_type")
        type_b = cols_b[name].get("data_type")
        if type_a != type_b:
            diffs.append(
                {
                    "column": name,
                    "issue": "type_mismatch",
                    "source_a_type": type_a,
                    "source_b_type": type_b,
                }
            )
        null_a = cols_a[name].get("nullable")
        null_b = cols_b[name].get("nullable")
        if null_a != null_b:
            diffs.append(
                {
                    "column": name,
                    "issue": "nullability_mismatch",
                    "source_a_nullable": null_a,
                    "source_b_nullable": null_b,
                }
            )
    return diffs


def _candidate_ref(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": item["schema"],
        "relation": item["relation"],
        "role": item.get("role"),
        "data_level": item.get("data_level"),
        "status": item.get("status", "CANDIDATE"),
    }


def _count_entity_candidates(candidates: dict[str, Any]) -> int:
    return sum(len(items) for items in candidates.get("entity_types", {}).values())


def _count_unique_candidate_relations(candidates: dict[str, Any]) -> int:
    keys: set[tuple[str, str]] = set()
    for items in candidates.get("entity_types", {}).values():
        for item in items:
            keys.add((item["schema"], item["relation"]))
    return len(keys)


def _artifact_hashes(artifacts_dir: Path, names: tuple[str, ...]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in names:
        path = artifacts_dir / name
        if path.exists():
            hashes[name] = _sha256_file(path)
    return hashes


def _relation_key(relation: dict[str, Any]) -> tuple[str, str]:
    return relation["schema"], relation["name"]


def _format_key(key: tuple[str, str]) -> str:
    return f"{key[0]}.{key[1]}"


def _normalize_column(name: str) -> str:
    normalized = name.lower()
    return _COLUMN_ALIASES.get(normalized, normalized)


def _normalize_relation_name(name: str) -> str:
    normalized = name.lower().replace("-", "_")
    for prefix in ("account_", "appointment_", "document_", "reference_", "diagnosis_"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def _dedupe_hypotheses(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = (item["source_a"], item["source_b"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _count_relation_graph_nodes(path: Path) -> int:
    if not path.exists():
        return 0
    return len(re.findall(r'N\d+\["', path.read_text(encoding="utf-8")))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}
