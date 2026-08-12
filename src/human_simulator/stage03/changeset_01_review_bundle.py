"""Build the external review bundle for Stage 03 Implementation Changeset 01.

The archive is schema-only evidence. It carries migrations, source code, tests, gate
results and the frozen design/plan inputs, and it structurally excludes secrets, DSNs,
database dumps, raw rows, nested archives and `artifacts/external-review/`.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from human_simulator.stage03.changeset_01_constants import (
    ARTIFACT_CONFLICTS_NAME,
    CANONICAL_ENV_FILE,
    CHANGESET_CONTENT_ARTIFACTS,
    CHANGESET_DIR,
    CHANGESET_MANIFEST_NAME,
    CHANGESET_REPORT_NAME,
    CHANGESET_SUBTITLE,
    CHANGESET_VERIFICATION_NAME,
    CHANGESET_VERSION,
    DEFINITION_BASELINE_NAME,
    DESIGN_ARCHIVE_FINDING_NAME,
    DESIGN_DIR,
    GATE_RESULT_NAME,
    LIVE_LOAD_CONTRACT_SCHEMA_NAME,
    CONTRACT_AUTHORITY_POLICY_NAME,
    MIGRATION_RESULT_NAME,
    PERMISSION_REPORT_NAME,
    PRE_LIVE_LOAD_BLOCKERS_NAME,
    PRIOR_STAGE_INTEGRITY_NAME,
    RELEASE_VERIFICATION_NAME,
)
from human_simulator.stage03.frozen_evidence import (
    DESIGN_EVIDENCE_SOURCE_ARCHIVES,
    DESIGN_REPORT_NAME,
    DESIGN_VERIFICATION_NAME,
    FROZEN_DESIGN_EVIDENCE_SHA256,
)
from human_simulator.stage03.implementation_publication_evidence import ReviewBundleEvidence
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.release_verification import (
    changeset_01_clean_bundle_suite_command,
    changeset_01_gate_suite_command,
    changeset_01_migration_suite_command,
    full_repository_suite_command,
    shell_quote,
)
from human_simulator.stage03.review_bundle_validation import (
    parse_review_index,
    validate_review_bundle_zip,
)
from human_simulator.stage03.review_dependencies import (
    get_changeset_01_review_bundle_paths,
    should_skip_member,
)

BUNDLE_ZIP_NAME = f"stage-03-implementation-changeset-01-v{CHANGESET_VERSION}-review.zip"
BUNDLE_SHA256_SIDECAR_NAME = f"{BUNDLE_ZIP_NAME}.sha256"
STAGING_DIR_NAME = ".review-bundle-staging-changeset-01"

# Members that must never reach an external reviewer.
FORBIDDEN_MEMBER_SUFFIXES: tuple[str, ...] = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".dump",
    ".sql.gz",
    ".pgdump",
    ".env",
)
FORBIDDEN_MEMBER_NAMES: frozenset[str] = frozenset({CANONICAL_ENV_FILE, "db.env", ".env"})

TEXT_SUFFIXES: frozenset[str] = frozenset(
    {".md", ".yaml", ".yml", ".json", ".py", ".sql", ".toml", ".mdc", ".sha256", ".template", ".txt"}
)
DSN_PATTERN = re.compile(r"postgres(?:ql)?://(?P<credentials>[^\s\"'/]*:[^\s\"'@]+)@")
# Format templates and redaction markers are not credentials; anything else is treated as one.
INTERPOLATION_MARKERS: tuple[str, ...] = ("{", "}", "$", "%", "***", "<", ">", "[", "]")


class ChangesetBundleError(RuntimeError):
    """Raised when the bundle cannot be published safely."""


def validate_changeset_snapshot(changeset_dir: Path) -> tuple[bool, str]:
    """Verify the published changeset directory is internally consistent."""
    report = changeset_dir / CHANGESET_REPORT_NAME
    verification = changeset_dir / CHANGESET_VERIFICATION_NAME
    manifest = changeset_dir / CHANGESET_MANIFEST_NAME
    for path in (report, verification, manifest):
        if not path.exists():
            return False, f"missing {path.name}"

    document = json.loads(verification.read_text(encoding="utf-8"))
    if document.get("overall_status") != "PASS":
        return False, f"verification overall_status={document.get('overall_status')}"
    if document.get("report_status") != "DRAFT":
        return False, f"report_status={document.get('report_status')}"

    report_bytes = report.read_bytes()
    if document.get("report_sha256") != hashlib.sha256(report_bytes).hexdigest():
        return False, "report_sha256 does not match the published report bytes"
    if "Report status: DRAFT" not in report_bytes.decode("utf-8"):
        return False, "report does not declare DRAFT status"

    recorded = _manifest_entries(manifest)
    expected = {name: sha256_file(changeset_dir / name) for name in CHANGESET_CONTENT_ARTIFACTS}
    if recorded != expected:
        return False, "changeset manifest does not match content artifacts"
    if document.get("content_manifest_sha256") != sha256_file(manifest):
        return False, "verification does not record the published manifest hash"

    gate = json.loads((changeset_dir / GATE_RESULT_NAME).read_text(encoding="utf-8"))
    if gate.get("status") != "FAIL":
        return False, "stage02 pre-live-load gate result must remain FAIL until repaired"
    return True, "changeset snapshot consistent"


def _manifest_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        digest, _, name = stripped.partition("  ")
        entries[name.strip()] = digest
    return entries


def build_changeset_01_review_bundle(repo_root: Path, *, generated_at: str) -> ReviewBundleEvidence:
    root = repo_root.resolve()
    changeset_dir = root / CHANGESET_DIR

    ok, detail = validate_changeset_snapshot(changeset_dir)
    if not ok:
        raise ChangesetBundleError(f"Refusing to publish review bundle: {detail}")

    staging = root / STAGING_DIR_NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    try:
        for rel in get_changeset_01_review_bundle_paths():
            src = root / rel
            if not src.exists():
                raise FileNotFoundError(f"Missing required path for review bundle: {rel}")
            dst = staging / rel
            if src.is_dir():
                _copy_tree_filtered(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        _assert_no_forbidden_files(staging)
        _assert_frozen_design_evidence(staging)

        (staging / "REPRODUCE.md").write_text(
            _reproduce_content(changeset_dir, generated_at=generated_at), encoding="utf-8"
        )
        _write_review_index(staging, generated_at=generated_at)

        ok, detail = validate_changeset_snapshot(staging / CHANGESET_DIR)
        if not ok:
            raise ChangesetBundleError(f"Staged changeset snapshot invalid: {detail}")

        out_zip = root / "artifacts" / "external-review" / BUNDLE_ZIP_NAME
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        temp_zip = out_zip.with_suffix(".tmp.zip")
        temp_zip.unlink(missing_ok=True)
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file() and not should_skip_member(path):
                    archive.write(path, path.relative_to(staging).as_posix())

        ok, detail = validate_review_bundle_zip(temp_zip)
        if not ok:
            temp_zip.unlink(missing_ok=True)
            raise ChangesetBundleError(f"Review bundle ZIP validation failed: {detail}")

        with tempfile.TemporaryDirectory(prefix="changeset-01-bundle-check-") as tmp:
            extract_root = Path(tmp)
            with zipfile.ZipFile(temp_zip) as archive:
                archive.extractall(extract_root)
            _assert_no_forbidden_files(extract_root)
            ok, detail = validate_changeset_snapshot(extract_root / CHANGESET_DIR)
            if not ok:
                temp_zip.unlink(missing_ok=True)
                raise ChangesetBundleError(f"Extracted changeset snapshot invalid: {detail}")

        out_zip.unlink(missing_ok=True)
        temp_zip.rename(out_zip)

        # Final, immutable inspection. Nothing is rebuilt after this point.
        ok, detail = validate_review_bundle_zip(out_zip)
        if not ok:
            raise ChangesetBundleError(f"Published review bundle failed index validation: {detail}")
        with zipfile.ZipFile(out_zip) as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
            indexed = parse_review_index(archive.read("REVIEW_INDEX.md").decode("utf-8"))
        forbidden = [name for name in members if _is_forbidden_member(name)]
        external = [name for name in members if name.startswith("artifacts/external-review/")]
        if forbidden or external:
            raise ChangesetBundleError(
                f"Published review bundle contains forbidden members: {forbidden + external}"
            )

        zip_sha256 = sha256_file(out_zip)
        (out_zip.with_name(BUNDLE_SHA256_SIDECAR_NAME)).write_text(
            f"{zip_sha256}  {BUNDLE_ZIP_NAME}\n", encoding="utf-8"
        )
        return ReviewBundleEvidence(
            zip_path=out_zip,
            zip_sha256=zip_sha256,
            member_count=len(members),
            indexed_member_count=len(indexed),
            generated_at=generated_at,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _write_review_index(staging: Path, *, generated_at: str) -> None:
    indexed = [
        path.relative_to(staging)
        for path in sorted(staging.rglob("*"))
        if path.is_file() and not should_skip_member(path)
    ]
    lines = [
        f"# Stage 03 Implementation Changeset 01 v{CHANGESET_VERSION} — Review Index",
        "",
        f"Canonical Storage Foundation — {CHANGESET_SUBTITLE}. Schema-only evidence: this archive",
        "contains no clinical rows, no database dump, no `.env` file, no literal",
        "credential-bearing DSN or secret, and no key material. It also contains no transient",
        "publication-lock artifact. `uv.lock` is a dependency lockfile, is unrelated to",
        "publication locking, and is included deliberately for reproducible installs.",
        "",
        f"Generated: {generated_at}",
        "",
        "Note: This index intentionally excludes its own SHA-256 entry.",
        "",
        "| SHA-256 | Path |",
        "|---------|------|",
    ]
    lines.extend(f"| `{sha256_file(staging / rel)}` | `{rel.as_posix()}` |" for rel in indexed)
    (staging / "REVIEW_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assert_frozen_design_evidence(root: Path) -> None:
    """Refuse to package Design evidence that was regenerated instead of carried over.

    v0.2 shipped a bundle whose design report and verification had been rewritten by a test
    republish. Both files are pinned by hash, so a regenerated copy cannot reach a reviewer
    again: the build stops instead of quietly including it.
    """
    wrong: list[str] = []
    for name, accepted in sorted(FROZEN_DESIGN_EVIDENCE_SHA256.items()):
        member = root / DESIGN_DIR / name
        if not member.is_file():
            wrong.append(f"{name} missing")
            continue
        actual = sha256_file(member)
        if actual != accepted:
            wrong.append(f"{name} is {actual}, accepted {accepted}")
    if wrong:
        raise ChangesetBundleError(
            "Refusing to build a review bundle with non-accepted Design evidence: "
            + "; ".join(wrong)
            + ". Recover the accepted bytes from an accepted release "
            f"({', '.join(DESIGN_EVIDENCE_SOURCE_ARCHIVES)}); never regenerate them."
        )


def _is_forbidden_member(name: str) -> bool:
    lowered = name.lower()
    if Path(name).name in FORBIDDEN_MEMBER_NAMES:
        return True
    return lowered.endswith(FORBIDDEN_MEMBER_SUFFIXES)


def _has_concrete_dsn(content: str) -> bool:
    """True when a DSN carries literal credentials rather than a format template."""
    for match in DSN_PATTERN.finditer(content):
        credentials = match.group("credentials")
        if not any(marker in credentials for marker in INTERPOLATION_MARKERS):
            return True
    return False


def _assert_no_forbidden_files(root: Path) -> None:
    offenders: list[str] = []
    leaked_dsn: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _is_forbidden_member(rel):
            offenders.append(rel)
            continue
        if path.suffix in TEXT_SUFFIXES and _has_concrete_dsn(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            leaked_dsn.append(rel)
    if offenders or leaked_dsn:
        raise ChangesetBundleError(
            f"forbidden members={offenders[:6]} credential_bearing={leaked_dsn[:6]}"
        )


def _copy_tree_filtered(src: Path, dst: Path) -> None:
    if should_skip_member(src):
        return
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            _copy_tree_filtered(child, dst / child.name)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _suite_entry(document: dict[str, object] | None, name: str) -> dict[str, object] | None:
    if not document:
        return None
    for suite in document.get("suites", []):  # type: ignore[union-attr]
        if suite.get("name") == name:  # type: ignore[union-attr]
            return suite  # type: ignore[return-value]
    return None


def _suite_line(document: dict[str, object] | None, name: str) -> str:
    suite = _suite_entry(document, name)
    if suite is None:
        return "not recorded"
    return (
        f"exit code {suite.get('exit_code')}, collected {suite.get('collected')}, "
        f"selected {suite.get('selected')}, deselected {suite.get('deselected')}, "
        f"passed {suite.get('passed')}, failed {suite.get('failed')}, "
        f"skipped {suite.get('skipped')} ({suite.get('duration_seconds')}s)"
    )


def _suite_command(document: dict[str, object] | None, name: str, fallback: list[str]) -> str:
    suite = _suite_entry(document, name)
    return str(suite.get("command")) if suite else shell_quote(fallback)


def _reproduce_content(changeset_dir: Path, *, generated_at: str) -> str:
    release_path = changeset_dir / RELEASE_VERIFICATION_NAME
    document: dict[str, object] | None = None
    if release_path.exists():
        document = json.loads(release_path.read_text(encoding="utf-8"))

    gate_cmd = _suite_command(document, "changeset_01_gate_suite", changeset_01_gate_suite_command())
    clean_cmd = _suite_command(
        document, "clean_review_bundle_suite", changeset_01_clean_bundle_suite_command()
    )
    full_cmd = _suite_command(document, "full_repository_suite", full_repository_suite_command())
    migration_cmd = _suite_command(
        document, "integration_migration_suite", changeset_01_migration_suite_command()
    )
    changeset_rel = CHANGESET_DIR.as_posix()

    return f"""# Stage 03 Implementation Changeset 01 v{CHANGESET_VERSION} — Reproduce Verification

