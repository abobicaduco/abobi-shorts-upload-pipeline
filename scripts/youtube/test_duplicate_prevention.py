# -*- coding: utf-8 -*-
"""Smoke test: double resume / execute must not call upload when video_id or sidecar exists."""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from importlib.machinery import SourcelessFileLoader
from pathlib import Path
from unittest.mock import MagicMock

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_CACHE = Path(__file__).resolve().parent / "__pycache__"


def _bootstrap_youtube_modules() -> None:
    for stem in ("secrets_store", "config"):
        pyc = _CACHE / f"{stem}.cpython-312.pyc"
        if not pyc.is_file():
            continue
        modname = f"youtube.{stem}"
        if modname in sys.modules:
            continue
        loader = SourcelessFileLoader(modname, str(pyc))
        spec = importlib.util.spec_from_loader(modname, loader)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)


_bootstrap_youtube_modules()

from youtube.schedule_db import ScheduleDB
from youtube.scheduler import PlannedUpload, execute_planned_uploads, should_skip_upload
from youtube.uploader import YouTubeUploader, write_sidecar


def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp())


def test_skip_when_db_has_video_id() -> None:
    tmp = _tmp_dir()
    try:
        clip = Path(tmp) / "clip_099.mp4"
        clip.write_bytes(b"x")
        db_path = Path(tmp) / "test.db"
        db = ScheduleDB(db_path)
        row_id = db.insert_pending(
            clip,
            "TEST - Granny 2 #99 | abobicaduco",
            datetime(2026, 6, 20, 21, 0, tzinfo=timezone.utc),
            "2026-06-20",
            21,
        )
        db.mark_scheduled(row_id, "VID_FROM_DB")
        row = db.get_by_id(row_id)
        assert row is not None
        skip, reason, vid = should_skip_upload(db, clip, row)
        assert skip is True
        assert vid == "VID_FROM_DB"
        assert reason and "DB" in reason
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_skip_when_sidecar_exists() -> None:
    tmp = _tmp_dir()
    try:
        clip = Path(tmp) / "clip_001.mp4"
        clip.write_bytes(b"x")
        write_sidecar(clip, "SIDECAR_VID", "title")
        db_path = Path(tmp) / "test.db"
        db = ScheduleDB(db_path)
        db.insert_pending(
            clip,
            "title",
            datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc),
            "2026-06-20",
            16,
        )
        skip, reason, vid = should_skip_upload(db, clip)
        assert skip is True
        assert vid == "SIDECAR_VID"
        row = db.get_by_file(clip)
        assert row is not None and row.video_id == "SIDECAR_VID"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_double_execute_zero_uploads() -> None:
    tmp = _tmp_dir()
    try:
        clip = Path(tmp) / "clip_002.mp4"
        clip.write_bytes(b"x")
        write_sidecar(clip, "ALREADY_UP", "t")
        db_path = Path(tmp) / "test.db"
        db = ScheduleDB(db_path)
        row_id = db.insert_pending(
            clip,
            "t",
            datetime(2026, 6, 21, 18, 0, tzinfo=timezone.utc),
            "2026-06-21",
            18,
        )
        planned = [
            PlannedUpload(
                file_path=clip,
                title="t",
                description="d",
                scheduled_at_utc=datetime(2026, 6, 21, 18, 0, tzinfo=timezone.utc),
                slot_date="2026-06-21",
                slot_hour=18,
                db_id=row_id,
            )
        ]
        mock_yt = MagicMock()
        uploader = YouTubeUploader(mock_yt)
        ok1, fail1, skip1, _ = execute_planned_uploads(planned, uploader, db, dry_run=False)
        ok2, fail2, skip2, _ = execute_planned_uploads(planned, uploader, db, dry_run=False)
        assert mock_yt.videos().insert.call_count == 0
        assert skip1 == 1 and skip2 == 1
        assert ok1 == 0 and ok2 == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_skip_when_db_has_video_id()
    test_skip_when_sidecar_exists()
    test_double_execute_zero_uploads()
    print("OK: all duplicate-prevention checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
