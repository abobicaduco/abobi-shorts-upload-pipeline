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
from youtube.fix_video_metadata import (
    VideoMetadataSpec,
    apply_metadata_specs,
    fetch_video,
    neutralize_scheduled_duplicate,
    print_reports_json,
    reports_to_dict,
    snippet_summary,
)
from youtube.manifest import load_batch_yaml
from youtube.schedule_db import ScheduleDB

LOGGER = logging.getLogger(__name__)

INBOX = Path.home() / "YOUTUBE" / "inbox" / "fortnite_mobile_20260530"
HASHTAGS = (
    "#abobicaduco #fortnite #fortnitemobile #gameplay #battleroyale "
    "#victoryroyale #mobilegaming"
)
CATEGORY_ID = "20"

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
        "part": "01",
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
            "vitoria royale",
            "atualizacao fortnite",
            "fortnite brasil",
            "gameplay mobile",
            "partida completa",
        ],
        "tiktok_title": "VITORIA INSANA no Fortnite Mobile",
        "tiktok_body": (
            "Partida longa com clutch e final epico na atualizacao.\n"
            "Segue @abobicaduco para mais Fortnite Mobile!"
        ),
    },
    {
        "file": "fortnite_mobile_02.mp4",
        "part": "02",
        "title": "CLUTCH IMPOSSIVEL - Fortnite Mobile partida completa #02 | abobicaduco",
        "description": (
            "Quase eliminado e ainda assim virei o round.\n"
            "Gameplay Fortnite Mobile em PT-BR com abobicaduco.\n"
            "Deixa o like se curtiu o clutch!"
        ),
        "tags": [
            "fortnite mobile",
            "fortnite",
            "clutch",
            "gameplay",
            "abobicaduco",
            "battle royale",
            "victory royale",
            "mobile gaming",
            "1v3 clutch",
            "comeback",
            "fortnite brasil",
            "partida completa",
            "gameplay mobile",
        ],
        "tiktok_title": "CLUTCH no limite — Fortnite Mobile",
        "tiktok_body": "1v3 no final e ainda deu certo. Voce teria tentado?",
    },
    {
        "file": "fortnite_mobile_03.mp4",
        "part": "03",
        "title": "BUILD FIGHT EPICO no Fortnite Mobile #03 | abobicaduco",
        "description": (
            "Duelo de construcao intenso no mobile.\n"
            "Fortnite Mobile gameplay longo — abobicaduco.\n"
            "Comenta qual arma voce usaria nessa situacao!"
        ),
        "tags": [
            "fortnite mobile",
            "fortnite",
            "build fight",
            "gameplay",
            "abobicaduco",
            "battle royale",
            "victory royale",
            "mobile gaming",
            "construcao fortnite",
            "duelo build",
            "fortnite brasil",
            "gameplay mobile",
            "partida completa",
        ],
        "tiktok_title": "BUILD FIGHT no Fortnite Mobile",
        "tiktok_body": "Parede, rampa e tiro na sequencia. Treino pago.",
    },
    {
        "file": "fortnite_mobile_04.mp4",
        "part": "04",
        "title": "SOLO VS SQUAD - Fortnite Mobile gameplay longo #04 | abobicaduco",
        "description": (
            "Sozinho contra squad inteira no Fortnite Mobile.\n"
            "Partida longa com rotacao, loot e final caotico.\n"
            "Inscreva-se para a proxima live de mobile!"
        ),
        "tags": [
            "fortnite mobile",
            "fortnite",
            "solo vs squad",
            "gameplay",
            "abobicaduco",
            "battle royale",
            "victory royale",
            "mobile gaming",
            "squad wipe",
            "fortnite brasil",
            "gameplay mobile",
            "partida completa",
            "mobile royale",
        ],
        "tiktok_title": "SOLO VS SQUAD no Fortnite Mobile",
        "tiktok_body": "4 contra 1 e o final voce precisa ver ate o fim.",
    },
]

FIX_BY_FILE = {item["file"]: item for item in FIXED}


def _build_specs() -> list[VideoMetadataSpec]:
    specs: list[VideoMetadataSpec] = []
    for item in FIXED:
        fn = item["file"]
        specs.append(
            VideoMetadataSpec(
                video_id=CANONICAL_IDS[fn],
                title=item["title"],
                description_body=item["description"],
                tags=item["tags"],
                role=f"canonical #{item['part']} ({fn})",
                category_id=CATEGORY_ID,
            )
        )
    return specs


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


def apply_youtube(*, dry_run: bool, force: bool) -> dict[str, Any]:
    batch = load_batch_yaml(INBOX / "batch.yaml")
    youtube = get_youtube_service()

    def _desc(spec: VideoMetadataSpec) -> str:
        return build_youtube_description(
            spec.description_body,
            HASHTAGS,
            append_shorts=batch.append_shorts_hashtag,
        )

    reports = apply_metadata_specs(
        youtube,
        _build_specs(),
        build_description=_desc,
        dry_run=dry_run,
        force=force,
        expected_tag_count_min=10,
        required_hashtag_substrings=("#mobilegaming",),
    )
    payload: dict[str, Any] = reports_to_dict(reports)

    dup = fetch_video(youtube, DUPLICATE_02_ID)
    dup_report: dict[str, Any] = {"video_id": DUPLICATE_02_ID}
    if dup:
        sn_d, st_d = dup["snippet"], dup["status"]
        dup_report["before"] = snippet_summary(sn_d, st_d)
        dup_report["action"] = "neutralize_schedule"
        dup_report["recommendation"] = (
            "Upload duplicado do slot #02 com metadados corretos. "
            "Mantido private sem publishAt. "
            "Recomendado: apagar 3dRr7qHLfwo no YouTube Studio apos confirmar kw0FXbwlSEY."
        )
        neutralize_scheduled_duplicate(youtube, DUPLICATE_02_ID, dry_run=dry_run)
        if not dry_run:
            dup_after = fetch_video(youtube, DUPLICATE_02_ID)
            if dup_after:
                dup_report["after"] = snippet_summary(
                    dup_after["snippet"], dup_after["status"]
                )
    else:
        dup_report["error"] = "not found"
    payload["duplicate"] = dup_report
    return payload


def print_pt_table(payload: dict[str, Any], *, youtube: Any | None = None) -> None:
    print("\n=== TABELA PT (canonical) ===")
    print("| video_id | parte | acao | titulo aplicado | tags | mobilegaming |")
    print("|----------|-------|------|-----------------|------|--------------|")
    for item in FIXED:
        vid = CANONICAL_IDS[item["file"]]
        entry = (payload.get("videos") or {}).get(vid, {})
        action = entry.get("action", "?")
        title = item["title"][:100]
        n_tags = len(item["tags"])
        has_mobile = False
        if youtube is not None:
            current = fetch_video(youtube, vid)
            if current:
                sn = current["snippet"]
                title = sn.get("title") or title
                n_tags = len(sn.get("tags") or [])
                has_mobile = "#mobilegaming" in (sn.get("description") or "").lower()
        print(
            f"| {vid} | #{item['part']} | {action} | {title[:65]} | {n_tags} | "
            f"{'sim' if has_mobile else 'nao'} |"
        )


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
        "--force",
        action="store_true",
        help="Update all canonical snippets even if already OK",
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
        report = apply_youtube(dry_run=args.dry_run, force=args.force)
        print("\n=== REPORT ===")
        print_reports_json(report)
        yt_svc = None if args.dry_run else get_youtube_service()
        print_pt_table(report, youtube=yt_svc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
