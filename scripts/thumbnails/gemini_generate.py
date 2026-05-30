# -*- coding: utf-8 -*-
"""Generate YouTube thumbnails via Google Gemini image API."""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.paths import (
    DEFAULT_FACES_DIR,
    resolve_api_keys_path,
    resolve_faces_dir,
    validate_faces_dir,
)
from thumbnails.prompts import build_prompt, list_known_games

LOGGER = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
TARGET_SIZE = (1280, 720)
DEFAULT_MODEL = "gemini-2.5-flash-image"
FALLBACK_MODELS = ("gemini-2.5-flash-image", "gemini-3.1-flash-image", "gemini-3-pro-image")


def _load_api_keys() -> dict[str, Any]:
    api_keys_path = resolve_api_keys_path()
    if not api_keys_path.is_file():
        return {}
    try:
        data = json.loads(api_keys_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_gemini_api_key() -> tuple[Optional[str], str]:
    """Return (api_key, source_label). Never log the key value."""
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        val = os.environ.get(env_name, "").strip()
        if val:
            return val, env_name

    data = _load_api_keys()
    for key_name in ("google_ai", "gemini", "google"):
        entry = data.get(key_name)
        if isinstance(entry, dict):
            for field in ("api_key", "token", "key"):
                val = str(entry.get(field) or "").strip()
                if val:
                    return val, f"api-keys.json:{key_name}.{field}"

    custom = data.get("custom")
    if isinstance(custom, dict):
        for sub in ("google_gemini", "gemini", "google_ai"):
            entry = custom.get(sub)
            if isinstance(entry, dict):
                val = str(entry.get("api_key") or entry.get("key") or "").strip()
                if val:
                    return val, f"api-keys.json:custom.{sub}.api_key"

    return None, "missing"


def _iter_media(dir_path: Path, extensions: set[str]) -> list[Path]:
    if not dir_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {dir_path}")
    files = [
        p
        for p in sorted(dir_path.iterdir())
        if p.is_file() and p.suffix.lower() in extensions
    ]
    if not files:
        raise FileNotFoundError(f"No matching files in {dir_path} (ext: {sorted(extensions)})")
    return files


def assign_faces(faces: list[Path], count: int) -> list[Path]:
    """Pick `count` distinct face images; cycle only after exhausting the pool once."""
    if count <= 0:
        return []
    if count > len(faces):
        raise ValueError(
            f"Need {count} distinct face photos but only {len(faces)} in faces-dir. "
            "Add more selfies or lower --count."
        )
    return faces[:count]


def _output_path_for_video(video: Path, output_dir: Path) -> Path:
    out_dir = output_dir / "thumbnails"
    return out_dir / f"{video.stem}_thumb.png"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _resize_to_target(path: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        LOGGER.warning("Pillow not installed — skipping resize to %sx%s", *TARGET_SIZE)
        return

    with Image.open(path) as img:
        if img.size == TARGET_SIZE:
            return
        resized = img.convert("RGB").resize(TARGET_SIZE, Image.Resampling.LANCZOS)
        resized.save(path, format="PNG", optimize=True)
    LOGGER.info("Resized %s -> %sx%s", path.name, *TARGET_SIZE)


def _extract_image_bytes(response: Any) -> Optional[bytes]:
    parts = getattr(response, "parts", None)
    if parts is None:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) if content else None
    if not parts:
        return None

    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is not None and getattr(inline, "data", None):
            data = inline.data
            if isinstance(data, str):
                return base64.b64decode(data)
            return bytes(data)
        as_image = getattr(part, "as_image", None)
        if callable(as_image):
            try:
                img = as_image()
                if img is not None:
                    from io import BytesIO

                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    return buf.getvalue()
            except Exception:
                LOGGER.debug("part.as_image() failed", exc_info=True)
    return None


def _build_client(api_key: str):
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai package required. Install: pip install google-genai Pillow"
        ) from exc
    return genai.Client(api_key=api_key)


def _generation_config():
    from google.genai import types

    return types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(
            aspect_ratio="16:9",
        ),
    )


def generate_one(
    *,
    client: Any,
    model: str,
    prompt: str,
    face_path: Path,
    output_path: Path,
    dry_run: bool,
) -> bool:
    if dry_run:
        LOGGER.info(
            "[DRY-RUN] Would generate %s | face=%s | model=%s",
            output_path.name,
            face_path.name,
            model,
        )
        return True

    from PIL import Image

    _ensure_parent(output_path)
    config = _generation_config()
    contents: list[Any] = [prompt, Image.open(face_path)]

    last_err: Optional[Exception] = None
    models_to_try: list[str] = []
    for m in (model, *FALLBACK_MODELS):
        if m not in models_to_try:
            models_to_try.append(m)

    for attempt_model in models_to_try:
        try:
            response = client.models.generate_content(
                model=attempt_model,
                contents=contents,
                config=config,
            )
            raw = _extract_image_bytes(response)
            if not raw:
                raise RuntimeError(f"No image bytes in response ({attempt_model})")
            output_path.write_bytes(raw)
            _resize_to_target(output_path)
            LOGGER.info("Saved thumbnail: %s (model=%s)", output_path, attempt_model)
            return True
        except Exception as exc:
            last_err = exc
            err_text = str(exc)
            LOGGER.warning("Model %s failed: %s", attempt_model, type(exc).__name__)
            if "API_KEY_SERVICE_BLOCKED" in err_text or "PERMISSION_DENIED" in err_text:
                raise RuntimeError(
                    "Gemini API key blocked or missing Generative Language API access. "
                    "Create a key at https://aistudio.google.com/api-keys and ensure billing "
                    "is enabled for image models — see docs/THUMBNAILS.md#troubleshooting"
                ) from exc

    if last_err:
        raise last_err
    return False


def run_generation(
    *,
    faces_dir: Path,
    videos_dir: Path,
    game: str,
    count: Optional[int] = None,
    output_dir: Optional[Path] = None,
    dry_run: bool = False,
    model: str = DEFAULT_MODEL,
    skip_existing: bool = True,
) -> list[Path]:
    validate_faces_dir(faces_dir)
    faces = _iter_media(faces_dir, IMAGE_EXTENSIONS)
    videos = _iter_media(videos_dir, VIDEO_EXTENSIONS)
    n = count if count is not None else len(videos)
    if n > len(videos):
        LOGGER.warning("Count %s > videos %s — using %s videos", n, len(videos), len(videos))
        n = len(videos)

    selected_videos = videos[:n]
    selected_faces = assign_faces(faces, n)
    out_root = output_dir or videos_dir

    api_key, source = resolve_gemini_api_key()
    if not api_key and not dry_run:
        raise RuntimeError(
            "Gemini API key missing. Set GEMINI_API_KEY / GOOGLE_API_KEY or add "
            "google.api_key to %USERPROFILE%\\.secrets\\api-keys.json — see docs/THUMBNAILS.md"
        )
    LOGGER.info("API key source: %s", source)

    client = None
    if not dry_run:
        client = _build_client(api_key)  # type: ignore[arg-type]

    written: list[Path] = []
    for idx, (video, face) in enumerate(zip(selected_videos, selected_faces)):
        dest = _output_path_for_video(video, out_root)
        if skip_existing and dest.is_file() and not dry_run:
            LOGGER.info("Skip existing: %s", dest.name)
            written.append(dest)
            continue

        prompt = build_prompt(game=game, slot_index=idx, video_stem=video.stem)
        ok = generate_one(
            client=client,
            model=model,
            prompt=prompt,
            face_path=face,
            output_path=dest,
            dry_run=dry_run,
        )
        if ok:
            written.append(dest)

    return written


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate YouTube thumbnails via Gemini image API (PT-BR gaming style).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            '  python scripts/generate_thumbnails.py \\\n'
            f'    --faces-dir "%USERPROFILE%\\Pictures\\EU" \\\n'
            '    --videos-dir "%USERPROFILE%\\YOUTUBE\\inbox\\fortnite_mobile_20260530" \\\n'
            '    --game "Fortnite Mobile"\n'
            "\n"
            f"Default --faces-dir: FACES_DIR env, then .secrets/thumbnail_faces/, "
            f"then {DEFAULT_FACES_DIR} (thumbnail selfies only).\n"
        ),
    )
    p.add_argument(
        "--faces-dir",
        type=Path,
        default=None,
        help=(
            "Thumbnail face reference folder (jpg/png selfies only). "
            f"Default: FACES_DIR env, .secrets/thumbnail_faces/, or {DEFAULT_FACES_DIR}"
        ),
    )
    p.add_argument("--videos-dir", type=Path, required=True, help="Folder with MP4 videos")
    p.add_argument("--game", required=True, help=f'Game name (known: {", ".join(list_known_games())})')
    p.add_argument(
        "--count",
        type=int,
        default=None,
        help="Number of thumbnails (default: count .mp4 in videos-dir)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write thumbnails/ here (default: same as --videos-dir)",
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini image model (default: {DEFAULT_MODEL})")
    p.add_argument("--dry-run", action="store_true", help="Print plan only, no API calls")
    p.add_argument("--force", action="store_true", help="Regenerate even if output exists")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        faces_dir = resolve_faces_dir(args.faces_dir)
        paths = run_generation(
            faces_dir=faces_dir,
            videos_dir=args.videos_dir.resolve(),
            game=args.game,
            count=args.count,
            output_dir=args.output_dir.resolve() if args.output_dir else None,
            dry_run=args.dry_run,
            model=args.model,
            skip_existing=not args.force,
        )
    except Exception as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info("Done — %s thumbnail(s) %s", len(paths), "planned" if args.dry_run else "written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
