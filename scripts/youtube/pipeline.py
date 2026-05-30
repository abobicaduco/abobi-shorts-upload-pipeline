# -*- coding: utf-8 -*-
"""End-to-end pipeline: split video -> plan schedule -> upload to YouTube."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional
from .timezone_util import get_timezone, now_in_tz

from .auth import get_youtube_service
from .config import BatchConfig, YouTubeSettings, load_env_file
from .manifest import load_batch_yaml
from .schedule_db import ScheduleDB, default_db_path
from .scheduler import execute_planned_uploads, plan_uploads, print_schedule_plan
from .stdio import configure_stdio_utf8
from .upload import setup_logging
from .uploader import YouTubeUploader
from .video_splitter import split_video

LOGGER = logging.getLogger(__name__)

DEFAULT_SLOTS = (16, 18, 21)
DEFAULT_BATCH = {
    "hashtags": "#abobicaduco #granny2 #granny #gameplay #horror #shorts #terror #susto",
    "tags": [
        "granny 2",
        "granny",
        "granny horror",
        "horror",
        "gameplay",
        "abobicaduco",
        "shorts",
        "terror",
        "survival",
        "susto",
        "jogo de terror",
        "horror game",
    ],
    "privacy": "private",
    "category_id": "20",
    "append_shorts_hashtag": True,
}


def _parse_slots(raw: str) -> tuple[int, ...]:
    parts = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not parts:
        raise ValueError("At least one slot hour required")
    return tuple(sorted(set(parts)))


def _default_output_dir(input_path: Path) -> Path:
    stem = input_path.stem.replace(" ", "_")[:60]
    return Path.home() / "YOUTUBE" / "clips" / stem


def run_pipeline(argv: Optional[List[str]] = None) -> int:
    configure_stdio_utf8()
    load_env_file()

    p = argparse.ArgumentParser(
        description="Split long video into Shorts clips and schedule YouTube uploads.",
    )
    p.add_argument("--split-input", type=Path, help="Source MP4 to split (not needed with --resume)")
    p.add_argument(
        "--output-dir",
        type=Path,
        help="Folder for clips (default: ~/YOUTUBE/clips/<stem>)",
    )
    p.add_argument("--target-clips", type=int, default=50, help="Approximate clip count")
    p.add_argument("--segment-sec", type=int, help="Override segment duration (seconds)")
    p.add_argument("--force-split", action="store_true", help="Re-split even if clips exist")
    p.add_argument("--slots", default="16,18,21", help="Local publish hours (comma-separated)")
    p.add_argument("--per-day", type=int, default=3, help="Max uploads per day (info; uses --slots)")
    p.add_argument("--timezone", default="America/Sao_Paulo", help="IANA timezone for slots")
    p.add_argument("--start-date", help="First schedule date YYYY-MM-DD (default: today in tz)")
    p.add_argument("--db", type=Path, help="SQLite schedule DB path")
    p.add_argument("--batch", type=Path, help="batch.yaml for hashtags/tags")
    p.add_argument("--game", default="Granny 2", help="Game name for titles/descriptions")
    p.add_argument("--dry-run", action="store_true", help="Plan only; no upload")
    p.add_argument(
        "--upload-limit",
        type=int,
        help="Max clips to upload this run (default: all planned, or 3 without --upload-all)",
    )
    p.add_argument(
        "--upload-all",
        action="store_true",
        help="Upload/schedule all clips in this run (may hit quota)",
    )
    p.add_argument(
        "--schedule-only",
        action="store_true",
        help="Skip split if clips exist; only plan/schedule",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="Retry pending/failed rows from DB only (no split)",
    )
    p.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Regenerate titles/descriptions for pending rows before upload",
    )
    p.add_argument(
        "--source-stem",
        help="Series name for descriptions (default: infer from split_manifest.json)",
    )
    p.add_argument(
        "--until-done",
        action="store_true",
        help="Repeat resume batches until pending=0 or quota exhausted",
    )
    p.add_argument(
        "--use-llm",
        action="store_true",
        help="Force local Ollama (Llama) for clip metadata",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="Use template metadata only (skip Ollama)",
    )
    p.add_argument(
        "--metadata-manifest",
        type=Path,
        help="Path to clips_metadata.json (default: auto in clips folder)",
    )
    p.add_argument(
        "--pre-generate-metadata",
        action="store_true",
        help="Generate clips_metadata.json for all clips and exit",
    )

    args = p.parse_args(argv)
    setup_logging()

    use_llm: Optional[bool] = None
    if args.no_llm:
        use_llm = False
    elif args.use_llm:
        use_llm = True

    if args.pre_generate_metadata:
        from shared.llm_metadata import is_ollama_available, pregenerate_manifest, resolve_ollama_model

        clips_dir = args.output_dir
        if not clips_dir and args.split_input:
            clips_dir = _default_output_dir(args.split_input.resolve())
        if not clips_dir:
            p.error("--pre-generate-metadata requires --output-dir or --split-input")
        clips_dir = clips_dir.resolve()
        if not clips_dir.is_dir():
            LOGGER.error("Clips dir not found: %s", clips_dir)
            return 1
        available = is_ollama_available(force_check=True)
        LOGGER.info(
            "Ollama: %s | model=%s",
            "online" if available else "offline",
            resolve_ollama_model() if available else "template",
        )
        pregenerate_manifest(
            clips_dir,
            game=args.game,
            source_stem=args.source_stem or "Granny 2 Parte 2",
            use_llm=use_llm if use_llm is not False else False,
        )
        return 0

    if not args.resume and not args.split_input:
        p.error("--split-input is required unless using --resume")

    settings = YouTubeSettings.from_env()
    db_path = args.db or default_db_path()
    db = ScheduleDB(db_path)
    slots = _parse_slots(args.slots)

    if args.per_day != len(slots):
        LOGGER.warning(
            "--per-day=%s but %s slot hour(s) configured: %s",
            args.per_day,
            len(slots),
            slots,
        )

    if args.batch and args.batch.is_file():
        batch = load_batch_yaml(args.batch.resolve())
    else:
        batch = BatchConfig(**DEFAULT_BATCH)

    if args.resume:
        from .scheduler import infer_source_stem, refresh_pending_metadata, resume_pending

        source_stem = args.source_stem or infer_source_stem(db)
        if args.refresh_metadata:
            n = refresh_pending_metadata(
                db,
                batch,
                source_stem=source_stem,
                game=args.game,
                use_llm=use_llm,
                metadata_manifest=args.metadata_manifest,
            )
            LOGGER.info("Refreshed metadata for %s pending/failed row(s)", n)

        youtube = get_youtube_service(settings.client_secrets, settings.token_path)
        uploader = YouTubeUploader(youtube, batch=batch)

        total_ok = total_failed = total_skipped = 0
        batch_num = 0
        quota_exhausted = False

        while True:
            batch_num += 1
            summary_before = db.count_summary()
            pending_before = summary_before.get("pending", 0) + summary_before.get("failed", 0)
            if pending_before == 0:
                LOGGER.info("Nothing pending — all clips scheduled.")
                break

            ok, failed, skipped, quota_exhausted = resume_pending(
                db,
                uploader,
                batch,
                source_stem=source_stem,
                game=args.game,
                limit=args.upload_limit,
                use_llm=use_llm,
                metadata_manifest=args.metadata_manifest,
            )
            total_ok += ok
            total_failed += failed
            total_skipped += skipped
            summary = db.count_summary()
            LOGGER.info(
                "Batch %s: ok=%s failed=%s skipped=%s | DB: %s",
                batch_num,
                ok,
                failed,
                skipped,
                summary,
            )

            pending_after = summary.get("pending", 0) + summary.get("failed", 0)
            if pending_after == 0 or quota_exhausted:
                break
            if not args.until_done:
                break
            if ok == 0 and failed == 0:
                break

        LOGGER.info(
            "Resume session: ok=%s failed=%s skipped=%s | DB: %s",
            total_ok,
            total_failed,
            total_skipped,
            db.count_summary(),
        )
        return 1 if total_failed else 0

    input_path = args.split_input.resolve()
    if not input_path.is_file():
        LOGGER.error("Input not found: %s", input_path)
        return 1

    output_dir = (args.output_dir or _default_output_dir(input_path)).resolve()

    clips: list[Path] = []
    if args.schedule_only:
        clips = sorted(output_dir.glob("clip_*.mp4"))
        if not clips:
            LOGGER.error("No clips in %s (remove --schedule-only to split)", output_dir)
            return 1
    else:
        try:
            clips = split_video(
                input_path,
                output_dir,
                target_clips=args.target_clips,
                segment_sec=args.segment_sec,
                force=args.force_split,
            )
        except FileNotFoundError as exc:
            LOGGER.error("%s", exc)
            return 1
        except RuntimeError as exc:
            LOGGER.error("Split failed: %s", exc)
            return 1

    LOGGER.info("Clips ready: %s in %s", len(clips), output_dir)

    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
    else:
        start_date = now_in_tz(args.timezone).date()

    planned = plan_uploads(
        clips,
        batch,
        db,
        source_stem=input_path.stem,
        slots=slots,
        tz_name=args.timezone,
        start_date=start_date,
        game=args.game,
        persist=True,
        use_llm=use_llm,
        metadata_manifest=args.metadata_manifest,
    )
    print_schedule_plan(planned, tz_name=args.timezone)

    upload_limit = args.upload_limit
    if upload_limit is None and not args.upload_all:
        upload_limit = min(3, len(planned))

    if args.dry_run:
        stub = YouTubeUploader(youtube=object(), batch=batch)
        ok, failed, skipped, _ = execute_planned_uploads(
            planned, stub, db, dry_run=True, limit=upload_limit
        )
        summary = db.count_summary()
        LOGGER.info("Dry-run complete. DB summary: %s", summary)
        return 0

    youtube = get_youtube_service(settings.client_secrets, settings.token_path)
    uploader = YouTubeUploader(youtube, batch=batch)
    ok, failed, skipped, _ = execute_planned_uploads(
        planned, uploader, db, dry_run=False, limit=upload_limit
    )
    summary = db.count_summary()
    LOGGER.info(
        "Pipeline upload pass: ok=%s failed=%s skipped=%s | DB: %s | db_path=%s",
        ok,
        failed,
        skipped,
        summary,
        db_path,
    )
    if failed:
        LOGGER.info("Retry later: python scripts/youtube-upload.py --pipeline --resume --db %s", db_path)
    remaining = summary.get("pending", 0) + summary.get("failed", 0)
    if remaining:
        LOGGER.warning(
            "%s clip(s) still pending/failed — YouTube daily quota may apply (~6 uploads/day default).",
            remaining,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_pipeline())
