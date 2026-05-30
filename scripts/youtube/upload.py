# -*- coding: utf-8 -*-
"""
YouTube Shorts batch upload — CLI entry point.

Examples:
  python scripts/youtube/upload.py video.mp4 --title "..." --description "..."
  python scripts/youtube/upload.py --manifest clips.csv --batch batch.yaml
  python scripts/youtube/upload.py --inbox
  python scripts/youtube/upload.py --inbox --watch
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from .auth import get_youtube_service
from .config import BatchConfig, YouTubeSettings, load_env_file
from .stdio import configure_stdio_utf8
from .manifest import ClipEntry, inbox_mp4_entries, load_batch_yaml, load_manifest_csv
from .uploader import YouTubeUploader

LOGGER = logging.getLogger(__name__)


def setup_logging(log_file: Optional[Path] = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def move_to_uploaded(video: Path, uploaded_dir: Path, *, dry_run: bool) -> Path:
    uploaded_dir.mkdir(parents=True, exist_ok=True)
    dest = uploaded_dir / video.name
    if dry_run:
        LOGGER.info("[DRY-RUN] Would move %s -> %s", video, dest)
        return dest
    if dest.exists():
        stem, suffix = video.stem, video.suffix
        n = 1
        while dest.exists():
            dest = uploaded_dir / f"{stem}_{n}{suffix}"
            n += 1
    shutil.move(str(video), str(dest))
    sc_src = video.with_suffix(video.suffix + ".uploaded.json")
    if sc_src.is_file():
        shutil.move(str(sc_src), str(dest.with_suffix(dest.suffix + ".uploaded.json")))
    LOGGER.info("Moved to %s", dest)
    return dest


def run_batch(
    entries: List[ClipEntry],
    settings: YouTubeSettings,
    batch: BatchConfig,
    *,
    dry_run: bool,
    skip_uploaded: bool,
) -> int:
    log_file = settings.uploaded_dir / "upload.log" if settings.log_to_uploaded_dir else None
    setup_logging(log_file)

    failures = 0
    if dry_run:
        stub = YouTubeUploader(youtube=object(), batch=batch)
        for entry in entries:
            try:
                stub.upload_video(entry, dry_run=True, skip_if_uploaded=skip_uploaded)
            except Exception:
                LOGGER.exception("Dry-run error for %s", entry.file_path)
                failures += 1
        return 1 if failures else 0

    youtube = get_youtube_service(settings.client_secrets, settings.token_path)
    uploader = YouTubeUploader(youtube, batch=batch)

    for entry in entries:
        try:
            vid = uploader.upload_video(entry, dry_run=False, skip_if_uploaded=skip_uploaded)
            if vid and vid != "dry-run":
                move_to_uploaded(entry.file_path, settings.uploaded_dir, dry_run=False)
        except Exception:
            LOGGER.exception("Upload failed - leaving in place: %s", entry.file_path)
            failures += 1

    LOGGER.info("Batch done: %s ok, %s failed", len(entries) - failures, failures)
    return 1 if failures else 0


def single_upload(
    video: Path,
    title: str,
    description: str,
    settings: YouTubeSettings,
    batch: Optional[BatchConfig],
    *,
    dry_run: bool,
    thumb: Optional[Path],
) -> int:
    settings.uploaded_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(settings.uploaded_dir / "upload.log" if settings.log_to_uploaded_dir else None)

    b = batch or BatchConfig()
    desc = b.build_description(description) if batch else description
    entry = ClipEntry(
        file_path=video.resolve(),
        title=title,
        description=desc,
        thumb_path=thumb or (b.default_thumb if batch else None),
    )
    return run_batch([entry], settings, b, dry_run=dry_run, skip_uploaded=True)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Upload videos to YouTube (Shorts-friendly) via Data API v3.",
    )
    p.add_argument("video", nargs="?", type=Path, help="Single video file path")
    p.add_argument("--title", help="Title (single upload)")
    p.add_argument("--description", default="", help="Description (single upload)")
    p.add_argument("--thumb", type=Path, help="Thumbnail image (JPEG/PNG)")
    p.add_argument("--manifest", type=Path, help="CSV manifest (file_path, title, description)")
    p.add_argument("--batch", type=Path, help="YAML shared config (hashtags, tags, privacy, ...)")
    p.add_argument(
        "--inbox",
        action="store_true",
        help="Process inbox (manifest.csv inside inbox if present)",
    )
    p.add_argument(
        "--watch",
        action="store_true",
        help="Watch inbox for new files / manifest changes (use with --inbox)",
    )
    p.add_argument("--dry-run", action="store_true", help="Log actions without uploading")
    p.add_argument(
        "--no-skip-uploaded",
        action="store_true",
        help="Re-upload even if .uploaded.json sidecar exists",
    )
    p.add_argument(
        "--auth-only",
        action="store_true",
        help="Run OAuth flow and exit (first-time setup)",
    )

    # --- Pipeline (split + schedule) ---
    p.add_argument(
        "--pipeline",
        action="store_true",
        help="Split long video, plan slots, schedule uploads (see --split-input)",
    )
    p.add_argument("--split-input", type=Path, help="Source MP4 for --pipeline")
    p.add_argument("--output-dir", type=Path, help="Clip output folder for --pipeline")
    p.add_argument("--target-clips", type=int, default=50)
    p.add_argument("--segment-sec", type=int)
    p.add_argument("--force-split", action="store_true")
    p.add_argument("--slots", default="16,18,21")
    p.add_argument("--per-day", type=int, default=3)
    p.add_argument("--timezone", default="America/Sao_Paulo")
    p.add_argument("--start-date", help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, help="SQLite schedule DB")
    p.add_argument("--game", default="Granny 2")
    p.add_argument("--upload-limit", type=int)
    p.add_argument("--upload-all", action="store_true")
    p.add_argument("--schedule-only", action="store_true")
    p.add_argument(
        "--audit-schedule",
        action="store_true",
        help="Audit channel: fix metadata + schedule private Shorts (see audit_and_schedule.py)",
    )
    p.add_argument("--audit-all-videos", action="store_true", help="With --audit-schedule: all videos")
    p.add_argument("--audit-limit", type=int, help="With --audit-schedule: max videos to process")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    configure_stdio_utf8()
    load_env_file()
    settings = YouTubeSettings.from_env()
    args = parse_args(argv)

    if args.auth_only:
        setup_logging()
        get_youtube_service(settings.client_secrets, settings.token_path)
        LOGGER.info(
            "OAuth OK - token file: %s | api-keys: google_oauth_youtube (if configured)",
            settings.token_path,
        )
        return 0

    if args.audit_schedule:
        from .audit_and_schedule import main as audit_main

        audit_argv: list[str] = []
        if args.dry_run:
            audit_argv.append("--dry-run")
        if args.db:
            audit_argv.extend(["--db", str(args.db)])
        if args.batch:
            audit_argv.extend(["--batch", str(args.batch)])
        if args.game != "Granny 2":
            audit_argv.extend(["--game", args.game])
        if args.audit_all_videos:
            audit_argv.append("--all-videos")
        if args.audit_limit is not None:
            audit_argv.extend(["--limit", str(args.audit_limit)])
        return audit_main(audit_argv)

    if args.pipeline or args.resume:
        from .pipeline import run_pipeline

        pipeline_argv: list[str] = []
        if args.pipeline:
            pipeline_argv.append("--pipeline")
        if args.resume:
            pipeline_argv.append("--resume")
        if args.split_input:
            pipeline_argv.extend(["--split-input", str(args.split_input)])
        if args.output_dir:
            pipeline_argv.extend(["--output-dir", str(args.output_dir)])
        if args.target_clips != 50:
            pipeline_argv.extend(["--target-clips", str(args.target_clips)])
        if args.segment_sec:
            pipeline_argv.extend(["--segment-sec", str(args.segment_sec)])
        if args.force_split:
            pipeline_argv.append("--force-split")
        if args.slots != "16,18,21":
            pipeline_argv.extend(["--slots", args.slots])
        if args.per_day != 3:
            pipeline_argv.extend(["--per-day", str(args.per_day)])
        if args.timezone != "America/Sao_Paulo":
            pipeline_argv.extend(["--timezone", args.timezone])
        if args.start_date:
            pipeline_argv.extend(["--start-date", args.start_date])
        if args.db:
            pipeline_argv.extend(["--db", str(args.db)])
        if args.batch:
            pipeline_argv.extend(["--batch", str(args.batch)])
        if args.game != "Granny 2":
            pipeline_argv.extend(["--game", args.game])
        if args.dry_run:
            pipeline_argv.append("--dry-run")
        if args.upload_limit is not None:
            pipeline_argv.extend(["--upload-limit", str(args.upload_limit)])
        if args.upload_all:
            pipeline_argv.append("--upload-all")
        if args.schedule_only:
            pipeline_argv.append("--schedule-only")
        if args.pipeline and not args.split_input and not args.resume:
            LOGGER.error("--pipeline requires --split-input")
            return 2
        return run_pipeline(pipeline_argv)

    batch: Optional[BatchConfig] = None
    if args.batch:
        batch = load_batch_yaml(args.batch.resolve())
    elif args.inbox:
        default_batch = settings.inbox / "batch.yaml"
        if default_batch.is_file():
            batch = load_batch_yaml(default_batch)

    skip_uploaded = not args.no_skip_uploaded

    if args.watch:
        if not args.inbox:
            LOGGER.error("--watch requires --inbox")
            return 2
        from .watcher import watch_inbox

        return watch_inbox(
            settings,
            batch,
            manifest_path=settings.inbox / "manifest.csv",
            batch_path=args.batch,
            dry_run=args.dry_run,
            skip_uploaded=skip_uploaded,
        )

    if args.inbox:
        settings.inbox.mkdir(parents=True, exist_ok=True)
        manifest_path = settings.inbox / "manifest.csv"
        if manifest_path.is_file():
            entries = load_manifest_csv(manifest_path, settings.inbox, batch)
        elif batch:
            entries = inbox_mp4_entries(settings.inbox, batch)
            LOGGER.info("No manifest.csv - using filename as title for %s file(s)", len(entries))
        else:
            LOGGER.error(
                "Inbox mode needs inbox/manifest.csv or inbox/batch.yaml (or --batch)"
            )
            return 2
        if not entries:
            LOGGER.warning("No videos to process in %s", settings.inbox)
            return 0
        b = batch or BatchConfig()
        return run_batch(entries, settings, b, dry_run=args.dry_run, skip_uploaded=skip_uploaded)

    if args.manifest:
        if not args.batch:
            LOGGER.error("--manifest requires --batch for shared hashtags/settings")
            return 2
        batch = load_batch_yaml(args.batch.resolve())
        inbox = settings.inbox
        entries = load_manifest_csv(args.manifest.resolve(), inbox, batch)
        if not entries:
            LOGGER.warning("Manifest produced zero valid entries")
            return 1
        return run_batch(entries, settings, batch, dry_run=args.dry_run, skip_uploaded=skip_uploaded)

    if args.video:
        if not args.title:
            LOGGER.error("Single upload requires --title")
            return 2
        if not args.video.is_file():
            LOGGER.error("Video not found: %s", args.video)
            return 1
        return single_upload(
            args.video,
            args.title,
            args.description,
            settings,
            batch,
            dry_run=args.dry_run,
            thumb=args.thumb,
        )

    parse_args(["--help"])
    return 2


if __name__ == "__main__":
    sys.exit(main())
