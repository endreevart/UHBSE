"""Settings for privacy-preserving identity linkage (HMAC)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LinkageSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("db-audit.env",),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    linkage_hmac_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="LINKAGE_HMAC_KEY",
    )

    @classmethod
    def from_repo(cls, repo_root: Path) -> LinkageSettings:
        previous = Path.cwd()
        try:
            import os

            os.chdir(repo_root)
            return cls()
        finally:
            os.chdir(previous)

    def require_key(self) -> bytes:
        value = self.linkage_hmac_key.get_secret_value().strip()
        if not value:
            raise ValueError(
                "LINKAGE_HMAC_KEY is required for identity linkage assessment. "
                "Set it in db-audit.env (local only, never commit)."
            )
        return value.encode("utf-8")
