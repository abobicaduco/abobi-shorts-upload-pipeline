# -*- coding: utf-8 -*-
"""Paths and defaults for TikTok upload scripts."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.paths import (
    PROJECT_SECRETS_DIR,
    project_secret,
    project_secret_dir_with_fallbacks,
    project_secret_with_home_fallback,
)

_ENV_FILE = _SCRIPTS_DIR / ".env"

DEFAULT_CLIPS_DIR = (
    Path.home()
    / "YOUTUBE"
    / "clips"
    / "abobicaduco_jogando_Granny_2_-_Parte_#2_tiktok"
)

TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
TIKTOK_LOGIN_URL = "https://www.tiktok.com/login"
TIKTOK_PROFILE_URL = "https://www.tiktok.com/@abobicaduco"

DEFAULT_HASHTAGS = (
    "#abobicaduco #granny2 #granny #gameplay #horror #terror #susto #jogodeterro"
)

DEFAULT_SLOTS = (16, 18, 21)
DEFAULT_TIMEZONE = "America/Sao_Paulo"
MAX_TIKTOK_PER_DAY = 3


def load_env_file() -> None:
    if not _ENV_FILE.is_file():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_storage_state_path() -> Path:
    raw = os.environ.get("TIKTOK_STORAGE_STATE", "").strip()
    if raw:
        return Path(raw)
    return project_secret_with_home_fallback("tiktok_storage_state.json")


def resolve_browser_profile_dir() -> Path:
    raw = os.environ.get("TIKTOK_BROWSER_PROFILE", "").strip()
    if raw:
        return Path(raw)
    return project_secret_dir_with_fallbacks(
        "browser-profile-tiktok",
        _SCRIPTS_DIR / "browser-profile-tiktok",
        Path.home() / ".secrets" / "browser-profile-tiktok",
    )


def resolve_schedule_db_path() -> Path:
    raw = os.environ.get("TIKTOK_SCHEDULE_DB", "").strip()
    if raw:
        return Path(raw)
    return project_secret_with_home_fallback("tiktok_schedule.db")


@dataclass
class TikTokSettings:
    clips_dir: Path
    storage_state: Path
    browser_profile: Path
    schedule_db: Path
    timezone: str = DEFAULT_TIMEZONE
    headless: bool = False

    @classmethod
    def from_env(
        cls,
        *,
        clips_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
        headless: bool = False,
    ) -> TikTokSettings:
        load_env_file()
        return cls(
            clips_dir=(clips_dir or DEFAULT_CLIPS_DIR).resolve(),
            storage_state=resolve_storage_state_path(),
            browser_profile=resolve_browser_profile_dir(),
            schedule_db=(db_path or resolve_schedule_db_path()).resolve(),
            timezone=os.environ.get("TIKTOK_TIMEZONE", DEFAULT_TIMEZONE),
            headless=headless,
        )


@dataclass
class BatchConfig:
    hashtags: str = DEFAULT_HASHTAGS
    game: str = "Granny 2"
    source_stem: str = "Granny 2 Parte 2"
    allow_comment: bool = True
    allow_duet: bool = True
    allow_stitch: bool = True

    def build_caption(self, title_line: str, hook: str) -> str:
        parts: list[str] = []
        if title_line.strip():
            parts.append(title_line.strip())
        if hook.strip():
            parts.append(hook.strip())
        if self.hashtags.strip():
            parts.append(self.hashtags.strip())
        return "\n\n".join(parts)