Generated: {generated_at}

Canonical Storage Foundation. Every command below is literal and complete; copy it verbatim,
including each `-m` and `-k` expression and every test path.

## Setup

```bash
uv sync --frozen --extra dev
```

## Gates (reproducible from this archive, no database required)

```bash
uv run audit --root . changeset-01-baseline
uv run audit --root . changeset-01-check --no-publish
uv run audit --root . stage-02-pre-live-load-gate; echo "exit=$?"
```

`changeset-01-baseline` re-hashes the nine controlled Stage 01/02 files, the frozen Design
v0.7.4 content manifest and the accepted Implementation Plan v0.3.5 manifest. It is read-only
and performs no repair.

`stage-02-pre-live-load-gate` is expected to exit non-zero. It reports the open
`stage02_relationship_manifest_drift` defect and blocks every future live extraction, load and
ETL command. It does not block creating the empty canonical database or applying migrations.

Prior gates, unchanged by this changeset:

```bash
uv run audit --root . stage-03-check --no-publish
uv run audit --root . stage-03-implementation-plan-check --no-publish
```

## Changeset 01 gate suite (reproducible from this archive)

```bash
{gate_cmd}
```

Recorded result: {_suite_line(document, "changeset_01_gate_suite")}

## Clean review bundle suite (reproducible from this archive)

