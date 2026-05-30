# -*- coding: utf-8 -*-
"""PT-BR caption/title templates for TikTok (title + hook + hashtags in description)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from shared.llm_metadata import (
    build_tiktok_caption,
    load_metadata_manifest,
    manifest_path_for_dir,
    resolve_clip_metadata,
)
from youtube.video_splitter import (
    DESC_HOOKS,
    extract_clip_part,
    generate_clip_description,
    generate_clip_title,
)

from .config import BatchConfig


def extract_part_from_clip(path: Path, caption: str = "") -> int:
    part = extract_clip_part(caption, path)
    if part == 1:
        match = re.search(r"_(\d{3})\.mp4$", path.name, re.IGNORECASE)
        if match:
            return int(match.group(1)) + 1
    return part


def build_title_line(part: int, *, game: str = "Granny 2") -> str:
    return generate_clip_title(part, "Granny 2 Parte 2", game=game)


def build_hook_line(part: int, *, game: str = "Granny 2") -> str:
    base = generate_clip_description(part, "Granny 2 Parte 2", game=game)
    lines = [ln.strip() for ln in base.splitlines() if ln.strip()]
    if not lines:
        return DESC_HOOKS[(part - 1) % len(DESC_HOOKS)]
    return lines[0]


def build_caption_for_clip(
    clip_path: Path,
    batch: BatchConfig,
    *,
    part: Optional[int] = None,
    clip_index: Optional[int] = None,
    use_llm: Optional[bool] = None,
    metadata_manifest: Optional[Path] = None,
    manifest: Optional[dict] = None,
) -> str:
    idx = part or extract_part_from_clip(clip_path)
    clip_idx = clip_index or idx

    if metadata_manifest is None:
        default_manifest = manifest_path_for_dir(clip_path.parent)
        if default_manifest.is_file():
            metadata_manifest = default_manifest

    meta = resolve_clip_metadata(
        clip_idx,
        idx,
        game=batch.game,
        platform="tiktok",
        clip_path=clip_path,
        source_stem=batch.source_stem,
        use_llm=use_llm,
        manifest=manifest,
        manifest_path=metadata_manifest,
    )

    hashtags = meta.get("hashtags") or batch.hashtags
    if batch.hashtags.strip() and batch.hashtags not in str(hashtags):
        hashtags = f"{hashtags.strip()}\n{batch.hashtags.strip()}".strip()

    description_lines = [ln.strip() for ln in meta["description"].splitlines() if ln.strip()]
    hook = description_lines[0] if description_lines else build_hook_line(idx, game=batch.game)
    if len(description_lines) > 1:
        hook = "\n".join(description_lines)

    return build_tiktok_caption(meta["title"], hook, hashtags)


def refresh_caption(
    part: int,
    batch: BatchConfig,
    *,
    clip_path: Optional[Path] = None,
    use_llm: Optional[bool] = None,
    metadata_manifest: Optional[Path] = None,
) -> str:
    if clip_path is not None:
        return build_caption_for_clip(
            clip_path,
            batch,
            part=part,
            use_llm=use_llm,
            metadata_manifest=metadata_manifest,
        )
    title_line = build_title_line(part, game=batch.game)
    hook = build_hook_line(part, game=batch.game)
    return batch.build_caption(title_line, hook)
