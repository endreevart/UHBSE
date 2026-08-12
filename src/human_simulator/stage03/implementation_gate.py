"""Explicit state of the Stage 03 implementation gate.

Stage 03 stayed in planning until the user opened the implementation gate for a single
authorised changeset. The gate is declared here rather than inferred, so that no verifier
can drift into accepting implementation artifacts by accident.

While the gate is open, only the paths in ``CHANGESET_01_AUTHORIZED_PATHS`` are permitted to
exist. Anything else that looks like DDL, migrations or ETL still fails the plan gate.
"""

from __future__ import annotations

from pathlib import Path

IMPLEMENTATION_GATE_OPEN = True
AUTHORIZED_CHANGESET_ID = "stage-03-implementation-changeset-01"
AUTHORIZED_CHANGESET_VERSION = "0.1"
AUTHORIZED_CHANGESET_TITLE = "Canonical Storage Foundation"

# Design baseline and implementation plan remain frozen inputs while the gate is open.
FROZEN_DESIGN_VERSION = "0.7.4"
FROZEN_IMPLEMENTATION_PLAN_VERSION = "0.3.5"

# Repository paths that Changeset 01 is authorised to introduce. Everything outside this
# allowlist is still treated as forbidden implementation material.
CHANGESET_01_AUTHORIZED_PATHS: tuple[str, ...] = (
    "migrations",
    "migrations/canonical",
    "migrations/canonical/0001_roles_and_schema.sql",
    "migrations/canonical/0002_pilot_evidence_tables.sql",
    "migrations/canonical/0003_pilot_grants.sql",
    "src/human_simulator/canonical",
)

# Capabilities that remain closed even with the gate open. Changeset 01 is empty storage
# plus migrations; nothing may read or move clinical rows.
STILL_FORBIDDEN_CAPABILITIES: tuple[str, ...] = (
    "clinical_row_read",
    "extraction",
    "etl_execution",
    "pilot_cohort_creation",
    "canonical_data_load",
    "raw_database_mutation",
    "stage_01_02_artifact_mutation",
    "source_b_connection",
    "patient_linkage_or_merge",
    "simulation_or_prediction",
    "design_or_plan_mutation",
)


def is_authorized_changeset_path(relative_path: str) -> bool:
    normalized = Path(relative_path).as_posix()
    return any(
        normalized == allowed or normalized.startswith(f"{allowed}/")
        for allowed in CHANGESET_01_AUTHORIZED_PATHS
    )


def unauthorized_paths(candidates: list[str]) -> list[str]:
    return sorted(path for path in candidates if not is_authorized_changeset_path(path))