```bash
{clean_cmd}
```

Recorded result: {_suite_line(document, "clean_review_bundle_suite")}

## Full repository suite (publisher workspace only)

```bash
{full_cmd}
```

Recorded result: {_suite_line(document, "full_repository_suite")}

This suite is not reproducible from the archive alone, because the archive intentionally omits
repository paths outside Stage 03 scope.

## Integration / migration suite (requires the isolated canonical PostgreSQL 16 service)

```bash
docker compose up -d canonical-db
cp config/canonical-db.env.template canonical-db.env    # then set the local values
set -a && . ./canonical-db.env && set +a
{migration_cmd}
```

Recorded result: {_suite_line(document, "integration_migration_suite")}

The migration suite creates a disposable database, applies every migration, probes each
constraint inside transactions that are always rolled back, then drops the database. It never
reads Source A or Source B, and it asserts the canonical database ends with zero rows in every
table.

To apply the migrations to the isolated development database instead:

```bash
uv run audit --root . canonical-migrate
```

## Evidence in this archive

| Artifact | Contents |
|----------|----------|
| `{changeset_rel}/{CHANGESET_REPORT_NAME}` | Changeset report, status DRAFT |
| `{changeset_rel}/{CHANGESET_VERIFICATION_NAME}` | Every changeset check with its status |
| `{changeset_rel}/{RELEASE_VERIFICATION_NAME}` | All four suites with literal commands and counts |
| `{changeset_rel}/{PRIOR_STAGE_INTEGRITY_NAME}` | Stage 01/02 hashes before and after the suites |
| `{changeset_rel}/{GATE_RESULT_NAME}` | `stage02_relationship_integrity_pre_live_load` result (FAIL) |
| `{changeset_rel}/{MIGRATION_RESULT_NAME}` | Schema-only migration result, zero rows |
| `{changeset_rel}/{PERMISSION_REPORT_NAME}` | Role and grant state |
| `{changeset_rel}/{DEFINITION_BASELINE_NAME}` | Pinned normalized constraint, index, enum, owner and privilege definitions |
| `{changeset_rel}/{PRE_LIVE_LOAD_BLOCKERS_NAME}` | All five open blockers that gate the first live load |
| `{changeset_rel}/{ARTIFACT_CONFLICTS_NAME}` | Conflicts between accepted artifacts; OPEN + BLOCKS_LIVE_LOAD entries become gate checks |
| `{changeset_rel}/{LIVE_LOAD_CONTRACT_SCHEMA_NAME}` | Required shape and meaning of the two contracts that would close the contract blockers |
| `{changeset_rel}/{CONTRACT_AUTHORITY_POLICY_NAME}` | Which release owns each contract, and the exact path it may occupy |
| `{changeset_rel}/{DESIGN_ARCHIVE_FINDING_NAME}` | Design v0.7.4 archive finding, bound to the archive's own SHA-256 |
| `src/human_simulator/stage03/live_load_contracts.py` | Contract authority resolution and semantic field validation |
| `src/human_simulator/stage03/conflict_registry.py` | Fail-closed validator for the conflict registry itself |
| `src/human_simulator/stage03/pre_live_load_blockers.py` | Single blocker registry; conflict blockers are derived, not restated |
| `tests/test_pre_live_load_gate_hardening.py` | Gate hardening regression tests |
| `tests/test_contract_authority.py` | Contract authority, semantic validation and registry-integrity regression tests |
| `migrations/canonical/` | All versioned migrations, 0001-0004, all byte identical to their accepted bytes |
| `artifacts/stage-02/relationship-manifest.sha256` | Gate input, so the Stage 02 failure reproduces here |
| `artifacts/stage-03/{DESIGN_REPORT_NAME}` | Design evidence, bytes of the accepted release |
| `artifacts/stage-03/{DESIGN_VERIFICATION_NAME}` | Design evidence, bytes of the accepted release |
| `tests/test_publication_isolation.py` | Frozen-evidence, isolation and concurrency regression tests |

