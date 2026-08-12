"""Inter-process lock around the publication pipeline.

Changeset 01 v0.2 was published while two full test runs were executing concurrently. Both runs
republished the same Stage 03 evidence, and the interleaving left the workspace holding
regenerated Design files that then travelled into the review bundle. A single writer at a time
is the structural fix; the frozen-evidence check is the detector.

The lock is advisory between cooperating processes and is acquired with ``O_EXCL``, so the
winner is decided by the filesystem rather than by a timing assumption. Read-only gates never
take it: they cannot corrupt a snapshot.

The lock file records only technical facts — pid, host, an opaque operation name and timestamps.
It never contains a secret, a DSN, a credential or a patient value.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

LOCK_NAME = ".publication.lock"
LOCK_DIR = Path("artifacts") / "external-review"

# A lock older than this whose owner is gone is treated as abandoned. The window is generous
# relative to a publication run so that a live publisher is never mistaken for a corpse.
STALE_AFTER_SECONDS = 3600.0


class PublicationLocked(RuntimeError):
    """Raised when another publisher already holds the lock."""


@dataclass
class _Ownership:
    info: "LockInfo"
    thread_ident: int
    depth: int


# In-process ownership, so nesting on the acquiring thread is allowed while any other thread is
# refused exactly as another process would be.
_OWNERSHIP_MUTEX = threading.Lock()
_OWNED: dict[Path, _Ownership] = {}


@dataclass(frozen=True)
class LockInfo:
    pid: int
    host: str
    operation: str
    acquired_at: str

    def document(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "host": self.host,
            "operation": self.operation,
            "acquired_at": self.acquired_at,
        }


def lock_path(repo_root: Path) -> Path:
    return repo_root.resolve() / LOCK_DIR / LOCK_NAME


def _read_lock(path: Path) -> LockInfo | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return LockInfo(
            pid=int(payload["pid"]),
            host=str(payload["host"]),
            operation=str(payload["operation"]),
            acquired_at=str(payload["acquired_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Owned by another user; it exists, so the lock is live.
        return True
    except OSError:
        return True
    return True


def _age_seconds(path: Path) -> float:
    try:
        return max(0.0, datetime.now(tz=UTC).timestamp() - path.stat().st_mtime)
    except OSError:
        return 0.0


def is_stale(repo_root: Path) -> bool:
    """A lock is stale only when its owner is gone, or it is old and not from this host."""
    path = lock_path(repo_root)
    if not path.is_file():
        return False
    info = _read_lock(path)
    if info is None:
        # Unreadable or truncated: a half-written lock from a killed process.
        return True
    if info.host == socket.gethostname():
        return not _process_alive(info.pid)
    return _age_seconds(path) > STALE_AFTER_SECONDS


@contextmanager
def publication_lock(repo_root: Path, *, operation: str) -> Iterator[LockInfo]:
    """Hold the publication lock for the duration of the block.

    Fails immediately rather than waiting: a second publisher is a mistake to report, not a
    queue to join.
    """
    path = lock_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Re-entrant on the acquiring thread only: the publisher holds the lock for the whole run
    # and calls publishing verifier steps inside it. Another thread, like another process, is
    # refused, so two parallel tests can never write one snapshot.
    with _OWNERSHIP_MUTEX:
        owner = _OWNED.get(path)
        if owner is not None:
            if owner.thread_ident == threading.get_ident():
                owner.depth += 1
                reentered = owner.info
            else:
                raise PublicationLocked(
                    f"Another publication is already in progress on this process: "
                    f"{owner.info.operation} on thread {owner.thread_ident}. "
                    "Refusing to write a second snapshot or archive concurrently."
                )
        else:
            reentered = None

    if reentered is not None:
        try:
            yield reentered
        finally:
            with _OWNERSHIP_MUTEX:
                owner = _OWNED.get(path)
                if owner is not None:
                    owner.depth -= 1
        return

    info = LockInfo(
        pid=os.getpid(),
        host=socket.gethostname(),
        operation=operation,
        acquired_at=datetime.now(tz=UTC).isoformat(),
    )
    payload = json.dumps(info.document(), indent=2, sort_keys=True) + "\n"

    def _try_acquire() -> int | None:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return None

    handle = _try_acquire()
    if handle is None and is_stale(repo_root):
        # Breaking a stale lock is itself a race, so re-acquire with O_EXCL afterwards and
        # accept losing to whoever else was breaking it at the same moment.
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        handle = _try_acquire()
    if handle is None:
        existing = _read_lock(path)
        holder = (
            f"pid {existing.pid} on {existing.host} running {existing.operation} "
            f"since {existing.acquired_at}"
            if existing
            else "an unreadable lock file"
        )
        raise PublicationLocked(
            f"Another publication is already in progress: {holder}. "
            f"Refusing to write a second snapshot or archive concurrently. "
            f"If that process is gone, remove {path.relative_to(repo_root.resolve())}."
        )

    with _OWNERSHIP_MUTEX:
        _OWNED[path] = _Ownership(info=info, thread_ident=threading.get_ident(), depth=1)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        yield info
    finally:
        with _OWNERSHIP_MUTEX:
            _OWNED.pop(path, None)
        try:
            current = _read_lock(path)
            if current is None or (current.pid == info.pid and current.host == info.host):
                path.unlink(missing_ok=True)
        except OSError:
            pass


def lock_verification(info: LockInfo | None) -> dict[str, Any]:
    """Evidence that the publication ran under an exclusive lock.

    Says nothing about release: this is recorded while the lock is still held, so a release
    flag here could only ever be false. Release is asserted after the pipeline exits.
    """
    return {
        "lock_file": (LOCK_DIR / LOCK_NAME).as_posix(),
        "held_during_publication": info is not None,
        "holder": info.document() if info else None,
        "contains_secrets": False,
    }
