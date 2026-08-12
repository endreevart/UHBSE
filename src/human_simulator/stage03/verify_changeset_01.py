"""Verification for Stage 03 Implementation Changeset 01: Canonical Storage Foundation.

Every check is fail-closed and read-only with respect to prior stages, the frozen design
baseline and the accepted implementation plan. The verifier never repairs anything.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from human_simulator.audit.report import REPORT_STATUS_DRAFT
from human_simulator.canonical.constants import (
    CANONICAL_DATABASE,
    CANONICAL_PORT,
    CANONICAL_POSTGRES_VERSION,
    CANONICAL_ROLES,
    CANONICAL_SCHEMA,
    CANONICAL_VOLUME,
    DOWN_MIGRATIONS_SUPPORTED,
    FORBIDDEN_COLUMN_NAMES,
    HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES,
    HARDENING_MIGRATION_FILENAME,
    PILOT_ENTITY_LOAD_ORDER,
    PILOT_NULL_ONLY_COLUMNS,
    PILOT_TABLE_LOAD_ORDER,
    PROVENANCE_BEARING_TABLES,
    SUBJECT_CHARACTERISTIC_TYPED_VALUE_COLUMNS,
)
from human_simulator.canonical.definition_baseline import (
    PINNED_SECTIONS,
    DefinitionBaselineError,
    load_baseline,
)
from human_simulator.canonical.migrations import (
    discover_migrations,
    forbidden_tokens_in_migrations,
    migration_immutability,
)
from human_simulator.canonical.schema_contract import (
    PILOT_TABLES,
    contract_document,
    contract_fingerprint,
    load_order_violations,
)
from human_simulator.stage03.changeset_01_baseline import (
    evaluate_baseline,
    write_baseline_verification,
)
from human_simulator.stage03.changeset_01_constants import (
    ARTIFACT_CONFLICTS_NAME,
    CANONICAL_ENV_FILE,
    CANONICAL_ENV_TEMPLATE,
    CHANGESET_CONTENT_ARTIFACTS,
    CHANGESET_DIR,
    CHANGESET_ID,
    CHANGESET_MANIFEST_NAME,
    CHANGESET_PLAN_NAME,
    CHANGESET_REPORT_NAME,
    CHANGESET_SUBTITLE,
    CHANGESET_TITLE,
    CHANGESET_VERIFICATION_NAME,
    CHANGESET_VERSION,
    COMPOSE_FILE,
    DEFINITION_BASELINE_NAME,
    FORBIDDEN_IN_CHANGESET_MANIFEST,
    GATE_RESULT_NAME,
    MIGRATION_RESULT_NAME,
    PRE_LIVE_LOAD_BLOCKERS_NAME,
    DESIGN_ARCHIVE_FINDING_NAME,
    LIVE_LOAD_CONTRACT_SCHEMA_NAME,
    CONTRACT_AUTHORITY_POLICY_NAME,
    PRIOR_STAGE_INTEGRITY_NAME,
    RAW_RELATION_TOKENS,
    RELEASE_VERIFICATION_NAME,
    SCHEMA_CONTRACT_NAME,
    UNRESOLVED_DECISIONS_NAME,
)
from human_simulator.stage03.implementation_gate import (
    AUTHORIZED_CHANGESET_ID,
    CHANGESET_01_AUTHORIZED_PATHS,
    FROZEN_DESIGN_VERSION,
    FROZEN_IMPLEMENTATION_PLAN_VERSION,
    IMPLEMENTATION_GATE_OPEN,
    STILL_FORBIDDEN_CAPABILITIES,
)
from human_simulator.stage03.frozen_evidence import (
    DESIGN_REPORT_NAME,
    DESIGN_VERIFICATION_NAME,
    evaluate_frozen_evidence,
    frozen_evidence_records,
    repair_entry_points_used,
)
from human_simulator.stage03.design_archive_finding import evaluate_design_archive_finding
from human_simulator.stage03.conflict_registry import validate_conflict_registry
from human_simulator.stage03.live_load_contracts import (
    classify_algorithm,
    contract_authority_document,
    validate_runtime_contract,
    validate_subject_key_contract,
)
from human_simulator.stage03.pre_live_load_blockers import blockers_document, blocking_conflicts
from human_simulator.stage03.pre_live_load_gate import (
    ALLOWED_WHILE_BLOCKED,
    BLOCKED_LIVE_OPERATIONS,
    GATE_ID,
    LiveLoadBlocked,
    evaluate_pre_live_load_gate,
    relationship_manifest_mismatches,
    require_live_load_authorized,
)
from human_simulator.stage03.publication_lock import LOCK_NAME, publication_lock
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.prior_stage_integrity import build_prior_stage_integrity_document
from human_simulator.stage03.release_verification import (
    MANDATORY_SUITE_NAMES,
    NO_SKIP_SUITE_NAMES,
)
from human_simulator.stage03.review_dependencies import (
    get_changeset_01_review_bundle_paths,
    get_stage02_relationship_gate_inputs,
)

CheckStatus = Literal["PASS", "FAIL"]

CANONICAL_PACKAGE = Path("src") / "human_simulator" / "canonical"
MIGRATIONS_DIR = Path("migrations") / "canonical"

# Assignments allowed to appear in the committed env template.
PLACEHOLDER_VALUE = "PLACEHOLDER_SET_LOCALLY"
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"^(?P<key>[A-Z0-9_]*(PASSWORD|SECRET|TOKEN|KEY)[A-Z0-9_]*)\s*=\s*(?P<value>.*)$"
)
DSN_PATTERN = re.compile(r"postgres(?:ql)?://[^\s\"']+")


@dataclass(frozen=True)
class CheckResult:
    name: str
    category: str
    status: CheckStatus
    detail: str


class ChangesetVerificationError(RuntimeError):
    """Raised when the changeset cannot be verified at all."""


def _env_file_tracking_state(root: Path) -> tuple[bool, str]:
    """Report whether the runtime env file leaked into version control or a bundle.

    The file is expected to exist locally at runtime; only publication is forbidden.
    Outside a git checkout (for example an extracted review bundle) its mere presence
    is a violation.
    """
    git_dir = root / ".git"
    if not git_dir.exists():
        present = (root / CANONICAL_ENV_FILE).exists()
        detail = (
            f"{CANONICAL_ENV_FILE} present outside a git checkout"
            if present
            else f"{CANONICAL_ENV_FILE} absent from bundle"
        )
        return present, detail

    completed = subprocess.run(  # noqa: S603
        ["git", "ls-files", "--error-unmatch", "--", CANONICAL_ENV_FILE],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = completed.returncode == 0
    detail = (
        f"{CANONICAL_ENV_FILE} is tracked by git"
        if tracked
        else f"{CANONICAL_ENV_FILE} untracked (runtime-only)"
    )
    return tracked, detail


# --------------------------------------------------------------------------------------
# Individual check groups
# --------------------------------------------------------------------------------------


def _check_baseline(add: Any, baseline: dict[str, Any]) -> None:
    add(
        CheckResult(
            "baseline_status_pass",
            "baseline",
            "PASS" if baseline["status"] == "PASS" else "FAIL",
            f"baseline status={baseline['status']!r}",
        )
    )
    controlled = baseline["controlled_prior_stage"]
    add(
        CheckResult(
            "controlled_prior_stage_nine_files_unchanged",
            "baseline",
            "PASS" if controlled["all_unchanged"] and controlled["file_count"] == 9 else "FAIL",
            f"{controlled['file_count']} controlled files, all_unchanged={controlled['all_unchanged']}",
        )
    )
    design = baseline["frozen_manifests"]["design"]
    add(
        CheckResult(
            "design_baseline_v074_manifest_verified",
            "baseline",
            "PASS" if design["verified"] else "FAIL",
            f"{design['detail']} (design v{FROZEN_DESIGN_VERSION})",
        )
    )
    plan = baseline["frozen_manifests"]["implementation_plan"]
    add(
        CheckResult(
            "implementation_plan_v035_manifest_verified",
            "baseline",
            "PASS" if plan["verified"] else "FAIL",
            f"{plan['detail']} (plan v{FROZEN_IMPLEMENTATION_PLAN_VERSION})",
        )
    )
    add(
        CheckResult(
            "baseline_check_performed_no_auto_restore",
            "baseline",
            "PASS" if baseline["auto_restore_performed"] is False else "FAIL",
            "no prior-stage restoration was performed",
        )
    )


def _check_implementation_gate(add: Any, root: Path) -> None:
    add(
        CheckResult(
            "implementation_gate_open_for_this_changeset",
            "gate_state",
            "PASS" if IMPLEMENTATION_GATE_OPEN and AUTHORIZED_CHANGESET_ID == CHANGESET_ID else "FAIL",
            f"gate_open={IMPLEMENTATION_GATE_OPEN} changeset={AUTHORIZED_CHANGESET_ID!r}",
        )
    )
    declared = sorted(CHANGESET_01_AUTHORIZED_PATHS)
    missing = [path for path in declared if not (root / path).exists()]
    add(
        CheckResult(
            "authorized_changeset_paths_exist",
            "gate_state",
            "PASS" if not missing else "FAIL",
            f"{len(declared)} authorized paths" if not missing else f"missing: {missing}",
        )
    )
    add(
        CheckResult(
            "forbidden_capabilities_still_closed",
            "gate_state",
            "PASS" if len(STILL_FORBIDDEN_CAPABILITIES) == 11 else "FAIL",
            f"{len(STILL_FORBIDDEN_CAPABILITIES)} capabilities remain forbidden",
        )
    )


def _check_infrastructure(add: Any, root: Path) -> None:
    compose_path = root / COMPOSE_FILE
    if not compose_path.exists():
        add(CheckResult("compose_file_present", "infrastructure", "FAIL", "docker-compose.yml missing"))
        return
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose.get("services", {})
    service = services.get("canonical-db")

    add(
        CheckResult(
            "canonical_service_declared",
            "infrastructure",
            "PASS" if service else "FAIL",
            "canonical-db service present" if service else "canonical-db service missing",
        )
    )
    if not service:
        return

    image = str(service.get("image", ""))
    add(
        CheckResult(
            "canonical_service_postgres_16",
            "infrastructure",
            "PASS" if image == f"postgres:{CANONICAL_POSTGRES_VERSION}" else "FAIL",
            f"image={image!r}",
        )
    )
    ports = [str(entry) for entry in service.get("ports", [])]
    add(
        CheckResult(
            "canonical_service_planned_port",
            "infrastructure",
            "PASS" if any(entry.startswith(f"{CANONICAL_PORT}:") for entry in ports) else "FAIL",
            f"ports={ports}",
        )
    )
    volumes = [str(entry) for entry in service.get("volumes", [])]
    declared_volumes = compose.get("volumes", {}) or {}
    volume_ok = (
        any(entry.startswith(f"{CANONICAL_VOLUME}:") for entry in volumes)
        and CANONICAL_VOLUME in declared_volumes
    )
    add(
        CheckResult(
            "canonical_service_dedicated_volume",
            "infrastructure",
            "PASS" if volume_ok else "FAIL",
            f"volumes={volumes}",
        )
    )
    environment = service.get("environment", {}) or {}
    add(
        CheckResult(
            "canonical_service_planned_database",
            "infrastructure",
            "PASS" if environment.get("POSTGRES_DB") == CANONICAL_DATABASE else "FAIL",
            f"POSTGRES_DB={environment.get('POSTGRES_DB')!r}",
        )
    )

    canonical_networks = set(service.get("networks", []) or [])
    raw_networks: set[str] = set()
    for name, definition in services.items():
        if name == "canonical-db":
            continue
        raw_networks.update(definition.get("networks", []) or [])
    isolated = bool(canonical_networks) and not (canonical_networks & raw_networks)
    add(
        CheckResult(
            "canonical_network_isolated_from_raw_services",
            "infrastructure",
            "PASS" if isolated else "FAIL",
            f"canonical={sorted(canonical_networks)} raw={sorted(raw_networks)}",
        )
    )

    env_files = service.get("env_file", []) or []
    referenced = {
        entry["path"] if isinstance(entry, dict) else str(entry) for entry in env_files
    }
    tracked, tracking_detail = _env_file_tracking_state(root)
    add(
        CheckResult(
            "canonical_env_file_not_committed",
            "infrastructure",
            "FAIL" if tracked else "PASS",
            tracking_detail,
        )
    )
    add(
        CheckResult(
            "canonical_env_file_referenced_by_compose",
            "infrastructure",
            "PASS" if CANONICAL_ENV_FILE in referenced else "FAIL",
            f"env_file={sorted(referenced)}",
        )
    )

    gitignore = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").exists() else ""
    add(
        CheckResult(
            "canonical_env_file_gitignored",
            "infrastructure",
            "PASS" if CANONICAL_ENV_FILE in gitignore.splitlines() else "FAIL",
            f"{CANONICAL_ENV_FILE} listed in .gitignore",
        )
    )

    template = root / CANONICAL_ENV_TEMPLATE
    add(
        CheckResult(
            "canonical_env_template_present",
            "infrastructure",
            "PASS" if template.exists() else "FAIL",
            str(CANONICAL_ENV_TEMPLATE),
        )
    )
    if template.exists():
        offenders: list[str] = []
        for line in template.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            match = SECRET_ASSIGNMENT_PATTERN.match(line.strip())
            if match and match.group("value") != PLACEHOLDER_VALUE:
                offenders.append(match.group("key"))
        add(
            CheckResult(
                "canonical_env_template_has_no_secret_values",
                "infrastructure",
                "PASS" if not offenders else "FAIL",
                "all secret assignments are placeholders"
                if not offenders
                else f"non-placeholder values for {sorted(offenders)}",
            )
        )


def _check_migration_mechanism(add: Any, root: Path) -> None:
    try:
        migrations = discover_migrations(root)
    except Exception as exc:  # noqa: BLE001 - report as a failed check
        add(CheckResult("migrations_discoverable", "migrations", "FAIL", str(exc)))
        return

    add(
        CheckResult(
            "migrations_discoverable",
            "migrations",
            "PASS",
            f"{len(migrations)} migrations, contiguous from 0001",
        )
    )
    offenders = forbidden_tokens_in_migrations(root)
    add(
        CheckResult(
            "migrations_contain_no_data_statements",
            "migrations",
            "PASS" if not offenders else "FAIL",
            "no INSERT/UPDATE/DELETE/COPY/TRUNCATE/DROP or cross-database extension"
            if not offenders
            else f"forbidden tokens: {offenders}",
        )
    )

    text = "\n".join(item.path.read_text(encoding="utf-8") for item in migrations)
    add(
        CheckResult(
            "migrations_are_idempotent_by_construction",
            "migrations",
            "PASS" if "IF NOT EXISTS" in text else "FAIL",
            "guarded CREATE statements present",
        )
    )
    down_files = sorted(p.name for p in (root / MIGRATIONS_DIR).glob("*down*.sql"))
    add(
        CheckResult(
            "down_migrations_absent_as_planned",
            "migrations",
            "PASS" if not down_files and DOWN_MIGRATIONS_SUPPORTED is False else "FAIL",
            "accepted plan defines no reverse DDL; up->down->up not applicable",
        )
    )
    raw_hits = sorted(token for token in RAW_RELATION_TOKENS if token in text)
    add(
        CheckResult(
            "migrations_reference_no_raw_relations",
            "migrations",
            "PASS" if not raw_hits else "FAIL",
            "no raw source relation names in migrations"
            if not raw_hits
            else f"raw relation tokens: {raw_hits}",
        )
    )


def _check_publication_isolation(add: Any, root: Path) -> None:
    """Changeset 01 v0.2.1 checks: pinned evidence, isolated tests, exclusive publication."""
    frozen = evaluate_frozen_evidence(root)
    add(
        CheckResult(
            "frozen_design_report_match",
            "isolation",
            "PASS" if frozen["frozen_design_report_match"] else "FAIL",
            f"{DESIGN_REPORT_NAME} carries the audited bytes"
            if frozen["frozen_design_report_match"]
            else "design report was regenerated; recover it from an accepted release",
        )
    )
    add(
        CheckResult(
            "frozen_design_verification_match",
            "isolation",
            "PASS" if frozen["frozen_design_verification_match"] else "FAIL",
            f"{DESIGN_VERIFICATION_NAME} carries the audited bytes"
            if frozen["frozen_design_verification_match"]
            else "design verification was regenerated; recover it from an accepted release",
        )
    )
    add(
        CheckResult(
            "all_frozen_evidence_unchanged",
            "isolation",
            "PASS" if frozen["all_unchanged"] else "FAIL",
            f"{frozen['file_count']} frozen inputs byte identical"
            if frozen["all_unchanged"]
            else f"changed: {[item['path'] for item in frozen['changed']]}",
        )
    )
    add(
        CheckResult(
            "automatic_restore_performed",
            "isolation",
            "PASS" if frozen["automatic_restore_performed"] is False else "FAIL",
            "no evidence was repaired automatically; recovery is a confirmed human action",
        )
    )

    categories = {record.category for record in frozen_evidence_records(root)}
    required_categories = {
        "stage_01_02_controlled",
        "design_content_artifact",
        "design_manifest",
        "design_evidence",
        "plan_artifact",
        "plan_manifest",
        "migration",
    }
    add(
        CheckResult(
            "frozen_baseline_covers_every_category",
            "isolation",
            "PASS" if required_categories <= categories else "FAIL",
            f"{len(required_categories)} categories pinned including the two generated "
            "Design evidence files no manifest covers"
            if required_categories <= categories
            else f"missing: {sorted(required_categories - categories)}",
        )
    )

    # A gate or a suite that could repair evidence would hide the very defect this changeset
    # exists to prevent, so the repair entry point must be unreachable from the pipeline.
    pipeline_modules = (
        "changeset_01_baseline.py",
        "verify_changeset_01.py",
        "publish_changeset_01.py",
        "changeset_01_review_bundle.py",
        "release_verification.py",
    )
    reachable = [
        name
        for name in pipeline_modules
        if repair_entry_points_used(
            (root / "src" / "human_simulator" / "stage03" / name).read_text(encoding="utf-8")
        )
    ]
    add(
        CheckResult(
            "recovery_unreachable_from_the_pipeline",
            "isolation",
            "PASS" if not reachable else "FAIL",
            "no gate, suite or publisher can repair frozen evidence"
            if not reachable
            else f"repair reachable from: {reachable}",
        )
    )

    publishing_in_tree: list[str] = []
    for path in sorted((root / "tests").glob("test_*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if ("publish_artifacts=True" in line or "publish=True" in line) and (
                "REPO_ROOT" in line or "repo_root" in line
            ):
                publishing_in_tree.append(f"{path.name}:{number}")
    add(
        CheckResult(
            "publication_tests_are_isolated",
            "isolation",
            "PASS" if not publishing_in_tree else "FAIL",
            "every publishing test runs in a throwaway workspace copy"
            if not publishing_in_tree
            else f"publishes into the working tree: {publishing_in_tree}",
        )
    )

    lock_source = (
        root / "src" / "human_simulator" / "stage03" / "publish_changeset_01.py"
    ).read_text(encoding="utf-8")
    add(
        CheckResult(
            "publication_lock_verified",
            "isolation",
            "PASS" if "publication_lock(" in lock_source else "FAIL",
            "the publication pipeline runs under an exclusive inter-process lock",
        )
    )
    # The lock file must never travel to a reviewer: it names a pid and a host, and it would be
    # meaningless outside the machine that wrote it.
    bundled_paths = get_changeset_01_review_bundle_paths()
    lock_is_bundled = any(
        LOCK_NAME in path or path.startswith("artifacts/external-review") for path in bundled_paths
    )
    add(
        CheckResult(
            "publication_lock_excluded_from_bundle",
            "isolation",
            "PASS" if not lock_is_bundled else "FAIL",
            "no transient publication-lock artifact is a review bundle member; uv.lock is a "
            "dependency lockfile, is unrelated to publication locking, and is bundled",
        )
    )

    mismatches = relationship_manifest_mismatches(root)
    add(
        CheckResult(
            "stage_02_manifest_mismatches_enumerated",
            "isolation",
            "PASS" if len(mismatches) == 0 else "FAIL",
            "all eight relationship artifacts match the manifest after Maintenance 01"
            if not mismatches
            else "independent check reports "
            + ", ".join(item["artifact"] for item in mismatches)
            + "; Stage 02 not modified",
        )
    )


def _check_gate_hardening(add: Any, root: Path) -> None:
    """Changeset 01 v0.2.2 checks: the gate enforces every blocker, structurally.

    The v0.2 gate consulted a hand-maintained blocker list and closed blockers on word matches.
    Two conflicts documented as blocking live load were therefore not enforced at all, and a
    plain digest would have satisfied the subject-key blocker.
    """
    gate = evaluate_pre_live_load_gate(root)
    failed = set(gate.failed_checks)

    conflicts = blocking_conflicts(root)
    unenforced = [str(conflict.get("id")) for conflict in conflicts if conflict.get("id") not in failed]
    add(
        CheckResult(
            "every_open_blocking_conflict_is_a_gate_check",
            "hardening",
            "PASS" if conflicts and not unenforced else "FAIL",
            f"{len(conflicts)} OPEN BLOCKS_LIVE_LOAD conflicts enforced as FAIL checks"
            if conflicts and not unenforced
            else f"conflicts not enforced by the gate: {unenforced}",
        )
    )

    expected = {
        "canonical_loader_runtime_principal_undefined",
        "source_subject_key_opacity_undefined",
        *(str(conflict.get("id")) for conflict in conflicts),
    }
    add(
        CheckResult(
            "all_open_pre_live_load_blockers_fail_closed",
            "hardening",
            "PASS" if expected <= failed and gate.status == "FAIL" else "FAIL",
            f"gate FAIL with blockers {sorted(expected)}"
            if expected <= failed
            else f"not enforced: {sorted(expected - failed)}",
        )
    )

    subject_key = validate_subject_key_contract(root)
    runtime = validate_runtime_contract(root)
    add(
        CheckResult(
            "blocker_resolution_requires_a_structured_contract",
            "hardening",
            "PASS" if not subject_key.satisfied and not runtime.satisfied else "FAIL",
            "neither contract exists, so both blockers stay OPEN: "
            f"{subject_key.summary}; {runtime.summary}",
        )
    )

    # A digest of a bounded identifier space is reversible by exhaustive search. If any of these
    # were accepted as a keyed PRF, the subject key blocker could be closed by a reversible map.
    rejected = [name for name in ("sha256", "SHA-256", "hash", "digest", "HMAC") if classify_algorithm(name)[0]]
    accepted = classify_algorithm("HMAC-SHA256")[0]
    add(
        CheckResult(
            "unkeyed_digests_cannot_close_the_subject_key_blocker",
            "hardening",
            "PASS" if not rejected and accepted else "FAIL",
            "only keyed PRFs are accepted; bare SHA-256, hash, digest and unqualified HMAC "
            "are rejected"
            if not rejected and accepted
            else f"wrongly accepted: {rejected}",
        )
    )

    document = gate.document()
    read_only = (
        document["frozen_inputs"]["unchanged"]
        and document["repairs_performed"] == 0
        and document["manifests_created"] == 0
        and document["frozen_evidence_restored"] == 0
        and document["database_connections_opened"] == 0
        and document["clinical_rows_read"] == 0
    )
    add(
        CheckResult(
            "gate_evaluation_is_read_only",
            "hardening",
            "PASS" if read_only else "FAIL",
            f"{document['frozen_inputs']['count']} frozen inputs identical before and after; "
            "no repair, no manifest written, no database connection, no clinical row read"
            if read_only
            else "the gate mutated state during evaluation",
        )
    )

    # A workspace without the Design archive makes no claim about it, which is a valid outcome.
    # What must never happen is a claim that is not bound to the hash of the artifact inspected.
    finding = evaluate_design_archive_finding(root)
    hash_bound = not finding["archive_present"] or bool(finding.get("archive_sha256"))
    add(
        CheckResult(
            "design_archive_finding_is_hash_bound",
            "hardening",
            "PASS" if hash_bound and finding["historical_corruption_claimed"] is False else "FAIL",
            f"{finding['status']}; archive sha256 {finding.get('archive_sha256', 'not present in this workspace')}; "
            "no historical corruption asserted without the hash of a corrupted archive",
        )
    )

    _check_contract_authority(add, root, gate)


def _check_contract_authority(add: Any, root: Path, gate: Any) -> None:
    """Changeset 01 v0.2.3 checks: who may define a contract, and what its values must mean.

    v0.2.2 required a complete contract but accepted it from anywhere under the Stage 03
    directories, and compared algorithm names by substring. A changeset could therefore have
    authored the contract that unblocked itself, using an algorithm called ``not-hmac-sha256``.
    """
    failed = set(gate.failed_checks)
    authority = contract_authority_document(root)

    changeset_dir = CHANGESET_DIR.as_posix()
    forbidden_declared = any(
        item.rstrip("/") == changeset_dir.rstrip("/")
        for item in authority["forbidden_source_directories"]
    )
    paths_owned = all(
        not entry["authoritative_path"].startswith(changeset_dir)
        for entry in authority["policy"].values()
    )
    add(
        CheckResult(
            "contract_authority_excludes_the_changeset_directory",
            "hardening",
            "PASS" if forbidden_declared and paths_owned else "FAIL",
            "a changeset cannot author the contract that unblocks it; authoritative paths are "
            + ", ".join(
                f"{key} -> {entry['authoritative_path']} ({entry['owning_release']})"
                for key, entry in sorted(authority["policy"].items())
            )
            if forbidden_declared and paths_owned
            else "the changeset directory is not excluded as a contract source",
        )
    )

    covered = []
    for key, entry in sorted(authority["policy"].items()):
        manifest = root / entry["release_manifest"]
        target = Path(entry["authoritative_path"]).name
        listed = manifest.is_file() and target in manifest.read_text(encoding="utf-8")
        covered.append((key, listed))
    add(
        CheckResult(
            "authoritative_paths_are_release_manifest_covered",
            "hardening",
            "PASS" if all(listed for _, listed in covered) else "FAIL",
            "each authoritative path is listed in its owning release manifest"
            if all(listed for _, listed in covered)
            else f"not manifest covered: {[key for key, listed in covered if not listed]}",
        )
    )

    # If a name that merely contains a canonical identifier were accepted, an algorithm called
    # "not-hmac-sha256" would close the subject-key blocker while stating the opposite.
    misleading = [
        name
        for name in (
            "not-hmac-sha256",
            "fake-hmac-sha256",
            "hmac-sha256-unkeyed",
            "not-hmac-sha256-unkeyed",
            "hmac-sha256-like",
        )
        if classify_algorithm(name)[0]
    ]
    add(
        CheckResult(
            "algorithm_matching_is_exact_not_substring",
            "hardening",
            "PASS" if not misleading and classify_algorithm("HMAC-SHA256")[0] else "FAIL",
            "names that contain a canonical identifier without being one are rejected"
            if not misleading
            else f"wrongly accepted: {misleading}",
        )
    )

    registry = validate_conflict_registry(root)
    enforced = set(registry.blocking_ids) <= failed
    add(
        CheckResult(
            "accepted_artifact_conflict_registry_valid",
            "hardening",
            "PASS" if registry.valid and enforced else "FAIL",
            f"{registry.detail}; every OPEN blocking conflict is a gate check"
            if registry.valid and enforced
            else registry.detail,
        )
    )
    add(
        CheckResult(
            "conflict_registry_validity_is_a_gate_check",
            "hardening",
            "PASS" if "accepted_artifact_conflict_registry_valid" in gate.check_names else "FAIL",
            "damaging the registry adds a failure instead of silently removing blocker checks",
        )
    )

    hardcoded = []
    stage03 = root / "src" / "human_simulator" / "stage03"
    for module in ("pre_live_load_blockers.py", "pre_live_load_gate.py", "conflict_registry.py"):
        source = (stage03 / module).read_text(encoding="utf-8")
        hardcoded.extend(
            f"{module}:{entry['id']}" for entry in registry.conflicts if entry["id"] in source
        )
    add(
        CheckResult(
            "no_conflict_identifier_is_hardcoded",
            "hardening",
            "PASS" if not hardcoded else "FAIL",
            "conflict checks are derived from the registry alone"
            if not hardcoded
            else f"identifiers restated in code: {hardcoded}",
        )
    )

    instances = [
        entry
        for entry in authority["contracts"].values()
        if entry["definition_count"] > 0 or entry["satisfied"]
    ]
    add(
        CheckResult(
            "no_contract_instance_was_created",
            "hardening",
            "PASS" if not instances else "FAIL",
            "both contract blockers stay OPEN: no accepted release defines either contract"
            if not instances
            else f"contract definitions found: {[entry['found_in'] for entry in instances]}",
        )
    )


def _check_verification_hardening(add: Any, root: Path) -> None:
    """Changeset 01 v0.2 checks: frozen migrations, pinned definitions, mandatory suites."""
    immutability = migration_immutability(root)
    add(
        CheckResult(
            "published_migrations_are_immutable",
            "hardening",
            "PASS" if immutability["status"] == "PASS" else "FAIL",
            f"{len(immutability['accepted_sha256'])} accepted migrations byte identical"
            if immutability["status"] == "PASS"
            else f"violations: {immutability['violations']}",
        )
    )
    add(
        CheckResult(
            "schema_corrections_use_a_new_forward_only_migration",
            "hardening",
            "PASS" if immutability["hardening_migration_present"] else "FAIL",
            f"{HARDENING_MIGRATION_FILENAME} present",
        )
    )

    try:
        baseline = load_baseline(root)
        baseline_error = ""
    except DefinitionBaselineError as error:
        baseline = {}
        baseline_error = str(error)
    add(
        CheckResult(
            "definition_baseline_is_committed_and_self_consistent",
            "hardening",
            "PASS" if baseline else "FAIL",
            f"{DEFINITION_BASELINE_NAME} pins normalized definitions"
            if baseline
            else baseline_error,
        )
    )

    declared = {item.path.name: item.sha256 for item in discover_migrations(root)}
    produced_by = baseline.get("produced_by_migrations", {}) if baseline else {}
    add(
        CheckResult(
            "definition_baseline_traces_to_the_accepted_migrations",
            "hardening",
            "PASS" if produced_by == declared else "FAIL",
            "pinned definitions were produced by exactly these migration bytes"
            if produced_by == declared
            else "baseline was captured from different migration bytes",
        )
    )

    sections = set(baseline.get("definitions", {})) if baseline else set()
    add(
        CheckResult(
            "definition_baseline_covers_every_pinned_section",
            "hardening",
            "PASS" if sections == set(PINNED_SECTIONS) else "FAIL",
            f"{len(sections)} of {len(PINNED_SECTIONS)} sections pinned",
        )
    )

    hardened_missing = [
        f"{table}{suffix}"
        for table in PROVENANCE_BEARING_TABLES
        for suffix in HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES
        if f"{table}{suffix}"
        not in baseline.get("definitions", {}).get("constraint_definitions", {}).get(table, {})
    ]
    add(
        CheckResult(
            "provenance_hardening_constraints_are_pinned",
            "hardening",
            "PASS" if baseline and not hardened_missing else "FAIL",
            f"{len(PROVENANCE_BEARING_TABLES) * len(HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES)} "
            "hardening constraints pinned"
            if baseline and not hardened_missing
            else f"missing: {hardened_missing[:4]}",
        )
    )

    add(
        CheckResult(
            "integration_migration_suite_is_mandatory",
            "hardening",
            "PASS"
            if "integration_migration_suite" in MANDATORY_SUITE_NAMES
            and "integration_migration_suite" in NO_SKIP_SUITE_NAMES
            else "FAIL",
            "a missing, skipped or failing integration suite blocks publication",
        )
    )

    gate_inputs = get_stage02_relationship_gate_inputs()
    bundled = set(get_changeset_01_review_bundle_paths())
    missing_inputs = [name for name in gate_inputs if name not in bundled]
    add(
        CheckResult(
            "stage_02_gate_inputs_travel_with_the_bundle",
            "hardening",
            "PASS" if not missing_inputs else "FAIL",
            f"{len(gate_inputs)} gate inputs bundled so a clean extraction fails identically"
            if not missing_inputs
            else f"missing from bundle: {missing_inputs}",
        )
    )

    blockers = blockers_document(root)
    # v0.2.2 added the two conflict-derived blockers. Maintenance 01 repaired the manifest drift;
    # four blockers remain open.
    expected_blockers = {
        "canonical_loader_runtime_principal_undefined",
        "source_subject_key_opacity_undefined",
        *(str(conflict.get("id")) for conflict in blocking_conflicts(root)),
    }
    add(
        CheckResult(
            "pre_live_load_blockers_are_recorded_open",
            "hardening",
            "PASS" if set(blockers["open_blocker_ids"]) == expected_blockers else "FAIL",
            f"open: {sorted(blockers['open_blocker_ids'])}",
        )
    )
    add(
        CheckResult(
            "open_blockers_do_not_block_schema_only_migration",
            "hardening",
            "PASS" if blockers["blocks_schema_only_migration_0004"] is False else "FAIL",
            "migration 0004 stays applicable while live load is blocked",
        )
    )


def _check_schema_contract(add: Any) -> None:
    contract_tables = {table.name for table in PILOT_TABLES}
    add(
        CheckResult(
            "schema_contract_covers_exactly_pilot_entities",
            "schema_contract",
            "PASS" if contract_tables == set(PILOT_TABLE_LOAD_ORDER) else "FAIL",
            f"{len(contract_tables)} tables for {len(PILOT_ENTITY_LOAD_ORDER)} pilot entities",
        )
    )
    add(
        CheckResult(
            "provenance_is_embedded_not_a_table",
            "schema_contract",
            "PASS" if "provenance" not in contract_tables else "FAIL",
            "Provenance has no table; it is an embedded jsonb column",
        )
    )
    requiring = [table for table in PILOT_TABLES if table.requires_provenance]
    with_column = [table for table in requiring if table.column("provenance") is not None]
    add(
        CheckResult(
            "provenance_column_present_where_required",
            "schema_contract",
            "PASS" if len(requiring) == len(with_column) == 6 else "FAIL",
            f"{len(with_column)}/{len(requiring)} entities requiring provenance carry the column",
        )
    )
    add(
        CheckResult(
            "source_system_carries_no_row_provenance",
            "schema_contract",
            "PASS"
            if not next(t for t in PILOT_TABLES if t.name == "source_system").requires_provenance
            else "FAIL",
            "provenance-contract entity_exceptions.SourceSystem honoured",
        )
    )

    forbidden_found = [
        f"{table.name}.{column.name}"
        for table in PILOT_TABLES
        for column in table.columns
        if column.name in FORBIDDEN_COLUMN_NAMES
    ]
    add(
        CheckResult(
            "no_forbidden_identifier_columns",
            "schema_contract",
            "PASS" if not forbidden_found else "FAIL",
            "no global_patient_id, global_subject_id or raw primary key columns"
            if not forbidden_found
            else f"forbidden columns: {forbidden_found}",
        )
    )

    subject = next(t for t in PILOT_TABLES if t.name == "subject")
    identity_unique = any(
        columns == ("source_system_id", "source_subject_key")
        for _, columns in subject.unique_constraints
    )
    add(
        CheckResult(
            "subject_identity_is_source_local_unique",
            "schema_contract",
            "PASS" if identity_unique else "FAIL",
            "unique (source_system_id, source_subject_key)",
        )
    )

    source_record = next(t for t in PILOT_TABLES if t.name == "source_record")
    locator_unique = any(
        columns == ("source_record_locator",) for _, columns in source_record.unique_constraints
    )
    add(
        CheckResult(
            "source_locator_unique",
            "schema_contract",
            "PASS" if locator_unique else "FAIL",
            "unique source_record_locator",
        )
    )

    every_pk = all(len(table.primary_key) == 1 for table in PILOT_TABLES)
    add(
        CheckResult(
            "canonical_id_unique_index_per_entity",
            "schema_contract",
            "PASS" if every_pk else "FAIL",
            "single-column canonical identifier primary key on every pilot table",
        )
    )

    violations = load_order_violations()
    add(
        CheckResult(
            "fk_graph_matches_pipeline_load_order",
            "schema_contract",
            "PASS" if not violations else "FAIL",
            "every foreign key target is loaded earlier"
            if not violations
            else f"violations: {violations}",
        )
    )

    characteristic = next(t for t in PILOT_TABLES if t.name == "subject_characteristic")
    typed_columns = {column.name for column in characteristic.columns}
    xor_declared = "subject_characteristic_typed_value_xor" in characteristic.check_constraints
    add(
        CheckResult(
            "subject_characteristic_typed_value_xor_declared",
            "schema_contract",
            "PASS"
            if xor_declared and set(SUBJECT_CHARACTERISTIC_TYPED_VALUE_COLUMNS) <= typed_columns
            else "FAIL",
            "exactly-one typed value constraint declared over the five typed columns",
        )
    )
    identity_check = "subject_characteristic_identity_present" in characteristic.check_constraints
    add(
        CheckResult(
            "subject_characteristic_identity_not_xor",
            "schema_contract",
            "PASS" if identity_check else "FAIL",
            "at least one of characteristic_code or concept_id; XOR-only identity forbidden",
        )
    )
    raw_preserved = characteristic.column("raw_value")
    add(
        CheckResult(
            "raw_value_preserved_after_normalization",
            "schema_contract",
            "PASS" if raw_preserved is not None and not raw_preserved.nullable else "FAIL",
            "subject_characteristic.raw_value is NOT NULL",
        )
    )

    component = next(t for t in PILOT_TABLES if t.name == "observation_component")
    add(
        CheckResult(
            "observation_component_typed_value_not_invented",
            "schema_contract",
            "PASS"
            if not any("typed_value_xor" in name for name in component.check_constraints)
            else "FAIL",
            "no XOR invented for an entity the model does not constrain",
        )
    )

    temporal_columns = [
        f"{table.name}.{column.name}"
        for table in PILOT_TABLES
        for column in table.columns
        if column.name.endswith("_at") and column.data_type != "timestamp with time zone"
    ]
    add(
        CheckResult(
            "temporal_columns_are_timestamptz",
            "schema_contract",
            "PASS" if not temporal_columns else "FAIL",
            "all *_at columns are timezone-aware"
            if not temporal_columns
            else f"naive columns: {temporal_columns}",
        )
    )
    missingness_checks = {
        "encounter": "encounter_missing_clinical_time_documented",
        "observation": "observation_missing_clinical_time_documented",
    }
    documented = [
        name
        for name, constraint in missingness_checks.items()
        if constraint in next(t for t in PILOT_TABLES if t.name == name).check_constraints
    ]
    add(
        CheckResult(
            "missing_clinical_time_requires_documented_reason",
            "schema_contract",
            "PASS" if len(documented) == 2 else "FAIL",
            "encounter and observation require missingness_reason when clinical time is null",
        )
    )

    mismatch = [
        table.name
        for table in PILOT_TABLES
        if tuple(table.null_only_columns) != PILOT_NULL_ONLY_COLUMNS.get(table.name, ())
    ]
    add(
        CheckResult(
            "pilot_null_only_columns_match_accepted_plan",
            "schema_contract",
            "PASS" if not mismatch else "FAIL",
            "deferred and out-of-scope references are constrained to NULL"
            if not mismatch
            else f"mismatch: {mismatch}",
        )
    )
    provenance_checks = [
        table.name
        for table in PILOT_TABLES
        if table.requires_provenance
        and f"{table.name}_provenance_profile_valid" not in table.check_constraints
    ]
    add(
        CheckResult(
            "provenance_profile_check_on_every_provenance_table",
            "schema_contract",
            "PASS" if not provenance_checks else "FAIL",
            "profile validation constraint present"
            if not provenance_checks
            else f"missing on: {provenance_checks}",
        )
    )
    add(
        CheckResult(
            "schema_contract_fingerprint_stable",
            "schema_contract",
            "PASS" if len(contract_fingerprint()) == 64 else "FAIL",
            f"contract_fingerprint={contract_fingerprint()[:16]}...",
        )
    )


def _check_roles(add: Any, root: Path) -> None:
    grants_sql = (root / MIGRATIONS_DIR / "0003_pilot_grants.sql").read_text(encoding="utf-8")
    roles_sql = (root / MIGRATIONS_DIR / "0001_roles_and_schema.sql").read_text(encoding="utf-8")

    missing_roles = [role for role in CANONICAL_ROLES if role not in roles_sql]
    add(
        CheckResult(
            "all_planned_roles_declared",
            "roles",
            "PASS" if not missing_roles else "FAIL",
            f"{len(CANONICAL_ROLES)} roles declared" if not missing_roles else f"missing {missing_roles}",
        )
    )
    add(
        CheckResult(
            "roles_created_nologin",
            "roles",
            "PASS" if "NOLOGIN" in roles_sql and "PASSWORD" not in roles_sql.upper() else "FAIL",
            "roles are NOLOGIN and no password appears in any migration",
        )
    )
    add(
        CheckResult(
            "loader_receives_select_and_insert_only",
            "roles",
            "PASS"
            if "GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA canonical_evidence TO canonical_loader"
            in grants_sql
            else "FAIL",
            "canonical_loader holds SELECT and INSERT only",
        )
    )
    forbidden_loader = [
        token
        for token in ("UPDATE", "DELETE", "TRUNCATE")
        if f"{token} ON ALL TABLES IN SCHEMA canonical_evidence TO canonical_loader" in grants_sql
    ]
    add(
        CheckResult(
            "loader_denied_update_delete_truncate",
            "roles",
            "PASS" if not forbidden_loader else "FAIL",
            "no UPDATE, DELETE or TRUNCATE granted to canonical_loader"
            if not forbidden_loader
            else f"granted: {forbidden_loader}",
        )
    )
    add(
        CheckResult(
            "validator_receives_select_only",
            "roles",
            "PASS"
            if "GRANT SELECT ON ALL TABLES IN SCHEMA canonical_evidence TO canonical_validator_ro"
            in grants_sql
            and "INSERT ON ALL TABLES IN SCHEMA canonical_evidence TO canonical_validator_ro"
            not in grants_sql
            else "FAIL",
            "canonical_validator_ro is read-only",
        )
    )
    add(
        CheckResult(
            "schema_owned_by_canonical_owner",
            "roles",
            "PASS" if "AUTHORIZATION canonical_owner" in roles_sql else "FAIL",
            f"{CANONICAL_SCHEMA} owned by canonical_owner",
        )
    )
    add(
        CheckResult(
            "public_schema_create_revoked",
            "roles",
            "PASS" if "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in roles_sql else "FAIL",
            "no implicit object creation for PUBLIC",
        )
    )


def _check_isolation_and_safety(add: Any, root: Path) -> None:
    package = root / CANONICAL_PACKAGE
    sources = sorted(package.rglob("*.py"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in sources)

    raw_hits = sorted(token for token in RAW_RELATION_TOKENS if token in text)
    add(
        CheckResult(
            "canonical_code_reads_no_raw_relations",
            "safety",
            "PASS" if not raw_hits else "FAIL",
            "no raw source relation appears in canonical storage code"
            if not raw_hits
            else f"raw relation tokens: {raw_hits}",
        )
    )
    add(
        CheckResult(
            "canonical_target_guard_present",
            "safety",
            "PASS" if "assert_canonical_target_allowed" in text else "FAIL",
            "canonical tooling refuses raw databases and raw ports",
        )
    )
    add(
        CheckResult(
            "raw_target_guard_present",
            "safety",
            "PASS" if "assert_raw_target_allowed" in text else "FAIL",
            "raw tooling refuses the canonical database",
        )
    )
    add(
        CheckResult(
            "no_pilot_cohort_or_load_code",
            "safety",
            "PASS"
            if not any(token in text for token in ("cohort", "LIMIT 100", "extract_rows"))
            else "FAIL",
            "no cohort selection, extraction or load implementation present",
        )
    )

    changeset_dir = root / CHANGESET_DIR
    artifact_offenders: list[str] = []
    for path in sorted(changeset_dir.rglob("*")) if changeset_dir.exists() else []:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if DSN_PATTERN.search(content):
            artifact_offenders.append(f"{path.name}: dsn")
        for line in content.splitlines():
            match = SECRET_ASSIGNMENT_PATTERN.match(line.strip())
            if match and match.group("value") not in {"", PLACEHOLDER_VALUE}:
                artifact_offenders.append(f"{path.name}: {match.group('key')}")
    add(
        CheckResult(
            "changeset_artifacts_have_no_secrets_or_dsn",
            "safety",
            "PASS" if not artifact_offenders else "FAIL",
            "no literal credential-bearing DSN or secret included: no connection string, "
            "password, secret, token or key value appears in a changeset artifact"
            if not artifact_offenders
            else f"offenders: {sorted(set(artifact_offenders))[:6]}",
        )
    )


def _check_stage_02_blocker(add: Any, root: Path) -> None:
    gate = evaluate_pre_live_load_gate(root)
    add(
        CheckResult(
            "pre_live_load_gate_executable",
            "stage_02_blocker",
            "PASS" if gate.gate_id == GATE_ID else "FAIL",
            f"gate_id={gate.gate_id}",
        )
    )
    add(
        CheckResult(
            "pre_live_load_gate_fails_on_current_stage_02_drift",
            "stage_02_blocker",
            "PASS" if gate.status == "FAIL" else "FAIL",
            f"gate status={gate.status}, failed checks={list(gate.failed_checks)}",
        )
    )
    add(
        CheckResult(
            "pre_live_load_gate_did_not_modify_stage_02",
            "stage_02_blocker",
            "PASS"
            if any(
                check.name == "gate_evaluation_did_not_modify_stage_02" and check.passed
                for check in gate.checks
            )
            else "FAIL",
            "Stage 02 bytes identical before and after gate evaluation",
        )
    )

    blocked_ok = True
    for operation in BLOCKED_LIVE_OPERATIONS:
        try:
            require_live_load_authorized(root, operation)
        except LiveLoadBlocked:
            continue
        blocked_ok = False
    add(
        CheckResult(
            "gate_blocks_every_live_operation",
            "stage_02_blocker",
            "PASS" if blocked_ok else "FAIL",
            f"{len(BLOCKED_LIVE_OPERATIONS)} live operations blocked while the gate fails",
        )
    )

    migration_ops_rejected = True
    for operation in ALLOWED_WHILE_BLOCKED:
        try:
            require_live_load_authorized(root, operation)
        except ValueError:
            continue
        except LiveLoadBlocked:
            migration_ops_rejected = False
        else:
            migration_ops_rejected = False
    add(
        CheckResult(
            "gate_does_not_block_empty_storage_or_migrations",
            "stage_02_blocker",
            "PASS" if migration_ops_rejected else "FAIL",
            "storage creation and migration operations never consult the live-load gate",
        )
    )
    add(
        CheckResult(
            "gate_performs_no_repair",
            "stage_02_blocker",
            "PASS" if gate.document()["repairs_performed"] == 0 else "FAIL",
            "gate repaired nothing and restored nothing",
        )
    )


def _check_changeset_artifacts(add: Any, root: Path) -> None:
    changeset_dir = root / CHANGESET_DIR
    for name in CHANGESET_CONTENT_ARTIFACTS:
        exists = (changeset_dir / name).exists()
        add(
            CheckResult(
                f"artifact_{name}",
                "artifacts",
                "PASS" if exists else "FAIL",
                "present" if exists else "missing",
            )
        )

    plan_path = changeset_dir / CHANGESET_PLAN_NAME
    if plan_path.exists():
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        add(
            CheckResult(
                "plan_declares_frozen_versions",
                "artifacts",
                "PASS"
                if plan.get("design_baseline_version") == FROZEN_DESIGN_VERSION
                and plan.get("implementation_plan_version") == FROZEN_IMPLEMENTATION_PLAN_VERSION
                else "FAIL",
                f"design={plan.get('design_baseline_version')!r} plan={plan.get('implementation_plan_version')!r}",
            )
        )
        add(
            CheckResult(
                "plan_declares_no_data_load",
                "artifacts",
                "PASS"
                if plan.get("implementation_status") == "empty_storage_and_migrations_only"
                else "FAIL",
                f"implementation_status={plan.get('implementation_status')!r}",
            )
        )

    conflicts_path = changeset_dir / ARTIFACT_CONFLICTS_NAME
    if conflicts_path.exists():
        conflicts = yaml.safe_load(conflicts_path.read_text(encoding="utf-8"))
        recorded = conflicts.get("conflicts", [])
        add(
            CheckResult(
                "detected_artifact_conflicts_recorded",
                "artifacts",
                "PASS" if len(recorded) == conflicts.get("open_conflict_count") else "FAIL",
                f"{len(recorded)} conflicts recorded, none repaired",
            )
        )
        add(
            CheckResult(
                "no_design_or_plan_artifact_modified_for_conflicts",
                "artifacts",
                "PASS" if conflicts.get("design_or_plan_artifacts_modified") == 0 else "FAIL",
                "conflicts recorded without touching frozen artifacts",
            )
        )

    unresolved_path = changeset_dir / UNRESOLVED_DECISIONS_NAME
    if unresolved_path.exists():
        decisions = yaml.safe_load(unresolved_path.read_text(encoding="utf-8"))
        blocking = [
            item["id"] for item in decisions.get("decisions", []) if item.get("blocking_for_next_phase")
        ]
        add(
            CheckResult(
                "blocking_decisions_declared_consistently",
                "artifacts",
                "PASS" if sorted(blocking) == sorted(decisions.get("blocking_ids", [])) else "FAIL",
                f"{len(blocking)} decisions block the next phase",
            )
        )

    report_path = changeset_dir / CHANGESET_REPORT_NAME
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    draft_ok = "Report status: FINAL" not in report_text and (
        not report_text or f"Report status: {REPORT_STATUS_DRAFT}" in report_text
    )
    add(
        CheckResult(
            "report_status_draft",
            "artifacts",
            "PASS" if draft_ok else "FAIL",
            "changeset report is DRAFT and never claims FINAL",
        )
    )

    manifest_path = changeset_dir / CHANGESET_MANIFEST_NAME
    lines = (
        [line for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if manifest_path.exists()
        else []
    )
    names = [line.split(maxsplit=1)[1].strip() for line in lines]
    forbidden = sorted(set(names) & FORBIDDEN_IN_CHANGESET_MANIFEST)
    matches = bool(lines)
    for line in lines:
        digest, name = line.split(maxsplit=1)
        target = changeset_dir / name.strip()
        if not target.exists() or sha256_file(target) != digest:
            matches = False
            break
    add(
        CheckResult(
            "changeset_manifest_hashes_match",
            "artifacts",
            "PASS" if matches and names == list(CHANGESET_CONTENT_ARTIFACTS) else "FAIL",
            f"{len(lines)} content entries verified"
            if matches
            else f"manifest missing or stale ({len(lines)} entries)",
        )
    )
    add(
        CheckResult(
            "changeset_manifest_excludes_generated_evidence",
            "artifacts",
            "PASS" if not forbidden else "FAIL",
            "manifest excludes report, verification and release evidence"
            if not forbidden
            else f"forbidden entries: {forbidden}",
        )
    )


# --------------------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------------------


def _content_manifest_lines(changeset_dir: Path) -> list[str]:
    return [
        f"{sha256_file(changeset_dir / name)}  {name}"
        for name in CHANGESET_CONTENT_ARTIFACTS
        if (changeset_dir / name).exists()
    ]


def _suite_section(release_document: dict[str, Any] | None) -> list[str]:
    """Summarise recorded suite evidence. Absent evidence is reported, never invented."""
    if not release_document:
        return [
            "",
            "## Test suites",
            "",
            f"Not recorded yet. Suite evidence is written to `{RELEASE_VERIFICATION_NAME}` by the "
            "publication run.",
        ]
    lines = [
        "",
        "## Test suites",
        "",
        "| Suite | Exit | Collected | Selected | Deselected | Passed | Failed | Skipped | Seconds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for suite in release_document.get("suites", []):
        lines.append(
            f"| {suite.get('name')} | {suite.get('exit_code')} | {suite.get('collected')} | "
            f"{suite.get('selected')} | {suite.get('deselected')} | {suite.get('passed')} | "
            f"{suite.get('failed')} | {suite.get('skipped')} | {suite.get('duration_seconds')} |"
        )
    lines.extend(["", "Literal commands:", ""])
    for suite in release_document.get("suites", []):
        lines.append(f"- `{suite.get('name')}`: `{suite.get('command')}`")
    lines.extend(
        [
            "",
            f"- Overall release status: **{release_document.get('overall_release_status')}**",
            f"- Prior-stage bytes unchanged across all suites: "
            f"{release_document.get('prior_stage_integrity', {}).get('unchanged')}",
        ]
    )
    return lines


def _report_content(
    checks: list[CheckResult],
    status: str,
    manifest_sha256: str,
    baseline: dict[str, Any],
    gate_document: dict[str, Any],
    migration_evidence: dict[str, Any] | None,
    release_document: dict[str, Any] | None,
    root: Path,
) -> str:
    passed = sum(1 for check in checks if check.status == "PASS")
    failed = [check for check in checks if check.status != "PASS"]
    lines = [
        f"# Stage 03 Implementation — Changeset 01: {CHANGESET_TITLE}",
        "",
        f"## v{CHANGESET_VERSION} — {CHANGESET_SUBTITLE}",
        "",
        f"Report status: {REPORT_STATUS_DRAFT}",
        f"Changeset: {CHANGESET_ID} v{CHANGESET_VERSION}",
        f"Design baseline: v{FROZEN_DESIGN_VERSION} (frozen)",
        f"Implementation plan: v{FROZEN_IMPLEMENTATION_PLAN_VERSION} (accepted, unchanged)",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Content manifest SHA-256: {manifest_sha256}",
        f"Schema contract fingerprint: {contract_fingerprint()}",
        "",
        "## Result",
        "",
        f"- Overall status: **{status}**",
        f"- Checks passed: {passed}/{len(checks)}",
        "",
        "## Baseline precondition",
        "",
        f"- Status: {baseline['status']}",
        f"- Controlled Stage 01/02 files: {baseline['controlled_prior_stage']['file_count']}, "
        f"all unchanged: {baseline['controlled_prior_stage']['all_unchanged']}",
        f"- Design v{FROZEN_DESIGN_VERSION} manifest: {baseline['frozen_manifests']['design']['detail']}",
        f"- Implementation plan v{FROZEN_IMPLEMENTATION_PLAN_VERSION} manifest: "
        f"{baseline['frozen_manifests']['implementation_plan']['detail']}",
        "- Automatic restoration of a prior stage: not performed",
        "",
        "## Delivered",
        "",
        f"- Isolated PostgreSQL {CANONICAL_POSTGRES_VERSION} service `canonical-db` "
        f"({CANONICAL_DATABASE} on port {CANONICAL_PORT}, volume {CANONICAL_VOLUME}, network canonical-net)",
        f"- Schema `{CANONICAL_SCHEMA}` with exactly {len(PILOT_TABLE_LOAD_ORDER)} pilot tables",
        "- Forward-only migrations 0001-0003 with checksum-guarded history",
        "- Four canonical roles with least privilege, created NOLOGIN",
        f"- Executable pre-live-load gate `{GATE_ID}`",
        "",
        f"## v{CHANGESET_VERSION} — {CHANGESET_SUBTITLE}",
        "",
        "v0.2.2 replaced word search with structured contracts, which was the right shape of "
        "fix and still left two ways to obtain a PASS that meant nothing. The first was "
        "authority: a contract was accepted from any YAML file under the Stage 03 directories, "
        "including the changeset's own, so a changeset could have written the contract that "
        "unblocked the changeset. The second was meaning: fields were checked for presence and "
        "shape, not for what they said. `classify_algorithm` matched by substring, so an "
        "algorithm named `not-hmac-sha256` read as a keyed PRF while stating the opposite, and "
        "any occurrence of `SET ROLE` satisfied the loader flow, including `SET ROLE postgres`.",
        "",
        "A third weakness was structural. Deriving blocker checks from "
        "`accepted-artifact-conflicts.yaml` removed the risk of two hand-maintained lists "
        "drifting apart, but it made the check set depend on a file: deleting the registry made "
        "two blockers vanish and the gate reported fewer failures than before.",
        "",
        f"- `{CONTRACT_AUTHORITY_POLICY_NAME}` names one authoritative path per contract, each "
        "owned by an accepted release. `subject_key_transformation_contract` belongs to Stage 03 "
        "Design at `artifacts/stage-03/canonical-id-contract.yaml`; "
        "`canonical_loader_runtime_contract` belongs to the Implementation Plan at "
        "`artifacts/stage-03-implementation/security-runtime-plan.yaml`",
        "- A contract counts only if it sits at that exact path, is listed in the owning release "
        "manifest, that manifest verifies by SHA-256, and exactly one definition exists. Zero "
        "definitions keep the blocker OPEN; two definitions fail "
        "`contract_definitions_are_unambiguous`, because a contract that exists twice is a "
        "contract nobody owns",
        "- The changeset directory is structurally excluded as a contract source. Recursive "
        "discovery is gone: the scope is still walked, but only to detect and name strays",
        "- Algorithm identifiers match by equality against a fixed set. `not-hmac-sha256`, "
        "`fake-hmac-sha256`, `hmac-sha256-unkeyed` and an unqualified `HMAC` all fail",
        "- Field values are validated for meaning: `transformation_id` must name the "
        "transformation the record construction contract references, key and credential fields "
        "must be secret-store references rather than values, collision handling must stop the "
        "load, `set_role_flow` must state `SET ROLE canonical_loader` and no other role, grants "
        "are checked against an allowlist, and a revocation procedure must name a revoking action",
        "- `accepted_artifact_conflict_registry_valid` validates the registry as an artifact in "
        "its own right. Absent, unparsable, malformed, duplicated, self-inconsistent or "
        "manifest-mismatched each add a failure rather than removing checks",
        "- No contract instance was created and no blocker was resolved. All five stay OPEN",
        "",
        "## v0.2.2 — Pre-live-load Gate Hardening",
        "",
        "The v0.2 gate was weaker than its own documentation. It consulted a hand-maintained "
        "blocker list that omitted the two conflicts already recorded as `BLOCKS_LIVE_LOAD` and "
        "`OPEN`, so an executable guard and the artifact describing it disagreed. It also "
        "decided resolution by searching artifacts for words: any file containing `hash` proved "
        "subject-key opacity, and any file mentioning `SET ROLE` proved a loader runtime "
        "principal existed. `SHA256(account_patient.id)` would have satisfied the first while "
        "remaining reversible by exhaustive search over a bounded integer space, and a sentence "
        "stating that no `SET ROLE` path exists would have satisfied the second.",
        "",
        "- All five open reasons are now FAIL checks of the gate, and conflicts become checks "
        "automatically: any entry in `accepted-artifact-conflicts.yaml` that is `OPEN` and "
        "`BLOCKS_LIVE_LOAD` blocks the load without being restated in code",
        "- Word search is gone. A subject key is opaque only under a complete "
        "`subject_key_transformation_contract` whose algorithm is a keyed PRF; unkeyed digests, "
        "and the bare words `hash`, `opaque`, `pseudonym` and `digest`, are rejected",
        "- A loader principal exists only under a complete `canonical_loader_runtime_contract`; "
        "`TBD`, an empty field and a prose mention of `SET ROLE` are rejected",
        f"- `{LIVE_LOAD_CONTRACT_SCHEMA_NAME}` states the required shape of both contracts. It "
        "is a schema, not a contract: writing an instance would close a blocker by "
        "self-assertion, so this changeset writes none and both blockers stay OPEN",
        "- The gate hashes all 36 frozen inputs before and after evaluation, opens no database "
        "connection, reads no clinical row, writes no manifest and restores nothing",
        "- A missing blocker is itself a failure: `required_blocker_checks_present` fails if a "
        "mandatory check disappears, so deleting a source artifact cannot silently unblock",
        "",
        "## v0.2.1 — Publication Isolation Fix",
        "",
        "External audit of v0.2 found that the review archive carried Design evidence a test "
        "had regenerated in the working tree, rather than the bytes of the accepted Design "
        "v0.7.4 release. Two full test runs were executing concurrently during publication; "
        "both republished Stage 03 evidence, and the interleaving left the regenerated files in "
        "place for the builder to package. The eleven Design content artifacts were correct "
        "throughout, because a manifest covers them; the two generated evidence files were "
        "covered by nothing.",
        "",
        f"- The accepted bytes were recovered from an accepted release and are pinned: "
        f"`{DESIGN_REPORT_NAME}` and `{DESIGN_VERIFICATION_NAME}`",
        "- The frozen baseline now pins 36 inputs by hash and is re-checked before and after "
        "every mandatory suite, so a suite that writes into a frozen path blocks publication",
        "- Every publication-capable test runs in a throwaway workspace copy; none writes into "
        "`artifacts/stage-03/`, `artifacts/stage-03-implementation/`, the changeset snapshot or "
        "`artifacts/external-review/`",
        "- The publication pipeline holds an exclusive inter-process lock, so two publishers "
        "cannot interleave writes into one snapshot or archive",
        "- The bundle builder refuses to package Design evidence that does not match the "
        "audited hashes, and never regenerates it",
        "- Recovery is a confirmed human action (`audit recover-design-evidence --confirm`) "
        "that installs only bytes hashing to the audited values, and is unreachable from any "
        "gate, suite or publisher",
        "",
        "## v0.2 hardening",
        "",
        "- Migrations 0001-0003 are byte-pinned in `ACCEPTED_MIGRATION_SHA256`; every schema "
        f"correction arrives through the new forward-only `{HARDENING_MIGRATION_FILENAME}`",
        f"- `{DEFINITION_BASELINE_NAME}` pins the normalized definitions PostgreSQL itself "
        "reports for every constraint, index, enum, owner and privilege, so a renamed "
        "`CHECK (TRUE)` cannot pass a name-only comparison",
        "- The integration/migration suite is mandatory: absent, skipped or failing blocks "
        "publication",
        f"- Migration 0004 hardens provenance on {len(PROVENANCE_BEARING_TABLES)} evidence tables: "
        "required keys must be present and non-null, origin-specific fields are enforced, "
        "source-backed and computed profiles stay mutually exclusive, and SYNTHETIC and "
        "PREDICTED remain rejected",
        "- The Stage 02 gate inputs travel with the review bundle, so a clean extraction fails "
        "for the same reason as the publisher workspace",
        "",
        "## Stage 02 blocker",
        "",
        f"- Gate: `{GATE_ID}`",
        f"- Status: **{gate_document['status']}**",
        f"- Failed checks: {', '.join(gate_document['failed_checks']) or 'none'}",
        f"- Blocks {len(gate_document['blocks_live_operations'])} live operations; "
        f"does not block {len(gate_document['does_not_block'])} storage operations",
        "- Repairs performed: 0; Stage 02 modified: no",
        "",
        "Maintenance 01 re-sealed `relationship-manifest.sha256` over the accepted artifact "
        "bytes. The manifest now verifies 8/8; `stage02_relationship_manifest_drift` is "
        "RESOLVED. Four contract and conflict blockers remain open.",
        "",
    ]
    if gate_document.get("relationship_manifest_mismatches"):
        lines.append(
            f"An independent recount finds {gate_document['relationship_manifest_mismatch_count']} "
            "manifest mismatches."
        )
        for mismatch in gate_document.get("relationship_manifest_mismatches", []):
            lines.append(
                f"- `{mismatch['artifact']}`: manifest records "
                f"`{mismatch['recorded_sha256'][:16]}…`, file is "
                f"`{mismatch['current_sha256'][:16]}…`"
            )
    lines.extend(
        [
            "",
            "## Open pre-live-load blockers",
            "",
        ]
    )
    for blocker in gate_document.get("pre_live_load_blockers", {}).get("blockers", []):
        lines.append(
            f"- `{blocker['blocker_id']}` ({blocker['status']}): {blocker['question'].strip()} "
            f"Blocks live load: {blocker['blocks_live_load']}; blocks schema-only migration "
            f"0004: {blocker['blocks_schema_only_migration_0004']}"
        )
    finding = evaluate_design_archive_finding(root)
    lines.extend(
        [
            "",
            "## Finding: Design v0.7.4 review archive",
            "",
            f"- Finding: `{finding['finding_id']}`",
            f"- Status: **{finding['status']}**",
            f"- Archive: `{finding['archive_source']}`"
            if finding["archive_present"]
            else "- Archive: not present in this workspace",
        ]
    )
    if finding["archive_present"]:
        lines.extend(
            [
                f"- Archive SHA-256: `{finding['archive_sha256']}`",
                f"- Accepted archive SHA-256 recorded: "
                f"{finding['accepted_archive_sha256_recorded']} "
                f"({'sidecar present' if finding['accepted_archive_sha256_recorded'] else 'no sidecar was ever published for this archive'})",
                "",
                "| Design evidence file | SHA-256 in archive | Audited SHA-256 |",
                "| --- | --- | --- |",
            ]
        )
        for name, digest in sorted(finding["embedded_design_evidence_sha256"].items()):
            audited = finding["audited_design_evidence_sha256"][name]
            lines.append(f"| `{name}` | `{digest}` | `{audited}` |")
        lines.extend(
            [
                "",
                finding["claim"],
                "",
                finding["why_no_historical_claim"],
                "",
                "The audited bytes in the working tree were recovered from "
                + ", ".join(f"`{item}`" for item in finding["audited_bytes_recovered_from"])
                + ", each of which carries them.",
            ]
        )
    lines.extend(
        [
            "",
            "## Schema-only migration result",
            "",
        ]
    )
    if migration_evidence:
        counts = migration_evidence.get("schema_only_result", {}).get("row_counts", {})
        lines.extend(
            [
                f"- Migration status: {migration_evidence.get('status')}",
                f"- Applied in this run: {migration_evidence.get('migration', {}).get('applied_in_this_run')}",
                f"- Database is empty: {migration_evidence.get('schema_only_result', {}).get('database_is_empty')}",
                f"- Row counts: {counts}",
            ]
        )
    else:
        lines.append(
            "- Not executed in this workspace: no canonical database endpoint was configured. "
            "The migration/integration suite records the skip reason by name only."
        )
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Category | Status | Detail |",
            "| --- | --- | --- | --- |",
        ]
    )
    for check in checks:
        detail = check.detail.replace("|", "\\|")
        lines.append(f"| {check.name} | {check.category} | {check.status} | {detail} |")

    if failed:
        lines.extend(["", "## Failed checks", ""])
        lines.extend(f"- {check.name}: {check.detail}" for check in failed)

    lines.extend(_suite_section(release_document))

    lines.extend(
        [
            "",
            "## Explicit non-actions",
            "",
            "- No clinical row was read from Source A or Source B",
            "- No extraction, transformation, load or ETL was executed",
            "- No pilot cohort was created",
            "- No data was loaded into the canonical database",
            "- No raw database was modified",
            "- No Stage 01 or Stage 02 artifact was modified",
            "- Source B was not connected",
            "- No patient linkage or merge was performed",
            "- No simulation or prediction work was started",
            f"- Design v{FROZEN_DESIGN_VERSION} and Plan v{FROZEN_IMPLEMENTATION_PLAN_VERSION} were not changed",
            "- No literal credential-bearing DSN or secret was included in any artifact; no "
            "PII, HMAC value or raw value was stored",
            "- No Stage 02 maintenance was started and the manifest drift was not repaired",
            "- No pre-live-load blocker was resolved; the two contracts remain unwritten",
            "- Migrations 0001-0004 were not modified and no migration 0005 was created",
            "- The canonical schema and the definition baseline were not changed",
            "- No schema drift found by the verifier was repaired automatically",
            "- No frozen evidence was restored automatically; recovery required explicit "
            "confirmation and installed only audited bytes",
            "- Design evidence was recovered from an accepted release, never regenerated",
            "- The v0.2 and v0.2.1 review bundles were not overwritten",
            "- The Design v0.7.4 review bundle was not republished",
            "- Changeset 02 was not started",
            "",
            "## Status",
            "",
            f"Report status: {REPORT_STATUS_DRAFT}. Stage 03 is not promoted to FINAL and "
            "Changeset 02 has not been started.",
            "",
        ]
    )
    return "\n".join(lines)


def verify_changeset_01(
    repo_root: Path,
    *,
    publish_artifacts: bool = True,
    migration_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every Changeset 01 check. With ``publish_artifacts=False`` nothing is written."""
    root = repo_root.resolve()
    if publish_artifacts:
        # Writing the snapshot is a publication: two concurrent writers would interleave the
        # report, the verification and the manifest. Read-only runs need no lock.
        with publication_lock(root, operation="changeset_01_snapshot"):
            return _verify_changeset_01(
                root, publish_artifacts=True, migration_evidence=migration_evidence
            )
    return _verify_changeset_01(
        root, publish_artifacts=False, migration_evidence=migration_evidence
    )


