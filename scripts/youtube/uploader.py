# -*- coding: utf-8 -*-
"""Resumable video upload, thumbnail, playlist — YouTube Data API v3."""
from __future__ import annotations

import json
import logging
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import BatchConfig
from .manifest import ClipEntry

LOGGER = logging.getLogger(__name__)

CHUNK_SIZE = 8 * 1024 * 1024
THUMB_MAX_ATTEMPTS = 3
THUMB_RETRY_SEC = 2.0


def sidecar_path(video: Path) -> Path:
    return video.with_suffix(video.suffix + ".uploaded.json")


def is_already_uploaded(video: Path) -> Optional[str]:
    sc = sidecar_path(video)
    if not sc.is_file():
        return None
    try:
        data = json.loads(sc.read_text(encoding="utf-8"))
        vid = data.get("videoId") or data.get("video_id")
        if vid:
            return str(vid)
    except (json.JSONDecodeError, OSError):
        LOGGER.warning("Invalid sidecar %s - will re-upload", sc)
    return None


def write_sidecar(video: Path, video_id: str, title: str) -> None:
    sc = sidecar_path(video)
    payload = {
        "videoId": video_id,
        "title": title,
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    sc.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class YouTubeUploader:
    def __init__(self, youtube: Any, batch: Optional[BatchConfig] = None) -> None:
        self.youtube = youtube
        self.batch = batch or BatchConfig()

    @staticmethod
    def _format_publish_at(publish_at: datetime) -> str:
        dt = publish_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc).replace(microsecond=0)
        return dt.isoformat().replace("+00:00", "Z")

    def _snippet_body(self, entry: ClipEntry, *, publish_at: Optional[datetime] = None) -> dict:
        if entry.tags:
            tags = list(entry.tags)
        else:
            tags = list(self.batch.tags) if self.batch.tags else []
        privacy = self.batch.privacy
        status: dict[str, Any] = {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        }
        if publish_at is not None:
            status["privacyStatus"] = "private"
            status["publishAt"] = self._format_publish_at(publish_at)

        return {
            "snippet": {
                "title": entry.title[:100],
                "description": entry.description[:5000],
                "categoryId": self.batch.category_id,
                "tags": tags[:500] if tags else None,
            },
            "status": status,
        }

    def upload_video(
        self,
        entry: ClipEntry,
        *,
        dry_run: bool = False,
        skip_if_uploaded: bool = True,
        publish_at: Optional[datetime] = None,
    ) -> Optional[str]:
        video = entry.file_path
        if skip_if_uploaded:
            existing = is_already_uploaded(video)
            if existing:
                LOGGER.info("Skip (already uploaded): %s -> videoId=%s", video.name, existing)
                return existing

        if dry_run:
            LOGGER.info(
                "[DRY-RUN] Would upload: %s | title=%r | desc_len=%s",
                video,
                entry.title,
                len(entry.description),
            )
            if publish_at is not None:
                LOGGER.info(
                    "[DRY-RUN] Scheduled publishAt=%s (private until then)",
                    self._format_publish_at(publish_at),
                )
            if entry.thumb_path:
                LOGGER.info("[DRY-RUN] Would set thumbnail: %s", entry.thumb_path)
            if self.batch.playlist_id:
                LOGGER.info("[DRY-RUN] Would add to playlist: %s", self.batch.playlist_id)
            return "dry-run"

        body = self._snippet_body(entry, publish_at=publish_at)
        # Remove empty tags key
        if not body["snippet"].get("tags"):
            body["snippet"].pop("tags", None)

        media = MediaFileUpload(
            str(video),
            chunksize=CHUNK_SIZE,
            resumable=True,
            mimetype="video/*",
        )
        request = self.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        LOGGER.info("Uploading %s (%s bytes)...", video.name, video.stat().st_size)
        response = None
        last_progress = -1
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct != last_progress and pct % 10 == 0:
                    LOGGER.info("  %s - %s%%", video.name, pct)
                    last_progress = pct

        video_id = response["id"]
        LOGGER.info("Uploaded %s -> https://youtu.be/%s", video.name, video_id)

        if entry.thumb_path and entry.thumb_path.is_file():
            self.set_thumbnail(video_id, entry.thumb_path)
        elif entry.thumb_path:
            LOGGER.warning("Thumbnail path missing, skipped: %s", entry.thumb_path)

        if self.batch.playlist_id:
            self.add_to_playlist(video_id, self.batch.playlist_id)

        write_sidecar(video, video_id, entry.title)
        return video_id

    def set_thumbnail(self, video_id: str, thumb_path: Path) -> None:
        for attempt in range(1, THUMB_MAX_ATTEMPTS + 1):
            try:
                mime, _ = mimetypes.guess_type(str(thumb_path))
                media = MediaFileUpload(
                    str(thumb_path),
                    mimetype=mime or "image/jpeg",
                )
                self.youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=media,
                ).execute()
                LOGGER.info("Thumbnail set for %s", video_id)
                return
            except HttpError as exc:
                LOGGER.warning(
                    "thumbnails.set attempt %s/%s failed for %s: %s",
                    attempt,
                    THUMB_MAX_ATTEMPTS,
                    video_id,
                    exc,
                )
                if attempt < THUMB_MAX_ATTEMPTS:
                    time.sleep(THUMB_RETRY_SEC * attempt)
            except Exception:
                LOGGER.exception("thumbnails.set failed for %s", video_id)
                if attempt < THUMB_MAX_ATTEMPTS:
                    time.sleep(THUMB_RETRY_SEC * attempt)
        LOGGER.error(
            "Could not set thumbnail for %s after %s attempts (video upload still OK)",
            video_id,
            THUMB_MAX_ATTEMPTS,
        )

    def add_to_playlist(self, video_id: str, playlist_id: str) -> None:
        try:
            self.youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id,
                        },
                    }
                },
            ).execute()
            LOGGER.info("Added %s to playlist %s", video_id, playlist_id)
        except HttpError as exc:
            LOGGER.warning("playlistItems.insert failed: %s", exc)
