"""Build the Stage 03 external review bundle."""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

from human_simulator.stage03.review_dependencies import (
    get_stage03_design_review_dependencies,
    should_skip_member,
)

EXCLUDE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".venv", ".uv", ".mypy_cache", ".ruff_cache"}
EXCLUDE_FILE_NAMES = {".DS_Store"}
BUNDLE_ZIP_NAME = "stage-03-design-v0.7.4-review.zip"
STAGING_DIR_NAME = ".review-bundle-staging-v074"
BUNDLE_VERSION = "0.7.4"


def should_skip(path: Path) -> bool:
    return should_skip_member(path)


def copy_tree_filtered(src: Path, dst: Path) -> None:
    if should_skip(src):
        return
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            copy_tree_filtered(child, dst / child.name)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_stage03_review_bundle(
    repo_root: Path,
    *,
    generated_at: str,
) -> str:
    """Build review zip using the exact REVIEW_INDEX ``Generated`` timestamp."""
    root = repo_root.resolve()
    if not generated_at or not generated_at.strip():
        raise ValueError("generated_at is required and must be the pre-planned ISO-8601 timestamp")

    staging = root / STAGING_DIR_NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    for rel in get_stage03_design_review_dependencies():
        src = root / rel
        dst = staging / rel
        if not src.exists():
            raise FileNotFoundError(f"Missing required path for review bundle: {rel}")
        if src.is_dir():
            copy_tree_filtered(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    reproduce = f"""# Stage 03 Design v{BUNDLE_VERSION} — Reproduce Verification

Generated: {generated_at}

## Setup

```bash
uv sync --frozen --extra dev
```

## Verify (clean extraction — before re-publish)

```bash
uv run python -c "
from pathlib import Path
from human_simulator.stage03.verify_stage_03_design import verify_stage_03_design
result = verify_stage_03_design(Path('.'), run_pytest=False, publish_artifacts=False)
print(result['status'], result['checks_passed'], result['checks_total'])
assert result['status'] == 'PASS'
"
uv run pytest tests/test_verify_stage_03_design.py -q
uv run audit --root . stage-03-check
uv run pytest -q
```
"""
    (staging / "REPRODUCE.md").write_text(reproduce, encoding="utf-8")

    files = [
        path.relative_to(staging)
        for path in sorted(staging.rglob("*"))
        if path.is_file() and not should_skip(path)
    ]

    index_lines = [
        f"# Stage 03 Design v{BUNDLE_VERSION} — Review Index",
        "",
        f"Generated: {generated_at}",
        "",
        "Note: This index intentionally excludes its own SHA-256 entry to avoid a cyclic self-hash.",
        "",
        "| SHA-256 | Path |",
        "|---------|------|",
    ]
    for rel in files:
        index_lines.append(f"| `{sha256_file(staging / rel)}` | `{rel.as_posix()}` |")
    (staging / "REVIEW_INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    out_zip = root / "artifacts" / "external-review" / BUNDLE_ZIP_NAME
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file() and not should_skip(path):
                archive.write(path, path.relative_to(staging).as_posix())

    shutil.rmtree(staging)
    return generated_at
