# -*- coding: utf-8 -*-
"""Safe read/write for api-keys.json (home canonical, project fallback)."""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.paths import resolve_api_keys_path

LOGGER = logging.getLogger(__name__)

API_KEYS_PATH = resolve_api_keys_path()
YOUTUBE_OAUTH_KEY = "google_oauth_youtube"


def load_api_keys() -> dict[str, Any]:
    """Load api-keys.json; return empty dict if missing or invalid."""
    global API_KEYS_PATH
    API_KEYS_PATH = resolve_api_keys_path()
    if not API_KEYS_PATH.is_file():
        return {}
    try:
        data = json.loads(API_KEYS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Could not read %s: %s", API_KEYS_PATH, type(exc).__name__)
        return {}


def get_service_key(name: str) -> dict[str, Any] | None:
    """Return a top-level service entry dict, or None."""
    entry = load_api_keys().get(name)
    return entry if isinstance(entry, dict) else None


def save_api_keys(data: dict[str, Any]) -> None:
    """Atomically write api-keys.json (preserves caller's full document)."""
    global API_KEYS_PATH
    API_KEYS_PATH = resolve_api_keys_path()
    API_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        suffix=".json",
        dir=API_KEYS_PATH.parent,
        prefix=".api-keys.",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, API_KEYS_PATH)
        LOGGER.info("Updated %s (top-level keys: %s)", API_KEYS_PATH, sorted(data.keys()))
    except Exception:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise


def update_service_key(name: str, updates: dict[str, Any], *, merge: bool = True) -> None:
    """Read-merge-write one top-level key without touching other entries."""
    data = load_api_keys()
    current = data.get(name)
    if merge and isinstance(current, dict):
        merged = {**current, **updates}
    else:
        merged = dict(updates)
    data[name] = merged
    save_api_keys(data)
    LOGGER.info("Merged api-keys entry %r (fields: %s)", name, sorted(merged.keys()))