## What v0.2.3 fixes

v0.2.2 required a complete structured contract before a blocker could close. That was the right
shape of fix and still permitted two kinds of meaningless PASS.

* **Authority.** A contract was accepted from any YAML file under the Stage 03 directories,
  including the changeset's own. A changeset could have written the contract that unblocked the
  changeset.
* **Meaning.** Fields were checked for presence and shape. `classify_algorithm` matched by
  substring, so `not-hmac-sha256` and `hmac-sha256-unkeyed` both read as keyed PRFs, and any
  occurrence of `SET ROLE` satisfied the loader flow, including `SET ROLE postgres`.

`{CONTRACT_AUTHORITY_POLICY_NAME}` now names one authoritative path per contract, each owned by an
accepted release, and the changeset directory is structurally excluded. A contract counts only at
that exact path, listed in the owning release manifest, with the manifest verifying, and with
exactly one definition in scope. Zero definitions keep the blocker OPEN; two fail as ambiguous.
Values are validated for what they say: exact algorithm identifiers, secret-store references
rather than secrets, fail-closed collision handling, `SET ROLE canonical_loader` and no other
role, an allowlist of grants, and a revocation procedure that names a revoking action.

A third weakness was structural. Deriving blocker checks from `{ARTIFACT_CONFLICTS_NAME}` meant
damaging the file removed checks — deleting the registry made two blockers vanish and the gate
reported fewer failures than before. `accepted_artifact_conflict_registry_valid` now validates the
registry as an artifact in its own right, so absent, unparsable, malformed, duplicated,
self-inconsistent or manifest-mismatched each add a failure.

