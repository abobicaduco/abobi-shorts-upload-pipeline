# -*- coding: utf-8 -*-
"""TikTok Content Posting API v2 — not enabled by default.

Official API is free but requires:
- Developer app at developers.tiktok.com
- OAuth with video.publish scope
- App audit for public posts (sandbox = SELF_ONLY private only)
- UX compliance (user picks privacy, commercial disclosure, etc.)

See docs/tiktok/HANDOFF.md for setup steps. This project uses Playwright instead
until audit passes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


class TikTokApiUploader:
    """Placeholder — implement after TikTok app audit."""

    def upload_video(
        self,
        video_path: Path,
        caption: str,
        *,
        dry_run: bool = False,
    ) -> Optional[str]:
        raise NotImplementedError(
            "TikTok Content Posting API not wired yet. Use uploader_playwright.py "
            "or complete developer app audit (docs/tiktok/HANDOFF.md)."
        )
