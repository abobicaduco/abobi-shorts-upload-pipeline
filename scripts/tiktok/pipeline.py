# -*- coding: utf-8 -*-
"""TikTok upload pipeline: plan SQLite slots -> Playwright upload."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional

from youtube.stdio import configure_stdio_utf8
from youtube.timezone_util import get_timezone, now_in_tz

from .auth import run_auth_only
from .config import BatchConfig, DEFAULT_SLOTS, TikTokSettings, load_env_file, DEFAULT_CLIPS_DIR
from .metadata import build_caption_for_clip
from .schedule_db import ScheduleDB, default_db_path
from .scheduler import (
    execute_planned_uploads,
    next_available_slots,
    plan_uploads,
    print_schedule_plan,
    refresh_pending_metadata,
    resume_pending,
    utc_to_local,
)
from .uploader_playwright import SCHEDULE_ONLY, upload_video_playwright

LOGGER = logging.getLogger(__name__)

# Default pipeline mode: always use TikTok schedule UI (never immediate publish).
SCHEDULE_MODE = True


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _parse_slots(raw: str) -> tuple[int, ...]:
    parts = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if not parts:
        raise ValueError("At least one slot hour required")
    return tuple(sorted(set(parts)))


def _smallest_clip(clips_dir: Path) -> Optional[Path]:
    clips = sorted(clips_dir.glob("*.mp4"), key=lambda p: p.stat().st_size)
    return clips[0] if clips else None


def _warn_if_auth_only_with_other_flags(args: argparse.Namespace) -> None:
    extras = [
        name
        for name, active in (
            ("--test-upload", args.test_upload is not None),
            ("--resume", args.resume),
            ("--schedule-only", args.schedule_only),
            ("--refresh-metadata", args.refresh_metadata),
            ("--until-done", args.until_done),
            ("--dry-run", args.dry_run),
        )
        if active
    ]
    if extras:
        LOGGER.warning(
            "--auth-only isolado: ignorando %s nesta execucao.",
            ", ".join(extras),
        )


def run_pipeline(argv: Optional[List[str]] = None) -> int:
    configure_stdio_utf8()
    load_env_file()
    setup_logging()

    p = argparse.ArgumentParser(
        description="Schedule and upload TikTok clips via Playwright (3/day policy).",
    )
    p.add_argument(
        "--auth-only",
        action="store_true",
        help=(
            "Abre Chrome uma vez em tiktok.com/login para login manual (QR); "
            "pressione ENTER no terminal para salvar sessao em "
            "~/.secrets/tiktok_storage_state.json"
        ),
    )
    p.add_argument(
        "--test-upload",
        type=Path,
        metavar="MP4",
        help="Um upload real de teste (agenda no proximo slot do DB; use --post-now para publicar ja)",
    )
    p.add_argument("--clips-dir", type=Path, help="Pasta com clip_*.mp4")
    p.add_argument("--slots", default="16,18,21", help="Horas locais de publicacao")
    p.add_argument("--timezone", default="America/Sao_Paulo")
    p.add_argument("--start-date", help="YYYY-MM-DD primeiro dia de slots")
    p.add_argument("--db", type=Path, help="SQLite tiktok_schedule.db")
    p.add_argument("--dry-run", action="store_true", help="Plano/log sem upload real")
    p.add_argument("--schedule-only", action="store_true", help="So grava slots no SQLite")
    p.add_argument("--resume", action="store_true", help="Retoma pending/failed do SQLite")
    p.add_argument("--upload-limit", type=int, help="Max uploads nesta execucao (default 3)")
    p.add_argument("--until-done", action="store_true", help="Repete lotes ate pending=0")
    p.add_argument("--refresh-metadata", action="store_true", help="Regenera captions pending")
    p.add_argument(
        "--post-now",
        action="store_true",
        help="Publica agora (ignora agendamento UI; padrao e agendar via Creator Center)",
    )
    p.add_argument("--headless", action="store_true", help="Browser sem janela (nao use no login)")
    p.add_argument("--game", default="Granny 2")
    p.add_argument("--source-stem", default="Granny 2 Parte 2")
    p.add_argument(
        "--use-llm",
        action="store_true",
        help="Force local Ollama (Llama) for clip captions",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="Use template captions only (skip Ollama)",
    )
    p.add_argument(
        "--metadata-manifest",
        type=Path,
        help="Path to clips_metadata.json (default: auto in clips folder)",
    )
    p.add_argument(
        "--pre-generate-metadata",
        action="store_true",
        help="Generate clips_metadata.json for all clips and exit",
    )

    args = p.parse_args(argv)

    use_llm: Optional[bool] = None
    if args.no_llm:
        use_llm = False
    elif args.use_llm:
        use_llm = True

    if args.pre_generate_metadata:
        from shared.llm_metadata import is_ollama_available, pregenerate_manifest, resolve_ollama_model

        clips_dir = (args.clips_dir or DEFAULT_CLIPS_DIR).resolve()
        if not clips_dir.is_dir():
            LOGGER.error("Pasta de clipes nao encontrada: %s", clips_dir)
            return 1
        available = is_ollama_available(force_check=True)
        LOGGER.info(
            "Ollama: %s | model=%s",
            "online" if available else "offline",
            resolve_ollama_model() if available else "template",
        )
        pregenerate_manifest(
            clips_dir,
            game=args.game,
            source_stem=args.source_stem,
            use_llm=use_llm if use_llm is not False else False,
        )
        return 0

    if SCHEDULE_ONLY and args.post_now:
        LOGGER.error(
            "--post-now bloqueado: SCHEDULE_ONLY=True em uploader_playwright.py. "
            "Corrija agendamento UI antes de publicar ao vivo."
        )
        return 1
    if SCHEDULE_MODE and not args.post_now:
        LOGGER.debug("Modo agendado (SCHEDULE_MODE=True, sem --post-now).")

    settings = TikTokSettings.from_env(
        clips_dir=args.clips_dir,
        db_path=args.db,
        headless=args.headless and not args.auth_only,
    )
    db_path = args.db or default_db_path()
    db = ScheduleDB(db_path)
    batch = BatchConfig(game=args.game, source_stem=args.source_stem)
    slots = _parse_slots(args.slots)

    if args.auth_only:
        _warn_if_auth_only_with_other_flags(args)
        ok = run_auth_only(settings)
        return 0 if ok else 1

    if args.test_upload:
        clip = args.test_upload.resolve()
        if not clip.is_file():
            smallest = _smallest_clip(settings.clips_dir)
            if smallest:
                LOGGER.warning("Arquivo informado invalido; usando menor clipe: %s", smallest.name)
                clip = smallest
            else:
                LOGGER.error("Clip nao encontrado: %s", args.test_upload)
                return 1
        caption = build_caption_for_clip(
            clip,
            batch,
            use_llm=use_llm,
            metadata_manifest=args.metadata_manifest,
        )
        existing = db.get_by_file(clip)
        row_id: Optional[int] = existing.id if existing else None

        if existing and existing.status in ("scheduled", "uploaded") and existing.post_id:
            LOGGER.info(
                "Test upload skip (ja no DB): %s status=%s post_id=%s",
                clip.name,
                existing.status,
                existing.post_id,
            )
            return 0

        schedule_local = None
        if not args.post_now:
            if existing:
                schedule_local = utc_to_local(existing.scheduled_at_utc, get_timezone(args.timezone))
            else:
                utc_dt, slot_date, hour = next_available_slots(
                    1,
                    slots=slots,
                    tz_name=args.timezone,
                    start_date=now_in_tz(args.timezone).date(),
                    db=db,
                )[0]
                row_id = db.insert_pending(clip, caption, utc_dt, slot_date, hour)
                schedule_local = utc_to_local(utc_dt, get_timezone(args.timezone))

        mode = "post-now" if args.post_now else f"schedule {schedule_local.isoformat() if schedule_local else '?'}"
        LOGGER.info("Test upload (%s): %s", mode, clip.name)
        LOGGER.info("Caption preview:\n%s", caption)

        result = upload_video_playwright(
            settings,
            clip,
            caption,
            dry_run=args.dry_run,
            post_now=args.post_now,
            schedule_at_local=schedule_local,
        )
        if result.ok:
            if not args.dry_run and row_id is not None:
                if result.posted_immediately:
                    db.mark_uploaded(row_id, result.post_id or "test-immediate")
                else:
                    db.mark_scheduled(row_id, result.post_id or "test-scheduled")
            LOGGER.info(
                "Test upload OK post_id=%s immediate=%s",
                result.post_id,
                result.posted_immediately,
            )
            return 0
        LOGGER.error("Test upload falhou: %s", result.error)
        return 1

    if args.resume:
        if args.refresh_metadata:
            n = refresh_pending_metadata(
                db,
                batch,
                use_llm=use_llm,
                metadata_manifest=args.metadata_manifest,
            )
            LOGGER.info("Captions atualizadas: %s", n)

        total_ok = total_failed = total_skipped = 0
        batch_num = 0
        while True:
            batch_num += 1
            summary_before = db.count_summary()
            pending_before = summary_before.get("pending", 0) + summary_before.get("failed", 0)
            if pending_before == 0:
                LOGGER.info("Nada pendente no TikTok DB.")
                break

            ok, failed, skipped = resume_pending(
                db,
                settings,
                batch,
                limit=args.upload_limit,
                post_now=args.post_now,
                tz_name=args.timezone,
            )
            total_ok += ok
            total_failed += failed
            total_skipped += skipped
            summary = db.count_summary()
            LOGGER.info(
                "Batch %s: ok=%s failed=%s skipped=%s | DB: %s",
                batch_num,
                ok,
                failed,
                skipped,
                summary,
            )
            pending_after = summary.get("pending", 0) + summary.get("failed", 0)
            if pending_after == 0 or not args.until_done:
                break
            if ok == 0 and failed == 0:
                break

        LOGGER.info(
            "Resume TikTok: ok=%s failed=%s skipped=%s | DB: %s",
            total_ok,
            total_failed,
            total_skipped,
            db.count_summary(),
        )
        return 1 if total_failed else 0

    clips_dir = (args.clips_dir or settings.clips_dir).resolve()
    if not clips_dir.is_dir():
        LOGGER.error("Pasta de clipes nao encontrada: %s", clips_dir)
        return 1

    clips = sorted(clips_dir.glob("*.mp4"))
    if not clips:
        LOGGER.error("Nenhum MP4 em %s", clips_dir)
        return 1

    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
    else:
        start_date = now_in_tz(args.timezone).date()

    planned = plan_uploads(
        clips,
        batch,
        db,
        slots=slots,
        tz_name=args.timezone,
        start_date=start_date,
        persist=True,
        use_llm=use_llm,
        metadata_manifest=args.metadata_manifest,
    )
    print_schedule_plan(planned, tz_name=args.timezone)

    if args.schedule_only:
        LOGGER.info("Schedule-only: %s clip(s) no DB %s", len(planned), db_path)
        return 0

    upload_limit = args.upload_limit
    if upload_limit is None:
        upload_limit = min(3, len(planned))

    ok, failed, skipped = execute_planned_uploads(
        planned,
        settings,
        db,
        dry_run=args.dry_run,
        limit=upload_limit,
        post_now=args.post_now,
        tz_name=args.timezone,
    )
    LOGGER.info(
        "TikTok pass: ok=%s failed=%s skipped=%s | DB: %s | db_path=%s",
        ok,
        failed,
        skipped,
        db.count_summary(),
        db_path,
    )
    remaining = db.count_summary().get("pending", 0) + db.count_summary().get("failed", 0)
    if remaining:
        LOGGER.warning(
            "%s clip(s) ainda pending — rode amanha: python scripts/tiktok-pipeline.py --resume --upload-limit 3",
            remaining,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_pipeline())
