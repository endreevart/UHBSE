"""Gitignored media factory locations."""

from __future__ import annotations

from pathlib import Path

from human_simulator.core.policy import CORE_ARTIFACT_DIR, CORE_SLICE_VERSION

SAFE_DIR = Path("private") / "media-safe"
OUT_DIR = Path("private") / "media-out"
SUMMARY_NAME = "summary.json"
CATALOG_NAME = "catalog.yaml"
MEDIA_PACKAGE = Path("media")

HEX64 = r"\b[0-9a-fA-F]{64}\b"
ISO_TS = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
POSTGRES_URI = r"(?i)postgres(?:ql)?://"
PATIENT_ID = r"(?i)patient_id"
EMAIL = r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"


def artifact_dir(root: Path) -> Path:
    return root / CORE_ARTIFACT_DIR


def safe_dir(root: Path) -> Path:
    return root / SAFE_DIR


def summary_path(root: Path) -> Path:
    return safe_dir(root) / SUMMARY_NAME


def out_dir(root: Path) -> Path:
    return root / OUT_DIR / CORE_SLICE_VERSION


def media_package(root: Path) -> Path:
    return root / MEDIA_PACKAGE
