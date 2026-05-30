# -*- coding: utf-8 -*-
"""One-off: fix Fortnite long metadata (remove Granny bleed)."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from shared.llm_metadata import build_youtube_description, save_metadata_manifest
from youtube.config import BatchConfig
from youtube.manifest import load_batch_yaml
from youtube.schedule_db import ScheduleDB

INBOX = Path.home() / "YOUTUBE" / "inbox" / "fortnite_mobile_20260530"
HASHTAGS = "#abobicaduco #fortnite #fortnitemobile #gameplay #battleroyale #victoryroyale #mobile"

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


def main() -> int:
    batch = load_batch_yaml(INBOX / "batch.yaml")
    clips_manifest: dict = {"clips": {}}
    manifest_rows = []

    for item in FIXED:
        fn = item["file"]
        yt = {
            "title": item["title"][:100],
            "description": item["description"],
            "hashtags": HASHTAGS,
            "tags": item["tags"],
            "source": "manual_fix",
        }
        tt_cap = f"{item['tiktok_title']}\n\n{item['tiktok_body']}\n\n{HASHTAGS}"
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
        manifest_rows.append(
            [fn, yt["title"], desc, "|".join(yt["tags"]), tt_cap]
        )

    save_metadata_manifest(INBOX / "clips_metadata.json", clips_manifest)

    with (INBOX / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file_path", "title", "description", "tags", "tiktok_caption"])
        w.writerows(manifest_rows)

    db = ScheduleDB()
    for item in FIXED:
        path = (INBOX / item["file"]).resolve()
        row = db.get_by_file(path)
        if row:
            db.update_title(row.id, item["title"][:100])
            print("updated DB title", row.id, item["title"][:60])

    pending = Path.home() / "YOUTUBE" / "pending_tiktok" / "fortnite_mobile"
    pending.mkdir(parents=True, exist_ok=True)
    with (pending / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file_path", "caption", "slot_date", "slot_hour", "note"])
        for item in FIXED:
            cap = f"{item['tiktok_title']}\n\n{item['tiktok_body']}\n\n{HASHTAGS}"
            w.writerow([item["file"], cap, "", "", "pending_tiktok_cap_30"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
