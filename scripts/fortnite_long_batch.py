# -*- coding: utf-8 -*-
"""Ingest long-form Fortnite Mobile videos: inbox, metadata, SQLite, optional upload."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.llm_metadata import (
    build_youtube_description,
    generate_clip_metadata,
    is_ollama_available,
    resolve_ollama_model,
    save_metadata_manifest,
)
from youtube.config import BatchConfig, YouTubeSettings, load_env_file
from youtube.manifest import load_batch_yaml
from youtube.schedule_db import ScheduleDB, default_db_path
from youtube.scheduler import (
    LONG_FORM_SLOT_HOUR,
    execute_planned_uploads,
    plan_uploads,
    print_schedule_plan,
)
from youtube.stdio import configure_stdio_utf8
from youtube.uploader import YouTubeUploader
from youtube.auth import get_youtube_service

LOGGER = logging.getLogger(__name__)

DEFAULT_SOURCES = [
    Path(r"C:\Users\carlo\Videos\XRecorder_20260530_01.mp4"),
    Path(r"C:\Users\carlo\Videos\XRecorder_20260530_02.mp4"),
    Path(r"C:\Users\carlo\Videos\XRecorder_20260530_03.mp4"),
    Path(r"C:\Users\carlo\Videos\XRecorder_20260530_04.mp4"),
]
BATCH_ID = "fortnite_mobile_20260530"
GAME = "Fortnite Mobile"
SOURCE_STEM = "Fortnite Mobile gameplay"
LONG_SLOTS = (LONG_FORM_SLOT_HOUR,)


def _probe_duration_sec(path: Path) -> Optional[float]:
    for cmd in ("ffprobe", "ffmpeg"):
        try:
            proc = subprocess.run(
                [
                    cmd,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return float(proc.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            continue
    return None


def _tiktok_caption(meta: dict[str, Any]) -> str:
    title = str(meta.get("title") or "").strip()
    body = str(meta.get("description") or "").strip()
    hashtags = str(meta.get("hashtags") or "").strip()
    lines = [title, "", body]
    if hashtags:
        lines.extend(["", hashtags])
    return "\n".join(lines).strip()


def _generate_metadata(index: int, filename: str, *, use_llm: bool) -> dict[str, Any]:
    yt = generate_clip_metadata(
        index,
        index,
        game=GAME,
        platform="youtube",
        clip_filename=filename,
        source_stem=SOURCE_STEM,
        use_llm=use_llm,
    )
    tt = generate_clip_metadata(
        index,
        index,
        game=GAME,
        platform="tiktok",
        clip_filename=filename,
        source_stem=SOURCE_STEM,
        use_llm=use_llm,
    )
    return {"youtube": yt, "tiktok": tt}


def _write_batch_yaml(path: Path) -> None:
    text = """# Fortnite Mobile long-form batch — abobicaduco
hashtags: "#abobicaduco #fortnite #fortnitemobile #gameplay #battleroyale #victoryroyale"

append_shorts_hashtag: false

tags:
  - fortnite
  - fortnite mobile
  - gameplay
  - abobicaduco
  - battle royale
  - mobile gaming

