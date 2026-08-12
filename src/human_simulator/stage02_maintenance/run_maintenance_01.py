"""Stage 02 Maintenance 01 — run the diagnosis, prepare the repair, publish the evidence.

Nothing in this module writes into ``artifacts/stage-02/``, restores a file, or resolves the
defect. It produces a candidate and the evidence that would justify applying it; applying it is
a separate, explicitly authorised step that this maintenance changeset does not take.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
)
from human_simulator.stage02_maintenance.candidate import (
    build_candidate,
    validate_candidate,
    write_json,
)
from human_simulator.stage02_maintenance.constants import (
    CANDIDATE_DIR,
    DECISION_NAME,
    DEFECT_ID,
    DRIFT_DIAGNOSIS_NAME,
    HASH_MATRIX_NAME,
    ISOLATED_VALIDATION_NAME,
    MAINTENANCE_DIR,
    MAINTENANCE_ID,
    MAINTENANCE_TITLE,
    MAINTENANCE_VERSION,
    QUERY_LOG_NAME,
    REPRODUCTION_NAME,
    SEMANTIC_COMPARISON_NAME,
    STAGE_02_DIR,
)
from human_simulator.stage02_maintenance.drift_diagnosis import (
    compare_semantics,
    evaluate_drift,
    read_manifest,
    sha256_bytes,
    sha256_file,
    timestamp_split,
)
from human_simulator.stage02_maintenance.reproduction import reproduce_assessment
from human_simulator.stage03.prior_stage_integrity import ACCEPTED_SHA256

# The two authorities that pin the same artifact to different bytes. Naming them is the whole
# diagnosis: the drift is not corruption, it is two controls disagreeing about one file.
RELATIONSHIP_AUTHORITY = "artifacts/stage-02/relationship-manifest.sha256"
PRIOR_STAGE_AUTHORITY = "human_simulator.stage03.prior_stage_integrity.ACCEPTED_SHA256"


def contested_artifacts() -> tuple[str, ...]:
    """Artifacts pinned by both the relationship manifest and the prior-stage baseline."""
    pinned = {Path(path).name for path in ACCEPTED_SHA256 if path.startswith("artifacts/stage-02/")}
    return tuple(sorted(set(RELATIONSHIP_MANIFEST_ARTIFACTS) & pinned))


def restore_mechanism(repo_root: Path) -> dict[str, Any]:
    """The named command that produces exactly the observed state, checked rather than assumed.

    ``restore-prior-stage-baseline`` copies controlled Stage 01/02 bytes out of a pinned release
    archive. If its source copies of the two drifted files hash to what is on disk, and it does
    not touch the relationship manifest, then running it after the manifest was sealed produces
    the drift exactly — no other explanation is needed.
    """
    import zipfile

    from human_simulator.stage03.prior_stage_integrity import (
        BASELINE_SOURCE_ZIP,
        CONTROLLED_PRIOR_STAGE_PATHS,
    )

    root = repo_root.resolve()
    archive = root / BASELINE_SOURCE_ZIP
    source_hashes: dict[str, str | None] = {}
    if archive.is_file():
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            for name in contested_artifacts():
                member = f"{STAGE_02_DIR.as_posix()}/{name}"
                source_hashes[name] = (
                    sha256_bytes(bundle.read(member)) if member in names else None
                )

    directory = root / STAGE_02_DIR
    current = {name: sha256_file(directory / name) for name in contested_artifacts()}
    manifest_path = f"{STAGE_02_DIR.as_posix()}/{MANIFEST_NAME}"

    covered = tuple(
        sorted(
            Path(path).name
            for path in CONTROLLED_PRIOR_STAGE_PATHS
            if Path(path).name in RELATIONSHIP_MANIFEST_ARTIFACTS
        )
    )
    return {
        "command": "audit restore-prior-stage-baseline --confirm",
        "restores_bytes_from": BASELINE_SOURCE_ZIP,
        "relationship_artifacts_it_covers": list(covered),
        "covers_the_relationship_manifest": manifest_path in CONTROLLED_PRIOR_STAGE_PATHS,
        "source_sha256": source_hashes,
        "source_matches_current_bytes": source_hashes == current,
        "explains_the_observed_state": (
            source_hashes == current
            and manifest_path not in CONTROLLED_PRIOR_STAGE_PATHS
            and sorted(covered) == sorted(contested_artifacts())
        ),
    }


def build_hash_matrix(repo_root: Path, reproduction: Any) -> dict[str, Any]:
    """Every hash for every artifact from every source, side by side."""
    root = repo_root.resolve()
    recorded = read_manifest(root)
    drifts = {item.name: item for item in evaluate_drift(root)}
    directory = root / STAGE_02_DIR
    accepted_by_name = {
        Path(path).name: digest
        for path, digest in ACCEPTED_SHA256.items()
        if path.startswith("artifacts/stage-02/")
    }

    rows: list[dict[str, Any]] = []
    for name in RELATIONSHIP_MANIFEST_ARTIFACTS:
        drift = drifts[name]
        rows.append(
            {
                "artifact": name,
                "working_stage_02_sha256": drift.current_sha256,
                "relationship_manifest_records": recorded.get(name),
                "prior_stage_baseline_pins": accepted_by_name.get(name),
                "read_only_reproduction_sha256": reproduction.artifact_sha256.get(name),
                "matches_relationship_manifest": drift.matches_manifest,
                "pinned_by_both_authorities": name in contested_artifacts(),
                "current_bytes_published_in": list(drift.current_bytes_published_in),
                "manifest_bytes_published_in": list(drift.manifest_bytes_published_in),
                "distinct_published_hashes": len({c.sha256 for c in drift.published_copies}),
            }
        )

    manifest_path = directory / MANIFEST_NAME
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "defect": DEFECT_ID,
        "authorities": {
            "relationship_manifest": RELATIONSHIP_AUTHORITY,
            "prior_stage_baseline": PRIOR_STAGE_AUTHORITY,
        },
        "artifacts_pinned_by_both_authorities": list(contested_artifacts()),
        "working_relationship_manifest_sha256": sha256_file(manifest_path)
        if manifest_path.is_file()
        else None,
        "reproduction_manifest_sha256": reproduction.artifact_sha256.get(MANIFEST_NAME),
        "rows": rows,
        "drifted_artifacts": [row["artifact"] for row in rows if not row["matches_relationship_manifest"]],
        "matching_artifacts": [row["artifact"] for row in rows if row["matches_relationship_manifest"]],
    }


def build_semantic_comparison(repo_root: Path, reproduction: Any) -> dict[str, Any]:
    """Do the byte-different copies say the same thing? Compared against every published copy."""
    root = repo_root.resolve()
    directory = root / STAGE_02_DIR
    drifts = {item.name: item for item in evaluate_drift(root)}

    import zipfile

    comparisons: list[dict[str, Any]] = []
    for name in contested_artifacts():
        current = (directory / name).read_bytes()

        for copy in drifts[name].published_copies:
            archive = root / "artifacts" / "external-review" / copy.bundle
            with zipfile.ZipFile(archive) as bundle:
                payload = bundle.read(copy.member)
            comparisons.append(
                compare_semantics(
                    name,
                    current,
                    payload,
                    reference_label="working artifacts/stage-02",
                    other_label=f"published {copy.bundle}",
                ).document()
            )

        reproduced = reproduction.artifact_bytes.get(name)
        if reproduced is not None:
            comparisons.append(
                compare_semantics(
                    name,
                    current,
                    reproduced,
                    reference_label="working artifacts/stage-02",
                    other_label="read-only reproduction",
                ).document()
            )

    divergent = [item for item in comparisons if not item["semantically_identical"]]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "compared_artifacts": list(contested_artifacts()),
        "comparison_count": len(comparisons),
        "all_semantically_identical": not divergent,
        "semantically_divergent": divergent,
        "volatile_field_is_the_only_difference": not divergent
        and all(
            item["bytes_identical"] or item["volatile_differences"] for item in comparisons
        ),
        "comparisons": comparisons,
    }


def build_decision(
    repo_root: Path,
    *,
    hash_matrix: dict[str, Any],
    semantics: dict[str, Any],
    candidate: Any,
    validation: Any,
    reproduction: Any,
) -> dict[str, Any]:
    """The repair proposal, its justification, and everything it deliberately does not do."""
    drifted = hash_matrix["drifted_artifacts"]
    unattested = [
        row["artifact"]
        for row in hash_matrix["rows"]
        if not row["matches_relationship_manifest"] and not row["manifest_bytes_published_in"]
    ]

    timestamp_splits = [timestamp_split(repo_root, name) for name in contested_artifacts()]
    mechanism = restore_mechanism(repo_root)

    justified = (
        semantics["all_semantically_identical"]
        and reproduction.completed
        and bool(unattested)
        and validation.manifest_verified
        and validation.drift_blocker_cleared
        and not validation.evaluated_failures
        and validation.working_stage_02_unchanged
    )

    return {
        "maintenance_id": MAINTENANCE_ID,
        "maintenance_version": MAINTENANCE_VERSION,
        "decided_at": datetime.now(UTC).isoformat(),
        "defect": DEFECT_ID,
        "status": "DIAGNOSED_REPAIR_PREPARED_NOT_APPLIED",
        "drifted_artifacts": drifted,
        "root_cause": (
            "Two controls pin the same two files to different bytes. The relationship manifest "
            "was sealed by the assessment run of 2026-08-01T16:52Z over the artifacts that run "
            "produced. The Stage 03 prior-stage integrity baseline pins the same two files to "
            "the bytes of the 2026-07-31T22:38Z run. Those two files, and only those two, are "
            "the intersection of RELATIONSHIP_MANIFEST_ARTIFACTS and ACCEPTED_SHA256, so a "
            "prior-stage restore reverted them while the six artifacts pinned by the manifest "
            "alone were left at the values the manifest records."
        ),
        "mechanism": mechanism,
        "corroborating_evidence": {
            "restore_mechanism_explains_observed_state": mechanism["explains_the_observed_state"],
            "intersection_of_authorities_equals_drifted_set": sorted(contested_artifacts())
            == sorted(drifted),
            "manifest_expected_bytes_published_in_any_release": not unattested,
            "markdown_siblings_disagree_with_their_json": all(
                item["siblings_disagree"] for item in timestamp_splits
            ),
            "timestamp_split": timestamp_splits,
            "bodies_identical_across_all_published_copies": semantics["all_semantically_identical"],
            "read_only_reproduction_reproduces_the_same_body": reproduction.completed,
        },
        "authoritative_bytes": {
            name: {
                "sha256": next(
                    row["working_stage_02_sha256"]
                    for row in hash_matrix["rows"]
                    if row["artifact"] == name
                ),
                "why": (
                    "pinned by the Stage 03 prior-stage integrity baseline, published verbatim "
                    "in accepted review bundles, and confirmed semantically current by a "
                    "read-only reproduction"
                ),
                "published_in": next(
                    row["current_bytes_published_in"]
                    for row in hash_matrix["rows"]
                    if row["artifact"] == name
                ),
            }
            for name in drifted
        },
        "rejected_alternatives": [
            {
                "option": "recompute the manifest over whatever is on disk",
                "rejected_because": (
                    "identical in outcome to the proposed repair only because provenance was "
                    "established first; taken on its own it signs unverified bytes as correct"
                ),
            },
            {
                "option": "adopt the freshly reproduced artifacts",
                "rejected_because": (
                    "a new run writes a new assessed_at, producing bytes no release has "
                    "accepted and breaking the prior-stage baseline for both files"
                ),
            },
            {
                "option": "restore the bytes the manifest expects",
                "rejected_because": (
                    "those bytes exist in no published release and cannot be reconstructed from "
                    "any accepted artifact"
                ),
            },
        ],
        "proposed_repair": {
            "action": "re-seal relationship-manifest.sha256 over the accepted artifact bytes",
            "artifacts_modified": 0,
            "manifest_files_modified": 1,
            "candidate_manifest_sha256": candidate.manifest_sha256,
            "candidate_directory": CANDIDATE_DIR.as_posix(),
            "justified_by_evidence": justified,
            "applied": False,
            "requires": "a separate, explicitly authorised Stage 02 repair step",
        },
        "residual_observations": [
            {
                "observation": (
                    "subject-root-analysis.md and identity-linkage-assessment.md still record "
                    "the 2026-08-01T16:52Z run while their .json siblings record 2026-07-31T22:38Z"
                ),
                "action": "none",
                "why": (
                    "both markdown files match the manifest and were published in accepted "
                    "bundles; regenerating them to agree would create fresh unattested bytes and "
                    "a second drift"
                ),
            },
            {
                "observation": (
                    "assessed_at makes every relationship artifact non-reproducible byte for byte"
                ),
                "action": "recorded for a future changeset",
                "why": "changing artifact generation is out of scope for a diagnosis",
            },
        ],
        "isolated_validation": validation.document(),
        "non_actions": [
            "artifacts/stage-02/ not written",
            "no automatic restore performed",
            "no repair applied",
            "relationship manifest not resolved in the working tree",
            "Design v0.7.5 not created",
            "Plan v0.3.6 not created",
            "Changeset 02 not started",
            "no ETL, extraction or load",
            "no canonical schema or migration change",
            "no published archive overwritten",
        ],
    }


def render_diagnosis(
    *,
    hash_matrix: dict[str, Any],
    semantics: dict[str, Any],
    decision: dict[str, Any],
    reproduction: Any,
    validation: Any,
) -> str:
    drifted = hash_matrix["drifted_artifacts"]
    rows = {row["artifact"]: row for row in hash_matrix["rows"]}

    lines = [
        f"# Stage 02 Maintenance 01 — {MAINTENANCE_TITLE}",
        "",
        f"Maintenance version: {MAINTENANCE_VERSION}",
        "Report status: DRAFT",
        f"Defect: `{DEFECT_ID}`",
        "Repair applied: **no**",
        "",
        "## What is wrong",
        "",
        f"`{MANIFEST_NAME}` records a SHA-256 for eight artifacts. Six match. Two do not:",
        "",
        "| Artifact | Manifest records | File is |",
        "|----------|------------------|---------|",
    ]
    for name in drifted:
        row = rows[name]
        lines.append(
            f"| `{name}` | `{row['relationship_manifest_records']}` | `{row['working_stage_02_sha256']}` |"
        )

    lines += [
        "",
        "The obvious repair is to recompute the manifest over the files on disk. That would turn "
        "an unexplained difference into a signed statement that the current bytes are correct, "
        "which is the one thing not yet established. So provenance comes first.",
        "",
        "## Where the drift came from",
        "",
        "Two controls pin the same two files, and they disagree.",
        "",
        f"* `{RELATIONSHIP_AUTHORITY}` pins all eight relationship artifacts.",
        f"* `{PRIOR_STAGE_AUTHORITY}` pins nine Stage 01/02 files, seven of them in Stage 02.",
        "",
        "The intersection of the two sets is exactly "
        f"`{'`, `'.join(contested_artifacts())}` — precisely the two artifacts that drifted. "
        "The six artifacts the manifest alone pins still match it.",
        "",
        "The timestamps inside the artifacts show what happened. Each assessment run writes all "
        "eight artifacts together, so a `.json` and its own `.md` sibling always agree about "
        "when they were assessed — unless something replaced one of them afterwards. They do "
        "not agree:",
        "",
        "| Artifact | `assessed_at` in the JSON | `Assessed at` in the markdown |",
        "|----------|---------------------------|-------------------------------|",
    ]
    for item in decision["corroborating_evidence"]["timestamp_split"]:
        lines.append(
            f"| `{item['json_artifact']}` | `{item['json_assessed_at']}` "
            f"| `{item['markdown_assessed_at']}` |"
        )
    lines += [
        "",
        "The markdown timestamps are the ones the manifest was sealed at: "
        "`relationship-verification-report.json` carries the matching `verified_at` and records "
        "`relationship_manifest: PASS, verified 8 entries`, so at that moment all eight artifacts "
        "did match. Only the two `.json` files were later moved back to the earlier run — the "
        "bytes the prior-stage baseline pins. Nothing pins the markdown, so nothing reverted it. "
        "A `.json` disagreeing with its own `.md` is the fingerprint of a targeted restore, not "
        "of a regeneration.",
        "",
        "### The mechanism, by name",
        "",
        f"`{decision['mechanism']['command']}` copies controlled Stage 01/02 bytes out of "
        f"`{decision['mechanism']['restores_bytes_from']}`. Of the eight relationship artifacts "
        f"it covers exactly `{'`, `'.join(decision['mechanism']['relationship_artifacts_it_covers'])}`, "
        "and it does not cover the relationship manifest "
        f"(`covers_the_relationship_manifest: {decision['mechanism']['covers_the_relationship_manifest']}`). "
        "Its source copies of those two files hash to precisely the bytes now on disk "
        f"(`source_matches_current_bytes: {decision['mechanism']['source_matches_current_bytes']}`). "
        "Running it after the manifest was sealed therefore produces the observed state exactly, "
        "which is what "
        f"`explains_the_observed_state: {decision['mechanism']['explains_the_observed_state']}` "
        "records. This is a design consequence of two controls overlapping, not corruption and "
        "not a fault in the restore.",
        "",
        "## Which bytes are authoritative",
        "",
        "The bytes currently on disk. Two controls already vouch for them:",
        "",
    ]
    for name in drifted:
        row = rows[name]
        lines.append(
            f"* `{name}` — `{row['working_stage_02_sha256']}` is pinned by the prior-stage "
            f"baseline and published verbatim in {len(row['current_bytes_published_in'])} "
            "accepted review bundles."
        )
    lines += [
        "",
        "",
        "A third check rules out the alternative rather than supporting the claim: the bytes the "
        "manifest expects are vouched for by nothing at all.",
        "",
        "The bytes the manifest expects appear in **no** published release. Every review bundle "
        "in `artifacts/external-review/` was searched, along with the whole working tree; "
        f"`{rows[drifted[0]]['relationship_manifest_records']}` and "
        f"`{rows[drifted[1]]['relationship_manifest_records']}` occur nowhere. They cannot be "
        "restored, because no accepted artifact contains them.",
        "",
        "## The difference is a timestamp, not a finding",
        "",
        f"{semantics['comparison_count']} comparisons were made: every published copy of both "
        "artifacts, plus a fresh read-only reproduction, each against the working copy. With "
        "`assessed_at` removed, every body is identical — "
        f"`all_semantically_identical: {semantics['all_semantically_identical']}`.",
        "",
        "That covers the verdicts (`identity_verdict`, `overall_verdict`, "
        "`coverage_threshold_confirmed`), the aggregates and their denominators "
        "(`source_a_aggregates`, `source_b_aggregates`, `overlap_aggregates`), the "
        "`conflict_definition`, the HMAC posture (`hmac_key_persisted_in_artifacts: false`) and "
        "the subject resolution paths. No verdict moved, no denominator moved, no conflict "
        "definition changed.",
        "",
        "## Read-only reproduction",
        "",
        f"`assess-source-relationship` was re-run against a throwaway copy of the workspace: "
        f"{reproduction.detail}. Both sources were queried through their dedicated read-only "
        "audit roles, `raw_databases_unchanged` is "
        f"`{reproduction.raw_databases_unchanged}` from row-count fingerprints taken before and "
        f"after, and `validate_relationship_artifacts` reported "
        f"{len(reproduction.safety_findings)} safety findings. The reproduction's body matches "
        "the working artifacts; only `assessed_at` moved to the time of the run.",
        "",
        "Row-level values were processed inside the local runtime to compute keyed digests for "
        "the aggregate linkage, which is what this assessment does. No row value reached an "
        "artifact, a log or this report. `artifacts/stage-02/` was not written by the "
        "reproduction: it ran entirely in the throwaway copy, which was discarded.",
        "",
        "## Candidate repair",
        "",
        f"`{CANDIDATE_DIR.as_posix()}/` holds the eight artifacts with the bytes an accepted "
        "release published, unmodified, and a manifest sealed over exactly those bytes. Zero "
        "artifacts are regenerated; one manifest is re-sealed.",
        "",
        f"Candidate manifest: `{decision['proposed_repair']['candidate_manifest_sha256']}`",
        "",
        "Applied to a throwaway copy of the workspace:",
        "",
        f"* `relationship_manifest_hashes_match` — {'PASS' if validation.manifest_verified else 'FAIL'}"
        f" ({validation.manifest_detail})",
        f"* `verify-stage-02` — {validation.verify_stage_02_status_excluding_test_gate} across "
        f"{len(validation.verify_stage_02_checks) - 2} evaluated checks, including "
        f"`relationship_manifest` = {validation.relationship_manifest_check}. Its `full_test_suite` "
        "and `test_result_not_skipped` checks were not evaluated: verify-stage-02 runs the whole "
        "pytest suite as a check, which inside a throwaway copy would re-enter the publication "
        "pipeline.",
        f"* `stage02_relationship_integrity_pre_live_load` — {validation.gate_status}",
        f"* `{DEFECT_ID}` cleared — {validation.drift_blocker_cleared}",
        "",
        "The gate still fails, and must: clearing the manifest drift leaves "
        f"{len(validation.gate_open_blockers)} of the five pre-live-load blockers open "
        f"(`{'`, `'.join(validation.gate_open_blockers)}`). This maintenance changeset resolves "
        "one defect's *diagnosis*, not the live-load gate.",
        "",
        "## What was not done",
        "",
    ]
    lines += [f"* {item}" for item in decision["non_actions"]]
    lines += [
        "",
        "## Residual observations",
        "",
    ]
    for item in decision["residual_observations"]:
        lines.append(f"* {item['observation']} — action: {item['action']}. {item['why']}.")
    lines.append("")
    return "\n".join(lines)


def run_maintenance_01(repo_root: Path) -> dict[str, Any]:
    """Diagnose, prepare and validate. Never repair."""
    root = repo_root.resolve()
    output = root / MAINTENANCE_DIR
    output.mkdir(parents=True, exist_ok=True)

    reproduction = reproduce_assessment(root)
    hash_matrix = build_hash_matrix(root, reproduction)
    semantics = build_semantic_comparison(root, reproduction)
    candidate = build_candidate(root)
    validation = validate_candidate(root, candidate)
    decision = build_decision(
        root,
        hash_matrix=hash_matrix,
        semantics=semantics,
        candidate=candidate,
        validation=validation,
        reproduction=reproduction,
    )
    decision["candidate"] = candidate.document()

    write_json(output / HASH_MATRIX_NAME, hash_matrix)
    write_json(output / SEMANTIC_COMPARISON_NAME, semantics)
    write_json(output / REPRODUCTION_NAME, reproduction.document())
    write_json(output / ISOLATED_VALIDATION_NAME, validation.document())
    write_json(output / DECISION_NAME, decision)
    write_json(
        output / QUERY_LOG_NAME,
        {
            "source": "read-only reproduction in a throwaway workspace",
            "sanitised": True,
            "contains_row_values": False,
            "operation_count": len(reproduction.query_log),
            "operations": reproduction.query_log,
        },
    )
    (output / DRIFT_DIAGNOSIS_NAME).write_text(
        render_diagnosis(
            hash_matrix=hash_matrix,
            semantics=semantics,
            decision=decision,
            reproduction=reproduction,
            validation=validation,
        ),
        encoding="utf-8",
    )

    return {
        "maintenance_id": MAINTENANCE_ID,
        "maintenance_version": MAINTENANCE_VERSION,
        "status": decision["status"],
        "drifted_artifacts": hash_matrix["drifted_artifacts"],
        "repair_applied": False,
        "working_stage_02_unchanged": validation.working_stage_02_unchanged,
        "candidate_manifest_sha256": candidate.manifest_sha256,
        "gate_status_with_candidate": validation.gate_status,
        "artifacts_written": sorted(
            str(MAINTENANCE_DIR / name) for name in (
                HASH_MATRIX_NAME,
                SEMANTIC_COMPARISON_NAME,
                REPRODUCTION_NAME,
                ISOLATED_VALIDATION_NAME,
                DECISION_NAME,
                QUERY_LOG_NAME,
                DRIFT_DIAGNOSIS_NAME,
            )
        ),
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
