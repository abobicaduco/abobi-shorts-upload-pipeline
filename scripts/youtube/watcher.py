# -*- coding: utf-8 -*-
"""Watch inbox folder for new MP4 files and manifest updates."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from .config import BatchConfig, YouTubeSettings
from .manifest import inbox_mp4_entries, load_batch_yaml, load_manifest_csv
from .upload import run_batch, setup_logging

LOGGER = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5.0
FILE_STABLE_SEC = 3.0


def _file_stable(path: Path, stable_sec: float = FILE_STABLE_SEC) -> bool:
    if not path.is_file():
        return False
    try:
        size_a = path.stat().st_size
        time.sleep(stable_sec)
        size_b = path.stat().st_size
        return size_a > 0 and size_a == size_b
    except OSError:
        return False


def _collect_entries(
    inbox: Path,
    manifest_path: Path,
    batch: Optional[BatchConfig],
) -> list:
    if manifest_path.is_file() and batch:
        return load_manifest_csv(manifest_path, inbox, batch)
    if batch:
        return inbox_mp4_entries(inbox, batch)
    return []


def watch_inbox(
    settings: YouTubeSettings,
    batch: Optional[BatchConfig],
    *,
    manifest_path: Path,
    batch_path: Optional[Path],
    dry_run: bool,
    skip_uploaded: bool,
    poll_interval: float = POLL_INTERVAL_SEC,
) -> int:
    setup_logging(settings.uploaded_dir / "watch.log" if settings.log_to_uploaded_dir else None)
    inbox = settings.inbox
    inbox.mkdir(parents=True, exist_ok=True)

    if batch is None and batch_path and batch_path.is_file():
        batch = load_batch_yaml(batch_path.resolve())
    if batch is None:
        default = inbox / "batch.yaml"
        if default.is_file():
            batch = load_batch_yaml(default)

    if batch is None:
        LOGGER.error("Watcher needs batch.yaml in inbox or --batch")
        return 2

    LOGGER.info("Watching %s (Ctrl+C to stop)", inbox)
    processed: set[str] = set()

    try:
        while True:
            entries = _collect_entries(inbox, manifest_path, batch)
            pending = []
            for e in entries:
                key = str(e.file_path.resolve())
                if key in processed:
                    continue
                if not _file_stable(e.file_path, stable_sec=1.0):
                    continue
                pending.append(e)

            if pending:
                LOGGER.info("Processing %s new item(s)", len(pending))
                code = run_batch(
                    pending,
                    settings,
                    batch,
                    dry_run=dry_run,
                    skip_uploaded=skip_uploaded,
                )
                for e in pending:
                    processed.add(str(e.file_path.resolve()))
                if code != 0:
                    LOGGER.warning("Batch had failures; will retry new files on next event")

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        LOGGER.info("Watcher stopped.")
        return 0
