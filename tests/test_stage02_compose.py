"""Tests for Stage 02 docker-compose infrastructure."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_compose_has_isolated_kgz_db(repo_root: Path) -> None:
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert "mg-db" in services
    assert "kgz-db" in services

    mg = services["mg-db"]
    kgz = services["kgz-db"]

    assert any("5434:5432" in str(p) for p in mg["ports"])
    assert any("5435:5432" in str(p) for p in kgz["ports"])
    assert mg["env_file"] == ["db.env"]
    kgz_env = kgz["env_file"]
    assert any(
        (isinstance(e, dict) and e.get("path") == "db-kgz.env") or e == "db-kgz.env"
        for e in kgz_env
    )
    assert kgz["environment"]["POSTGRES_DB"] == "kgz_raw"

    volumes = compose["volumes"]
    assert "mg-db-data" in volumes
    assert "kgz-db-data" in volumes
    assert mg["volumes"] == ["mg-db-data:/var/lib/postgresql/data"]
    assert kgz["volumes"] == ["kgz-db-data:/var/lib/postgresql/data"]


def test_kgz_healthcheck_uses_kgz_raw(repo_root: Path) -> None:
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    test_cmd = compose["services"]["kgz-db"]["healthcheck"]["test"]
    joined = " ".join(test_cmd)
    assert "kgz_raw" in joined


def test_db_kgz_env_example(repo_root: Path) -> None:
    text = (repo_root / "db-kgz.env.example").read_text(encoding="utf-8")
    assert "POSTGRES_DB=kgz_raw" in text
    assert "POSTGRES_USER=kgz_raw" in text


def test_sources_example_kgz_config(repo_root: Path) -> None:
    data = yaml.safe_load((repo_root / "config" / "sources.example.yaml").read_text(encoding="utf-8"))
    kgz = data["sources"]["local_kgz"]
    assert kgz["database"] == "kgz_raw"
    assert kgz["port"] == 5435
    assert data["stage02"]["target_database"] == "kgz_raw"
    assert data["dumps"]["kgz"] == "kgz-20231204.dump"
