"""Shared pg_restore invocation for Stage 02 restore."""

from __future__ import annotations

from human_simulator.stage02.settings import KgzRestoreSettings

RESTORE_FORBIDDEN_FLAGS = ("--clean", "--create", "--drop")
RESTORE_REQUIRED_FLAGS = ("--no-owner", "--no-privileges")


def build_pg_restore_argv(settings: KgzRestoreSettings) -> list[str]:
    return [
        "docker",
        "compose",
        "exec",
        "-T",
        "kgz-db",
        "pg_restore",
        "-U",
        settings.pg_user,
        "-d",
        settings.pg_database,
        "--no-owner",
        "--no-privileges",
        f"--role={settings.pg_user}",
    ]


def build_redacted_pg_restore_command(settings: KgzRestoreSettings) -> str:
    argv = build_pg_restore_argv(settings)
    redacted = []
    for token in argv:
        if token in {settings.pg_user, settings.pg_database}:
            redacted.append(token)
        else:
            redacted.append(token)
    cmd = " ".join(redacted)
    return f"{cmd} < {settings.dump_path.name}"


def assert_restore_flags_safe(argv: list[str]) -> None:
    for forbidden in RESTORE_FORBIDDEN_FLAGS:
        if forbidden in argv:
            raise ValueError(f"Forbidden restore flag present: {forbidden}")
    for required in RESTORE_REQUIRED_FLAGS:
        if required not in argv:
            raise ValueError(f"Required restore flag missing: {required}")
