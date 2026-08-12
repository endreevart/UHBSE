"""Live migration suite for the canonical pilot storage.

Every test in this module runs against a disposable database that the suite creates and
drops. Constraint probes use synthetic, non-clinical values inside transactions that are
always rolled back, so no row is ever loaded anywhere. The dev canonical database
``uhbse_canonical_dev`` is only ever read for row counts, which must all be zero.

The suite skips, by prerequisite name only, when no canonical endpoint is configured.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from human_simulator.canonical.connection import canonical_connection, postgres_major_version
from human_simulator.canonical.constants import (
    ACCEPTED_MIGRATION_SHA256,
    CANONICAL_POSTGRES_VERSION,
    CANONICAL_SCHEMA,
    HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES,
    MIGRATION_HISTORY_TABLE,
    MIGRATION_SCHEMA,
    PILOT_TABLE_LOAD_ORDER,
    PROVENANCE_BEARING_TABLES,
    ROLE_LOADER,
    ROLE_MIGRATOR,
    ROLE_VALIDATOR_RO,
)
from human_simulator.canonical.definition_baseline import load_baseline
from human_simulator.canonical.migrations import (
    MigrationError,
    applied_migrations,
    apply_migrations,
    contract_violations,
    discover_migrations,
    introspect_schema,
    migration_immutability,
    permission_violations,
    role_state,
    row_counts,
    verify_permissions,
    verify_schema,
)
from human_simulator.canonical.schema_contract import PILOT_TABLES, contract_fingerprint
from human_simulator.canonical.settings import (
    CanonicalConnectionSettings,
    load_canonical_settings,
    missing_canonical_prerequisites,
)

pytestmark = [pytest.mark.integration, pytest.mark.canonical_migration]

TEST_DATABASE = "uhbse_canonical_migration_test"

# Module-scoped fixtures cannot depend on the function-scoped ``repo_root`` fixture.
REPO_ROOT = Path(__file__).resolve().parents[1]

VALID_PROVENANCE = {
    "record_origin": "OBSERVED",
    "source_system": "test_source",
    "source_schema": "test_schema",
    "source_relation": "test_relation",
    "source_record_locator": "0" * 64,
    "transformation_id": "test_transformation",
    "transformation_version": "0.0.0",
    "transformed_at": "2026-01-01T00:00:00+00:00",
    "input_artifact_sha256": "1" * 64,
    "confidence": "test",
    "mapping_status": "CANDIDATE",
}


def _missing_prerequisites() -> list[str]:
    missing = missing_canonical_prerequisites()
    if missing:
        return missing
    try:
        settings = load_canonical_settings()
    except Exception:  # noqa: BLE001 - reported as a named prerequisite
        return ["CANONICAL_DB_SETTINGS_INVALID"]
    try:
        with canonical_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception:  # noqa: BLE001 - reported as a named prerequisite
        return [f"CANONICAL_DB_UNREACHABLE_AT_{settings.safe_target()}"]
    return []


@pytest.fixture(scope="module")
def live_settings() -> CanonicalConnectionSettings:
    missing = _missing_prerequisites()
    if missing:
        pytest.skip("missing canonical prerequisites: " + ", ".join(missing))
    return load_canonical_settings()


@pytest.fixture(scope="module")
def disposable_database(live_settings: CanonicalConnectionSettings) -> Iterator[CanonicalConnectionSettings]:
    """Create an empty database, yield its settings, then drop it."""
    admin = load_canonical_settings(database_override="postgres")
    with canonical_connection(admin) as conn, conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    try:
        yield load_canonical_settings(database_override=TEST_DATABASE)
    finally:
        with canonical_connection(admin) as conn, conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')


@pytest.fixture(scope="module")
def migrated(
    disposable_database: CanonicalConnectionSettings,
) -> Iterator[dict[str, Any]]:
    with canonical_connection(disposable_database) as conn:
        result = apply_migrations(conn, REPO_ROOT)
        yield {"apply_result": result, "settings": disposable_database}


@pytest.fixture
def conn(migrated: dict[str, Any]) -> Iterator[Any]:
    with canonical_connection(migrated["settings"]) as connection:
        yield connection


def _insert(cur: Any, table: str, values: dict[str, Any]) -> None:
    columns = ", ".join(values)
    placeholders = ", ".join(["%s"] * len(values))
    payload = [
        json.dumps(value) if isinstance(value, dict) else value for value in values.values()
    ]
    cur.execute(
        f"INSERT INTO {CANONICAL_SCHEMA}.{table} ({columns}) VALUES ({placeholders})",  # noqa: S608
        payload,
    )


def _matching_provenance(row: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Source-backed provenance that agrees with a source_record row's own columns."""
    return {
        **VALID_PROVENANCE,
        "source_system": row["source_system_id"],
        "source_schema": row["source_schema"],
        "source_relation": row["source_relation"],
        "source_record_locator": row["source_record_locator"],
        **overrides,
    }


