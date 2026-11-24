"""Inventory the configured repositories and record identifier coverage. Dumps are not read."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v022.policy import MAGERYA_CODE_ROOT_DEFAULT, MAGERYA_CODE_ROOT_ENV
from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import COVERAGE_CLASSES, EXACT_IDENTIFIERS, STRUCTURAL_SYMBOLS

_SKIP = {"_git", ".git", "__pycache__", "node_modules", ".venv", "media", "static", "dumps", "private", "artifacts"}
_MAX_BYTES = 1_000_000
_EXT = {
    ".py": "python",
    ".js": "javascript_typescript",
    ".mjs": "javascript_typescript",
    ".ts": "javascript_typescript",
    ".jsx": "react_vue",
    ".tsx": "react_vue",
    ".vue": "react_vue",
    ".kt": "mobile",
    ".swift": "mobile",
    ".dart": "mobile",
    ".sql": "sql_migrations",
    ".html": "html_templates",
    ".md": "technical_documentation",
    ".rst": "technical_documentation",
    ".json": "json_yaml_schemas",
    ".yaml": "json_yaml_schemas",
    ".yml": "json_yaml_schemas",
}


def magerya_root() -> Path:
    return Path(os.environ.get(MAGERYA_CODE_ROOT_ENV) or MAGERYA_CODE_ROOT_DEFAULT).expanduser()


def _git(root: Path) -> dict[str, Any]:
    if not (root / ".git").exists():
        return {"commit_sha": None, "worktree": "NOT_A_GIT_REPOSITORY"}
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=False)
    dirty = bool(status.stdout.strip())
    return {
        "commit_sha": commit.stdout.strip() if commit.returncode == 0 else None,
        "worktree": "DIRTY" if dirty else "CLEAN",
        "dirty_entry_count": len(status.stdout.splitlines()) if status.returncode == 0 else None,
    }


def _class_for(path: Path) -> str:
    if "migrations" in path.parts:
        return "sql_migrations"
    name = path.name.lower()
    if "openapi" in name or "swagger" in name:
        return "openapi"
    if path.suffix.lower() == ".json" and path.name.endswith(".dump"):
        return "database_dumps"
    return _EXT.get(path.suffix.lower(), "other")


def _walk(root: Path) -> tuple[dict[str, int], list[dict[str, Any]], dict[str, int]]:
    counts = {name: 0 for name in (*COVERAGE_CLASSES, "other")}
    dumps_skipped = 0
    large_skipped = 0
    hits: list[dict[str, Any]] = []
    hit_counts = {identifier: 0 for identifier in (*EXACT_IDENTIFIERS, *STRUCTURAL_SYMBOLS)}
    if not root.is_dir():
        return counts, hits, hit_counts
    for path in root.rglob("*"):
        if not path.is_file() or _SKIP.intersection(path.parts):
            continue
        if path.suffix.lower() in {".dump", ".backup"} or "dumps" in path.parts:
            counts["database_dumps"] += 1
            dumps_skipped += 1
            continue
        kind = _class_for(path)
        counts[kind] = counts.get(kind, 0) + 1
        if path.stat().st_size > _MAX_BYTES or kind == "other":
            large_skipped += path.stat().st_size > _MAX_BYTES
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        rel = path.relative_to(root).as_posix()
        for identifier in (*EXACT_IDENTIFIERS, *STRUCTURAL_SYMBOLS):
            if identifier not in text:
                continue
            hit_counts[identifier] += 1
            if hit_counts[identifier] > 20:
                continue
            line_no = next((index for index, line in enumerate(lines, start=1) if identifier in line), None)
            line_text = lines[line_no - 1] if line_no else ""
            hits.append({
                "path": rel,
                "coverage_class": kind,
                "identifier": identifier,
                "identifier_group": "exact" if identifier in EXACT_IDENTIFIERS else "structural_symbol",
                "line": line_no,
                "line_sha256": hashlib.sha256(line_text.strip().encode("utf-8")).hexdigest() if line_text else None,
                "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    counts["database_dumps_not_read"] = dumps_skipped
    counts["large_files_not_read"] = int(large_skipped)
    return counts, hits, hit_counts


def inventory(workspace: Path) -> dict[str, Any]:
    magerya = magerya_root()
    entries = [
        {
            "name": "human-simulator",
            "path": ".",
            "available": True,
            "backend": True,
            "frontend": False,
            "mobile": False,
            "source_link": "ANALYSIS_REPOSITORY",
            "link_evidence": "this repository analyses restored database copies and does not contain the clinic application",
            **_git(workspace),
        },
        {
            "name": "django-develop",
            "path": "UHBSE_MAGERYA_CODE_ROOT",
            "available": magerya.is_dir(),
            "backend": (magerya / "apps").is_dir(),
            "frontend": any((magerya / name).exists() for name in ("frontend", "web", "client", "package.json")),
            "mobile": any((magerya / name).exists() for name in ("ios", "android", "mobile")),
            "source_link": "SOURCE_A_CANDIDATE",
            "link_evidence": "configured Magerya checkout used by exposure discovery v0.2.2; not a Source B application",
            **(_git(magerya) if magerya.is_dir() else {"commit_sha": None, "worktree": "UNAVAILABLE"}),
        },
    ]
    return {
        "roots_considered": [item["name"] for item in entries],
        "arbitrary_home_scan": False,
        "SOURCE_B_APPLICATION_CODE_ACCESS_STATUS": "NOT_AVAILABLE",
        "repositories": entries,
    }


def coverage(workspace: Path) -> dict[str, Any]:
    repos = []
    combined = {name: 0 for name in (*COVERAGE_CLASSES, "other", "database_dumps_not_read", "large_files_not_read")}
    all_hits: list[dict[str, Any]] = []
    targets = [("human-simulator", workspace, "ANALYSIS_CODE")]
    magerya = magerya_root()
    if magerya.is_dir():
        targets.append(("django-develop", magerya, "SOURCE_A_CANDIDATE"))
    for name, root, link in targets:
        if name == "django-develop" and (root / "apps").is_dir():
            search_roots = [root / "apps"]
            search_roots.extend(path for path in (root / "templates", root / "frontend", root / "web") if path.is_dir())
        else:
            search_roots = [root / name for name in ("src", "docs", "config", "tests") if (root / name).is_dir()]
        counts: dict[str, int] = {}
        hits = []
        hit_counts: dict[str, int] = {}
        for search_root in search_roots:
            part_counts, part_hits, part_hit_counts = _walk(search_root)
            for key, value in part_counts.items():
                counts[key] = counts.get(key, 0) + value
            prefix = search_root.relative_to(root).as_posix()
            hits.extend({**hit, "path": f"{prefix}/{hit['path']}"} for hit in part_hits)
            for key, value in part_hit_counts.items():
                hit_counts[key] = hit_counts.get(key, 0) + value
        for key, value in counts.items():
            combined[key] = combined.get(key, 0) + value
        for hit in hits:
            hit["repository"] = name
            hit["source_link"] = link
        all_hits.extend(hits)
        repos.append({
            "repository": name,
            "searched_roots": [path.relative_to(root).as_posix() for path in search_roots],
            "nested_git_checkouts_excluded": name == "django-develop" and (root / "_git").is_dir(),
            "dumps_not_read_reason": "MAY_CONTAIN_ROW_DATA",
            "counts": counts,
            "identifier_file_counts": [
                {"identifier": identifier, "files": count}
                for identifier, count in hit_counts.items()
            ],
        })
    gaps = [
        {
            "area": "source_b_application_repository",
            "status": "NOT_AVAILABLE",
            "searched": False,
            "consequence": "zero identifier hits in other repositories are not a Source B form conclusion",
        },
        {
            "area": "javascript_typescript",
            "files_in_searched_roots": combined["javascript_typescript"],
            "status": "NO_FILES_IN_SEARCHED_ROOTS",
        },
        {
            "area": "react_vue",
            "files_in_searched_roots": combined["react_vue"],
            "status": "NO_FILES_IN_SEARCHED_ROOTS",
        },
        {
            "area": "mobile",
            "files_in_searched_roots": combined["mobile"],
            "status": "NO_FILES_IN_SEARCHED_ROOTS",
        },
        {
            "area": "database_dumps",
            "status": "NOT_READ",
            "reason": "MAY_CONTAIN_ROW_DATA",
        },
    ]
    return {"repositories": repos, "combined_counts": combined, "hits": all_hits, "coverage_gaps": gaps}
