"""Pinned normalized definitions of the canonical schema.

Checking that a constraint *name* exists proves almost nothing: a reviewer can rename
``CHECK (TRUE)`` to ``subject_characteristic_typed_value_xor`` and a name-only verifier will
pass. Changeset 01 v0.2 therefore pins the normalized definition text that PostgreSQL itself
reports for every constraint, index, enum, owner and privilege in the canonical schema.

Trust chain:

1. Migrations 0001-0004 are byte-pinned in ``ACCEPTED_MIGRATION_SHA256`` /
   ``HARDENING_MIGRATION_FILENAME`` and are the only authored DDL.
2. :func:`capture_definition_baseline` refuses to run unless those exact bytes produced the
   schema it is reading, and unless the target is a disposable database.
3. The captured document is committed and reviewed alongside the migration SQL.
4. :func:`baseline_violations` compares a live schema to the committed document and fails
   closed on any difference. It never writes and never repairs.

The document contains catalog metadata only: no row, value, credential or identifier.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BASELINE_PATH = (
    Path("artifacts")
    / "stage-03-implementation-changeset-01"
    / "canonical-definition-baseline.json"
)

# Sections of the introspection document that the baseline pins verbatim.
PINNED_SECTIONS: tuple[str, ...] = (
    "constraint_definitions",
    "index_definitions",
    "enums",
    "table_owners",
    "schema_owner",
    "schema_privileges",
    "table_privileges",
    "default_privileges",
)


class DefinitionBaselineError(RuntimeError):
    """Raised when the baseline is missing, malformed or captured from an untrusted schema."""


def baseline_path(repo_root: Path) -> Path:
    return repo_root / BASELINE_PATH


def _pinned(document: dict[str, Any]) -> dict[str, Any]:
    return {section: document[section] for section in PINNED_SECTIONS if section in document}


def baseline_document(introspection: dict[str, Any], *, migration_sha256: dict[str, str]) -> dict[str, Any]:
    """Build the committed document from a live introspection result."""
    pinned = _pinned(introspection)
    missing = [section for section in PINNED_SECTIONS if section not in pinned]
    if missing:
        raise DefinitionBaselineError(f"introspection is missing pinned sections: {missing}")
    payload = {
        "schema": introspection["schema"],
        "produced_by_migrations": dict(sorted(migration_sha256.items())),
        "definitions": pinned,
    }
    payload["definitions_sha256"] = definitions_fingerprint(pinned)
    return payload


def definitions_fingerprint(pinned: dict[str, Any]) -> str:
    encoded = json.dumps(pinned, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_baseline(repo_root: Path) -> dict[str, Any]:
    path = baseline_path(repo_root)
    if not path.is_file():
        raise DefinitionBaselineError(f"definition baseline not found: {BASELINE_PATH}")
    document = json.loads(path.read_text(encoding="utf-8"))
    for key in ("schema", "produced_by_migrations", "definitions", "definitions_sha256"):
        if key not in document:
            raise DefinitionBaselineError(f"definition baseline is missing {key!r}")
    recomputed = definitions_fingerprint(document["definitions"])
    if recomputed != document["definitions_sha256"]:
        raise DefinitionBaselineError(
            "definition baseline fingerprint does not match its own content"
        )
    return document


def _diff_mapping(label: str, expected: Any, actual: Any, problems: list[str]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                problems.append(f"{label}.{key} missing from live schema")
            elif key not in expected:
                problems.append(f"{label}.{key} present in live schema but not in the baseline")
            else:
                _diff_mapping(f"{label}.{key}", expected[key], actual[key], problems)
        return
    if expected != actual:
        problems.append(f"{label} differs from the pinned definition")


def baseline_violations(repo_root: Path, introspection: dict[str, Any]) -> list[str]:
    """Every difference between the live schema and the pinned definitions.

    Returns a list of human-readable differences. Definition text is deliberately not echoed:
    it is available in the committed baseline and in the migration SQL.
    """
    document = load_baseline(repo_root)
    problems: list[str] = []
    if document["schema"] != introspection.get("schema"):
        problems.append("live schema name differs from the pinned baseline")
    expected = document["definitions"]
    actual = _pinned(introspection)
    for section in PINNED_SECTIONS:
        if section not in actual:
            problems.append(f"introspection did not report {section}")
            continue
        _diff_mapping(section, expected.get(section), actual[section], problems)
    return problems
