"""Settings for Stage 02 kgz source restore."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

KGZ_TARGET_DATABASE = "kgz_raw"
KGZ_AUDIT_USER = "kgz_audit_ro"


class KgzRestoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KGZ_",
        env_file="db-kgz.env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    pg_host: str = "localhost"
    pg_port: int = 5435
    pg_database: str = KGZ_TARGET_DATABASE
    pg_user: str = KGZ_TARGET_DATABASE
    pg_password: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("KGZ_PG_PASSWORD", "KGZ_POSTGRES_PASSWORD", "POSTGRES_PASSWORD"),
    )
    audit_user: str = KGZ_AUDIT_USER
    audit_password: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("KGZ_AUDIT_PASSWORD", "AUDIT_PASSWORD"),
    )
    dump_path: Path = Path("kgz-20231204.dump")
    artifacts_dir: Path = Path("artifacts/stage-02")
    repo_root: Path = Path.cwd()
    disk_space_multiplier: float = 2.0
    compose_file: Path = Path("docker-compose.yml")
    restore_script: Path = Path("restore-kgz.sh")

    @property
    def sqlalchemy_url(self) -> str:
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

    @property
    def audit_redacted_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.audit_user}:***"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def audit_sqlalchemy_url(self) -> str:
        password = self.audit_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.audit_user}:{password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def dump_absolute(self) -> Path:
        path = self.dump_path
        if path.is_absolute():
            return path
        return self.repo_root / path

    @classmethod
    def from_repo(cls, repo_root: Path | None = None) -> KgzRestoreSettings:
        root = repo_root or Path.cwd()
        private_path = root / "private" / "sources.yaml"
        example_path = root / "config" / "sources.example.yaml"
        path = private_path if private_path.exists() else example_path

        overrides: dict[str, object] = {"repo_root": root}
        if path.exists():
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            src = data.get("sources", {}).get("local_kgz", {})
            audit_src = data.get("sources", {}).get("local_kgz_audit", {})
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
            if audit_src.get("user"):
                overrides["audit_user"] = str(audit_src["user"])
            if audit_src.get("password"):
                overrides["audit_password"] = SecretStr(str(audit_src["password"]))

            dumps = data.get("dumps", {})
            if dumps.get("kgz"):
                overrides["dump_path"] = Path(str(dumps["kgz"]))

            stage02 = data.get("stage02", {})
            if stage02.get("artifacts_dir"):
                overrides["artifacts_dir"] = Path(str(stage02["artifacts_dir"]))
            if stage02.get("target_database"):
                overrides["pg_database"] = str(stage02["target_database"])

        return cls(**overrides)


class SourceABaseline(BaseSettings):
    """Expected immutable configuration for source A (magerya_api)."""

    pg_host: str = "localhost"
    pg_port: int = 5434
    pg_database: str = "magerya_api"
    pg_user: str = "magerya_api"
    compose_service: str = "mg-db"
    compose_port_mapping: str = "5434:5432"

    @classmethod
    def from_repo(cls, repo_root: Path) -> SourceABaseline:
        private_path = repo_root / "private" / "sources.yaml"
        example_path = repo_root / "config" / "sources.example.yaml"
        path = private_path if private_path.exists() else example_path
        overrides: dict[str, object] = {}
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
        return cls(**overrides)
