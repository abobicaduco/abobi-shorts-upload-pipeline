# -*- coding: utf-8 -*-
"""Plan and execute TikTok uploads with SQLite slot tracking."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

from youtube.timezone_util import get_timezone, local_to_utc, now_in_tz

from .config import BatchConfig, DEFAULT_SLOTS, MAX_TIKTOK_PER_DAY
from .metadata import build_caption_for_clip, extract_part_from_clip, refresh_caption
from .schedule_db import ScheduleDB, ScheduledRow
from .uploader_playwright import SCHEDULE_ONLY, upload_video_playwright
from .config import TikTokSettings

LOGGER = logging.getLogger(__name__)

MAX_RETRIES = 3


@dataclass
class PlannedUpload:
    file_path: Path
    caption: str
    scheduled_at_utc: datetime
    slot_date: str
    slot_hour: int
    db_id: Optional[int] = None


def next_available_slots(
    count: int,
    *,
    slots: Sequence[int],
    tz_name: str,
    start_date: date,
    db: ScheduleDB,
    min_lead_minutes: int = 30,
) -> list[tuple[datetime, str, int]]:
    if len(slots) > MAX_TIKTOK_PER_DAY:
        LOGGER.warning(
            "%s slot hour(s) configured (> %s/day policy): %s",
            len(slots),
            MAX_TIKTOK_PER_DAY,
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
            f"Could only allocate {len(results)} of {count} TikTok slots (check DB occupancy)."
        )
    return results


def plan_uploads(
    clips: Sequence[Path],
    batch: BatchConfig,
    db: ScheduleDB,
    *,
    slots: Sequence[int] = DEFAULT_SLOTS,
    tz_name: str = "America/Sao_Paulo",
    start_date: Optional[date] = None,
    persist: bool = True,
    use_llm: Optional[bool] = None,
    metadata_manifest: Optional[Path] = None,
) -> list[PlannedUpload]:
    from shared.llm_metadata import load_metadata_manifest, manifest_path_for_dir

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

    for clip_index, clip_path in enumerate(clips, start=1):
        existing = db.get_by_file(clip_path)
        if existing and existing.status in ("scheduled", "uploaded", "pending", "uploading"):
            LOGGER.info("Skip planning (already in DB): %s status=%s", clip_path.name, existing.status)
            planned.append(
                PlannedUpload(
                    file_path=clip_path,
                    caption=existing.caption,
                    scheduled_at_utc=existing.scheduled_at_utc,
                    slot_date=existing.slot_date,
                    slot_hour=existing.slot_hour,
                    db_id=existing.id,
                )
            )
        else:
            to_schedule.append((clip_index, clip_path))

    if to_schedule:
        free_slots = next_available_slots(
            len(to_schedule),
            slots=slots,
            tz_name=tz_name,
            start_date=start,
            db=db,
        )
        for (clip_index, clip_path), (utc_dt, slot_date, hour) in zip(to_schedule, free_slots):
            caption = build_caption_for_clip(
                clip_path,
                batch,
                clip_index=clip_index,
                use_llm=use_llm,
                metadata_manifest=metadata_manifest,
                manifest=manifest,
            )
            db_id = None
            if persist:
                db_id = db.insert_pending(clip_path, caption, utc_dt, slot_date, hour)
            planned.append(
                PlannedUpload(
                    file_path=clip_path,
                    caption=caption,
                    scheduled_at_utc=utc_dt,
                    slot_date=slot_date,
                    slot_hour=hour,
                    db_id=db_id,
                )
            )

    planned.sort(key=lambda p: p.scheduled_at_utc)
    return planned


def utc_to_local(utc_dt: datetime, tz: object) -> datetime:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(tz)


def print_schedule_plan(planned: Sequence[PlannedUpload], tz_name: str = "America/Sao_Paulo") -> None:
    tz = get_timezone(tz_name)
    LOGGER.info("=== TIKTOK SCHEDULE PLAN (%s clips) ===", len(planned))
    for i, item in enumerate(planned, 1):
        local = utc_to_local(item.scheduled_at_utc, tz)
        LOGGER.info(
            "%3d | %s %02d:00 %s | %s | %s",
            i,
            item.slot_date,
            item.slot_hour,
            tz_name,
            item.caption.splitlines()[0][:60],
            item.file_path.name,
        )
        LOGGER.info("     publish UTC: %s | local: %s", item.scheduled_at_utc.isoformat(), local.isoformat())


def refresh_pending_metadata(
    db: ScheduleDB,
    batch: BatchConfig,
    *,
    use_llm: Optional[bool] = None,
    metadata_manifest: Optional[Path] = None,
) -> int:
    from shared.llm_metadata import load_metadata_manifest, manifest_path_for_dir

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
    updated = 0
    for row in rows:
        clip_path = Path(row.file_path)
        part = extract_part_from_clip(clip_path, row.caption)
        caption = refresh_caption(
            part,
            batch,
            clip_path=clip_path,
            use_llm=use_llm,
            metadata_manifest=metadata_manifest,
        )
        if caption != row.caption:
            db.update_caption(row.id, caption)
            updated += 1
    return updated


def execute_planned_uploads(
    planned: Sequence[PlannedUpload],
    settings: TikTokSettings,
    db: ScheduleDB,
    *,
    dry_run: bool = False,
    limit: Optional[int] = None,
    post_now: bool = False,
    tz_name: str = "America/Sao_Paulo",
) -> tuple[int, int, int]:
    ok = failed = skipped = 0
    items = list(planned)
    if limit is not None:
        items = items[:limit]

    tz = get_timezone(tz_name)

    if SCHEDULE_ONLY and post_now:
        raise RuntimeError(
            "post_now=True bloqueado: SCHEDULE_ONLY=True em uploader_playwright.py"
        )

    batch_count_by_date: dict[str, int] = {}

    for item in items:
        active_on_date = db.count_active_for_date(item.slot_date)
        in_batch = batch_count_by_date.get(item.slot_date, 0)
        row_pre = db.get_by_file(item.file_path) if item.db_id else None
        row_counts_today = (
            row_pre is not None
            and row_pre.status in ("pending", "failed", "uploading")
        )
        effective = active_on_date - (1 if row_counts_today else 0) + in_batch
        if effective >= MAX_TIKTOK_PER_DAY:
            LOGGER.warning(
                "Skip (daily cap %s/%s for %s): %s",
                effective,
                MAX_TIKTOK_PER_DAY,
                item.slot_date,
                item.file_path.name,
            )
            skipped += 1
            continue

        row = row_pre
        if row and row.status in ("scheduled", "uploaded") and row.post_id:
            LOGGER.info("Skip (already done): %s -> %s", item.file_path.name, row.post_id)
            skipped += 1
            continue

        row_id = item.db_id
        if row_id is None and row:
            row_id = row.id
        if row_id is None:
            row_id = db.insert_pending(
                item.file_path,
                item.caption,
                item.scheduled_at_utc,
                item.slot_date,
                item.slot_hour,
            )

        if dry_run:
            upload_video_playwright(
                settings,
                item.file_path,
                item.caption,
                dry_run=True,
                post_now=False if SCHEDULE_ONLY else post_now,
                schedule_at_local=utc_to_local(item.scheduled_at_utc, tz),
            )
            ok += 1
            continue

        db.mark_uploading(row_id)
        attempts = 0
        while attempts < MAX_RETRIES:
            attempts += 1
            try:
                effective_post_now = False if SCHEDULE_ONLY else post_now
                schedule_local = None if effective_post_now else utc_to_local(item.scheduled_at_utc, tz)
                result = upload_video_playwright(
                    settings,
                    item.file_path,
                    item.caption,
                    dry_run=False,
                    post_now=effective_post_now,
                    schedule_at_local=schedule_local,
                )
                if result.ok and result.post_id:
                    if result.posted_immediately:
                        db.mark_uploaded(row_id, result.post_id)
                        LOGGER.info("Publicado imediatamente (--post-now): %s", item.file_path.name)
                    else:
                        db.mark_scheduled(row_id, result.post_id)
                        LOGGER.info(
                            "Agendado na UI TikTok para slot %s %02d:00: %s",
                            item.slot_date,
                            item.slot_hour,
                            item.file_path.name,
                        )
                    ok += 1
                    batch_count_by_date[item.slot_date] = (
                        batch_count_by_date.get(item.slot_date, 0) + 1
                    )
                    break
                raise RuntimeError(result.error or "Upload failed without error message")
            except Exception as exc:
                LOGGER.exception(
                    "TikTok upload attempt %s/%s failed for %s",
                    attempts,
                    MAX_RETRIES,
                    item.file_path.name,
                )
                if attempts >= MAX_RETRIES:
                    db.mark_failed(row_id, str(exc))
                    failed += 1
                else:
                    db.reset_for_retry(row_id)
                    db.mark_uploading(row_id)

    return ok, failed, skipped


def resume_pending(
    db: ScheduleDB,
    settings: TikTokSettings,
    batch: BatchConfig,
    *,
    limit: Optional[int] = None,
    post_now: bool = False,
    tz_name: str = "America/Sao_Paulo",
) -> tuple[int, int, int]:
    rows = db.list_by_status(["pending", "failed"])
    planned: list[PlannedUpload] = []
    for row in rows:
        if row.retry_count >= MAX_RETRIES and row.status == "failed":
            continue
        planned.append(
            PlannedUpload(
                file_path=Path(row.file_path),
                caption=row.caption,
                scheduled_at_utc=row.scheduled_at_utc,
                slot_date=row.slot_date,
                slot_hour=row.slot_hour,
                db_id=row.id,
            )
        )
    return execute_planned_uploads(
        planned,
        settings,
        db,
        dry_run=False,
        limit=limit,
        post_now=post_now,
        tz_name=tz_name,
    )
