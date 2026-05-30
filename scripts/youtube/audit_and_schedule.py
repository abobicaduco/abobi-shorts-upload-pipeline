# -*- coding: utf-8 -*-
"""Audit channel videos: fix metadata and schedule private Shorts not yet in DB.

Unlisted videos are already published — videos.update can refresh title/description/tags
but CANNOT set a future publishAt to make them public on a schedule. Only private
videos accept status.publishAt for scheduled public release.

See docs/youtube/HANDOFF.md § audit_and_schedule.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Sequence

from googleapiclient.errors import HttpError

from shared.llm_metadata import build_youtube_description, resolve_clip_metadata
from .auth import get_youtube_service
from .config import BatchConfig, YouTubeSettings, load_env_file
from .manifest import load_batch_yaml
from .schedule_db import ScheduleDB, default_db_path
from .scheduler import DEFAULT_SHORTS_SLOTS
from .timezone_util import get_timezone, now_in_tz
from .uploader import YouTubeUploader
from .video_splitter import extract_clip_part

LOGGER = logging.getLogger(__name__)

TARGET_SLOTS = DEFAULT_SHORTS_SLOTS
TZ_NAME = "America/Sao_Paulo"
CATEGORY_ID = "20"
DEFAULT_LANGUAGE = "pt"

TITLE_MATCH_PATTERNS = (
    re.compile(r"granny\s*2", re.IGNORECASE),
    re.compile(r"granny", re.IGNORECASE),
    re.compile(r"abobicaduco", re.IGNORECASE),
    re.compile(r"#\d{1,3}\b"),
)

TargetKind = Literal["private_schedulable", "unlisted_metadata", "skip"]


@dataclass
class ChannelVideo:
    video_id: str
    title: str
    description: str
    tags: list[str]
    privacy_status: str
    publish_at: Optional[datetime]
    published_at: Optional[datetime]
    category_id: str
    default_language: Optional[str]


@dataclass
class AuditTarget:
    video: ChannelVideo
    kind: TargetKind
    part_number: int
    skip_reason: Optional[str] = None


@dataclass
class AuditReport:
    total_on_channel: int = 0
    matched_pattern: int = 0
    skipped_in_db: int = 0
    skipped_other: int = 0
    private_schedulable: int = 0
    unlisted_metadata: int = 0
    metadata_updated: int = 0
    scheduled: int = 0
    metadata_only: int = 0
    failed: int = 0
    dry_run: bool = False
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    failures: list[dict[str, str]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)


def _parse_api_datetime(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _matches_title_pattern(title: str) -> bool:
    return any(p.search(title) for p in TITLE_MATCH_PATTERNS)


def _fetch_uploads_playlist_id(youtube: Any) -> str:
    resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        raise RuntimeError("No channel found for authenticated user (mine=True).")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _list_playlist_video_ids(youtube: Any, playlist_id: str, *, max_items: int = 5000) -> list[str]:
    ids: list[str] = []
    token: Optional[str] = None
    while len(ids) < max_items:
        resp = (
            youtube.playlistItems()
            .list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=min(50, max_items - len(ids)),
                pageToken=token,
            )
            .execute()
        )
        for item in resp.get("items") or []:
            vid = (item.get("snippet") or {}).get("resourceId", {}).get("videoId")
            if vid:
                ids.append(vid)
        token = resp.get("nextPageToken")
        if not token:
            break
    return ids


def _fetch_video_details(youtube: Any, video_ids: Sequence[str]) -> list[ChannelVideo]:
    results: list[ChannelVideo] = []
    for i in range(0, len(video_ids), 50):
        batch = list(video_ids[i : i + 50])
        resp = (
            youtube.videos()
            .list(part="snippet,status", id=",".join(batch))
            .execute()
        )
        for item in resp.get("items") or []:
            sn = item.get("snippet") or {}
            st = item.get("status") or {}
            tags = sn.get("tags") or []
            if not isinstance(tags, list):
                tags = []
            results.append(
                ChannelVideo(
                    video_id=item["id"],
                    title=str(sn.get("title") or ""),
                    description=str(sn.get("description") or ""),
                    tags=[str(t) for t in tags],
                    privacy_status=str(st.get("privacyStatus") or "unknown"),
                    publish_at=_parse_api_datetime(st.get("publishAt")),
                    published_at=_parse_api_datetime(sn.get("publishedAt")),
                    category_id=str(sn.get("categoryId") or CATEGORY_ID),
                    default_language=sn.get("defaultLanguage"),
                )
            )
    return results


def _channel_occupied_slots(
    videos: Sequence[ChannelVideo],
    *,
    tz_name: str = TZ_NAME,
) -> set[tuple[str, int]]:
    """Map future private publishAt on channel to (slot_date, hour) in local TZ."""
    tz = get_timezone(tz_name)
    now = datetime.now(timezone.utc)
    occupied: set[tuple[str, int]] = set()
    for video in videos:
        if video.privacy_status != "private" or not video.publish_at:
            continue
        if video.publish_at <= now:
            continue
        local = video.publish_at.astimezone(tz)
        if local.hour in TARGET_SLOTS:
            occupied.add((local.date().isoformat(), local.hour))
    return occupied


def _classify_video(
    video: ChannelVideo,
    *,
    known_db_ids: set[str],
    now: datetime,
    match_pattern: bool,
) -> AuditTarget:
    part = extract_clip_part(video.title)
    if video.video_id in known_db_ids:
        return AuditTarget(
            video=video,
            kind="skip",
            part_number=part,
            skip_reason="already_in_schedule_db",
        )
    if match_pattern and not _matches_title_pattern(video.title):
        return AuditTarget(
            video=video,
            kind="skip",
            part_number=part,
            skip_reason="title_pattern_mismatch",
        )

    if video.privacy_status == "private":
        if video.publish_at and video.publish_at > now:
            return AuditTarget(
                video=video,
                kind="skip",
                part_number=part,
                skip_reason="private_already_scheduled_on_youtube",
            )
        return AuditTarget(video=video, kind="private_schedulable", part_number=part)

    if video.privacy_status == "unlisted":
        return AuditTarget(video=video, kind="unlisted_metadata", part_number=part)

    return AuditTarget(
        video=video,
        kind="skip",
        part_number=part,
        skip_reason=f"privacy_{video.privacy_status}",
    )


def _next_free_slot_with_channel(
    db: ScheduleDB,
    channel_occupied: set[tuple[str, int]],
    *,
    tz_name: str = TZ_NAME,
    start_date: Optional[date] = None,
    min_lead_minutes: int = 20,
) -> tuple[datetime, str, int]:
    """Allocate one slot respecting DB + channel occupancy."""
    tz = get_timezone(tz_name)
    start = start_date or now_in_tz(tz_name).date()
    now_utc = datetime.now(timezone.utc)
    min_publish = now_utc + timedelta(minutes=min_lead_minutes)
    day = start
    safety = 0
    while safety < 3650:
        safety += 1
        for hour in sorted(TARGET_SLOTS):
            local_dt = datetime(day.year, day.month, day.day, hour, 0, 0)
            from .timezone_util import local_to_utc

            utc_dt = local_to_utc(local_dt, tz)
            if utc_dt <= min_publish:
                continue
            slot_date = day.isoformat()
            if db.is_slot_taken(slot_date, hour):
                continue
            if (slot_date, hour) in channel_occupied:
                continue
            return utc_dt, slot_date, hour
        day = day + timedelta(days=1)
    raise RuntimeError("Could not find a free slot within 10 years.")


def _build_metadata(
    target: AuditTarget,
    *,
    game: str,
    source_stem: str,
    batch: BatchConfig,
    use_llm: Optional[bool],
) -> tuple[str, str, list[str]]:
    meta = resolve_clip_metadata(
        target.part_number,
        target.part_number,
        game=game,
        platform="youtube",
        source_stem=source_stem,
        use_llm=use_llm,
    )
    hashtags = meta.get("hashtags") or batch.hashtags
    description = build_youtube_description(
        meta["description"],
        hashtags,
        append_shorts=batch.append_shorts_hashtag,
    )
    tags = meta.get("tags") or batch.tags or []
    return meta["title"], description, list(tags)


def _update_video_snippet(
    youtube: Any,
    video_id: str,
    *,
    title: str,
    description: str,
    tags: list[str],
    dry_run: bool,
) -> None:
    body = {
        "id": video_id,
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": CATEGORY_ID,
            "defaultLanguage": DEFAULT_LANGUAGE,
            "tags": tags[:500] if tags else None,
        },
    }
    if not body["snippet"].get("tags"):
        body["snippet"].pop("tags", None)

    if dry_run:
        LOGGER.info(
            "[DRY-RUN] videos.update snippet id=%s title=%r",
            video_id,
            title[:60],
        )
        return
    youtube.videos().update(part="snippet", body=body).execute()


def _schedule_private_video(
    youtube: Any,
    video_id: str,
    publish_at: datetime,
    *,
    dry_run: bool,
) -> None:
    status = {
        "privacyStatus": "private",
        "publishAt": YouTubeUploader._format_publish_at(publish_at),
        "selfDeclaredMadeForKids": False,
    }
    if dry_run:
        LOGGER.info(
            "[DRY-RUN] videos.update status id=%s publishAt=%s",
            video_id,
            status["publishAt"],
        )
        return
    youtube.videos().update(
        part="status",
        body={"id": video_id, "status": status},
    ).execute()


def _assign_sequential_parts(targets: Sequence[AuditTarget], db: ScheduleDB) -> None:
    """Assign unique part numbers when title lacks #NN (avoids duplicate #01 titles)."""
    max_part = 0
    for target in targets:
        if re.search(r"#\d{1,3}\b", target.video.title):
            max_part = max(max_part, target.part_number)
    for row in db.list_by_status(["pending", "uploading", "scheduled", "uploaded", "failed"]):
        max_part = max(max_part, extract_clip_part(row.title))

    next_part = max_part + 1
    for target in targets:
        if target.kind == "skip":
            continue
        if re.search(r"#\d{1,3}\b", target.video.title):
            continue
        target.part_number = next_part
        next_part += 1


