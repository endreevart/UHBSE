"""Build the Stage 03 implementation planning external review bundle."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from human_simulator.stage03.implementation_constants import (
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
    IMPLEMENTATION_PLAN_REPORT_NAME,
    IMPLEMENTATION_PLAN_VERIFICATION_NAME,
)
from human_simulator.stage03.implementation_publication import validate_publication_snapshot
from human_simulator.stage03.implementation_publication_evidence import ReviewBundleEvidence
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.release_verification import (
    CLEAN_BUNDLE_SUITE_TARGETS,
    RELEASE_VERIFICATION_NAME,
    clean_bundle_suite_command,
    full_repository_suite_command,
    integration_suite_command,
    shell_quote,
)
from human_simulator.stage03.review_bundle_validation import parse_review_index, validate_review_bundle_zip
from human_simulator.stage03.review_dependencies import (
    get_implementation_review_bundle_paths,
    should_skip_member,
)

COPY_PATHS = get_implementation_review_bundle_paths()

BUNDLE_ZIP_NAME = "stage-03-implementation-plan-v0.3.5-review.zip"
BUNDLE_SHA256_SIDECAR_NAME = f"{BUNDLE_ZIP_NAME}.sha256"
STAGING_DIR_NAME = ".review-bundle-staging-impl-v035"
BUNDLE_VERSION = "0.3.5"

BUNDLE_PYTEST_TARGETS: tuple[str, ...] = CLEAN_BUNDLE_SUITE_TARGETS


def should_skip(path: Path) -> bool:
    return should_skip_member(path)


def build_implementation_plan_review_bundle(repo_root: Path, *, generated_at: str) -> ReviewBundleEvidence:
    root = repo_root.resolve()
    impl_dir = root / "artifacts" / "stage-03-implementation"
    ok, detail = validate_publication_snapshot(impl_dir)
    if not ok:
        raise RuntimeError(f"Refusing to publish review bundle: publication snapshot invalid ({detail})")

    staging = root / STAGING_DIR_NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    for rel in get_implementation_review_bundle_paths():
        src = root / rel
        dst = staging / rel
        if not src.exists():
            raise FileNotFoundError(f"Missing required path for review bundle: {rel}")
        if src.is_dir():
            _copy_tree_filtered(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    (staging / "REPRODUCE.md").write_text(
        _reproduce_content(impl_dir, generated_at=generated_at), encoding="utf-8"
    )

    indexed_files = [
        path.relative_to(staging)
        for path in sorted(staging.rglob("*"))
        if path.is_file() and not should_skip(path)
    ]
    index_lines = [
        f"# Stage 03 Implementation Plan v{BUNDLE_VERSION} — Review Index",
        "",
        f"Generated: {generated_at}",
        "",
        "Note: This index intentionally excludes its own SHA-256 entry.",
        "",
        "| SHA-256 | Path |",
        "|---------|------|",
    ]
    for rel in indexed_files:
        index_lines.append(f"| `{sha256_file(staging / rel)}` | `{rel.as_posix()}` |")
    (staging / "REVIEW_INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    staging_impl = staging / "artifacts" / "stage-03-implementation"
    ok, detail = validate_publication_snapshot(staging_impl)
    if not ok:
        shutil.rmtree(staging)
        raise RuntimeError(f"Staged publication snapshot invalid: {detail}")

    out_zip = root / "artifacts" / "external-review" / BUNDLE_ZIP_NAME
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = out_zip.with_suffix(".tmp.zip")
    if temp_zip.exists():
        temp_zip.unlink()
    with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file() and not should_skip(path):
                archive.write(path, path.relative_to(staging).as_posix())

    ok, detail = validate_review_bundle_zip(temp_zip)
    if not ok:
        temp_zip.unlink(missing_ok=True)
        shutil.rmtree(staging)
        raise RuntimeError(f"Review bundle ZIP validation failed: {detail}")

    with tempfile.TemporaryDirectory(prefix="impl-plan-bundle-check-") as tmp:
        extract_root = Path(tmp)
        with zipfile.ZipFile(temp_zip) as archive:
            archive.extractall(extract_root)
        ok, detail = validate_publication_snapshot(extract_root / "artifacts" / "stage-03-implementation")
        if not ok:
            temp_zip.unlink(missing_ok=True)
            shutil.rmtree(staging)
            raise RuntimeError(f"Extracted bundle publication snapshot invalid: {detail}")
        verification = json.loads(
            (extract_root / "artifacts" / "stage-03-implementation" / IMPLEMENTATION_PLAN_VERIFICATION_NAME).read_text(
                encoding="utf-8"
            )
        )
        report_bytes = (
            extract_root / "artifacts" / "stage-03-implementation" / IMPLEMENTATION_PLAN_REPORT_NAME
        ).read_bytes()
        if verification.get("report_sha256") != hashlib.sha256(report_bytes).hexdigest():
            temp_zip.unlink(missing_ok=True)
            shutil.rmtree(staging)
            raise RuntimeError("Extracted bundle report SHA does not match verification")

    if out_zip.exists():
        out_zip.unlink()
    temp_zip.rename(out_zip)

    # Final, immutable inspection of the published archive: index match, no nested archive,
    # then the SHA-256 that is written to the sidecar. Nothing is rebuilt after this point.
    ok, detail = validate_review_bundle_zip(out_zip)
    if not ok:
        shutil.rmtree(staging)
        raise RuntimeError(f"Published review bundle failed index validation: {detail}")
    with zipfile.ZipFile(out_zip) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        indexed = parse_review_index(archive.read("REVIEW_INDEX.md").decode("utf-8"))
    nested = [name for name in members if name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz"))]
    external = [name for name in members if name.startswith("artifacts/external-review/")]
    if nested or external:
        shutil.rmtree(staging)
        raise RuntimeError(f"Published review bundle contains forbidden members: {nested + external}")

    zip_sha256 = sha256_file(out_zip)
    sidecar = out_zip.with_name(BUNDLE_SHA256_SIDECAR_NAME)
    sidecar.write_text(f"{zip_sha256}  {BUNDLE_ZIP_NAME}\n", encoding="utf-8")

    shutil.rmtree(staging)
    return ReviewBundleEvidence(
        zip_path=out_zip,
        zip_sha256=zip_sha256,
        member_count=len(members),
        indexed_member_count=len(indexed),
        generated_at=generated_at,
    )


def _suite_line(document: dict[str, object] | None, name: str) -> str:
    if not document:
        return "not recorded"
    for suite in document.get("suites", []):  # type: ignore[union-attr]
        if suite.get("name") == name:
            return (
                f"exit code {suite.get('exit_code')}, collected {suite.get('collected')}, "
                f"selected {suite.get('selected')}, deselected {suite.get('deselected')}, "
                f"passed {suite.get('passed')}, failed {suite.get('failed')}, "
                f"skipped {suite.get('skipped')} ({suite.get('duration_seconds')}s)"
            )
    return "not recorded"


def _suite_command(document: dict[str, object] | None, name: str, fallback: list[str]) -> str:
    if document:
        for suite in document.get("suites", []):  # type: ignore[union-attr]
            if suite.get("name") == name:
                return str(suite.get("command"))
    return shell_quote(fallback)


def _reproduce_content(impl_dir: Path, *, generated_at: str) -> str:
    release_path = impl_dir / RELEASE_VERIFICATION_NAME
    document: dict[str, object] | None = None
    if release_path.exists():
        document = json.loads(release_path.read_text(encoding="utf-8"))

    clean_cmd = _suite_command(document, "clean_review_bundle_suite", clean_bundle_suite_command())
    full_cmd = _suite_command(document, "full_repository_suite", full_repository_suite_command())
    integration_cmd = _suite_command(document, "integration_suite", integration_suite_command())

    return f"""# Stage 03 Implementation Plan v{BUNDLE_VERSION} — Reproduce Verification

