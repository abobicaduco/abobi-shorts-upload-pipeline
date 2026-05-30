# -*- coding: utf-8 -*-
"""Timezone helpers (zoneinfo + pytz fallback on Windows)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def get_timezone(name: str) -> Any:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        import pytz

        return pytz.timezone(name)


def local_to_utc(dt_local: datetime, tz: Any) -> datetime:
    if dt_local.tzinfo is None:
        try:
            aware = dt_local.replace(tzinfo=tz)
        except TypeError:
            aware = tz.localize(dt_local)
    else:
        aware = dt_local
    return aware.astimezone(timezone.utc)


def now_in_tz(tz_name: str) -> datetime:
    tz = get_timezone(tz_name)
    return datetime.now(tz)
