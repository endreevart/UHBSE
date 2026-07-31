"""Database connection helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SourceConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


def load_source_config(
    repo_root: Path | None = None,
    source_id: str = "local_stage",
) -> SourceConfig:
    root = repo_root or Path.cwd()
    private_path = root / "private" / "sources.yaml"
    example_path = root / "config" / "sources.example.yaml"

    path = private_path if private_path.exists() else example_path
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    src = data["sources"][source_id]
    password = src.get("password") or os.environ.get("POSTGRES_PASSWORD")
    if not password:
        msg = "POSTGRES_PASSWORD is not set; configure db.env or private/sources.yaml"
        raise ValueError(msg)
    return SourceConfig(
        host=src["host"],
        port=int(src["port"]),
        database=src["database"],
        user=src["user"],
        password=password,
    )
