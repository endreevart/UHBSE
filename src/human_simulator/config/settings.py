"""Application settings."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuditSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUDIT_",
        env_file="db.env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    pg_host: str = "localhost"
    pg_port: int = 5434
    pg_database: str = "magerya_api"
    pg_user: str = "magerya_api"
    pg_password: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("AUDIT_PG_PASSWORD", "POSTGRES_PASSWORD"),
    )
    statement_timeout_ms: int = 30_000
    lock_timeout_ms: int = 5_000
    artifacts_dir: Path = Path("artifacts/stage-01")
    repo_root: Path = Path.cwd()
    database_url: str | None = None

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        password = self.pg_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.pg_user}:{password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def redacted_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.pg_user}:***"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @classmethod
    def from_repo(cls, repo_root: Path | None = None) -> AuditSettings:
        root = repo_root or Path.cwd()
        private_path = root / "private" / "sources.yaml"
        example_path = root / "config" / "sources.example.yaml"
        path = private_path if private_path.exists() else example_path

        overrides: dict[str, object] = {"repo_root": root}
        if path.exists():
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            src = data.get("sources", {}).get("local_stage", {})
            if "host" in src:
                overrides["pg_host"] = src["host"]
            if "port" in src:
                overrides["pg_port"] = int(src["port"])
            if "database" in src:
                overrides["pg_database"] = src["database"]
            if "user" in src:
                overrides["pg_user"] = src["user"]
            if src.get("password"):
                overrides["pg_password"] = SecretStr(str(src["password"]))

        return cls(**overrides)