def _seed_parents(cur: Any) -> None:
    _insert(cur, "source_system", {"source_system_id": "test_source", "source_label": "Test"})
    _insert(
        cur,
        "subject",
        {
            "subject_id": "subject-1",
            "source_system_id": "test_source",
            "source_subject_key": "key-1",
            "provenance": VALID_PROVENANCE,
        },
    )
    _insert(
        cur,
        "observation",
        {
            "observation_id": "observation-1",
            "subject_id": "subject-1",
            "data_level": "OBSERVATION_HEADER",
            "missingness_reason": "no evidenced clinical time",
            "provenance": VALID_PROVENANCE,
        },
    )


# --------------------------------------------------------------------------------------
# Migration application
# --------------------------------------------------------------------------------------


def test_migrations_apply_to_an_empty_database(migrated: dict[str, Any], repo_root: Path) -> None:
    expected = [item.identifier for item in discover_migrations(repo_root)]
    assert migrated["apply_result"]["applied_in_this_run"] == expected
    assert migrated["apply_result"]["already_applied_before_run"] == []
    assert migrated["apply_result"]["down_migrations_supported"] is False


def test_server_runs_the_planned_postgresql_major_version(conn: Any) -> None:
    assert str(postgres_major_version(conn)) == CANONICAL_POSTGRES_VERSION


def test_schema_matches_the_pilot_canonical_model(conn: Any) -> None:
    result = verify_schema(conn, REPO_ROOT)
    assert result["violations"] == []
    assert result["status"] == "PASS"
    assert result["contract_fingerprint"] == contract_fingerprint()
    assert result["definitions_verified"] is True
    assert result["definition_violations"] == []


def test_pinned_definitions_describe_the_accepted_migration_bytes(conn: Any) -> None:
    """The baseline must be traceable to the reviewed SQL, not to whatever exists."""
    document = load_baseline(REPO_ROOT)
    declared = {item.path.name: item.sha256 for item in discover_migrations(REPO_ROOT)}
    assert document["produced_by_migrations"] == declared
    for name, accepted in ACCEPTED_MIGRATION_SHA256.items():
        assert document["produced_by_migrations"][name] == accepted


def test_published_migrations_are_byte_identical_to_their_accepted_hashes() -> None:
    result = migration_immutability(REPO_ROOT)
    assert result["violations"] == []
    assert result["status"] == "PASS"
    assert result["hardening_migration_present"] is True


def test_every_pinned_constraint_definition_is_present_live(conn: Any) -> None:
    live = introspect_schema(conn)
    pinned = load_baseline(REPO_ROOT)["definitions"]["constraint_definitions"]
    assert live["constraint_definitions"] == pinned
    # Non-vacuity: the pinned set really does contain the hardening constraints.
    for table in PROVENANCE_BEARING_TABLES:
        for suffix in HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES:
            assert f"{table}{suffix}" in pinned[table]


def test_no_table_exists_outside_the_pilot_scope(conn: Any) -> None:
    actual = introspect_schema(conn)
    assert sorted(actual["tables"]) == sorted(PILOT_TABLE_LOAD_ORDER)
    assert len(actual["tables"]) == 7
    assert "provenance" not in actual["tables"]