```bash
uv run pytest tests/test_contract_authority.py -q
```

No contract instance was created and no blocker was resolved. All five stay OPEN.

## What v0.2.2 fixes

The v0.2 gate was weaker than the artifacts describing it. Two problems, both silent:

* it consulted a hand-maintained blocker list that omitted the two conflicts already recorded in
  `{ARTIFACT_CONFLICTS_NAME}` as `severity: BLOCKS_LIVE_LOAD` and `status: OPEN`, so the
  executable guard enforced three of five reasons while the documentation claimed all five;
* it decided resolution by searching artifacts for words. Any file containing `hash` proved
  subject-key opacity, and any file mentioning `SET ROLE` proved a loader runtime principal
  existed. `SHA256(account_patient.id)` would have closed the first blocker while remaining
  reversible by exhaustive search over a bounded integer space, and a sentence saying no
  `SET ROLE` path is defined would have closed the second.

Conflicts are now derived, not restated. Any entry that is `OPEN` and `BLOCKS_LIVE_LOAD` becomes
a FAIL check without a line of code naming it, so the two lists cannot drift apart again.
Resolution requires a complete structured contract; `{LIVE_LOAD_CONTRACT_SCHEMA_NAME}` states
exactly which fields, and rejects placeholders, unkeyed digests and prose.

```bash
uv run audit --root . stage-02-pre-live-load-gate
uv run pytest tests/test_pre_live_load_gate_hardening.py -q
```

