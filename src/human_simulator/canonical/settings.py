"""Connection settings for the isolated canonical database.

Credentials come from the runtime environment only. No DSN, password or key material is
ever written to a repository artifact. The isolation guard refuses any configuration that
would point canonical tooling at a raw source database, per
artifacts/stage-03-implementation/physical-storage-plan.yaml :: connection_policy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from human_simulator.canonical.constants import (
    CANONICAL_DATABASE,
    CANONICAL_PORT,
    FORBIDDEN_CANONICAL_TARGET_DATABASES,
    RAW_SOURCE_PORTS,
)

# Local runtime credential file. Git-ignored, never published, never logged. Reading it inside
# the runtime keeps the secret out of shell history and out of any process listing.
CANONICAL_ENV_FILE_NAME = "canonical-db.env"
REQUIRED_SETTING_NAMES: tuple[str, ...] = (
    "CANONICAL_DB_ADMIN_USER",
    "CANONICAL_DB_ADMIN_PASSWORD",
)


class CanonicalIsolationError(RuntimeError):
    """Raised when canonical tooling is aimed at a forbidden target."""


class CanonicalSettingsMissing(RuntimeError):
    """Raised when required runtime connection settings are absent."""


@dataclass(frozen=True)
class CanonicalConnectionSettings:
    host: str
    port: int
    database: str
    user: str
    password: str

    def dsn(self) -> str:
        """Runtime-only DSN. Never log, print or persist the return value."""
        return (
            f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        )

    def safe_target(self) -> str:
        """Redacted description safe for reports and logs."""
        return f"{self.host}:{self.port}/{self.database}"


def assert_canonical_target_allowed(database: str, port: int) -> None:
    """Fail closed when a canonical connection would reach a raw source database."""
    if database in FORBIDDEN_CANONICAL_TARGET_DATABASES:
        raise CanonicalIsolationError(
            f"canonical tooling may not target raw source database {database!r}"
        )
    if port in RAW_SOURCE_PORTS:
        raise CanonicalIsolationError(
            f"canonical tooling may not target raw source port {port}"
        )


def assert_raw_target_allowed(database: str) -> None:
    """Fail closed when raw-source tooling would reach the canonical database."""
    if database == CANONICAL_DATABASE:
        raise CanonicalIsolationError(
            f"raw source tooling may not target canonical database {database!r}"
        )


def _env_file_candidates() -> tuple[Path, ...]:
    here = Path(__file__).resolve()
    roots = [Path.cwd(), *here.parents[:5]]
    return tuple(root / CANONICAL_ENV_FILE_NAME for root in roots)


def read_runtime_env_file() -> dict[str, str]:
    """Parse the local runtime env file if present. Values are never logged or returned upward."""
    for candidate in _env_file_candidates():
        if not candidate.is_file():
            continue
        values: dict[str, str] = {}
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
        return values
    return {}


def resolve_setting_source(env: dict[str, str] | None = None) -> dict[str, str]:
    """Process environment first, then the local runtime env file as a fallback."""
    if env is not None:
        return dict(env)
    merged = read_runtime_env_file()
    merged.update({key: value for key, value in os.environ.items() if value})
    return merged


def load_canonical_settings(
    env: dict[str, str] | None = None,
    *,
    database_override: str | None = None,
) -> CanonicalConnectionSettings:
    source = resolve_setting_source(env)
    host = source.get("CANONICAL_DB_HOST", "localhost")
    port = int(source.get("CANONICAL_DB_PORT", str(CANONICAL_PORT)))
    database = database_override or source.get("CANONICAL_DB_NAME", CANONICAL_DATABASE)
    user = source.get("CANONICAL_DB_ADMIN_USER", "")
    password = source.get("CANONICAL_DB_ADMIN_PASSWORD", "")

    missing = [
        name
        for name, value in zip(REQUIRED_SETTING_NAMES, (user, password), strict=True)
        if not value
    ]
    if missing:
        raise CanonicalSettingsMissing(
            "missing canonical connection settings: " + ", ".join(sorted(missing))
        )

    assert_canonical_target_allowed(database, port)
    return CanonicalConnectionSettings(
        host=host, port=port, database=database, user=user, password=password
    )


def canonical_settings_available(env: dict[str, str] | None = None) -> bool:
    try:
        load_canonical_settings(env)
    except (CanonicalSettingsMissing, CanonicalIsolationError, ValueError):
        return False
    return True


def missing_canonical_prerequisites(env: dict[str, str] | None = None) -> list[str]:
    """Names of absent settings, never their values."""
    source = resolve_setting_source(env)
    return sorted(name for name in REQUIRED_SETTING_NAMES if not source.get(name))