Generated: {generated_at}

All commands below are literal and complete. Copy them verbatim; every `-k` and `-m`
expression and every test file is included.

## Setup

```bash
uv sync --frozen --extra dev
```

## Gates (reproducible from this archive)

```bash
uv run python -c "
from pathlib import Path
from human_simulator.stage03.verify_stage_03_design import verify_stage_03_design
from human_simulator.stage03.verify_implementation_plan import verify_implementation_plan

design = verify_stage_03_design(Path('.'), run_pytest=False, publish_artifacts=False)
plan = verify_implementation_plan(Path('.'), run_pytest=False, publish_artifacts=False)
print('design', design['status'], design['checks_passed'], design['checks_total'])
print('plan', plan['status'], plan['checks_passed'], plan['checks_total'])
assert design['status'] == 'PASS'
assert plan['status'] == 'PASS'
"
```

Equivalent read-only CLI form. `--no-publish` writes nothing to Stage 01/02 or Stage 03
artifacts, which is the only supported reviewer path (this archive intentionally omits
`artifacts/external-review/`, so publishing from an extraction is not possible):

```bash
uv run audit --root . stage-03-check --no-publish
uv run audit --root . stage-03-implementation-plan-check --no-publish
```

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

This suite is **not** reproducible from this archive alone, because the archive intentionally
omits repository paths outside the Stage 03 scope. Its evidence is stored in
`artifacts/stage-03-implementation/{RELEASE_VERIFICATION_NAME}`, not in
`implementation-plan-verification.json`.

## Integration suite (requires live PostgreSQL sources)

```bash
{integration_cmd}
```

Recorded result: {_suite_line(document, "integration_suite")}

Integration tests skip with an explicit list of missing prerequisite names when the live
environment is not configured. They never print DSNs, passwords or environment values.

## Release evidence

`artifacts/stage-03-implementation/{RELEASE_VERIFICATION_NAME}` records every gate and suite
with its literal command, counts, exit code, duration and the prior-stage before/after hashes.
`overall_release_status` is `PASS` only when all mandatory entries report exit code 0 and zero
failures.

## Archive integrity

```bash
shasum -a 256 -c {BUNDLE_SHA256_SIDECAR_NAME}
```
"""


def _copy_tree_filtered(src: Path, dst: Path) -> None:
    if should_skip(src):
        return
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            _copy_tree_filtered(child, dst / child.name)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