def identify_targets(
    videos: Sequence[ChannelVideo],
    db: ScheduleDB,
    *,
    match_pattern: bool = True,
) -> list[AuditTarget]:
    known = db.list_known_video_ids()
    now = datetime.now(timezone.utc)
    targets: list[AuditTarget] = []
    for video in videos:
        target = _classify_video(
            video,
            known_db_ids=known,
            now=now,
            match_pattern=match_pattern,
        )
        targets.append(target)
    return targets


def run_channel_audit(
    *,
    dry_run: bool = False,
    db_path: Optional[Path] = None,
    batch: Optional[BatchConfig] = None,
    game: str = "Granny 2",
    source_stem: str = "Granny 2 Parte 2",
    use_llm: Optional[bool] = None,
    match_pattern: bool = True,
    limit: Optional[int] = None,
    max_items: int = 5000,
) -> AuditReport:
    load_env_file()
    settings = YouTubeSettings.from_env()
    if use_llm is None:
        use_llm = False
    batch = batch or BatchConfig(
        hashtags="#abobicaduco #granny2 #granny #gameplay #horror #shorts #terror #susto",
        append_shorts_hashtag=True,
    )
    db = ScheduleDB(db_path or default_db_path())
    report = AuditReport(dry_run=dry_run)

    youtube = get_youtube_service(settings.client_secrets, settings.token_path)
    playlist_id = _fetch_uploads_playlist_id(youtube)
    video_ids = _list_playlist_video_ids(youtube, playlist_id, max_items=max_items)
    videos = _fetch_video_details(youtube, video_ids)
    report.total_on_channel = len(videos)

    pub_dates = [v.published_at for v in videos if v.published_at]
    if pub_dates:
        report.date_range_start = min(pub_dates).date().isoformat()
        report.date_range_end = max(pub_dates).date().isoformat()

    targets = identify_targets(videos, db, match_pattern=match_pattern)
    _assign_sequential_parts(targets, db)
    channel_occupied = _channel_occupied_slots(videos)

    actionable = [t for t in targets if t.kind != "skip"]
    if limit is not None:
        actionable = actionable[:limit]

    for target in targets:
        if target.kind == "skip":
            if target.skip_reason == "already_in_schedule_db":
                report.skipped_in_db += 1
            else:
                report.skipped_other += 1
        elif target.kind == "private_schedulable":
            report.private_schedulable += 1
        elif target.kind == "unlisted_metadata":
            report.unlisted_metadata += 1

    report.matched_pattern = sum(
        1 for v in videos if _matches_title_pattern(v.title)
    )

    for target in actionable:
        video = target.video
        try:
            title, description, tags = _build_metadata(
                target,
                game=game,
                source_stem=source_stem,
                batch=batch,
                use_llm=use_llm,
            )
            action: dict[str, Any] = {
                "video_id": video.video_id,
                "kind": target.kind,
                "old_title": video.title[:80],
                "new_title": title[:80],
            }

            _update_video_snippet(
                youtube,
                video.video_id,
                title=title,
                description=description,
                tags=tags,
                dry_run=dry_run,
            )
            report.metadata_updated += 1

            if target.kind == "private_schedulable":
                utc_dt, slot_date, hour = _next_free_slot_with_channel(
                    db,
                    channel_occupied,
                )
                channel_occupied.add((slot_date, hour))
                _schedule_private_video(
                    youtube,
                    video.video_id,
                    utc_dt,
                    dry_run=dry_run,
                )
                if not dry_run:
                    db.insert_audit_scheduled(
                        video.video_id,
                        title,
                        utc_dt,
                        slot_date,
                        hour,
                    )
                report.scheduled += 1
                action["scheduled_at_utc"] = utc_dt.isoformat()
                action["slot"] = f"{slot_date} {hour:02d}:00 {TZ_NAME}"
            elif target.kind == "unlisted_metadata":
                report.metadata_only += 1
                action["note"] = "metadata only — already published unlisted (publishAt not applicable)"
                LOGGER.info(
                    "metadata only — already published unlisted: %s | %s",
                    video.video_id,
                    video.title[:60],
                )

            report.actions.append(action)
        except HttpError as exc:
            report.failed += 1
            err = str(exc)[:500]
            report.failures.append({"video_id": video.video_id, "error": err})
            LOGGER.exception("Failed for %s: %s", video.video_id, exc)
        except Exception as exc:
            report.failed += 1
            err = str(exc)[:500]
            report.failures.append({"video_id": video.video_id, "error": err})
            LOGGER.exception("Failed for %s", video.video_id)

    return report


