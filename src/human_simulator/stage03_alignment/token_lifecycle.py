"""Token lifecycle helpers — never leave process-global VAULT_TOKEN polluted."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class TokenLifecycleError(RuntimeError):
    """Raised without embedding token material."""


@contextmanager
def isolated_vault_token(repo_root: Path) -> Iterator[str]:
    """Yield a Vault operator token without permanently mutating os.environ.

    Restores the prior VAULT_TOKEN value (including absence) on exit — success or error.
    """
    prior_present = "VAULT_TOKEN" in os.environ
    prior_value = os.environ.get("VAULT_TOKEN")
    token = ""
    try:
        script = repo_root / "ops" / "vault" / "scripts" / "decrypt-root-token.sh"
        env = {k: v for k, v in os.environ.items() if k != "VAULT_TOKEN"}
        env["GNUPGHOME"] = str(repo_root / "ops" / "vault" / "pgp" / "gnupg")
        proc = subprocess.run(  # noqa: S603
            [str(script)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=120,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            raise TokenLifecycleError("failed to obtain operator token")
        token = proc.stdout.strip()
        yield token
    finally:
        token = ""
        if prior_present:
            if prior_value is not None:
                os.environ["VAULT_TOKEN"] = prior_value
        else:
            os.environ.pop("VAULT_TOKEN", None)


def vault_token_env_snapshot() -> tuple[bool, str | None]:
    """Return (present, value_or_none) — caller must not log the value."""
    present = "VAULT_TOKEN" in os.environ
    return present, os.environ.get("VAULT_TOKEN") if present else None


def env_matches_snapshot(snapshot: tuple[bool, str | None]) -> bool:
    present, value = snapshot
    now_present = "VAULT_TOKEN" in os.environ
    if present != now_present:
        return False
    if not present:
        return True
    return os.environ.get("VAULT_TOKEN") == value