privacy: public
category_id: "20"
content_type: long
"""
    path.write_text(text, encoding="utf-8")


def _write_manifest(
    inbox: Path,
    rows: list[dict[str, Any]],
    batch: BatchConfig,
) -> Path:
    manifest_path = inbox / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file_path", "title", "description", "tags", "tiktok_caption"])
        for row in rows:
            yt = row["youtube"]
            desc = build_youtube_description(
                yt["description"],
                yt.get("hashtags") or batch.hashtags,
                append_shorts=batch.append_shorts_hashtag,
            )
            tags = "|".join(yt.get("tags") or [])
            writer.writerow(
                [
                    row["dest_name"],
                    yt["title"],
                    desc,
                    tags,
                    _tiktok_caption(row["tiktok"]),
                ]
            )
    return manifest_path


def _register_tiktok_pending(
    pending_dir: Path,
    rows: list[dict[str, Any]],
    db_path: Path,
    *,
    slots: tuple[int, ...],
    tz_name: str,
    start_date: date,
    dry_run: bool,
) -> int:
    from tiktok.schedule_db import ScheduleDB as TikTokDB
    from tiktok.scheduler import next_available_slots as tt_slots

    pending_dir.mkdir(parents=True, exist_ok=True)
    tt_db = TikTokDB(db_path)
    scheduled_count = sum(
        1
        for _ in tt_db.list_by_status(["scheduled"])
    )
    if scheduled_count >= 30:
        LOGGER.warning(
            "TikTok DB has %s scheduled rows (>=30) — skipping TikTok schedule; files stay in pending.",
            scheduled_count,
        )
        manifest_lines = ["file_path,caption,slot_date,slot_hour,note"]
        for row in rows:
            dest = pending_dir / row["dest_name"]
            if not dest.exists() and row["inbox_path"].is_file():
                if dry_run:
                    LOGGER.info("[DRY-RUN] Would copy to TikTok pending: %s", dest)
                else:
                    shutil.copy2(row["inbox_path"], dest)
            manifest_lines.append(
                f"{row['dest_name']},{_tiktok_caption(row['tiktok']).replace(chr(10), ' ')},,,pending_quota_or_cap"
            )
        (pending_dir / "manifest.csv").write_text(
            "\n".join(manifest_lines) + "\n", encoding="utf-8"
        )
        return 0

    paths = [pending_dir / r["dest_name"] for r in rows]
    for row, dest in zip(rows, paths):
        if not dest.exists() and row["inbox_path"].is_file():
            if dry_run:
                LOGGER.info("[DRY-RUN] Would copy %s -> %s", row["inbox_path"], dest)
            else:
                shutil.copy2(row["inbox_path"], dest)

    free = tt_slots(len(paths), slots=slots, tz_name=tz_name, start_date=start_date, db=tt_db)
    inserted = 0
    for (row, dest), (utc_dt, slot_date, hour) in zip(rows, free):
        cap = _tiktok_caption(row["tiktok"])
        if dry_run:
            LOGGER.info(
                "[DRY-RUN] TikTok pending %s @ %s %s:00",
                dest.name,
                slot_date,
                hour,
            )
            continue
        if tt_db.get_by_file(dest):
            continue
        tt_db.insert_pending(dest, cap, utc_dt, slot_date, hour)
        inserted += 1
    return inserted


def run(argv: Optional[list[str]] = None) -> int:
    configure_stdio_utf8()
    load_env_file()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    p = argparse.ArgumentParser(description="Fortnite Mobile long-form batch ingest.")
    p.add_argument("--sources", nargs="*", type=Path, help="Override source MP4 paths")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--schedule-only", action="store_true", help="Plan DB slots, no YouTube upload")
    p.add_argument("--upload-limit", type=int, default=1, help="Max YouTube uploads this run")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--start-date", help="YYYY-MM-DD for first long slot")
    p.add_argument("--db", type=Path, help="youtube_schedule.db path")
    p.add_argument("--tiktok-db", type=Path, help="tiktok_schedule.db path")
    args = p.parse_args(argv)

    sources = [Path(s) for s in args.sources] if args.sources else list(DEFAULT_SOURCES)
    for src in sources:
        if not src.is_file():
            LOGGER.error("Missing source: %s", src)
            return 1

    use_llm = not args.no_llm and is_ollama_available(force_check=True)
    LOGGER.info(
        "Ollama: %s | model=%s",
        "on" if use_llm else "templates",
        resolve_ollama_model() if use_llm else "n/a",
    )

    home = Path.home()
    inbox = home / "YOUTUBE" / "inbox" / BATCH_ID
    pending_tt = home / "YOUTUBE" / "pending_tiktok" / "fortnite_mobile"
    inbox.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for i, src in enumerate(sources, start=1):
        dest_name = f"fortnite_mobile_{i:02d}.mp4"
        dest = inbox / dest_name
        dur = _probe_duration_sec(src)
        size_mb = src.stat().st_size / (1024 * 1024)
        LOGGER.info(
            "Source %s | %.1f MB | duration=%s",
            src.name,
            size_mb,
            f"{dur/60:.1f} min" if dur else "unknown",
        )
        if args.dry_run:
            LOGGER.info("[DRY-RUN] Would copy %s -> %s", src, dest)
        elif not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)

        meta = _generate_metadata(i, dest_name, use_llm=use_llm)
        rows.append(
            {
                "index": i,
                "dest_name": dest_name,
                "inbox_path": dest,
                "youtube": meta["youtube"],
                "tiktok": meta["tiktok"],
                "duration_sec": dur,
                "size_mb": size_mb,
            }
        )

    batch_path = inbox / "batch.yaml"
    _write_batch_yaml(batch_path)
    batch = load_batch_yaml(batch_path)
    _write_manifest(inbox, rows, batch)
    clips_manifest: dict[str, Any] = {"clips": {}}
    for row in rows:
        fn = row["dest_name"]
        clips_manifest["clips"][fn] = {
            "youtube": row["youtube"],
            "tiktok": row["tiktok"],
        }
    save_metadata_manifest(inbox / "clips_metadata.json", clips_manifest)

    settings = YouTubeSettings.from_env()
    settings.inbox = inbox
    yt_db = ScheduleDB(args.db or default_db_path())

    tz_name = "America/Sao_Paulo"
    start = date.fromisoformat(args.start_date) if args.start_date else None
    if start is None:
        from youtube.timezone_util import now_in_tz

        start = now_in_tz(tz_name).date()

    clips = [inbox / r["dest_name"] for r in rows]
    planned = plan_uploads(
        clips,
        batch,
        yt_db,
        source_stem=SOURCE_STEM,
        slots=LONG_SLOTS,
        tz_name=tz_name,
        start_date=start,
        game=GAME,
        persist=not args.dry_run,
        use_llm=use_llm,
        metadata_manifest=inbox / "clips_metadata.json",
    )
    print_schedule_plan(planned, tz_name=tz_name)

    tt_db_path = args.tiktok_db or (Path.home() / ".secrets" / "tiktok_schedule.db")
    tt_inserted = _register_tiktok_pending(
        pending_tt,
        rows,
        tt_db_path,
        slots=(19,),
        tz_name=tz_name,
        start_date=start,
        dry_run=args.dry_run,
    )
    LOGGER.info("TikTok rows inserted: %s | pending dir: %s", tt_inserted, pending_tt)

    if args.schedule_only or args.dry_run:
        LOGGER.info("Schedule-only/dry-run — skipping YouTube upload.")
        return 0

    entries = load_manifest_csv(inbox / "manifest.csv", inbox, batch)
    youtube = get_youtube_service(settings.client_secrets, settings.token_path)
    uploader = YouTubeUploader(youtube, batch=batch)
    ok, failed, skipped, quota = execute_planned_uploads(
        planned,
        uploader,
        yt_db,
        dry_run=False,
        limit=args.upload_limit,
    )
    LOGGER.info(
        "YouTube upload: ok=%s failed=%s skipped=%s quota_hit=%s",
        ok,
        failed,
        skipped,
        quota,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