The gate must report FAIL with all five blockers, hash all 36 frozen inputs before and after
evaluation, and change none of them. It opens no database connection and reads no clinical row.

This changeset writes a schema, not a contract. Writing a contract instance would close a
blocker by self-assertion, so no instance exists and both contract blockers stay OPEN.

## What v0.2.1 fixes

External audit of v0.2 found that its review archive carried Design evidence a test had
regenerated in the working tree, rather than the bytes of the accepted Design v0.7.4 release.
Two full test runs were executing concurrently during publication; both republished Stage 03
evidence, and the interleaving left the regenerated files in place for the builder to package.
The eleven Design content artifacts were correct throughout, because
`design-content-manifest.sha256` covers them. The two *generated* evidence files were covered by
nothing, so no check compared them to an accepted value.

Verify the two files in this archive against the audited hashes:

```bash
shasum -a 256 artifacts/stage-03/stage-03-design-report.md \\
              artifacts/stage-03/stage-03-design-verification.json
```

Expected:

```
{FROZEN_DESIGN_EVIDENCE_SHA256[DESIGN_REPORT_NAME]}  artifacts/stage-03/{DESIGN_REPORT_NAME}
{FROZEN_DESIGN_EVIDENCE_SHA256[DESIGN_VERIFICATION_NAME]}  artifacts/stage-03/{DESIGN_VERIFICATION_NAME}
```

The whole frozen input set — the nine Stage 01/02 files, the eleven Design content artifacts,
the design manifest, these two evidence files, the Plan artifacts, the plan manifest and
migrations 0001-0004 — is pinned by hash and re-checked before and after every mandatory suite:

```bash
uv run audit --root . frozen-evidence-check
```

Four structural changes back that check:

* every publication-capable test runs in a throwaway copy of the workspace, so no test writes
  into `artifacts/stage-03/`, `artifacts/stage-03-implementation/`, the changeset snapshot or
  `artifacts/external-review/`, and none needs backup-and-restore;
* the publication pipeline holds an exclusive inter-process lock, so two publishers cannot
  interleave writes into one snapshot or archive;
* this bundle builder refuses to package Design evidence that does not match the audited
  hashes;
* recovery is a confirmed human action that installs only bytes hashing to the audited values,
  and is unreachable from any gate, suite or publisher.

One finding is left open, and v0.2.2 restates it with hashes rather than adjectives. The exact
archive inspected, its own SHA-256, the SHA-256 of the two Design evidence members inside it and
the source of the audited bytes are recorded in `{changeset_rel}/{DESIGN_ARCHIVE_FINDING_NAME}`.
The finding is a statement about the artifact present in the publisher workspace at the recorded
hash and nothing more: no sidecar was ever published for that archive, so no accepted hash exists
for it, and what it contained at first publication cannot be established. v0.2.2 therefore
asserts no historical corruption. Republishing the Design archive is out of scope here.

## Migration immutability

0001, 0002 and 0003 were accepted with v0.1 and 0004 with v0.2. All four are byte identical in
this archive; every further schema correction must arrive as a new forward-only file.

```bash
shasum -a 256 migrations/canonical/*.sql
```

Expected values are recorded in `src/human_simulator/canonical/constants.py`
(`ACCEPTED_MIGRATION_SHA256`) and re-checked by every migration run.

## Definition-level schema verification

The verifier compares live `pg_get_constraintdef`, `pg_get_indexdef`, enum value order, table
and schema owners, schema privileges, table privileges and default privileges against
`{changeset_rel}/{DEFINITION_BASELINE_NAME}`. To rebuild that baseline from scratch on a
throwaway database created and dropped by the command:

```bash
uv run audit --root . canonical-capture-baseline --no-publish
```

The captured `definitions_sha256` must equal the committed one. The command refuses to run if
any published migration differs from its accepted bytes.

## Archive integrity

```bash
shasum -a 256 -c {BUNDLE_SHA256_SIDECAR_NAME}
```

## Clean-extraction attestation

The publisher extracted this exact archive into an empty directory and re-ran the gates and
the reproducible suites from the extraction. The results are recorded beside the archive in
`{BUNDLE_ZIP_NAME.removesuffix(".zip")}.attestation.json`. The Stage 02 gate must fail there for
the same reason as in the publisher workspace: `relationship_manifest_hashes_match`. The
attestation also records the SHA-256 of both Design evidence files as read from inside the
extraction, so a reviewer can confirm the v0.2 defect did not recur.
"""