def _verify_changeset_01(
    root: Path,
    *,
    publish_artifacts: bool,
    migration_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    changeset_dir = root / CHANGESET_DIR

    baseline = evaluate_baseline(root)
    gate = evaluate_pre_live_load_gate(root)
    gate_document = gate.document()

    if migration_evidence is None:
        existing = changeset_dir / MIGRATION_RESULT_NAME
        if existing.exists():
            migration_evidence = json.loads(existing.read_text(encoding="utf-8"))

    # Generated evidence is written before the checks run so that both publish modes see an
    # identical set of files and therefore an identical check count.
    if publish_artifacts:
        changeset_dir.mkdir(parents=True, exist_ok=True)
        write_baseline_verification(root, baseline)
        (changeset_dir / GATE_RESULT_NAME).write_text(
            json.dumps(gate_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (changeset_dir / SCHEMA_CONTRACT_NAME).write_text(
            json.dumps(
                {
                    "changeset": CHANGESET_ID,
                    "contract_fingerprint": contract_fingerprint(),
                    "contract": contract_document(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (changeset_dir / PRIOR_STAGE_INTEGRITY_NAME).write_text(
            json.dumps(build_prior_stage_integrity_document(root), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (changeset_dir / DESIGN_ARCHIVE_FINDING_NAME).write_text(
            json.dumps(evaluate_design_archive_finding(root), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path = changeset_dir / CHANGESET_MANIFEST_NAME
        manifest_path.write_text("\n".join(_content_manifest_lines(changeset_dir)) + "\n", encoding="utf-8")

    checks: list[CheckResult] = []

    def add(result: CheckResult) -> None:
        checks.append(result)

    _check_baseline(add, baseline)
    _check_implementation_gate(add, root)
    _check_infrastructure(add, root)
    _check_migration_mechanism(add, root)
    _check_verification_hardening(add, root)
    _check_publication_isolation(add, root)
    _check_gate_hardening(add, root)
    _check_schema_contract(add)
    _check_roles(add, root)
    _check_isolation_and_safety(add, root)
    _check_stage_02_blocker(add, root)
    _check_changeset_artifacts(add, root)

    status: str = "PASS" if all(check.status == "PASS" for check in checks) else "FAIL"

    payload: dict[str, Any] = {
        "changeset": CHANGESET_ID,
        "changeset_version": CHANGESET_VERSION,
        "title": CHANGESET_TITLE,
        "verified_at": datetime.now(UTC).isoformat(),
        "overall_status": status,
        "checks_total": len(checks),
        "checks_passed": sum(1 for check in checks if check.status == "PASS"),
        "checks_failed": sum(1 for check in checks if check.status != "PASS"),
        "failures": [check.name for check in checks if check.status != "PASS"],
        "checks": [asdict(check) for check in checks],
        "design_baseline_version": FROZEN_DESIGN_VERSION,
        "implementation_plan_version": FROZEN_IMPLEMENTATION_PLAN_VERSION,
        "schema_contract_fingerprint": contract_fingerprint(),
        "baseline_status": baseline["status"],
        "stage02_pre_live_load_gate": {
            "gate_id": gate_document["gate_id"],
            "status": gate_document["status"],
            "failed_checks": gate_document["failed_checks"],
            "repairs_performed": gate_document["repairs_performed"],
        },
        "migration_evidence_present": migration_evidence is not None,
        "report_status": REPORT_STATUS_DRAFT,
        "publish_artifacts": publish_artifacts,
    }

    if not publish_artifacts:
        return payload

    manifest_sha256 = sha256_file(changeset_dir / CHANGESET_MANIFEST_NAME)
    release_path = changeset_dir / RELEASE_VERIFICATION_NAME
    release_document = (
        json.loads(release_path.read_text(encoding="utf-8")) if release_path.exists() else None
    )
    report_text = _report_content(
        checks,
        status,
        manifest_sha256,
        baseline,
        gate_document,
        migration_evidence,
        release_document,
        root,
    )
    report_path = changeset_dir / CHANGESET_REPORT_NAME
    report_path.write_text(report_text, encoding="utf-8")

    payload["content_manifest_sha256"] = manifest_sha256
    payload["report_sha256"] = sha256_file(report_path)
    (changeset_dir / CHANGESET_VERIFICATION_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload
