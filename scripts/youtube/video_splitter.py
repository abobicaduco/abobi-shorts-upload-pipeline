# -*- coding: utf-8 -*-
"""Split long videos into Shorts-sized clips via ffmpeg."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

FORBIDDEN_CHARS_RE = re.compile(r'[<>#|/\\:*?"\n\r\t]')


def resolve_ffmpeg() -> Path:
    """Return ffmpeg executable: FFMPEG_PATH env, PATH, or imageio_ffmpeg bundle."""
    import os
    import shutil

    env = os.environ.get("FFMPEG_PATH", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path

    found = shutil.which("ffmpeg")
    if found:
        return Path(found)

    try:
        import imageio_ffmpeg

        bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if bundled.is_file():
            return bundled
    except ImportError:
        pass

    raise FileNotFoundError(
        "ffmpeg not found. Install ffmpeg, pip install imageio-ffmpeg, or set FFMPEG_PATH."
    )


def probe_duration_seconds(video: Path, ffmpeg: Path) -> float:
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-i",
        str(video),
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = re.search(r"Duration:\s(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not match:
        raise RuntimeError(f"Could not probe duration for {video}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def segment_seconds_for_target(duration_sec: float, target_clips: int) -> int:
    if target_clips < 1:
        target_clips = 1
    raw = duration_sec / target_clips
    # Shorts-friendly window; allow slightly longer segments to hit ~50 clips.
    return max(30, min(90, int(round(raw))))


def sanitize_stem(name: str, max_len: int = 80) -> str:
    cleaned = FORBIDDEN_CHARS_RE.sub("", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:max_len] if cleaned else "clip"


TITLE_HOOKS = (
    "GRANNY APARECEU DO NADA",
    "QUASE FUI PEGO",
    "SUSTO INSANO NO GRANNY 2",
    "FUGA IMPOSSIVEL",
    "NAO ACREDITO NISSO",
    "GRANNY ME PERSEGUINDO",
    "MOMENTO EPICO DE TERROR",
    "ISSO FOI LOUCO DEMAIS",
    "GRANDPA ME PEGOU",
    "ESCONDERIJO PERIGOSO",
    "ARMADILHA DA GRANNY",
    "QUASE ESCAPEI",
    "SUSTO DE LEVE... NAO",
    "ABOBICADUCO EM PANICO",
    "GRANNY 2 ME ASSUSTOU",
    "JOGADA INSANA",
    "NAO OLHE ATRAS",
)

DESC_HOOKS = (
    "Mais um clipe insano de terror no asilo — voce vai se arrepiar!",
    "Sustos, perseguicoes e fugas impossiveis no Granny 2!",
    "Voce nao vai acreditar no que aconteceu nesta partida!",
    "Granny e Grandpa no encalco — sobrevivencia pura!",
    "Momento tenso demais no gameplay de horror!",
    "O susto veio do nada neste clipe de Granny 2!",
)


def extract_clip_part(title: str, file_path: Optional[Path] = None) -> int:
    """Parse clip number from title (#NN) or filename suffix (_NNN)."""
    match = re.search(r"#(\d{1,3})", title)
    if match:
        return int(match.group(1))
    if file_path is not None:
        match = re.search(r"_(\d{3})\.mp4$", file_path.name, re.IGNORECASE)
        if match:
            return int(match.group(1)) + 1
    return 1


def generate_clip_title(part: int, source_stem: str, *, game: str = "Granny 2") -> str:
    hook = TITLE_HOOKS[(part - 1) % len(TITLE_HOOKS)]
    title = f"{hook} - {game} #{part:02d} | abobicaduco"
    if len(title) > 100:
        title = f"{hook} - {game} #{part:02d}"
    return title[:100]


def generate_clip_description(part: int, source_stem: str, *, game: str = "Granny 2") -> str:
    hook = DESC_HOOKS[(part - 1) % len(DESC_HOOKS)]
    return (
        f"Parte {part:02d} — {hook}\n"
        f"Gameplay de {game} com abobicaduco: sobrevivencia, sustos e momentos epicos.\n"
        f"Inscreva-se e ative o sininho para nao perder o proximo clipe!"
    )


def split_video(
    input_path: Path,
    output_dir: Path,
    *,
    target_clips: int = 50,
    segment_sec: Optional[int] = None,
    ffmpeg: Optional[Path] = None,
    force: bool = False,
) -> list[Path]:
    """Split input into MP4 segments; returns sorted clip paths."""
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "split_manifest.json"
    existing = sorted(output_dir.glob("clip_*.mp4"))
    if existing and not force:
        LOGGER.info(
            "Output dir already has %s clip(s); reusing (use force=True to re-split).",
            len(existing),
        )
        return existing

    if force and existing:
        for clip in existing:
            clip.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)

    ff = ffmpeg or resolve_ffmpeg()
    duration = probe_duration_seconds(input_path, ff)
    seg = segment_sec or segment_seconds_for_target(duration, target_clips)
    expected = max(1, int(duration // seg) + (1 if duration % seg > 1 else 0))

    stem = sanitize_stem(input_path.stem)
    pattern = str(output_dir / f"clip_{stem}_%03d.mp4")

    cmd = [
        str(ff),
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0",
        "-c",
        "copy",
        "-f",
        "segment",
        "-segment_time",
        str(seg),
        "-reset_timestamps",
        "1",
        pattern,
    ]
    LOGGER.info(
        "Splitting %s (%.1fs) -> ~%s clips of %ss with %s",
        input_path.name,
        duration,
        expected,
        seg,
        ff.name,
    )
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        LOGGER.error("ffmpeg stderr: %s", proc.stderr[-4000:])
        raise RuntimeError(f"ffmpeg split failed (exit {proc.returncode})")

    clips = sorted(output_dir.glob(f"clip_{stem}_*.mp4"))
    if not clips:
        clips = sorted(output_dir.glob("clip_*.mp4"))

    meta = {
        "source": str(input_path),
        "duration_sec": duration,
        "segment_sec": seg,
        "clip_count": len(clips),
        "ffmpeg": str(ff),
    }
    manifest_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    LOGGER.info("Split complete: %s clip(s) in %s", len(clips), output_dir)
    return clips