def test_migration_history_lives_outside_the_evidence_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema FROM information_schema.tables
            WHERE table_name = %s
            """,
            (MIGRATION_HISTORY_TABLE,),
        )
        schemas = {row[0] for row in cur.fetchall()}
    assert schemas == {MIGRATION_SCHEMA}


def test_database_is_empty_after_migration(conn: Any) -> None:
    counts = row_counts(conn)
    assert set(counts) == set(PILOT_TABLE_LOAD_ORDER)
    assert all(value == 0 for value in counts.values())


def test_reapplying_migrations_changes_nothing(conn: Any, repo_root: Path) -> None:
    before_schema = introspect_schema(conn)
    before_history = applied_migrations(conn)

    second = apply_migrations(conn, repo_root)

    assert second["applied_in_this_run"] == []
    assert introspect_schema(conn) == before_schema
    assert applied_migrations(conn) == before_history
    assert all(value == 0 for value in row_counts(conn).values())


def test_checksum_drift_on_an_applied_migration_fails_closed(
    conn: Any, repo_root: Path, tmp_path: Path
) -> None:
    import shutil

    workspace = tmp_path / "drifted"
    shutil.copytree(repo_root / "migrations", workspace / "migrations")
    target = workspace / "migrations" / "canonical" / "0002_pilot_evidence_tables.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- drifted\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="checksum drift"):
        apply_migrations(conn, workspace)


def test_history_records_the_contract_fingerprint(conn: Any) -> None:
    history = applied_migrations(conn)
    assert sorted(history) == [item.version for item in discover_migrations(REPO_ROOT)]
    assert {entry["contract_fingerprint"] for entry in history.values()} == {contract_fingerprint()}


# --------------------------------------------------------------------------------------
# Negative schema-drift probes. PostgreSQL DDL is transactional, so every probe mutates the
# disposable schema inside a transaction that is always rolled back.
# --------------------------------------------------------------------------------------


def _drifted_verification(conn: Any, statements: tuple[str, ...]) -> dict[str, Any]:
    """Apply drift, verify, roll back. Returns the verification result seen under drift."""
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
            return verify_schema(conn, REPO_ROOT)
    finally:
        conn.rollback()
        conn.autocommit = True


def _drifted_permissions(conn: Any, statements: tuple[str, ...]) -> dict[str, Any]:
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
            return verify_permissions(conn)
    finally:
        conn.rollback()
        conn.autocommit = True


def test_a_constraint_replaced_by_check_true_under_the_same_name_fails(conn: Any) -> None:
    result = _drifted_verification(
        conn,
        (
            f"ALTER TABLE {CANONICAL_SCHEMA}.subject_characteristic "
            "DROP CONSTRAINT subject_characteristic_typed_value_xor",
            f"ALTER TABLE {CANONICAL_SCHEMA}.subject_characteristic "
            "ADD CONSTRAINT subject_characteristic_typed_value_xor CHECK (TRUE)",
        ),
    )
    assert result["status"] == "FAIL"
    assert any(
        "subject_characteristic_typed_value_xor" in problem
        for problem in result["definition_violations"]
    )


def test_a_changed_foreign_key_definition_fails(conn: Any) -> None:
    result = _drifted_verification(
        conn,
        (
            f"ALTER TABLE {CANONICAL_SCHEMA}.observation "
            "DROP CONSTRAINT observation_subject_fkey",
            f"ALTER TABLE {CANONICAL_SCHEMA}.observation "
            "ADD CONSTRAINT observation_subject_fkey FOREIGN KEY (subject_id) "
            f"REFERENCES {CANONICAL_SCHEMA}.subject (subject_id) ON DELETE CASCADE",
        ),
    )
    assert result["status"] == "FAIL"
    assert any(
        "observation_subject_fkey" in problem for problem in result["definition_violations"]
    )


def test_an_extra_index_fails(conn: Any) -> None:
    result = _drifted_verification(
        conn,
        (
            f"CREATE INDEX observation_status_idx ON {CANONICAL_SCHEMA}.observation (status)",
        ),
    )
    assert result["status"] == "FAIL"
    assert any("observation_status_idx" in problem for problem in result["violations"])


def test_a_changed_index_definition_fails(conn: Any) -> None:
    result = _drifted_verification(
        conn,
        (
            f"DROP INDEX {CANONICAL_SCHEMA}.observation_subject_idx",
            "CREATE INDEX observation_subject_idx ON "
            f"{CANONICAL_SCHEMA}.observation (subject_id, status)",
        ),
    )
    assert result["status"] == "FAIL"
    assert any(
        "observation_subject_idx" in problem for problem in result["definition_violations"]
    )


def test_a_reordered_enum_fails(conn: Any) -> None:
    """Enum order is part of the contract, not just the value set."""
    live = introspect_schema(conn)
    tampered = json.loads(json.dumps(live))
    values = tampered["enums"]["canonical_mapping_status"]
    tampered["enums"]["canonical_mapping_status"] = list(reversed(values))
    assert contract_violations(tampered)


def test_loader_gaining_update_or_delete_fails(conn: Any) -> None:
    for privilege in ("UPDATE", "DELETE"):
        result = _drifted_permissions(
            conn,
            (
                f"GRANT {privilege} ON {CANONICAL_SCHEMA}.subject TO {ROLE_LOADER}",
            ),
        )
        assert result["status"] == "FAIL", privilege
        assert any(ROLE_LOADER in problem for problem in result["violations"]), privilege


def test_validator_gaining_insert_or_create_fails(conn: Any) -> None:
    insert_result = _drifted_permissions(
        conn,
        (f"GRANT INSERT ON {CANONICAL_SCHEMA}.subject TO {ROLE_VALIDATOR_RO}",),
    )
    assert insert_result["status"] == "FAIL"
    assert any(ROLE_VALIDATOR_RO in problem for problem in insert_result["violations"])

    create_result = _drifted_permissions(
        conn,
        (f"GRANT CREATE ON SCHEMA {CANONICAL_SCHEMA} TO {ROLE_VALIDATOR_RO}",),
    )
    assert create_result["status"] == "FAIL"
    assert any(ROLE_VALIDATOR_RO in problem for problem in create_result["violations"])


def test_a_changed_table_owner_fails(conn: Any) -> None:
    statements = (
        f"ALTER TABLE {CANONICAL_SCHEMA}.subject OWNER TO {ROLE_MIGRATOR}",
    )
    schema_result = _drifted_verification(conn, statements)
    assert schema_result["status"] == "FAIL"
    assert any("owner" in problem for problem in schema_result["violations"])

    permission_result = _drifted_permissions(conn, statements)
    assert permission_result["status"] == "FAIL"
    assert any("owner" in problem for problem in permission_result["violations"])


def test_the_verifier_never_repairs_detected_drift(conn: Any) -> None:
    """After a drift probe rolls back, the schema is intact because nothing was rewritten."""
    before = introspect_schema(conn)
    drifted = _drifted_verification(
        conn,
        (
            f"CREATE INDEX observation_repair_probe_idx ON {CANONICAL_SCHEMA}.observation (status)",
        ),
    )
    assert drifted["status"] == "FAIL"
    assert introspect_schema(conn) == before
    assert verify_schema(conn, REPO_ROOT)["status"] == "PASS"


# --------------------------------------------------------------------------------------
# Constraint enforcement. Every probe is rolled back.
# --------------------------------------------------------------------------------------


def _expect_violation(conn: Any, action: Any) -> str:
    """Run a probe that must be rejected, then roll back."""
    import psycopg

    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            _seed_parents(cur)
            with pytest.raises(psycopg.errors.IntegrityError) as excinfo:
                action(cur)
        return str(excinfo.value)
    finally:
        conn.rollback()
        conn.autocommit = True


def _expect_accepted(conn: Any, action: Any) -> None:
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            _seed_parents(cur)
            action(cur)
    finally:
        conn.rollback()
        conn.autocommit = True


def test_primary_key_rejects_a_duplicate_canonical_id(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "source_system", {"source_system_id": "test_source", "source_label": "Dup"})

    assert "source_system_pkey" in _expect_violation(conn, probe)


def test_foreign_key_rejects_an_orphan_child(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(
            cur,
            "observation_component",
            {
                "component_id": "component-orphan",
                "observation_id": "missing-observation",
                "provenance": VALID_PROVENANCE,
            },
        )

    assert "observation_component_observation_fkey" in _expect_violation(conn, probe)


def test_subject_source_local_identity_is_unique(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(
            cur,
            "subject",
            {
                "subject_id": "subject-2",
                "source_system_id": "test_source",
                "source_subject_key": "key-1",
                "provenance": VALID_PROVENANCE,
            },
        )

    assert "subject_source_local_identity_unique" in _expect_violation(conn, probe)


def test_source_record_locator_is_unique(conn: Any) -> None:
    def probe(cur: Any) -> None:
        for index in (1, 2):
            row = {
                "source_record_id": f"record-{index}",
                "source_system_id": "test_source",
                "source_schema": "test_schema",
                "source_relation": "test_relation",
                "source_record_locator": "a" * 64,
                "locator_scheme": "deterministic_hmac_locator",
                "locator_key_version": "v1",
            }
            _insert(cur, "source_record", {**row, "provenance": _matching_provenance(row)})

    assert "source_record_locator_unique" in _expect_violation(conn, probe)


def test_locator_scheme_is_restricted_to_the_contract_value(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(
            cur,
            "source_record",
            {
                "source_record_id": "record-bad-scheme",
                "source_system_id": "test_source",
                "source_schema": "test_schema",
                "source_relation": "test_relation",
                "source_record_locator": "b" * 64,
                "locator_scheme": "plain_primary_key",
                "locator_key_version": "v1",
                "provenance": VALID_PROVENANCE,
            },
        )

    assert "source_record_locator_scheme_allowed" in _expect_violation(conn, probe)


def _characteristic(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "characteristic_id": "characteristic-1",
        "subject_id": "subject-1",
        "characteristic_code": "source_sex",
        "raw_code": "sex",
        "raw_value": "F",
        "categorical_value": "F",
        "status": "CANDIDATE",
        "provenance": VALID_PROVENANCE,
    }
    values.update(overrides)
    return {key: value for key, value in values.items() if value is not None}


def test_typed_value_xor_accepts_exactly_one_value(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic())

    _expect_accepted(conn, probe)


def test_typed_value_xor_rejects_two_values(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(text_value="female"))

    assert "subject_characteristic_typed_value_xor" in _expect_violation(conn, probe)


def test_typed_value_xor_rejects_zero_values(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(categorical_value=None))

    assert "subject_characteristic_typed_value_xor" in _expect_violation(conn, probe)


def test_characteristic_identity_requires_a_code_or_a_concept(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(characteristic_code=None))

    assert "subject_characteristic_identity_present" in _expect_violation(conn, probe)


def test_characteristic_raw_value_cannot_be_blank(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(raw_value="   "))

    assert "subject_characteristic_raw_value_preserved" in _expect_violation(conn, probe)


def test_out_of_pilot_concept_reference_is_rejected(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(concept_id="concept-1"))

    assert "subject_characteristic_concept_null_in_pilot" in _expect_violation(conn, probe)


def test_deferred_provider_reference_is_rejected(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(
            cur,
            "encounter",
            {
                "encounter_id": "encounter-1",
                "subject_id": "subject-1",
                "provider_id": "provider-1",
                "data_level": "PATIENT_EVENT",
                "missingness_reason": "no evidenced clinical time",
                "provenance": VALID_PROVENANCE,
            },
        )

    assert "encounter_provider_null_in_pilot" in _expect_violation(conn, probe)


def test_deferred_observation_encounter_reference_is_rejected(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(
            cur,
            "observation",
            {
                "observation_id": "observation-2",
                "subject_id": "subject-1",
                "encounter_id": "encounter-1",
                "data_level": "OBSERVATION_HEADER",
                "missingness_reason": "deferred",
                "provenance": VALID_PROVENANCE,
            },
        )

    assert "observation_encounter_null_in_pilot" in _expect_violation(conn, probe)


def test_missing_clinical_time_requires_a_documented_reason(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(
            cur,
            "encounter",
            {
                "encounter_id": "encounter-2",
                "subject_id": "subject-1",
                "data_level": "PATIENT_EVENT",
                "provenance": VALID_PROVENANCE,
            },
        )

    assert "encounter_missing_clinical_time_documented" in _expect_violation(conn, probe)


def test_documented_clinical_time_absence_is_accepted(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(
            cur,
            "encounter",
            {
                "encounter_id": "encounter-3",
                "subject_id": "subject-1",
                "data_level": "PATIENT_EVENT",
                "missingness_reason": "no evidenced clinical start in the source schema",
                "recorded_at": "2026-01-01T00:00:00+00:00",
                "provenance": VALID_PROVENANCE,
            },
        )

    _expect_accepted(conn, probe)


def test_data_level_enum_rejects_an_unknown_value(conn: Any) -> None:
    import psycopg

    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            _seed_parents(cur)
            with pytest.raises(psycopg.errors.InvalidTextRepresentation):
                _insert(
                    cur,
                    "encounter",
                    {
                        "encounter_id": "encounter-4",
                        "subject_id": "subject-1",
                        "data_level": "NOT_A_LEVEL",
                        "missingness_reason": "probe",
                        "provenance": VALID_PROVENANCE,
                    },
                )
    finally:
        conn.rollback()
        conn.autocommit = True


def test_provenance_rejects_a_missing_required_field(conn: Any) -> None:
    incomplete = {k: v for k, v in VALID_PROVENANCE.items() if k != "input_artifact_sha256"}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=incomplete))

    assert "subject_characteristic_provenance_profile_valid" in _expect_violation(conn, probe)


def test_provenance_rejects_a_forbidden_evidence_record_origin(conn: Any) -> None:
    synthetic = {**VALID_PROVENANCE, "record_origin": "SYNTHETIC"}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=synthetic))

    assert "subject_characteristic_provenance_profile_valid" in _expect_violation(conn, probe)


def test_computed_provenance_rejects_a_source_record_locator(conn: Any) -> None:
    computed = {
        "record_origin": "DERIVED",
        "input_record_references": ["a"],
        "computation_method": "test",
        "computation_version": "0.0.0",
        "uncertainty": {"kind": "none"},
        "transformation_id": "test_transformation",
        "transformation_version": "0.0.0",
        "transformed_at": "2026-01-01T00:00:00+00:00",
        "input_artifact_sha256": "1" * 64,
        "confidence": "test",
        "mapping_status": "CANDIDATE",
        "source_record_locator": "0" * 64,
    }

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=computed))

    assert "subject_characteristic_provenance_profile_valid" in _expect_violation(conn, probe)


def test_provenance_rejects_an_unknown_mapping_status(conn: Any) -> None:
    bad_status = {**VALID_PROVENANCE, "mapping_status": "TOTALLY_CONFIRMED"}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=bad_status))

    assert "subject_characteristic_provenance_profile_valid" in _expect_violation(conn, probe)


# --------------------------------------------------------------------------------------
# Provenance hardening added by migration 0004. Every origin profile is inserted for real;
# every rule has a matching rejection probe. All probes are rolled back.
# --------------------------------------------------------------------------------------

COMPUTED_PROVENANCE = {
    "record_origin": "DERIVED",
    "input_record_references": ["source-record-1"],
    "computation_method": "test_method",
    "computation_version": "0.0.0",
    "uncertainty": {"kind": "none"},
    "transformation_id": "test_transformation",
    "transformation_version": "0.0.0",
    "transformed_at": "2026-01-01T00:00:00+00:00",
    "input_artifact_sha256": "1" * 64,
    "confidence": "test",
    "mapping_status": "CANDIDATE",
}

ORIGIN_PROFILES: dict[str, dict[str, Any]] = {
    "OBSERVED": VALID_PROVENANCE,
    "CORRECTED": {
        **VALID_PROVENANCE,
        "record_origin": "CORRECTED",
        "prior_record_reference": "characteristic-0",
        "correction_reason": "test correction",
    },
    "NORMALIZED": {
        **VALID_PROVENANCE,
        "record_origin": "NORMALIZED",
        "normalization_lineage": ["raw", "normalized"],
    },
    "ANNOTATED": {
        **VALID_PROVENANCE,
        "record_origin": "ANNOTATED",
        "annotation_text": "test annotation",
        "annotated_at": "2026-01-01T00:00:00+00:00",
    },
    "DERIVED": COMPUTED_PROVENANCE,
    "IMPUTED": {**COMPUTED_PROVENANCE, "record_origin": "IMPUTED"},
}


@pytest.mark.parametrize("origin", sorted(ORIGIN_PROFILES))
def test_each_accepted_origin_profile_is_insertable(conn: Any, origin: str) -> None:
    def probe(cur: Any) -> None:
        _insert(
            cur,
            "subject_characteristic",
            _characteristic(provenance=ORIGIN_PROFILES[origin]),
        )

    _expect_accepted(conn, probe)


@pytest.mark.parametrize(
    ("origin", "omitted"),
    [
        ("CORRECTED", "prior_record_reference"),
        ("CORRECTED", "correction_reason"),
        ("NORMALIZED", "normalization_lineage"),
        ("ANNOTATED", "annotation_text"),
        ("ANNOTATED", "annotated_at"),
    ],
)
def test_origin_specific_fields_are_required(conn: Any, origin: str, omitted: str) -> None:
    provenance = {k: v for k, v in ORIGIN_PROFILES[origin].items() if k != omitted}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=provenance))

    message = _expect_violation(conn, probe)
    assert "subject_characteristic_provenance_origin_specific_fields" in message


@pytest.mark.parametrize(
    ("origin", "nulled"),
    [
        ("CORRECTED", "prior_record_reference"),
        ("NORMALIZED", "normalization_lineage"),
        ("ANNOTATED", "annotated_at"),
    ],
)
def test_origin_specific_fields_may_not_be_json_null(conn: Any, origin: str, nulled: str) -> None:
    provenance = {**ORIGIN_PROFILES[origin], nulled: None}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=provenance))

    message = _expect_violation(conn, probe)
    assert "subject_characteristic_provenance_origin_specific_fields" in message


@pytest.mark.parametrize("field", ["source_record_locator", "confidence", "mapping_status"])
def test_a_required_field_set_to_json_null_is_rejected(conn: Any, field: str) -> None:
    """A present key with a JSON null value carries no value and must not satisfy the rule."""
    provenance = {**VALID_PROVENANCE, field: None}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=provenance))

    message = _expect_violation(conn, probe)
    assert "subject_characteristic_provenance_required_values_present" in message


@pytest.mark.parametrize("field", ["input_record_references", "computation_method"])
def test_a_required_computed_field_set_to_json_null_is_rejected(conn: Any, field: str) -> None:
    provenance = {**COMPUTED_PROVENANCE, field: None}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=provenance))

    message = _expect_violation(conn, probe)
    assert "subject_characteristic_provenance_required_values_present" in message


def test_a_source_backed_row_may_not_carry_computed_fields(conn: Any) -> None:
    mixed = {**VALID_PROVENANCE, "computation_method": "test", "computation_version": "0.0.0"}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=mixed))

    message = _expect_violation(conn, probe)
    assert "subject_characteristic_provenance_profiles_exclusive" in message


def test_a_computed_row_may_not_carry_source_fields(conn: Any) -> None:
    mixed = {**COMPUTED_PROVENANCE, "source_schema": "test_schema"}

    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(provenance=mixed))

    message = _expect_violation(conn, probe)
    assert "subject_characteristic_provenance_profiles_exclusive" in message


@pytest.mark.parametrize("origin", ["SYNTHETIC", "PREDICTED"])
@pytest.mark.parametrize("table", PROVENANCE_BEARING_TABLES)
def test_simulation_and_prediction_origins_are_rejected_in_every_evidence_table(
    conn: Any, table: str, origin: str
) -> None:
    provenance = {**VALID_PROVENANCE, "record_origin": origin}
    values = {**ORPHAN_FREE_ROWS[table], "provenance": provenance}

    def probe(cur: Any) -> None:
        _insert(cur, table, values)

    message = _expect_violation(conn, probe)
    assert f"{table}_provenance" in message


def test_characteristic_status_must_match_provenance_mapping_status(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "subject_characteristic", _characteristic(status="HYPOTHESIS"))

    message = _expect_violation(conn, probe)
    assert "subject_characteristic_status_matches_provenance" in message


def test_characteristic_status_matching_provenance_is_accepted(conn: Any) -> None:
    provenance = {**VALID_PROVENANCE, "mapping_status": "HYPOTHESIS"}

    def probe(cur: Any) -> None:
        _insert(
            cur,
            "subject_characteristic",
            _characteristic(status="HYPOTHESIS", provenance=provenance),
        )

    _expect_accepted(conn, probe)


def _source_record(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "source_record_id": "record-consistency",
        "source_system_id": "test_source",
        "source_schema": "test_schema",
        "source_relation": "test_relation",
        "source_record_locator": "d" * 64,
        "locator_scheme": "deterministic_hmac_locator",
        "locator_key_version": "v1",
    }
    values["provenance"] = _matching_provenance(values)
    values.update(overrides)
    return values


def test_source_record_columns_consistent_with_provenance_are_accepted(conn: Any) -> None:
    def probe(cur: Any) -> None:
        _insert(cur, "source_record", _source_record())

    _expect_accepted(conn, probe)


def test_source_record_accepts_a_schema_qualified_relation_in_provenance(conn: Any) -> None:
    """record-construction-contract.yaml populates provenance with the qualified relation."""
    row = _source_record()
    qualified = _matching_provenance(row, source_relation="test_schema.test_relation")

    def probe(cur: Any) -> None:
        _insert(cur, "source_record", {**row, "provenance": qualified})

    _expect_accepted(conn, probe)


@pytest.mark.parametrize(
    ("provenance_key", "value"),
    [
        ("source_system", "other_source"),
        ("source_schema", "other_schema"),
        ("source_relation", "other_relation"),
        ("source_record_locator", "e" * 64),
    ],
)
def test_source_record_columns_contradicting_provenance_are_rejected(
    conn: Any, provenance_key: str, value: str
) -> None:
    row = _source_record()
    provenance = _matching_provenance(row, **{provenance_key: value})

    def probe(cur: Any) -> None:
        _insert(cur, "source_record", {**row, "provenance": provenance})

    message = _expect_violation(conn, probe)
    assert "source_record_provenance_matches_columns" in message


# Minimal valid rows whose parents exist after ``_seed_parents``, used to probe a rule on
# every provenance-bearing table rather than only on one.
ORPHAN_FREE_ROWS: dict[str, dict[str, Any]] = {
    "source_record": {
        "source_record_id": "record-origin-probe",
        "source_system_id": "test_source",
        "source_schema": "test_schema",
        "source_relation": "test_relation",
        "source_record_locator": "f" * 64,
        "locator_scheme": "deterministic_hmac_locator",
        "locator_key_version": "v1",
    },
    "subject": {
        "subject_id": "subject-origin-probe",
        "source_system_id": "test_source",
        "source_subject_key": "key-origin-probe",
    },
    "subject_characteristic": {
        "characteristic_id": "characteristic-origin-probe",
        "subject_id": "subject-1",
        "characteristic_code": "source_sex",
        "raw_code": "sex",
        "raw_value": "F",
        "categorical_value": "F",
        "status": "CANDIDATE",
    },
    "encounter": {
        "encounter_id": "encounter-origin-probe",
        "subject_id": "subject-1",
        "data_level": "PATIENT_EVENT",
        "missingness_reason": "probe",
    },
    "observation": {
        "observation_id": "observation-origin-probe",
        "subject_id": "subject-1",
        "data_level": "OBSERVATION_HEADER",
        "missingness_reason": "probe",
    },
    "observation_component": {
        "component_id": "component-origin-probe",
        "observation_id": "observation-1",
    },
}


# Minimal rows whose foreign key deliberately points at a non-existent parent.
ORPHAN_ROWS: dict[str, dict[str, Any]] = {
    "source_record": _source_record(
        source_record_id="orphan-record",
        source_system_id="no-such-source",
        source_record_locator="c" * 64,
        provenance=_matching_provenance(
            {
                "source_system_id": "no-such-source",
                "source_schema": "test_schema",
                "source_relation": "test_relation",
                "source_record_locator": "c" * 64,
            }
        ),
    ),
    "subject": {
        "subject_id": "orphan-subject",
        "source_system_id": "no-such-source",
        "source_subject_key": "orphan-key",
        "provenance": VALID_PROVENANCE,
    },
    "subject_characteristic": {
        "characteristic_id": "orphan-characteristic",
        "subject_id": "no-such-subject",
        "characteristic_code": "source_sex",
        "raw_code": "sex",
        "raw_value": "F",
        "categorical_value": "F",
        "status": "CANDIDATE",
        "provenance": VALID_PROVENANCE,
    },
    "encounter": {
        "encounter_id": "orphan-encounter",
        "subject_id": "no-such-subject",
        "data_level": "PATIENT_EVENT",
        "missingness_reason": "probe",
        "provenance": VALID_PROVENANCE,
    },
    "observation": {
        "observation_id": "orphan-observation",
        "subject_id": "no-such-subject",
        "data_level": "OBSERVATION_HEADER",
        "missingness_reason": "probe",
        "provenance": VALID_PROVENANCE,
    },
    "observation_component": {
        "component_id": "orphan-component",
        "observation_id": "no-such-observation",
        "provenance": VALID_PROVENANCE,
    },
}


def test_every_declared_foreign_key_rejects_an_orphan(conn: Any) -> None:
    """Load order is enforced: no child row can exist before its parent."""
    import psycopg

    expected = {table.name for table in PILOT_TABLES if table.foreign_keys}
    assert set(ORPHAN_ROWS) == expected

    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            _seed_parents(cur)
            for table_name, values in sorted(ORPHAN_ROWS.items()):
                cur.execute("SAVEPOINT probe")
                with pytest.raises(psycopg.errors.ForeignKeyViolation) as excinfo:
                    _insert(cur, table_name, values)
                assert table_name in str(excinfo.value)
                cur.execute("ROLLBACK TO SAVEPOINT probe")
    finally:
        conn.rollback()
        conn.autocommit = True


# --------------------------------------------------------------------------------------
# Roles and permissions
# --------------------------------------------------------------------------------------


def test_role_configuration_matches_the_plan(conn: Any) -> None:
    result = verify_permissions(conn)
    assert result["violations"] == []
    assert result["status"] == "PASS"
    assert result["schema_owner"] == "canonical_owner"


def test_permission_violation_detection_is_not_vacuous(conn: Any) -> None:
    state = role_state(conn)
    broken = json.loads(json.dumps(state))
    broken["table_grants"][ROLE_VALIDATOR_RO]["subject"] = ["SELECT", "INSERT"]
    assert permission_violations(broken)


def test_read_only_role_cannot_write(conn: Any) -> None:
    import psycopg

    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL ROLE {ROLE_VALIDATOR_RO}")
            cur.execute(f"SELECT count(*) FROM {CANONICAL_SCHEMA}.subject")
            assert cur.fetchone()[0] == 0
            for statement in (
                f"INSERT INTO {CANONICAL_SCHEMA}.source_system (source_system_id, source_label)"
                " VALUES ('x', 'x')",
                f"UPDATE {CANONICAL_SCHEMA}.subject SET subject_role_hint = 'x'",
                f"DELETE FROM {CANONICAL_SCHEMA}.subject",
                f"CREATE TABLE {CANONICAL_SCHEMA}.sneaky (id text)",
            ):
                cur.execute("SAVEPOINT probe")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cur.execute(statement)
                cur.execute("ROLLBACK TO SAVEPOINT probe")
    finally:
        conn.rollback()
        conn.autocommit = True


def test_loader_role_can_insert_but_not_update_or_delete(conn: Any) -> None:
    import psycopg

    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL ROLE {ROLE_LOADER}")
            _insert(cur, "source_system", {"source_system_id": "loader-probe", "source_label": "P"})
            for statement in (
                f"UPDATE {CANONICAL_SCHEMA}.source_system SET source_label = 'x'",
                f"DELETE FROM {CANONICAL_SCHEMA}.source_system",
                f"TRUNCATE {CANONICAL_SCHEMA}.source_system",
            ):
                cur.execute("SAVEPOINT probe")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cur.execute(statement)
                cur.execute("ROLLBACK TO SAVEPOINT probe")
    finally:
        conn.rollback()
        conn.autocommit = True


def test_no_canonical_role_can_log_in(conn: Any) -> None:
    state = role_state(conn)
    assert state["roles"]
    for role, attributes in state["roles"].items():
        assert attributes["can_login"] is False, role
        assert attributes["superuser"] is False, role


# --------------------------------------------------------------------------------------
# The dev canonical database stays empty
# --------------------------------------------------------------------------------------


def test_dev_canonical_database_holds_no_rows(live_settings: CanonicalConnectionSettings) -> None:
    with canonical_connection(live_settings) as connection:
        result = verify_schema(connection)
        if result["status"] != "PASS":
            pytest.skip("dev canonical database has not been migrated in this workspace")
        counts = row_counts(connection)
    assert all(value == 0 for value in counts.values()), counts


def test_contract_violation_detection_is_not_vacuous(conn: Any) -> None:
    actual = introspect_schema(conn)
    tampered = json.loads(json.dumps(actual))
    tampered["tables"].append("rogue_table")
    problems = contract_violations(tampered)
    assert any("rogue_table" in problem for problem in problems)
