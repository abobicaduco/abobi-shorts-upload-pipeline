# -*- coding: utf-8 -*-
"""Update YouTube video snippet metadata (title, description, tags, language)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

LOGGER = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "pt"
DEFAULT_CATEGORY_ID = "20"
GRANNY_MARKERS = ("granny", "horror", "terror", "susto", "shorts")


@dataclass
class VideoMetadataSpec:
    video_id: str
    title: str
    description_body: str
    tags: list[str]
    role: str = ""
    category_id: str = DEFAULT_CATEGORY_ID
    set_language: bool = True


@dataclass
class MetadataUpdateReport:
    video_id: str
    role: str = ""
    action: str = "none"
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


def fetch_video(youtube: Any, video_id: str) -> dict[str, Any] | None:
    resp = youtube.videos().list(part="snippet,status", id=video_id).execute()
    items = resp.get("items") or []
    return items[0] if items else None


def snippet_summary(snippet: dict[str, Any], status: dict[str, Any] | None = None) -> dict[str, Any]:
    desc = snippet.get("description") or ""
    out: dict[str, Any] = {
        "title": snippet.get("title"),
        "description_preview": desc[:160],
        "tags": snippet.get("tags") or [],
        "defaultLanguage": snippet.get("defaultLanguage"),
        "defaultAudioLanguage": snippet.get("defaultAudioLanguage"),
        "categoryId": snippet.get("categoryId"),
    }
    if status is not None:
        out["privacy"] = status.get("privacyStatus")
        out["publishAt"] = status.get("publishAt")
        out["selfDeclaredMadeForKids"] = status.get("selfDeclaredMadeForKids")
    return out


def looks_like_wrong_horror_metadata(snippet: dict[str, Any]) -> bool:
    desc = (snippet.get("description") or "").lower()
    title = (snippet.get("title") or "").lower()
    tags = [t.lower() for t in (snippet.get("tags") or [])]
    hay = f"{title} {desc} {' '.join(tags)}"
    return any(m in hay for m in GRANNY_MARKERS if m != "shorts") or (
        "granny" in hay or "horror" in tags or "terror" in tags
    )


def needs_full_metadata_refresh(
    snippet: dict[str, Any],
    *,
    expected_title: str,
    expected_tag_count_min: int = 10,
    required_hashtag_substrings: tuple[str, ...] = ("#mobilegaming",),
) -> bool:
    if looks_like_wrong_horror_metadata(snippet):
        return True
    title = (snippet.get("title") or "").strip()
    if title != expected_title[:100].strip():
        return True
    tags = snippet.get("tags") or []
    if len(tags) < expected_tag_count_min:
        return True
    desc_lower = (snippet.get("description") or "").lower()
    if any(h.lower() not in desc_lower for h in required_hashtag_substrings):
        return True
    if not snippet.get("defaultLanguage") or not snippet.get("defaultAudioLanguage"):
        return True
    if (snippet.get("categoryId") or "") != DEFAULT_CATEGORY_ID:
        return True
    return False


def update_video_snippet(
    youtube: Any,
    spec: VideoMetadataSpec,
    *,
    full_description: str,
    dry_run: bool = False,
) -> None:
    snippet: dict[str, Any] = {
        "title": spec.title[:100],
        "description": full_description[:5000],
        "categoryId": spec.category_id,
        "tags": spec.tags[:500],
    }
    if spec.set_language:
        snippet["defaultLanguage"] = DEFAULT_LANGUAGE
        snippet["defaultAudioLanguage"] = DEFAULT_LANGUAGE

    body = {"id": spec.video_id, "snippet": snippet}
    if dry_run:
        LOGGER.info(
            "[DRY-RUN] videos.update snippet %s title=%r tags=%d",
            spec.video_id,
            spec.title[:60],
            len(spec.tags),
        )
        return
    youtube.videos().update(part="snippet", body=body).execute()
    LOGGER.info("OK snippet updated %s", spec.video_id)


def neutralize_scheduled_duplicate(
    youtube: Any,
    video_id: str,
    *,
    dry_run: bool = False,
) -> None:
    """Private + no publishAt — does not delete."""
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    if dry_run:
        LOGGER.info("[DRY-RUN] videos.update status %s -> private", video_id)
        return
    youtube.videos().update(part="status", body={"id": video_id, "status": status}).execute()
    LOGGER.info("OK duplicate schedule neutralized %s", video_id)


def apply_metadata_specs(
    youtube: Any,
    specs: list[VideoMetadataSpec],
    *,
    build_description: Callable[[VideoMetadataSpec], str],
    dry_run: bool = False,
    force: bool = False,
    expected_tag_count_min: int = 10,
    required_hashtag_substrings: tuple[str, ...] = ("#mobilegaming",),
) -> list[MetadataUpdateReport]:
    reports: list[MetadataUpdateReport] = []
    for spec in specs:
        rep = MetadataUpdateReport(video_id=spec.video_id, role=spec.role or spec.video_id)
        current = fetch_video(youtube, spec.video_id)
        if not current:
            rep.error = "not found"
            reports.append(rep)
            continue

        sn = current["snippet"]
        st = current["status"]
        rep.before = snippet_summary(sn, st)

        full_desc = build_description(spec)
        refresh = force or needs_full_metadata_refresh(
            sn,
            expected_title=spec.title,
            expected_tag_count_min=expected_tag_count_min,
            required_hashtag_substrings=required_hashtag_substrings,
        )

        if refresh:
            update_video_snippet(
                youtube, spec, full_description=full_desc, dry_run=dry_run
            )
            rep.action = "snippet_update"
        else:
            rep.action = "skipped_ok"

        if not dry_run:
            after_item = fetch_video(youtube, spec.video_id)
            if after_item:
                rep.after = snippet_summary(
                    after_item["snippet"], after_item["status"]
                )
        else:
            rep.after = {
                "title": spec.title[:100],
                "description_preview": full_desc[:160],
                "tags": spec.tags,
                "defaultLanguage": DEFAULT_LANGUAGE if spec.set_language else None,
            }

        reports.append(rep)
    return reports


def reports_to_dict(reports: list[MetadataUpdateReport]) -> dict[str, Any]:
    return {
        "videos": {
            r.video_id: {
                "role": r.role,
                "action": r.action,
                "before": r.before,
                "after": r.after,
                **({"error": r.error} if r.error else {}),
            }
            for r in reports
        }
    }


def print_reports_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
