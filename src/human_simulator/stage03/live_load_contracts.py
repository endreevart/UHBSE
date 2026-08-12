"""Authority and semantics of the two contracts the first live load requires.

Three generations of this check, each closing a hole the previous one left:

* v0.2 searched accepted artifacts for words. A file containing ``hash`` proved subject-key
  opacity and a file mentioning ``SET ROLE`` proved a loader principal existed.
* v0.2.2 required a complete structured contract, but accepted it from *any* YAML file under the
  Stage 03 directories — including the changeset's own directory. A changeset could therefore
  have written the contract that unblocked itself, and ``classify_algorithm`` matched algorithm
  names by substring, so ``not-hmac-sha256`` and ``hmac-sha256-unkeyed`` both passed as keyed
  PRFs.
* v0.2.3 fixes authority and meaning. A contract counts only at one exact path owned by an
  accepted release, listed in that release's manifest, with the manifest verifying. Field values
  are checked for what they say, not for their shape alone.

Read-only. Parses repository artifacts; touches no database and no clinical row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from human_simulator.canonical.constants import ROLE_LOADER
from human_simulator.stage03.changeset_01_baseline import verify_sha256_manifest
from human_simulator.stage03.changeset_01_constants import (
    CHANGESET_DIR,
    DESIGN_CONTENT_MANIFEST_NAME,
    DESIGN_DIR,
    IMPLEMENTATION_DIR,
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
)

SUBJECT_KEY_CONTRACT_KEY = "subject_key_transformation_contract"
RUNTIME_CONTRACT_KEY = "canonical_loader_runtime_contract"

SUBJECT_KEY_TRANSFORMATION_ID = "subject_key_from_id"


@dataclass(frozen=True)
class ContractAuthority:
    """Where a contract may live, and which accepted release owns that place."""

    contract_key: str
    authoritative_path: Path
    manifest_path: Path
    owning_release: str

    @property
    def manifest_entry(self) -> str:
        return self.authoritative_path.name


# The Design release owns subject identity semantics: opacity of a subject key is a
# data-protection property of the model, not a loader implementation detail. The Implementation
# Plan release owns runtime security: which principal connects, and with what privileges.
CONTRACT_AUTHORITIES: dict[str, ContractAuthority] = {
    SUBJECT_KEY_CONTRACT_KEY: ContractAuthority(
        contract_key=SUBJECT_KEY_CONTRACT_KEY,
        authoritative_path=DESIGN_DIR / "canonical-id-contract.yaml",
        manifest_path=DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME,
        owning_release="Stage 03 Design",
    ),
    RUNTIME_CONTRACT_KEY: ContractAuthority(
        contract_key=RUNTIME_CONTRACT_KEY,
        authoritative_path=IMPLEMENTATION_DIR / "security-runtime-plan.yaml",
        manifest_path=IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME,
        owning_release="Stage 03 Implementation Plan",
    ),
}

# A changeset may not write the contract that unblocks the changeset. Self-authorisation is the
# failure this directory is excluded to prevent, so it is named rather than merely omitted.
FORBIDDEN_CONTRACT_DIRS: tuple[Path, ...] = (CHANGESET_DIR,)

# Where a stray definition is looked for, so that a contract placed somewhere plausible but
# unauthorised is reported rather than silently ignored.
CONTRACT_SEARCH_DIRS: tuple[Path, ...] = (DESIGN_DIR, IMPLEMENTATION_DIR, CHANGESET_DIR)

PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {
        "",
        "tbd",
        "tba",
        "todo",
        "none",
        "null",
        "n/a",
        "na",
        "unknown",
        "undefined",
        "unspecified",
        "pending",
        "?",
        "-",
        "xxx",
        "placeholder",
        "example",
        "fixme",
        "latest",
        "current",
        "default",
    }
)

# Exact canonical identifiers. Membership is by equality after normalising separators and case;
# no substring test is performed anywhere, because "not-hmac-sha256" contains "hmac-sha256".
KEYED_ALGORITHM_IDENTIFIERS: frozenset[str] = frozenset(
    {
        "hmac-sha256",
        "hmac-sha-256",
        "hmac-sha384",
        "hmac-sha-384",
        "hmac-sha512",
        "hmac-sha-512",
        "hmac-sha3-256",
        "hmac-sha3-512",
        "kmac128",
        "kmac256",
        "keyed-blake2b",
        "keyed-blake2s",
    }
)

# Reference schemes that name a secret store rather than carrying a secret.
SECRET_REFERENCE_SCHEMES: tuple[str, ...] = (
    "vault://",
    "aws-secretsmanager://",
    "gcp-secretmanager://",
    "azure-keyvault://",
    "k8s-secret://",
)

KEY_VERSION_PATTERN = re.compile(r"^(v\d+(\.\d+)*|\d+(\.\d+)*|\d{4}-\d{2}-\d{2})$")
NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
POSTGRES_IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_$]{0,62}$")

# A value that looks like key material rather than a pointer to it.
KEY_MATERIAL_PATTERN = re.compile(r"^[A-Fa-f0-9]{32,}$|^[A-Za-z0-9+/]{40,}={0,2}$")

INPUT_ENCODINGS: frozenset[str] = frozenset(
    {
        "utf8-decimal-string",
        "utf8-canonical-string",
        "utf8-nfc-string",
        "big-endian-int64",
        "big-endian-int32",
    }
)
OUTPUT_ENCODINGS: frozenset[str] = frozenset(
    {"base32-nopad", "base64url-nopad", "hex-lowercase", "hex-uppercase"}
)

ROTATION_POLICY_FIELDS: tuple[str, ...] = ("interval", "procedure", "prior_key_handling")

# Collision handling must stop the load. Anything that lets it continue silently would allow two
# distinct subjects to share one key without anyone noticing.
FAIL_CLOSED_COLLISION_ACTIONS: frozenset[str] = frozenset(
    {"abort", "quarantine", "abort-and-quarantine", "quarantine-and-abort", "reject"}
)
FORBIDDEN_COLLISION_ACTIONS: frozenset[str] = frozenset(
    {"ignore", "continue", "overwrite", "skip", "log-and-continue", "warn", "retry", "merge"}
)

GRANT_ALLOWLIST: frozenset[str] = frozenset({"SELECT", "INSERT", "USAGE"})
FORBIDDEN_GRANTS: frozenset[str] = frozenset(
    {
        "ALL",
        "ALL PRIVILEGES",
        "SUPERUSER",
        "CREATEDB",
        "CREATEROLE",
        "BYPASSRLS",
        "REPLICATION",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "CREATE",
        "DROP",
        "REFERENCES",
        "TRIGGER",
    }
)

SET_ROLE_PATTERN = re.compile(r"\bset\s+role\s+([A-Za-z_][A-Za-z0-9_$]*)", re.IGNORECASE)
REVOCATION_ACTION_PATTERN = re.compile(
    r"\b(revoke|drop\s+role|alter\s+role\s+\S+\s+nologin|disable\s+the\s+credential)\b",
    re.IGNORECASE,
)

REVOCATION_FIELDS: tuple[str, ...] = ("rotation", "revocation")

SUBJECT_KEY_REQUIRED_FIELDS: tuple[str, ...] = (
    "transformation_id",
    "algorithm",
    "key_reference",
    "key_version",
    "namespace",
    "input_encoding",
    "output_encoding",
    "rotation_policy",
    "collision_handling",
)

RUNTIME_REQUIRED_FIELDS: tuple[str, ...] = (
    "login_principal",
    "group_role",
    "group_role_is_nologin",
    "credential_source_reference",
    "connection_path",
    "set_role_flow",
    "minimal_grants",
    "audit_identity",
    "rotation_and_revocation_procedure",
)


@dataclass(frozen=True)
class ContractLocation:
    path: str
    authoritative: bool
    reason: str


@dataclass(frozen=True)
class ContractValidation:
    contract_key: str
    found_in: str | None
    satisfied: bool
    missing_fields: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()
    locations: tuple[ContractLocation, ...] = ()
    authority_failures: tuple[str, ...] = ()
    manifest_verified: bool = False
    ambiguous: bool = False
    authoritative_path: str = ""
    owning_release: str = ""
    definition_count: int = 0

    def document(self) -> dict[str, Any]:
        return {
            "contract_key": self.contract_key,
            "authoritative_path": self.authoritative_path,
            "owning_release": self.owning_release,
            "found_in": self.found_in,
            "definition_count": self.definition_count,
            "definitions": [
                {"path": item.path, "authoritative": item.authoritative, "reason": item.reason}
                for item in self.locations
            ],
            "ambiguous": self.ambiguous,
            "release_manifest_verified": self.manifest_verified,
            "authority_failures": list(self.authority_failures),
            "satisfied": self.satisfied,
            "missing_fields": list(self.missing_fields),
            "violations": list(self.violations),
        }

    @property
    def summary(self) -> str:
        if self.satisfied:
            return f"complete authoritative contract in {self.found_in}"
        if self.ambiguous:
            return (
                f"{self.definition_count} definitions of {self.contract_key}: "
                f"{[item.path for item in self.locations]}"
            )
        if self.definition_count == 0:
            return (
                f"no accepted release defines {self.contract_key} at its authoritative path "
                f"{self.authoritative_path}"
            )
        parts: list[str] = list(self.authority_failures)
        if self.missing_fields:
            parts.append(f"missing {list(self.missing_fields)}")
        parts.extend(self.violations)
        return f"{self.found_in or self.authoritative_path}: " + "; ".join(parts)


# ---------------------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------------------


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, list | tuple | set | dict):
        return len(value) == 0
    return str(value).strip().lower() in PLACEHOLDER_VALUES


def _normalize_token(value: Any) -> str:
    return re.sub(r"[\s_]+", "-", str(value).strip().lower())


def classify_algorithm(value: Any) -> tuple[bool, str]:
    """Is this exactly a canonical keyed-PRF identifier? Returns ``(accepted, reason)``.

    Matching is by equality against a fixed set. v0.2.2 used substring containment, which
    accepted ``not-hmac-sha256``, ``fake-hmac-sha256`` and ``hmac-sha256-unkeyed`` — the first
    two say the opposite of what they were read as, and the third names an unkeyed construction.
    """
    normalized = _normalize_token(value)
    if not normalized or normalized in PLACEHOLDER_VALUES:
        return False, "algorithm is empty or a placeholder"
    if normalized in KEYED_ALGORITHM_IDENTIFIERS:
        return True, f"keyed PRF {normalized}"
    return False, (
        f"algorithm {normalized!r} is not one of the canonical keyed-PRF identifiers "
        f"{sorted(KEYED_ALGORITHM_IDENTIFIERS)}; an unkeyed digest cannot make a bounded "
        "identifier space opaque, and a name that merely contains a keyed identifier is not one"
    )


def classify_secret_reference(value: Any, *, field_name: str) -> tuple[bool, str]:
    """A pointer into a secret store, never the secret."""
    if not isinstance(value, str) or not value.strip():
        return False, f"{field_name} is not a reference string"
    text = value.strip()
    if KEY_MATERIAL_PATTERN.match(text):
        return False, f"{field_name} looks like key material rather than a reference"
    for scheme in SECRET_REFERENCE_SCHEMES:
        if text.lower().startswith(scheme) and len(text) > len(scheme):
            return True, f"{field_name} references {scheme.rstrip(':/')}"
    return False, (
        f"{field_name} {text!r} is not a secret-store reference; allowed schemes are "
        f"{list(SECRET_REFERENCE_SCHEMES)}"
    )


def _check_literal_credentials(contract: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    for key, value in contract.items():
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        if re.search(r"(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S", lowered):
            violations.append(f"{key} carries a literal credential rather than a reference")
        elif re.search(r"postgres(?:ql)?://[^\s]*:[^\s@]+@", lowered):
            violations.append(f"{key} carries a credential-bearing connection string")
    return violations


# ---------------------------------------------------------------------------------------
# Locating definitions
# ---------------------------------------------------------------------------------------


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None


def _count_mappings(document: Any, key: str) -> list[dict[str, Any]]:
    """Every mapping stored under ``key``, at any depth, so duplicates are visible."""
    found: list[dict[str, Any]] = []
    if isinstance(document, dict):
        candidate = document.get(key)
        if isinstance(candidate, dict):
            found.append(candidate)
        for name, value in document.items():
            if name == key and isinstance(value, dict):
                continue
            found.extend(_count_mappings(value, key))
    elif isinstance(document, list):
        for item in document:
            found.extend(_count_mappings(item, key))
    return found


def locate_contract_definitions(
    repo_root: Path, contract_key: str
) -> list[tuple[ContractLocation, dict[str, Any]]]:
    """Every definition of ``contract_key`` in scope, each labelled with its authority."""
    authority = CONTRACT_AUTHORITIES[contract_key]
    results: list[tuple[ContractLocation, dict[str, Any]]] = []
    seen: set[Path] = set()

    for directory in CONTRACT_SEARCH_DIRS:
        base = repo_root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in {".yaml", ".yml"} or path in seen:
                continue
            seen.add(path)
            document = _load_yaml(path)
            mappings = _count_mappings(document, contract_key)
            if not mappings:
                continue
            relative = path.relative_to(repo_root)
            forbidden = any(
                relative == forbidden_dir or forbidden_dir in relative.parents
                for forbidden_dir in FORBIDDEN_CONTRACT_DIRS
            )
            if forbidden:
                reason = (
                    "the changeset directory can never authorise a contract that unblocks the "
                    "changeset"
                )
                authoritative = False
            elif relative == authority.authoritative_path:
                reason = f"authoritative path owned by {authority.owning_release}"
                authoritative = True
            else:
                reason = (
                    f"not the authoritative path; only {authority.authoritative_path.as_posix()} "
                    f"is owned by {authority.owning_release}"
                )
                authoritative = False
            for mapping in mappings:
                results.append(
                    (ContractLocation(relative.as_posix(), authoritative, reason), mapping)
                )
    return results


def _authority_result(
    contract_key: str,
    locations: list[ContractLocation],
    *,
    manifest_verified: bool,
    authority_failures: list[str],
    ambiguous: bool,
) -> ContractValidation:
    authority = CONTRACT_AUTHORITIES[contract_key]
    return ContractValidation(
        contract_key=contract_key,
        found_in=None,
        satisfied=False,
        locations=tuple(locations),
        authority_failures=tuple(authority_failures),
        manifest_verified=manifest_verified,
        ambiguous=ambiguous,
        authoritative_path=authority.authoritative_path.as_posix(),
        owning_release=authority.owning_release,
        definition_count=len(locations),
    )


def _validate_authority(
    repo_root: Path, contract_key: str
) -> tuple[ContractValidation | None, dict[str, Any], ContractLocation, bool]:
    """Resolve the one contract that may be trusted, or the reason none may be.

    Returns ``(failure, contract, location, manifest_verified)``; when ``failure`` is ``None``
    the remaining values describe the contract whose fields should be validated.
    """
    authority = CONTRACT_AUTHORITIES[contract_key]
    found = locate_contract_definitions(repo_root, contract_key)
    locations = [item[0] for item in found]

    manifest = verify_sha256_manifest(repo_root / authority.manifest_path)
    manifest_lists_path = False
    manifest_file = repo_root / authority.manifest_path
    if manifest_file.is_file():
        listed = {
            line.split(maxsplit=1)[1].strip()
            for line in manifest_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and len(line.split(maxsplit=1)) == 2
        }
        manifest_lists_path = authority.manifest_entry in listed

    if len(found) > 1:
        return (
            _authority_result(
                contract_key,
                locations,
                manifest_verified=manifest.verified,
                authority_failures=[
                    f"{len(found)} definitions of {contract_key} exist; exactly one "
                    "authoritative definition is required"
                ],
                ambiguous=True,
            ),
            {},
            ContractLocation("", False, ""),
            manifest.verified,
        )

    if not found:
        return (
            _authority_result(
                contract_key,
                locations,
                manifest_verified=manifest.verified,
                authority_failures=[],
                ambiguous=False,
            ),
            {},
            ContractLocation("", False, ""),
            manifest.verified,
        )

    location, contract = found[0]
    failures: list[str] = []
    if not location.authoritative:
        failures.append(f"{location.path}: {location.reason}")
    if not manifest_lists_path:
        failures.append(
            f"{authority.authoritative_path.as_posix()} is not listed in "
            f"{authority.manifest_path.name}"
        )
    if not manifest.verified:
        failures.append(f"{authority.manifest_path.name}: {manifest.detail}")

    if failures:
        result = _authority_result(
            contract_key,
            locations,
            manifest_verified=manifest.verified,
            authority_failures=failures,
            ambiguous=False,
        )
        return replace(result, found_in=location.path), {}, location, manifest.verified

    return None, contract, location, manifest.verified


def _result(
    contract_key: str,
    location: ContractLocation,
    *,
    manifest_verified: bool,
    missing: list[str],
    violations: list[str],
    definition_count: int,
) -> ContractValidation:
    authority = CONTRACT_AUTHORITIES[contract_key]
    return ContractValidation(
        contract_key=contract_key,
        found_in=location.path,
        satisfied=not missing and not violations,
        missing_fields=tuple(missing),
        violations=tuple(violations),
        locations=(location,),
        authority_failures=(),
        manifest_verified=manifest_verified,
        ambiguous=False,
        authoritative_path=authority.authoritative_path.as_posix(),
        owning_release=authority.owning_release,
        definition_count=definition_count,
    )


def _missing_fields(contract: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [name for name in required if name not in contract or _is_placeholder(contract[name])]


# ---------------------------------------------------------------------------------------
# Subject key
# ---------------------------------------------------------------------------------------


def _validate_subject_key_semantics(contract: dict[str, Any], missing: list[str]) -> list[str]:
    violations: list[str] = []
    present = {name for name in contract if name not in missing}

    if "transformation_id" in present:
        actual = str(contract["transformation_id"]).strip()
        if actual != SUBJECT_KEY_TRANSFORMATION_ID:
            violations.append(
                f"transformation_id {actual!r} does not name the transformation the record "
                f"construction contract references, {SUBJECT_KEY_TRANSFORMATION_ID!r}"
            )

    if "algorithm" in present:
        accepted, reason = classify_algorithm(contract["algorithm"])
        if not accepted:
            violations.append(reason)

    if "key_reference" in present:
        accepted, reason = classify_secret_reference(
            contract["key_reference"], field_name="key_reference"
        )
        if not accepted:
            violations.append(reason)

    if "key_version" in present:
        value = str(contract["key_version"]).strip()
        if not KEY_VERSION_PATTERN.match(value):
            violations.append(
                f"key_version {value!r} is not a comparable version; use v1, 1.2 or an ISO date "
                "so a rotation is detectable"
            )

    if "namespace" in present:
        value = str(contract["namespace"]).strip()
        if not NAMESPACE_PATTERN.match(value):
            violations.append(
                f"namespace {value!r} is not a stable domain separator: it must be a compact "
                "token without whitespace"
            )

    if "input_encoding" in present:
        value = _normalize_token(contract["input_encoding"])
        if value not in INPUT_ENCODINGS:
            violations.append(
                f"input_encoding {value!r} is not one of {sorted(INPUT_ENCODINGS)}; prose leaves "
                "the keyed input ambiguous, and two encodings of one id produce two keys"
            )

    if "output_encoding" in present:
        value = _normalize_token(contract["output_encoding"])
        if value not in OUTPUT_ENCODINGS:
            violations.append(f"output_encoding {value!r} is not one of {sorted(OUTPUT_ENCODINGS)}")

    if "rotation_policy" in present:
        policy = contract["rotation_policy"]
        if not isinstance(policy, dict):
            violations.append(
                "rotation_policy must be a mapping with "
                f"{list(ROTATION_POLICY_FIELDS)}, not free text"
            )
        else:
            absent = [name for name in ROTATION_POLICY_FIELDS if _is_placeholder(policy.get(name))]
            if absent:
                violations.append(f"rotation_policy is missing {absent}")

    if "collision_handling" in present:
        handling = contract["collision_handling"]
        action = handling.get("action") if isinstance(handling, dict) else handling
        token = _normalize_token(action)
        if token in FORBIDDEN_COLLISION_ACTIONS:
            violations.append(
                f"collision_handling action {token!r} lets the load continue; two distinct "
                "subjects sharing one key must stop it"
            )
        elif token not in FAIL_CLOSED_COLLISION_ACTIONS:
            violations.append(
                f"collision_handling action {token!r} is not a fail-closed action; use one of "
                f"{sorted(FAIL_CLOSED_COLLISION_ACTIONS)}"
            )

    violations.extend(_check_literal_credentials(contract))
    return violations


def validate_subject_key_contract(repo_root: Path) -> ContractValidation:
    """A subject key is opaque only under an authoritative, semantically valid contract."""
    failure, contract, location, manifest_verified = _validate_authority(
        repo_root, SUBJECT_KEY_CONTRACT_KEY
    )
    if failure is not None:
        return failure

    missing = _missing_fields(contract, SUBJECT_KEY_REQUIRED_FIELDS)
    violations = _validate_subject_key_semantics(contract, missing)
    return _result(
        SUBJECT_KEY_CONTRACT_KEY,
        location,
        manifest_verified=manifest_verified,
        missing=missing,
        violations=violations,
        definition_count=1,
    )


# ---------------------------------------------------------------------------------------
# Loader runtime principal
# ---------------------------------------------------------------------------------------


def _validate_runtime_semantics(contract: dict[str, Any], missing: list[str]) -> list[str]:
    violations: list[str] = []
    present = {name for name in contract if name not in missing}
    login_principal = str(contract.get("login_principal", "")).strip()

    if "group_role" in present:
        value = str(contract["group_role"]).strip()
        if value != ROLE_LOADER:
            violations.append(
                f"group_role {value!r} is not {ROLE_LOADER!r}; the loader session must assume "
                "the role migration 0001 created and no other"
            )

    if "group_role_is_nologin" in present and contract["group_role_is_nologin"] is not True:
        violations.append(
            f"group_role_is_nologin must be true: {ROLE_LOADER} is a privilege container, not a "
            "login account"
        )

    if "login_principal" in present:
        if login_principal == ROLE_LOADER:
            violations.append(
                f"login_principal must not be {ROLE_LOADER}; granting it LOGIN would make the "
                "privilege container an account and erase the audit distinction"
            )
        elif not POSTGRES_IDENTIFIER_PATTERN.match(login_principal):
            violations.append(
                f"login_principal {login_principal!r} is not a valid unquoted PostgreSQL "
                "identifier"
            )
        elif login_principal in {"postgres", "root", "admin"}:
            violations.append(
                f"login_principal {login_principal!r} is a superuser-adjacent account; the "
                "loader needs a dedicated named principal"
            )

    if "credential_source_reference" in present:
        accepted, reason = classify_secret_reference(
            contract["credential_source_reference"], field_name="credential_source_reference"
        )
        if not accepted:
            violations.append(reason)

    if "set_role_flow" in present:
        flow = contract["set_role_flow"]
        text = " ".join(flow) if isinstance(flow, list) else str(flow)
        roles = [match.group(1) for match in SET_ROLE_PATTERN.finditer(text)]
        if not roles:
            violations.append(
                f"set_role_flow states no SET ROLE statement; the exact operation "
                f"'SET ROLE {ROLE_LOADER}' is required"
            )
        else:
            other = sorted({role for role in roles if role != ROLE_LOADER})
            if other:
                violations.append(
                    f"set_role_flow assumes {other}; only 'SET ROLE {ROLE_LOADER}' is permitted"
                )

    if "minimal_grants" in present:
        grants = contract["minimal_grants"]
        listed = grants if isinstance(grants, list) else [grants]
        normalized = [str(item).strip().upper() for item in listed]
        forbidden = sorted({item for item in normalized if item in FORBIDDEN_GRANTS})
        unknown = sorted(
            {item for item in normalized if item not in GRANT_ALLOWLIST and item not in forbidden}
        )
        if forbidden:
            violations.append(
                f"minimal_grants includes {forbidden}, which exceed what a loader needs and are "
                "forbidden"
            )
        if unknown:
            violations.append(
                f"minimal_grants includes {unknown}, which are not on the allowlist "
                f"{sorted(GRANT_ALLOWLIST)}"
            )

    if "audit_identity" in present:
        text = str(contract["audit_identity"])
        lowered = text.lower()
        if "session_user" not in lowered:
            violations.append(
                "audit_identity must record session_user, or an action taken under the group "
                "role cannot be attributed to the principal that performed it"
            )
        elif login_principal and login_principal not in text:
            violations.append(
                f"audit_identity does not tie session_user to the login principal "
                f"{login_principal!r}"
            )

    if "rotation_and_revocation_procedure" in present:
        procedure = contract["rotation_and_revocation_procedure"]
        if not isinstance(procedure, dict):
            violations.append(
                "rotation_and_revocation_procedure must be a mapping with "
                f"{list(REVOCATION_FIELDS)}, not free text"
            )
        else:
            absent = [name for name in REVOCATION_FIELDS if _is_placeholder(procedure.get(name))]
            if absent:
                violations.append(f"rotation_and_revocation_procedure is missing {absent}")
            else:
                revocation = str(procedure["revocation"])
                if not REVOCATION_ACTION_PATTERN.search(revocation):
                    violations.append(
                        "rotation_and_revocation_procedure.revocation names no revoking action; "
                        "state REVOKE, DROP ROLE, ALTER ROLE ... NOLOGIN or credential disabling"
                    )

    violations.extend(_check_literal_credentials(contract))
    return violations


def validate_runtime_contract(repo_root: Path) -> ContractValidation:
    """A loader principal exists only under an authoritative, semantically valid contract."""
    failure, contract, location, manifest_verified = _validate_authority(
        repo_root, RUNTIME_CONTRACT_KEY
    )
    if failure is not None:
        return failure

    missing = _missing_fields(contract, RUNTIME_REQUIRED_FIELDS)
    violations = _validate_runtime_semantics(contract, missing)
    return _result(
        RUNTIME_CONTRACT_KEY,
        location,
        manifest_verified=manifest_verified,
        missing=missing,
        violations=violations,
        definition_count=1,
    )


def contract_authority_document(repo_root: Path) -> dict[str, Any]:
    """The authority policy as evaluated, for the gate result and the report."""
    subject_key = validate_subject_key_contract(repo_root)
    runtime = validate_runtime_contract(repo_root)
    return {
        "policy": {
            key: {
                "authoritative_path": authority.authoritative_path.as_posix(),
                "release_manifest": authority.manifest_path.as_posix(),
                "owning_release": authority.owning_release,
            }
            for key, authority in CONTRACT_AUTHORITIES.items()
        },
        "forbidden_source_directories": [item.as_posix() for item in FORBIDDEN_CONTRACT_DIRS],
        "recursive_search_for_authority": False,
        "substring_algorithm_matching": False,
        "contracts": {
            SUBJECT_KEY_CONTRACT_KEY: subject_key.document(),
            RUNTIME_CONTRACT_KEY: runtime.document(),
        },
        "ambiguous_definitions": sorted(
            key
            for key, validation in (
                (SUBJECT_KEY_CONTRACT_KEY, subject_key),
                (RUNTIME_CONTRACT_KEY, runtime),
            )
            if validation.ambiguous
        ),
    }