def print_report(report: AuditReport) -> None:
    LOGGER.info("=== AUDIT REPORT (%s) ===", "DRY-RUN" if report.dry_run else "LIVE")
    LOGGER.info("Total videos on channel: %s", report.total_on_channel)
    LOGGER.info("Matched Granny/abobicaduco pattern: %s", report.matched_pattern)
    LOGGER.info("Skipped (already in schedule DB): %s", report.skipped_in_db)
    LOGGER.info("Skipped (other): %s", report.skipped_other)
    LOGGER.info("Private schedulable targets: %s", report.private_schedulable)
    LOGGER.info("Unlisted metadata-only targets: %s", report.unlisted_metadata)
    LOGGER.info("Metadata updated: %s", report.metadata_updated)
    LOGGER.info("Scheduled (private -> publishAt): %s", report.scheduled)
    LOGGER.info("Metadata-only (unlisted): %s", report.metadata_only)
    LOGGER.info("Failed: %s", report.failed)
    if report.date_range_start:
        LOGGER.info(
            "Published date range: %s .. %s",
            report.date_range_start,
            report.date_range_end,
        )
    if report.failures:
        for item in report.failures:
            LOGGER.info("  FAIL %s: %s", item["video_id"], item["error"][:120])


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Audit abobicaduco channel: fix SEO metadata and schedule private Shorts. "
            "Unlisted videos get metadata-only updates (no future publishAt)."
        ),
    )
    p.add_argument("--dry-run", action="store_true", help="Plan only; no API writes")
    p.add_argument("--db", type=Path, help="SQLite schedule DB path")
    p.add_argument("--batch", type=Path, help="batch.yaml for hashtags/tags defaults")
    p.add_argument("--game", default="Granny 2")
    p.add_argument("--source-stem", default="Granny 2 Parte 2")
    p.add_argument("--use-llm", action="store_true", help="Force Ollama metadata")
    p.add_argument("--no-llm", action="store_true", help="Template metadata only")
    p.add_argument(
        "--all-videos",
        action="store_true",
        help="Process all channel videos (default: Granny/abobicaduco title patterns only)",
    )
    p.add_argument("--limit", type=int, help="Max videos to process this run")
    p.add_argument("--max-items", type=int, default=5000, help="Max playlist items to scan")
    p.add_argument("--json", action="store_true", help="Print report JSON to stdout")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    from .stdio import configure_stdio_utf8

    configure_stdio_utf8()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = parse_args(argv)
    use_llm: Optional[bool] = None
    if args.no_llm:
        use_llm = False
    elif args.use_llm:
        use_llm = True

    batch = load_batch_yaml(args.batch.resolve()) if args.batch else None

    report = run_channel_audit(
        dry_run=args.dry_run,
        db_path=args.db,
        batch=batch,
        game=args.game,
        source_stem=args.source_stem,
        use_llm=use_llm,
        match_pattern=not args.all_videos,
        limit=args.limit,
        max_items=args.max_items,
    )
    print_report(report)

    if args.json:
        payload = {
            "total_on_channel": report.total_on_channel,
            "matched_pattern": report.matched_pattern,
            "skipped_in_db": report.skipped_in_db,
            "skipped_other": report.skipped_other,
            "metadata_updated": report.metadata_updated,
            "scheduled": report.scheduled,
            "metadata_only": report.metadata_only,
            "failed": report.failed,
            "date_range": [report.date_range_start, report.date_range_end],
            "dry_run": report.dry_run,
            "actions": report.actions,
            "failures": report.failures,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
