# -*- coding: utf-8 -*-
"""Fix Fortnite long metadata on YouTube (remove Granny bleed) + local manifest/DB."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from shared.llm_metadata import build_youtube_description, save_metadata_manifest
from youtube.auth import get_youtube_service
from youtube.manifest import load_batch_yaml
from youtube.schedule_db import ScheduleDB

LOGGER = logging.getLogger(__name__)

INBOX = Path.home() / "YOUTUBE" / "inbox" / "fortnite_mobile_20260530"
HASHTAGS = "#abobicaduco #fortnite #fortnitemobile #gameplay #battleroyale #victoryroyale #mobile"
CATEGORY_ID = "20"
DEFAULT_LANGUAGE = "pt"

# Canonical video IDs (from youtube_schedule.db)
CANONICAL_IDS: dict[str, str] = {
    "fortnite_mobile_01.mp4": "KlmXPQi1aCA",
    "fortnite_mobile_02.mp4": "kw0FXbwlSEY",
    "fortnite_mobile_03.mp4": "LaW_ah7WftM",
    "fortnite_mobile_04.mp4": "bVVnwSipiUk",
}
DUPLICATE_02_ID = "3dRr7qHLfwo"

FIXED = [
    {
        "file": "fortnite_mobile_01.mp4",
        "title": "VITORIA INSANA no Fortnite Mobile - Atualizacao 2026 #01 | abobicaduco",
        "description": (
            "Partida completa no Fortnite Mobile com a atualizacao mais recente.\n"
            "Momentos de luta, build e vitoria royale com abobicaduco.\n"
            "Inscreva-se e ative o sininho para mais gameplay mobile!"
        ),
        "tags": [
            "fortnite mobile",
            "fortnite",
            "gameplay",
            "abobicaduco",
            "battle royale",
            "victory royale",
            "mobile gaming",
        ],
        "tiktok_title": "VITORIA INSANA no Fortnite Mobile",
        "tiktok_body": (
            "Partida longa com clutch e final epico na atualizacao.\n"
            "Segue @abobicaduco para mais Fortnite Mobile!"
        ),
    },
    {
        "file": "fortnite_mobile_02.mp4",
        "title": "CLUTCH IMPOSSIVEL - Fortnite Mobile partida completa #02 | abobicaduco",
        "description": (
            "Quase eliminado e ainda assim virei o round.\n"
            "Gameplay Fortnite Mobile em PT-BR com abobicaduco.\n"
            "Deixa o like se curtiu o clutch!"
        ),
        "tags": [
            "fortnite mobile",
            "clutch",
            "gameplay",
            "abobicaduco",
            "battle royale",
        ],
        "tiktok_title": "CLUTCH no limite — Fortnite Mobile",
        "tiktok_body": "1v3 no final e ainda deu certo. Voce teria tentado?",
    },
    {
        "file": "fortnite_mobile_03.mp4",
        "title": "BUILD FIGHT EPICO no Fortnite Mobile #03 | abobicaduco",
        "description": (
            "Duelo de construcao intenso no mobile.\n"
            "Fortnite Mobile gameplay longo — abobicaduco.\n"
            "Comenta qual arma voce usaria nessa situacao!"
        ),
        "tags": [
            "fortnite mobile",
            "build fight",
            "gameplay",
            "abobicaduco",
        ],
        "tiktok_title": "BUILD FIGHT no Fortnite Mobile",
        "tiktok_body": "Parede, rampa e tiro na sequencia. Treino pago.",
    },
    {
        "file": "fortnite_mobile_04.mp4",
        "title": "SOLO VS SQUAD - Fortnite Mobile gameplay longo #04 | abobicaduco",
        "description": (
            "Sozinho contra squad inteira no Fortnite Mobile.\n"
            "Partida longa com rotacao, loot e final caotico.\n"
            "Inscreva-se para a proxima live de mobile!"
        ),
        "tags": [
            "fortnite mobile",
            "solo vs squad",
            "gameplay",
            "abobicaduco",
            "battle royale",
        ],
        "tiktok_title": "SOLO VS SQUAD no Fortnite Mobile",
        "tiktok_body": "4 contra 1 e o final voce precisa ver ate o fim.",
    },
]

FIX_BY_FILE = {item["file"]: item for item in FIXED}


def _fetch_video(youtube: Any, video_id: str) -> dict[str, Any] | None:
    resp = youtube.videos().list(part="snippet,status", id=video_id).execute()
    items = resp.get("items") or []
    return items[0] if items else None


def _update_snippet(
    youtube: Any,
    video_id: str,
    *,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = CATEGORY_ID,
    set_language: bool = True,
    dry_run: bool,
) -> None:
    snippet: dict[str, Any] = {
        "title": title[:100],
        "description": description[:5000],
        "categoryId": category_id,
        "tags": tags[:500],
    }
    if set_language:
        snippet["defaultLanguage"] = DEFAULT_LANGUAGE
        snippet["defaultAudioLanguage"] = DEFAULT_LANGUAGE

    body = {"id": video_id, "snippet": snippet}
    if dry_run:
        print(f"[DRY-RUN] videos.update snippet {video_id} title={title[:50]!r}")
        return
    youtube.videos().update(part="snippet", body=body).execute()
    print(f"OK snippet updated {video_id}")


def _patch_language_only(
    youtube: Any,
    video_id: str,
    snippet: dict[str, Any],
    *,
    dry_run: bool,
) -> None:
    body = {
        "id": video_id,
        "snippet": {
            "title": snippet["title"],
            "description": snippet["description"],
            "categoryId": snippet.get("categoryId") or CATEGORY_ID,
            "tags": snippet.get("tags") or [],
            "defaultLanguage": DEFAULT_LANGUAGE,
            "defaultAudioLanguage": DEFAULT_LANGUAGE,
        },
    }
    if dry_run:
        print(f"[DRY-RUN] videos.update language {video_id}")
        return
    youtube.videos().update(part="snippet", body=body).execute()
    print(f"OK language patched {video_id}")


def _neutralize_duplicate_schedule(youtube: Any, video_id: str, *, dry_run: bool) -> None:
    """Cancel scheduled publish on duplicate — private, no publishAt."""
    status = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
    }
    if dry_run:
        print(f"[DRY-RUN] videos.update status {video_id} -> private, no publishAt")
        return
    youtube.videos().update(
        part="status",
        body={"id": video_id, "status": status},
    ).execute()
    print(f"OK duplicate schedule neutralized {video_id}")


def _looks_like_granny(snippet: dict[str, Any]) -> bool:
    desc = (snippet.get("description") or "").lower()
    tags = [t.lower() for t in (snippet.get("tags") or [])]
    granny_markers = ("granny", "horror", "terror", "susto")
    return any(m in desc for m in granny_markers) or any(
        any(m in t for m in granny_markers) for t in tags
    )


def sync_local_files() -> None:
    batch = load_batch_yaml(INBOX / "batch.yaml")
    clips_manifest: dict = {"clips": {}}

    for item in FIXED:
        fn = item["file"]
        yt = {
            "title": item["title"][:100],
            "description": item["description"],
            "hashtags": HASHTAGS,
            "tags": item["tags"],
            "source": "manual_fix",
        }
        clips_manifest["clips"][fn] = {
            "youtube": yt,
            "tiktok": {
                "title": item["tiktok_title"],
                "description": item["tiktok_body"],
                "hashtags": HASHTAGS,
                "tags": [],
                "source": "manual_fix",
            },
        }
        desc = build_youtube_description(
            yt["description"], HASHTAGS, append_shorts=batch.append_shorts_hashtag
        )
    save_metadata_manifest(INBOX / "clips_metadata.json", clips_manifest)

    with (INBOX / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file_path", "title", "description", "tags", "tiktok_caption"])
        for item in FIXED:
            fn = item["file"]
            yt = clips_manifest["clips"][fn]["youtube"]
            desc = build_youtube_description(
                yt["description"], HASHTAGS, append_shorts=batch.append_shorts_hashtag
            )
            tt = clips_manifest["clips"][fn]["tiktok"]
            cap = f"{tt['title']}\n\n{tt['description']}\n\n{HASHTAGS}"
            w.writerow([fn, yt["title"], desc, "|".join(yt["tags"]), cap])

    db = ScheduleDB()
    for item in FIXED:
        path = (INBOX / item["file"]).resolve()
        row = db.get_by_file(path)
        if row:
            db.update_title(row.id, item["title"][:100])
            print(f"DB title updated id={row.id} video_id={row.video_id}")


def apply_youtube(*, dry_run: bool) -> dict[str, Any]:
    batch = load_batch_yaml(INBOX / "batch.yaml")
    youtube = get_youtube_service()
    report: dict[str, Any] = {"videos": {}, "duplicate": {}}

    # --- #02 canonical: full metadata fix ---
    vid02 = CANONICAL_IDS["fortnite_mobile_02.mp4"]
    item02 = FIX_BY_FILE["fortnite_mobile_02.mp4"]
    before02 = _fetch_video(youtube, vid02)
    if not before02:
        raise RuntimeError(f"Video not found: {vid02}")

    sn_before = before02["snippet"]
    st_before = before02["status"]
    report["videos"][vid02] = {
        "role": "canonical #02",
        "before": {
            "title": sn_before.get("title"),
            "description_preview": (sn_before.get("description") or "")[:120],
            "tags": sn_before.get("tags"),
            "defaultLanguage": sn_before.get("defaultLanguage"),
            "privacy": st_before.get("privacyStatus"),
            "publishAt": st_before.get("publishAt"),
        },
    }

    desc02 = build_youtube_description(
        item02["description"], HASHTAGS, append_shorts=batch.append_shorts_hashtag
    )
    keep_title = sn_before.get("title") or item02["title"]
    if "CLUTCH" in keep_title.upper() and "#02" in keep_title:
        title02 = keep_title
    else:
        title02 = item02["title"]

    _update_snippet(
        youtube,
        vid02,
        title=title02,
        description=desc02,
        tags=item02["tags"],
        dry_run=dry_run,
    )

    after02 = _fetch_video(youtube, vid02) if not dry_run else before02
    sn_after = after02["snippet"] if after02 else sn_before
    report["videos"][vid02]["after"] = {
        "title": title02 if dry_run else sn_after.get("title"),
        "description_preview": desc02[:120],
        "tags": item02["tags"],
        "defaultLanguage": DEFAULT_LANGUAGE,
        "privacy": st_before.get("privacyStatus"),
        "publishAt": st_before.get("publishAt"),
    }

    # --- #01 #03 #04: language patch if missing ---
    for fn in (
        "fortnite_mobile_01.mp4",
        "fortnite_mobile_03.mp4",
        "fortnite_mobile_04.mp4",
    ):
        vid = CANONICAL_IDS[fn]
        current = _fetch_video(youtube, vid)
        if not current:
            report["videos"][vid] = {"error": "not found"}
            continue
        sn = current["snippet"]
        needs_lang = not sn.get("defaultLanguage") or not sn.get("defaultAudioLanguage")
        entry: dict[str, Any] = {
            "role": fn,
            "before": {
                "defaultLanguage": sn.get("defaultLanguage"),
                "defaultAudioLanguage": sn.get("defaultAudioLanguage"),
            },
            "action": "none",
        }
        if needs_lang:
            _patch_language_only(youtube, vid, sn, dry_run=dry_run)
            entry["action"] = "language_patch"
            entry["after"] = {
                "defaultLanguage": DEFAULT_LANGUAGE,
                "defaultAudioLanguage": DEFAULT_LANGUAGE,
            }
        else:
            entry["after"] = entry["before"]
        report["videos"][vid] = entry

    # --- duplicate #02: neutralize schedule (no delete) ---
    dup = _fetch_video(youtube, DUPLICATE_02_ID)
    if dup:
        sn_d = dup["snippet"]
        st_d = dup["status"]
        report["duplicate"] = {
            "video_id": DUPLICATE_02_ID,
            "before": {
                "privacy": st_d.get("privacyStatus"),
                "publishAt": st_d.get("publishAt"),
                "has_fortnite_metadata": not _looks_like_granny(sn_d),
            },
            "action": "neutralize_schedule",
            "recommendation": (
                "Duplicate upload of #02 with correct metadata but same slot. "
                "Schedule cancelled (private, no publishAt). "
                "Delete 3dRr7qHLfwo manually in YouTube Studio when ready."
            ),
        }
        _neutralize_duplicate_schedule(youtube, DUPLICATE_02_ID, dry_run=dry_run)
        if not dry_run:
            dup_after = _fetch_video(youtube, DUPLICATE_02_ID)
            st_a = dup_after["status"] if dup_after else {}
            report["duplicate"]["after"] = {
                "privacy": st_a.get("privacyStatus"),
                "publishAt": st_a.get("publishAt"),
            }
    else:
        report["duplicate"] = {"video_id": DUPLICATE_02_ID, "error": "not found"}

    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--apply-youtube",
        action="store_true",
        help="Push metadata fixes to YouTube API (default: local files + DB only)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="With --apply-youtube, log actions without API writes",
    )
    p.add_argument(
        "--skip-local",
        action="store_true",
        help="Skip clips_metadata.json, manifest.csv, and DB title sync",
    )
    args = p.parse_args()

    if not args.skip_local:
        sync_local_files()

    if args.apply_youtube:
        report = apply_youtube(dry_run=args.dry_run)
        print("\n=== REPORT ===")
        print(json.dumps(report, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
