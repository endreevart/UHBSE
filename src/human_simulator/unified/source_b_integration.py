"""Source B mapping decisions + partial canonical registration (no invented EXACT clinical maps)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.unified.policy import (
    MAPPING_EXACT,
    MAPPING_HYPOTHESIS,
    MAPPING_INCOMPATIBLE,
    MAPPING_SUPPORTED_TRANSFORM,
    MAPPING_UNKNOWN,
    SOURCE_B_INTEGRATION_PARTIAL,
    SOURCE_B_SYSTEM_ID,
)

SEMANTIC_ENTITIES = frozenset(
    {
        "Subject",
        "SubjectCharacteristic",
        "Encounter",
        "Observation",
        "ObservationComponent",
        "Provider",
        "Diagnosis",
        "MedicationOrder",
        "Intervention",
    }
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def classify_draft_status(raw_status: str, *, data_level: str | None = None) -> str:
    """Map Stage 03 draft statuses onto EXACT/SUPPORTED_TRANSFORM/HYPOTHESIS/UNKNOWN/INCOMPATIBLE."""
    s = (raw_status or "").strip().upper()
    if s == MAPPING_EXACT:
        return MAPPING_EXACT
    if s == MAPPING_SUPPORTED_TRANSFORM:
        return MAPPING_SUPPORTED_TRANSFORM
    if s == MAPPING_INCOMPATIBLE:
        return MAPPING_INCOMPATIBLE
    if s in ("HYPOTHESIS", "CANDIDATE"):
        return MAPPING_HYPOTHESIS
    if s in ("NOT_MAPPED", "UNRESOLVED", "UNKNOWN"):
        return MAPPING_UNKNOWN
    if s == "CONFIRMED_SCHEMA":
        # Structure-only confirmation. REFERENCE_CATALOG keys may be EXACT for catalog identity;
        # never promote to clinical Subject/Observation EXACT.
        if (data_level or "").upper() == "REFERENCE_CATALOG":
            return MAPPING_EXACT
        return MAPPING_HYPOTHESIS
    return MAPPING_UNKNOWN


def may_populate_semantic_field(decision: str, *, canonical_entity: str | None) -> bool:
    if decision not in (MAPPING_EXACT, MAPPING_SUPPORTED_TRANSFORM):
        return False
    if (canonical_entity or "") in SEMANTIC_ENTITIES and decision == MAPPING_EXACT:
        # Only EXACT clinical mappings — we do not invent them for Source B in v0.1.
        return True
    if decision == MAPPING_SUPPORTED_TRANSFORM and (canonical_entity or "") in SEMANTIC_ENTITIES:
        return True
    # Catalog Concept allowed when EXACT REFERENCE_CATALOG
    if (canonical_entity or "") == "Concept" and decision == MAPPING_EXACT:
        return True
    return False


def load_mapping_draft(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "artifacts" / "stage-03" / "source-b-mapping-draft.yaml"
    if not path.is_file():
        return {"mappings": [], "catalog_mappings": [], "missing": True}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_stage02_identity(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "artifacts" / "stage-02" / "identity-linkage-assessment.json"
    if not path.is_file():
        return {"missing": True}
    return json.loads(path.read_text(encoding="utf-8"))


def build_mapping_decisions(repo_root: Path) -> dict[str, Any]:
    draft = load_mapping_draft(repo_root)
    decisions: list[dict[str, Any]] = []
    counts = {
        MAPPING_EXACT: 0,
        MAPPING_SUPPORTED_TRANSFORM: 0,
        MAPPING_HYPOTHESIS: 0,
        MAPPING_UNKNOWN: 0,
        MAPPING_INCOMPATIBLE: 0,
    }

    def _add(entry: dict[str, Any], *, section: str) -> None:
        raw = str(entry.get("mapping_status") or "")
        data_level = entry.get("data_level")
        decision = classify_draft_status(raw, data_level=str(data_level) if data_level else None)
        entity = entry.get("canonical_entity")
        semantic = may_populate_semantic_field(decision, canonical_entity=str(entity) if entity else None)
        # Hard rule: do not invent EXACT clinical Subject/Observation mappings from HYPOTHESIS drafts.
        if entity in SEMANTIC_ENTITIES and decision == MAPPING_EXACT and raw.upper() != "EXACT":
            # CONFIRMED_SCHEMA never elevates clinical entities to EXACT.
            decision = MAPPING_HYPOTHESIS
            semantic = False
        row = {
            "section": section,
            "source_relation": entry.get("source_relation"),
            "source_column": entry.get("source_column") or entry.get("source_columns"),
            "canonical_entity": entity,
            "canonical_field": entry.get("canonical_field"),
            "draft_mapping_status": raw,
            "decision": decision,
            "data_level": data_level,
            "may_populate_semantic_canonical_field": semantic,
            "evidence": entry.get("evidence"),
            "unresolved_reason": entry.get("unresolved_reason"),
        }
        decisions.append(row)
        counts[decision] = counts.get(decision, 0) + 1

    for m in draft.get("catalog_mappings") or []:
        _add(m, section="catalog")
    for m in draft.get("mappings") or []:
        _add(m, section="clinical")

    clinical_exact = [
        d
        for d in decisions
        if d["section"] == "clinical"
        and d["decision"] in (MAPPING_EXACT, MAPPING_SUPPORTED_TRANSFORM)
        and d["canonical_entity"] in SEMANTIC_ENTITIES
    ]

    return {
        "source_system": SOURCE_B_SYSTEM_ID,
        "draft_path": "artifacts/stage-03/source-b-mapping-draft.yaml",
        "decision_counts": counts,
        "decisions": decisions,
        "clinical_exact_or_supported_transform_count": len(clinical_exact),
        "invented_exact_clinical_mappings": False,
        "notes": [
            "HYPOTHESIS/UNKNOWN/CANDIDATE/UNRESOLVED are preserved — not promoted to EXACT.",
            "CONFIRMED_SCHEMA is structural only; clinical entities stay non-EXACT unless draft says EXACT.",
            "Only EXACT/SUPPORTED_TRANSFORM may populate semantic Subject/Observation fields.",
        ],
    }


def register_source_b_system(repo_root: Path) -> dict[str, Any]:
    """Register source_system kgz_raw only — no clinical semantic load from HYPOTHESIS maps."""
    settings = load_canonical_settings()
    inserted = False
    error: str | None = None
    try:
        with canonical_connection(settings) as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("SET ROLE canonical_loader")
                except Exception:  # noqa: BLE001
                    pass
                cur.execute(
                    """
                    INSERT INTO canonical_evidence.source_system
                      (source_system_id, source_label, audit_stage_reference)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_system_id) DO NOTHING
                    """,
                    (SOURCE_B_SYSTEM_ID, "Source B kgz_raw", "stage-02"),
                )
                inserted = cur.rowcount > 0
                cur.execute("RESET ROLE")
    except Exception as exc:  # noqa: BLE001
        error = type(exc).__name__

    return {
        "source_system_id": SOURCE_B_SYSTEM_ID,
        "registered": error is None,
        "inserted": inserted,
        "error_type": error,
        "clinical_rows_loaded": 0,
        "reason": (
            "No EXACT/SUPPORTED_TRANSFORM clinical mappings available; "
            "semantic Subject/Observation load skipped."
        ),
    }


def empty_relation_accounting() -> dict[str, dict[str, int]]:
    return {}


def integrate_source_b(repo_root: Path) -> dict[str, Any]:
    """Produce mapping decisions + PARTIAL integration (register source_system only)."""
    root = Path(repo_root)
    decisions = build_mapping_decisions(root)
    identity = load_stage02_identity(root)
    registration = register_source_b_system(root)

    clinical_loadable = int(decisions.get("clinical_exact_or_supported_transform_count") or 0)
    status = SOURCE_B_INTEGRATION_PARTIAL
    if clinical_loadable > 0:
        # Still PARTIAL in v0.1 — clinical EXACT load is out of scope without owner gate.
        status = SOURCE_B_INTEGRATION_PARTIAL

    relation_accounting: dict[str, Any] = {
        "note": "No Source B clinical relations loaded into semantic canonical fields in v0.1.",
        "relations": {},
        "truncated_total": 0,
        "unaccounted_total": 0,
    }

    return {
        "status": status,
        "finished_at": _now(),
        "mapping_decisions": decisions,
        "stage02_identity_verdict": (identity.get("identity_verdict") or {}).get("verdict")
        if isinstance(identity.get("identity_verdict"), dict)
        else identity.get("identity_verdict"),
        "registration": registration,
        "relation_accounting": relation_accounting,
        "canonical_load": {
            "status": status,
            "subjects_loaded": 0,
            "encounters_loaded": 0,
            "observations_loaded": 0,
            "observation_components_loaded": 0,
            "source_system_registered": bool(registration.get("registered")),
            "migration_0005": False,
            "identity_merge": False,
        },
    }
