# -*- coding: utf-8 -*-
"""Parse manifest CSV and batch YAML for clip batches."""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

from .config import BatchConfig

LOGGER = logging.getLogger(__name__)


@dataclass
class ClipEntry:
    file_path: Path
    title: str
    description: str
    thumb_path: Optional[Path] = None
    tags: Optional[List[str]] = None


def load_batch_yaml(path: Path) -> BatchConfig:
    if not path.is_file():
        raise FileNotFoundError(f"Batch config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"batch.yaml must be a mapping, got {type(data).__name__}")

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif not isinstance(tags, list):
        tags = []

    thumb = data.get("thumbnail") or data.get("default_thumbnail")
    thumb_path = Path(thumb) if thumb else None

    return BatchConfig(
        hashtags=str(data.get("hashtags", "")),
        tags=[str(t).strip() for t in tags if str(t).strip()],
        privacy=str(data.get("privacy", "public")).strip().lower(),
        playlist_id=(str(data["playlist_id"]).strip() if data.get("playlist_id") else None),
        category_id=str(data.get("category_id", "20")),
        append_shorts_hashtag=bool(
            data.get("append_shorts_hashtag", data.get("add_shorts_hashtag", False))
        ),
        default_thumb=thumb_path,
    )


def _resolve_video_path(raw: str, inbox: Path, manifest_dir: Path) -> Path:
    p = Path(raw.strip())
    if p.is_absolute() and p.is_file():
        return p.resolve()
    for base in (manifest_dir, inbox):
        candidate = base / p
        if candidate.is_file():
            return candidate.resolve()
        candidate = base / p.name
        if candidate.is_file():
            return candidate.resolve()
    if p.is_file():
        return p.resolve()
    return (inbox / p.name).resolve()


def load_manifest_csv(
    manifest_path: Path,
    inbox: Path,
    batch: Optional[BatchConfig] = None,
) -> List[ClipEntry]:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    entries: List[ClipEntry] = []
    with manifest_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("Manifest CSV has no header row")
        fields = {f.strip().lower() for f in reader.fieldnames if f}
        if "file_path" not in fields:
            raise ValueError("Manifest CSV must include column: file_path")

        for row_num, row in enumerate(reader, start=2):
            normalized = {
                (k or "").strip().lower(): (v or "").strip()
                for k, v in row.items()
            }
            raw_file = normalized.get("file_path", "")
            if not raw_file:
                LOGGER.warning("Row %s: empty file_path, skipping", row_num)
                continue

            title = normalized.get("title") or Path(raw_file).stem
            desc_base = normalized.get("description", "")
            if batch:
                description = batch.build_description(desc_base)
            else:
                description = desc_base

            thumb_raw = normalized.get("thumb_path") or normalized.get("thumbnail")
            thumb: Optional[Path] = None
            if thumb_raw:
                thumb = Path(thumb_raw)
                if not thumb.is_absolute():
                    thumb = (inbox / thumb).resolve()
            elif batch and batch.default_thumb:
                thumb = batch.default_thumb

            tags_raw = normalized.get("tags", "")
            tags: Optional[List[str]] = None
            if tags_raw:
                tags = [t.strip() for t in tags_raw.replace(",", "|").split("|") if t.strip()]

            video = _resolve_video_path(raw_file, inbox, manifest_path.parent)
            if not video.is_file():
                LOGGER.warning("Row %s: file not found %s - skipping", row_num, video)
                continue

            entries.append(
                ClipEntry(
                    file_path=video,
                    title=title,
                    description=description,
                    thumb_path=thumb,
                    tags=tags,
                )
            )
    return entries


def inbox_mp4_entries(
    inbox: Path,
    batch: Optional[BatchConfig],
) -> List[ClipEntry]:
    """When no manifest: one entry per .mp4 using filename stem as title."""
    entries: List[ClipEntry] = []
    for path in sorted(inbox.glob("*.mp4")):
        if not path.is_file():
            continue
        if path.parent.name == "uploaded":
            continue
        desc = batch.build_description("") if batch else ""
        entries.append(
            ClipEntry(
                file_path=path.resolve(),
                title=path.stem,
                description=desc,
                thumb_path=batch.default_thumb if batch else None,
            )
        )
    return entries
