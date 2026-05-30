# -*- coding: utf-8 -*-
"""List (and optionally dry-run delete) duplicate uploads on the YouTube channel.

Default: LIST only. Use --apply-delete only after explicit user confirmation.
"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from importlib.machinery import SourcelessFileLoader
from pathlib import Path
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(__file__).resolve().parent / "__pycache__"


def _load_youtube_auth_modules() -> Any:
    """Load auth from .py or fallback .pyc (local-only gitignored modules)."""
    sys.path.insert(0, str(SCRIPTS_ROOT))

    def load_pyc(modname: str, stem: str):
        pyc = CACHE / f"{stem}.cpython-312.pyc"
        if not pyc.is_file():
            raise FileNotFoundError(f"Missing {pyc}")
        loader = SourcelessFileLoader(modname, str(pyc))
        spec = importlib.util.spec_from_loader(modname, loader)
        if spec is None or spec.loader is None:
            raise ImportError(modname)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        return mod

    try:
        from youtube.auth import get_youtube_service  # type: ignore
        from youtube.config import YouTubeSettings  # type: ignore
    except ModuleNotFoundError:
        load_pyc("youtube.secrets_store", "secrets_store")
        load_pyc("youtube.config", "config")
        auth_mod = load_pyc("youtube.auth", "auth")
        get_youtube_service = auth_mod.get_youtube_service  # type: ignore[attr-defined]
        from youtube.config import YouTubeSettings  # type: ignore

    settings = YouTubeSettings.from_env()
    return get_youtube_service(settings.client_secrets, settings.token_path)


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _fetch_uploads_playlist(youtube: Any, *, max_items: int = 500) -> list[dict]:
    ch = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items: list[dict] = []
    token: Optional[str] = None
    while len(items) < max_items:
        resp = (
            youtube.playlistItems()
            .list(
                part="snippet",
                playlistId=uploads_id,
                maxResults=min(50, max_items - len(items)),
                pageToken=token,
            )
            .execute()
        )
        items.extend(resp.get("items", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def _group_duplicates(
    items: list[dict],
    *,
    days: int,
) -> dict[str, list[tuple[str, str, str]]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for it in items:
        sn = it.get("snippet") or {}
        pub = sn.get("publishedAt") or ""
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            continue
        if pub_dt < cutoff:
            continue
        title = sn.get("title") or ""
        vid = (sn.get("resourceId") or {}).get("videoId")
        if not vid:
            continue
        key = _normalize_title(title)
        bucket = groups[key]
        if not any(existing[0] == vid for existing in bucket):
            bucket.append((vid, pub, title))
    return {k: v for k, v in groups.items() if len(v) > 1}


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Find duplicate YouTube uploads by title.")
    p.add_argument("--days", type=int, default=30, help="Look back N days (default 30)")
    p.add_argument(
        "--keep",
        choices=("oldest", "newest"),
        default="oldest",
        help="Which copy to keep when suggesting deletes",
    )
    p.add_argument(
        "--apply-delete",
        action="store_true",
        help="Actually call videos.delete (DANGEROUS — default is list only)",
    )
    p.add_argument(
        "--dry-run-delete",
        action="store_true",
        help="Log videos.delete calls without executing (default with --apply-delete off)",
    )
    args = p.parse_args(argv)

    youtube = _load_youtube_auth_modules()
    items = _fetch_uploads_playlist(youtube)
    dup_groups = _group_duplicates(items, days=args.days)

    extra = sum(len(v) - 1 for v in dup_groups.values())
    LOGGER.info("Duplicate title groups (last %s days): %s", args.days, len(dup_groups))
    LOGGER.info("Extra videos (candidates to remove): %s", extra)

    delete_ids: list[str] = []
    for _key, entries in sorted(dup_groups.items(), key=lambda x: -len(x[1])):
        keep_i = max(range(len(entries)), key=lambda i: entries[i][1]) if args.keep == "newest" else min(
            range(len(entries)), key=lambda i: entries[i][1]
        )
        keep_vid = entries[keep_i][0]
        LOGGER.info("KEEP %s | %s", keep_vid, entries[keep_i][2][:80])
        for i, (vid, pub, title) in enumerate(entries):
            if i == keep_i:
                continue
            LOGGER.info("  DUP %s | %s | %s", vid, pub, title[:80])
            delete_ids.append(vid)

    can_delete = True
    try:
        creds = getattr(youtube, "_http", None)
        if creds is None:
            pass
    except Exception:
        pass

    LOGGER.info(
        "videos.delete: scope https://www.googleapis.com/auth/youtube (or force-ssl) required — "
        "present in default OAuth if token was created with youtube.upload + youtube."
    )

    if not delete_ids:
        return 0

    if args.apply_delete or args.dry_run_delete:
        for vid in delete_ids:
            if args.dry_run_delete and not args.apply_delete:
                LOGGER.info("[DRY-RUN] videos.delete id=%s", vid)
            elif args.apply_delete:
                youtube.videos().delete(id=vid).execute()
                LOGGER.info("Deleted %s", vid)
    else:
        LOGGER.info(
            "List-only mode. To dry-run deletes: --dry-run-delete | To delete: --apply-delete (confirm first)"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
