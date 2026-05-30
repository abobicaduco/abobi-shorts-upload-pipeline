# -*- coding: utf-8 -*-
"""PID file lock to prevent concurrent pipeline/resume runs."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

LOGGER = logging.getLogger(__name__)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_lock_pid(lock_path: Path) -> Optional[int]:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip().splitlines()[0]
        return int(raw)
    except (OSError, ValueError, IndexError):
        return None


@contextmanager
def pipeline_lock(lock_path: Path, *, platform: str = "pipeline") -> Iterator[None]:
    """Acquire exclusive lock; raise RuntimeError if another live process holds it."""
    lock_path = lock_path.resolve()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.is_file():
        other = _read_lock_pid(lock_path)
        if other is not None and other != os.getpid() and _pid_alive(other):
            raise RuntimeError(
                f"Another {platform} run is active (PID {other}). "
                f"Lock: {lock_path}. Never run two pipelines at once."
            )
        lock_path.unlink(missing_ok=True)

    lock_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    LOGGER.debug("Acquired %s lock PID=%s path=%s", platform, os.getpid(), lock_path)
    try:
        yield
    finally:
        try:
            if lock_path.is_file():
                holder = _read_lock_pid(lock_path)
                if holder is None or holder == os.getpid():
                    lock_path.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("Could not release lock %s", lock_path)
