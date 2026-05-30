# -*- coding: utf-8 -*-
"""Plan and execute YouTube scheduled uploads with SQLite slot tracking."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence
from .timezone_util import get_timezone, local_to_utc, now_in_tz

from googleapiclient.errors import HttpError

from .config import BatchConfig
from .manifest import ClipEntry
from .schedule_db import ScheduleDB, ScheduledRow
from .uploader import YouTubeUploader
from shared.llm_metadata import (
    build_youtube_description,
    load_metadata_manifest,
    manifest_path_for_dir,
    resolve_clip_metadata,
)
from .video_splitter import extract_clip_part, generate_clip_description, generate_clip_title

LOGGER = logging.getLogger(__name__)

MAX_RETRIES = 3
# Shorts policy: exactly 3 publish slots per day (16h, 18h, 21h SP).
# next_available_slots() never assigns two clips to the same (slot_date, slot_hour).
DEFAULT_SHORTS_SLOTS = (16, 18, 21)
LONG_FORM_SLOT_HOUR = 19  # separate from Shorts; max 1 long/day at this hour (SP)
MAX_SHORTS_PER_DAY = 3
QUOTA_ERROR_MARKERS = ("quotaexceeded", "uploadlimitexceeded", "dailylimitexceeded")


def _is_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if any(marker in text for marker in QUOTA_ERROR_MARKERS):
        return True
    if isinstance(exc, HttpError):
        try:
            payload = json.loads(exc.content.decode("utf-8"))
            errors = payload.get("error", {}).get("errors", [])
            for err in errors:
                reason = str(err.get("reason", "")).lower()
                if any(marker in reason for marker in QUOTA_ERROR_MARKERS):
                    return True
        except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    return False


def infer_source_stem(db: ScheduleDB, fallback: str = "Granny 2 Parte 2") -> str:
    rows = db.list_by_status(["scheduled", "pending", "uploading", "failed", "uploaded"])
    if not rows:
        return fallback
    clip_dir = Path(rows[0].file_path).parent
    manifest = clip_dir / "split_manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            source = data.get("source")
            if source:
                return Path(str(source)).stem
        except (json.JSONDecodeError, OSError):
            pass
    return clip_dir.name.replace("_", " ")[:80] or fallback


def refresh_pending_metadata(
    db: ScheduleDB,
    batch: BatchConfig,
    *,
    source_stem: str,
    game: str = "Granny 2",
    use_llm: Optional[bool] = None,
    metadata_manifest: Optional[Path] = None,
) -> int:
    """Regenerate titles for pending/failed rows. Returns count updated."""
    manifest = (
        load_metadata_manifest(metadata_manifest)
        if metadata_manifest and metadata_manifest.is_file()
        else None
    )
    updated = 0
    for row in db.list_by_status(["pending", "failed"]):
        clip_path = Path(row.file_path)
        part = extract_clip_part(row.title, clip_path)
        meta = resolve_clip_metadata(
            part,
            part,
            game=game,
            platform="youtube",
            clip_path=clip_path,
            source_stem=source_stem,
            use_llm=use_llm,
            manifest=manifest,
            manifest_path=metadata_manifest,
        )
        title = meta["title"]
        if title != row.title:
            db.update_title(row.id, title)
            updated += 1
    return updated


@dataclass
class PlannedUpload:
    file_path: Path
    title: str
    description: str
    scheduled_at_utc: datetime
    slot_date: str
    slot_hour: int
    db_id: Optional[int] = None
    tags: Optional[List[str]] = None


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def next_available_slots(
    count: int,
    *,
    slots: Sequence[int],
    tz_name: str,
    start_date: date,
    db: ScheduleDB,
    min_lead_minutes: int = 20,
) -> list[tuple[datetime, str, int]]:
    """Return UTC datetimes for the next `count` free slots.

    At most one clip per (slot_date, hour). With default slots (16,18,21) this
    caps Shorts at MAX_SHORTS_PER_DAY per calendar day.
    """
    if len(slots) > MAX_SHORTS_PER_DAY:
        LOGGER.warning(
            "%s slot hour(s) configured (> %s Shorts/day policy): %s",
            len(slots),
            MAX_SHORTS_PER_DAY,
            slots,
        )
    tz = get_timezone(tz_name)
    now_utc = datetime.now(timezone.utc)
    min_publish = now_utc + timedelta(minutes=min_lead_minutes)

    results: list[tuple[datetime, str, int]] = []
    day = start_date
    safety = 0

    while len(results) < count and safety < 3650:
        safety += 1
        for hour in sorted(slots):
            local_dt = datetime(day.year, day.month, day.day, hour, 0, 0)
            utc_dt = local_to_utc(local_dt, tz)
            if utc_dt <= min_publish:
                continue
            slot_date = day.isoformat()
            if db.is_slot_taken(slot_date, hour):
                continue
            results.append((utc_dt, slot_date, hour))
            if len(results) >= count:
                break
        day = day + timedelta(days=1)

    if len(results) < count:
        raise RuntimeError(
            f"Could only allocate {len(results)} of {count} slots (check DB occupancy)."
        )
    return results


def _clip_metadata(
    idx: int,
    clip_path: Path,
    *,
    game: str,
    source_stem: str,
    batch: BatchConfig,
    use_llm: Optional[bool],
    manifest: Optional[dict],
    metadata_manifest: Optional[Path],
) -> tuple[str, str, Optional[List[str]]]:
    part = idx
    meta = resolve_clip_metadata(
        idx,
        part,
        game=game,
        platform="youtube",
        clip_path=clip_path,
        source_stem=source_stem,
        use_llm=use_llm,
        manifest=manifest,
        manifest_path=metadata_manifest,
    )
    hashtags = meta.get("hashtags") or batch.hashtags
    if batch.hashtags.strip() and batch.hashtags not in str(hashtags):
        hashtags = f"{meta.get('hashtags', '').strip()}\n{batch.hashtags.strip()}".strip()
    description = build_youtube_description(
        meta["description"],
        hashtags,
        append_shorts=batch.append_shorts_hashtag,
    )
    tags = meta.get("tags") or None
    return meta["title"], description, tags


def plan_uploads(
    clips: Sequence[Path],
    batch: BatchConfig,
    db: ScheduleDB,
    *,
    source_stem: str,
    slots: Sequence[int] = DEFAULT_SHORTS_SLOTS,
    tz_name: str = "America/Sao_Paulo",
    start_date: Optional[date] = None,
    game: str = "Granny 2",
    persist: bool = True,
    use_llm: Optional[bool] = None,
    metadata_manifest: Optional[Path] = None,
) -> list[PlannedUpload]:
    tz = get_timezone(tz_name)
    start = start_date or now_in_tz(tz_name).date()

    if metadata_manifest is None and clips:
        default_manifest = manifest_path_for_dir(Path(clips[0]).parent)
        if default_manifest.is_file():
            metadata_manifest = default_manifest

    manifest = (
        load_metadata_manifest(metadata_manifest)
        if metadata_manifest and metadata_manifest.is_file()
        else None
    )

    planned: list[PlannedUpload] = []
    to_schedule: list[tuple[int, Path]] = []

    for idx, clip_path in enumerate(clips, start=1):
        existing = db.get_by_file(clip_path)
        if existing and existing.status in ("scheduled", "uploaded", "pending", "uploading"):
            LOGGER.info(
                "Skip planning (already in DB): %s status=%s",
                clip_path.name,
                existing.status,
            )
            title, description, tags = _clip_metadata(
                idx,
                clip_path,
                game=game,
                source_stem=source_stem,
                batch=batch,
                use_llm=use_llm,
                manifest=manifest,
                metadata_manifest=metadata_manifest,
            )
            planned.append(
                PlannedUpload(
                    file_path=clip_path,
                    title=existing.title,
                    description=description,
                    scheduled_at_utc=existing.scheduled_at_utc,
                    slot_date=existing.slot_date,
                    slot_hour=existing.slot_hour,
                    db_id=existing.id,
                    tags=tags,
                )
            )
        else:
            to_schedule.append((idx, clip_path))

    if to_schedule:
        free_slots = next_available_slots(
            len(to_schedule),
            slots=slots,
            tz_name=tz_name,
            start_date=start,
            db=db,
        )
        for (idx, clip_path), (utc_dt, slot_date, hour) in zip(to_schedule, free_slots):
            title, description, tags = _clip_metadata(
                idx,
                clip_path,
                game=game,
                source_stem=source_stem,
                batch=batch,
                use_llm=use_llm,
                manifest=manifest,
                metadata_manifest=metadata_manifest,
            )

            db_id = None
            if persist:
                db_id = db.insert_pending(clip_path, title, utc_dt, slot_date, hour)

            planned.append(
                PlannedUpload(
                    file_path=clip_path,
                    title=title,
                    description=description,
                    scheduled_at_utc=utc_dt,
                    slot_date=slot_date,
                    slot_hour=hour,
                    db_id=db_id,
                    tags=tags,
                )
            )

    planned.sort(key=lambda p: p.scheduled_at_utc)
    return planned


def utc_to_local(utc_dt: datetime, tz: Any) -> datetime:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(tz)


def print_schedule_plan(planned: Sequence[PlannedUpload], tz_name: str = "America/Sao_Paulo") -> None:
    tz = get_timezone(tz_name)
    LOGGER.info("=== SCHEDULE PLAN (%s clips) ===", len(planned))
    for i, item in enumerate(planned, 1):
        local = utc_to_local(item.scheduled_at_utc, tz)
        LOGGER.info(
            "%3d | %s %02d:00 %s | %s | %s",
            i,
            item.slot_date,
            item.slot_hour,
            tz_name,
            item.title[:60],
            item.file_path.name,
        )
        LOGGER.info("     publish UTC: %s | local: %s", item.scheduled_at_utc.isoformat(), local.isoformat())


def execute_planned_uploads(
    planned: Sequence[PlannedUpload],
    uploader: YouTubeUploader,
    db: ScheduleDB,
    *,
    dry_run: bool = False,
    limit: Optional[int] = None,
    manifest_by_path: Optional[dict[Path, ClipEntry]] = None,
) -> tuple[int, int, int, bool]:
    """Upload with publishAt. Returns (ok, failed, skipped, quota_exhausted)."""
    ok = failed = skipped = 0
    quota_exhausted = False
    items = list(planned)
    if limit is not None:
        items = items[:limit]

    for item in items:
        if quota_exhausted:
            break
        row = db.get_by_file(item.file_path) if item.db_id else None
        if row and row.status == "scheduled" and row.video_id:
            LOGGER.info("Skip (already scheduled): %s -> %s", item.file_path.name, row.video_id)
            skipped += 1
            continue

        entry = ClipEntry(
            file_path=item.file_path,
            title=item.title,
            description=item.description,
            tags=item.tags,
        )
        if manifest_by_path:
            manifest_entry = manifest_by_path.get(item.file_path.resolve())
            if manifest_entry:
                if manifest_entry.thumb_path:
                    entry.thumb_path = manifest_entry.thumb_path
                if manifest_entry.tags:
                    entry.tags = manifest_entry.tags

        if dry_run:
            uploader.upload_video(
                entry,
                dry_run=True,
                skip_if_uploaded=True,
                publish_at=item.scheduled_at_utc,
            )
            LOGGER.info(
                "[DRY-RUN] Would schedule %s at %s",
                item.file_path.name,
                item.scheduled_at_utc.isoformat(),
            )
            ok += 1
            continue

        row_id = item.db_id
        if row_id is None and row:
            row_id = row.id
        if row_id is None:
            row_id = db.insert_pending(
                item.file_path,
                item.title,
                item.scheduled_at_utc,
                item.slot_date,
                item.slot_hour,
            )

        db.mark_uploading(row_id)
        attempts = 0
        while attempts < MAX_RETRIES:
            attempts += 1
            try:
                video_id = uploader.upload_video(
                    entry,
                    dry_run=False,
                    skip_if_uploaded=True,
                    publish_at=item.scheduled_at_utc,
                )
                if video_id and video_id not in ("dry-run",):
                    db.mark_scheduled(row_id, video_id)
                    ok += 1
                    break
            except Exception as exc:
                LOGGER.exception(
                    "Upload attempt %s/%s failed for %s",
                    attempts,
                    MAX_RETRIES,
                    item.file_path.name,
                )
                if _is_quota_error(exc):
                    db.reset_for_retry(row_id)
                    quota_exhausted = True
                    LOGGER.warning(
                        "YouTube quota/limit reached — stopping batch (ok=%s so far).",
                        ok,
                    )
                    break
                if attempts >= MAX_RETRIES:
                    db.mark_failed(row_id, str(exc))
                    failed += 1
                else:
                    db.reset_for_retry(row_id)
                    db.mark_uploading(row_id)

    return ok, failed, skipped, quota_exhausted


def resume_pending(
    db: ScheduleDB,
    uploader: YouTubeUploader,
    batch: BatchConfig,
    *,
    source_stem: Optional[str] = None,
    game: str = "Granny 2",
    limit: Optional[int] = None,
    use_llm: Optional[bool] = None,
    metadata_manifest: Optional[Path] = None,
    manifest_by_path: Optional[dict[Path, ClipEntry]] = None,
) -> tuple[int, int, int, bool]:
    stem = source_stem or infer_source_stem(db)
    rows = db.list_by_status(["pending", "failed"])
    if metadata_manifest is None and rows:
        default_manifest = manifest_path_for_dir(Path(rows[0].file_path).parent)
        if default_manifest.is_file():
            metadata_manifest = default_manifest
    manifest = (
        load_metadata_manifest(metadata_manifest)
        if metadata_manifest and metadata_manifest.is_file()
        else None
    )
    planned: list[PlannedUpload] = []
    for row in rows:
        if row.retry_count >= MAX_RETRIES and row.status == "failed":
            continue
        clip_path = Path(row.file_path)
        part = extract_clip_part(row.title, clip_path)
        title = row.title
        _, description, tags = _clip_metadata(
            part,
            clip_path,
            game=game,
            source_stem=stem,
            batch=batch,
            use_llm=use_llm,
            manifest=manifest,
            metadata_manifest=metadata_manifest,
        )
        planned.append(
            PlannedUpload(
                file_path=clip_path,
                title=title,
                description=description,
                scheduled_at_utc=row.scheduled_at_utc,
                slot_date=row.slot_date,
                slot_hour=row.slot_hour,
                db_id=row.id,
                tags=tags,
            )
        )
    return execute_planned_uploads(
        planned,
        uploader,
        db,
        dry_run=False,
        limit=limit,
        manifest_by_path=manifest_by_path,
    )
