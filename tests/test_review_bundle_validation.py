"""Regression tests for review bundle ZIP/index integrity."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from human_simulator.stage03.review_bundle_validation import parse_review_index, validate_review_bundle_zip

REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, payload in sorted(entries.items()):
            archive.writestr(path, payload)
    return buffer.getvalue()


def test_parse_review_index_reads_sha_and_path() -> None:
    text = "# index\n\n| SHA-256 | Path |\n|---------|------|\n| `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` | `foo.txt` |\n"
    entries = parse_review_index(text)
    assert len(entries) == 1
    assert entries[0].path == "foo.txt"
    assert entries[0].sha256 == "a" * 64


def test_validate_review_bundle_rejects_nested_zip() -> None:
    nested = _build_zip({"nested.zip": b"nested"})
    ok, detail = validate_review_bundle_zip_from_bytes(nested)
    assert not ok
    assert "nested zip" in detail


def test_validate_review_bundle_rejects_external_review_members() -> None:
    payload = _build_zip(
        {
            "REVIEW_INDEX.md": b"# index\n",
            "artifacts/external-review/other.zip": b"x",
        }
    )
    ok, detail = validate_review_bundle_zip_from_bytes(payload)
    assert not ok
    assert "external-review" in detail


def test_validate_review_bundle_exact_index_match() -> None:
    file_a = b"hello"
    file_b = b"world"
    index = "\n".join(
        [
            "# index",
            "",
            "| SHA-256 | Path |",
            "|---------|------|",
            f"| `{_sha256_bytes(file_a)}` | `a.txt` |",
            f"| `{_sha256_bytes(file_b)}` | `b.txt` |",
            "",
        ]
    )
    payload = _build_zip(
        {
            "a.txt": file_a,
            "b.txt": file_b,
            "REVIEW_INDEX.md": index.encode("utf-8"),
        }
    )
    ok, detail = validate_review_bundle_zip_from_bytes(payload)
    assert ok, detail


def test_validate_review_bundle_fails_on_missing_member() -> None:
    file_a = b"hello"
    index = "\n".join(
        [
            "# index",
            "",
            "| SHA-256 | Path |",
            "|---------|------|",
            f"| `{_sha256_bytes(file_a)}` | `a.txt` |",
            f"| `{_sha256_bytes(b'missing')}` | `missing.txt` |",
            "",
        ]
    )
    payload = _build_zip({"a.txt": file_a, "REVIEW_INDEX.md": index.encode("utf-8")})
    ok, detail = validate_review_bundle_zip_from_bytes(payload)
    assert not ok
    assert "missing" in detail


def test_validate_review_bundle_fails_on_extra_member() -> None:
    file_a = b"hello"
    index = "\n".join(
        [
            "# index",
            "",
            "| SHA-256 | Path |",
            "|---------|------|",
            f"| `{_sha256_bytes(file_a)}` | `a.txt` |",
            "",
        ]
    )
    payload = _build_zip({"a.txt": file_a, "extra.txt": b"x", "REVIEW_INDEX.md": index.encode("utf-8")})
    ok, detail = validate_review_bundle_zip_from_bytes(payload)
    assert not ok
    assert "extra" in detail


def test_validate_review_bundle_fails_on_sha_mismatch() -> None:
    file_a = b"hello"
    index = "\n".join(
        [
            "# index",
            "",
            "| SHA-256 | Path |",
            "|---------|------|",
            f"| `{_sha256_bytes(b'wrong')}` | `a.txt` |",
            "",
        ]
    )
    payload = _build_zip({"a.txt": file_a, "REVIEW_INDEX.md": index.encode("utf-8")})
    ok, detail = validate_review_bundle_zip_from_bytes(payload)
    assert not ok
    assert "sha256 mismatch" in detail


def test_repo_review_bundle_if_present_matches_index() -> None:
    from human_simulator.stage03.implementation_review_bundle import BUNDLE_ZIP_NAME

    bundle = REPO_ROOT / "artifacts/external-review" / BUNDLE_ZIP_NAME
    if not bundle.exists():
        pytest.skip("review bundle missing")
    ok, detail = validate_review_bundle_zip(bundle)
    assert ok, detail
    with zipfile.ZipFile(bundle) as archive:
        members = {name for name in archive.namelist() if not name.endswith("/")}
        indexed = parse_review_index(archive.read("REVIEW_INDEX.md").decode("utf-8"))
    assert not any(name.lower().endswith(".zip") for name in members)
    assert not any(name.startswith("artifacts/external-review/") for name in members)
    assert len(indexed) + 1 == len(members)


def validate_review_bundle_zip_from_bytes(payload: bytes) -> tuple[bool, str]:
    path = REPO_ROOT / ".pytest-review-bundle.zip"
    path.write_bytes(payload)
    try:
        return validate_review_bundle_zip(path)
    finally:
        path.unlink(missing_ok=True)
