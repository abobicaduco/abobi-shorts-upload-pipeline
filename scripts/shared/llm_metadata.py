# -*- coding: utf-8 -*-
"""Generate clip metadata via local Ollama (Llama) with template fallback."""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from youtube.video_splitter import (
    FORBIDDEN_CHARS_RE,
    generate_clip_description,
    generate_clip_title,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
MANIFEST_FILENAME = "clips_metadata.json"
OLLAMA_TIMEOUT_SEC = 90

DEFAULT_YOUTUBE_TAGS = [
    "granny 2",
    "granny",
    "granny horror",
    "horror",
    "gameplay",
    "abobicaduco",
    "shorts",
    "terror",
    "survival",
    "susto",
    "jogo de terror",
    "horror game",
]

DEFAULT_HASHTAGS = (
    "#abobicaduco #granny2 #granny #gameplay #horror #shorts #terror #susto"
)

_ollama_available: Optional[bool] = None
_resolved_model: Optional[str] = None


def _ollama_base_url() -> str:
    raw = (
        os.environ.get("OLLAMA_HOST", "").strip()
        or os.environ.get("OLLAMA_URL", "").strip()
        or "http://localhost:11434"
    )
    if not raw.startswith("http"):
        raw = f"http://{raw}"
    return raw.rstrip("/")


def _http_get_json(path: str, *, timeout: int = 8) -> dict[str, Any]:
    req = urllib.request.Request(f"{_ollama_base_url()}{path}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_ollama_models() -> list[str]:
    try:
        data = _http_get_json("/api/tags")
        models = data.get("models") or []
        return [str(m.get("name", "")).strip() for m in models if m.get("name")]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []


def is_ollama_available(*, force_check: bool = False) -> bool:
    global _ollama_available
    if not force_check and _ollama_available is not None:
        return _ollama_available
    models = list_ollama_models()
    _ollama_available = bool(models)
    return _ollama_available


def resolve_ollama_model() -> str:
    global _resolved_model
    if _resolved_model:
        return _resolved_model

    preferred = os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip()
    models = list_ollama_models()
    if preferred and preferred in models:
        _resolved_model = preferred
        return _resolved_model
    if preferred:
        for name in models:
            if name.startswith(f"{preferred}:") or name == preferred:
                _resolved_model = name
                return _resolved_model
    if DEFAULT_OLLAMA_MODEL in models:
        _resolved_model = DEFAULT_OLLAMA_MODEL
        return _resolved_model
    if models:
        _resolved_model = models[0]
        return _resolved_model
    _resolved_model = preferred or DEFAULT_OLLAMA_MODEL
    return _resolved_model


def _sanitize_title(title: str, *, max_len: int = 100) -> str:
    cleaned = FORBIDDEN_CHARS_RE.sub("", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return "Granny 2 gameplay abobicaduco"
    return cleaned[:max_len]


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM output is not a JSON object")
    return data


def _normalize_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,;#]+", raw)
        return [p.strip().lower() for p in parts if p.strip()]
    if isinstance(raw, list):
        return [str(t).strip().lower() for t in raw if str(t).strip()]
    return []


def _normalize_hashtags(raw: Any) -> str:
    if not raw:
        return DEFAULT_HASHTAGS
    text = str(raw).strip()
    tags = re.findall(r"#\w+", text)
    if tags:
        return " ".join(dict.fromkeys(tags))
    words = [w.strip() for w in re.split(r"[\s,;]+", text) if w.strip()]
    return " ".join(f"#{w.lstrip('#')}" for w in words)


def _template_metadata(
    part_number: int,
    *,
    game: str,
    platform: Literal["youtube", "tiktok"],
    source_stem: str,
) -> dict[str, Any]:
    title = generate_clip_title(part_number, source_stem, game=game)
    description = generate_clip_description(part_number, source_stem, game=game)
    hashtags = DEFAULT_HASHTAGS
    tags = list(DEFAULT_YOUTUBE_TAGS)
    if platform == "tiktok":
        return {
            "title": title,
            "description": description,
            "hashtags": hashtags,
            "tags": [],
            "source": "template",
        }
    return {
        "title": title,
        "description": description,
        "hashtags": hashtags,
        "tags": tags,
        "source": "template",
    }


def _build_prompt(
    *,
    clip_index: int,
    part_number: int,
    game: str,
    platform: Literal["youtube", "tiktok"],
    clip_filename: Optional[str],
) -> str:
    platform_rules = (
        "YouTube Shorts: titulo maximo 100 caracteres, SEM caracteres < > # | / \\ : * ? \" "
        "Tags separadas (lista JSON). Descricao com CTA inscricao."
        if platform == "youtube"
        else "TikTok: titulo curto vai na PRIMEIRA linha da descricao (campo unico). "
        "Sem campo titulo separado na UI — tudo na caixa de descricao."
    )
    hooks = (
        "SUSTO, FUGA, GRANNY APARECEU, QUASE FUI PEGO, MOMENTO EPICO, "
        "NAO OLHE ATRAS, ARMADILHA, ESCONDERIJO, GRANDPA, ABOBICADUCO EM PANICO"
    )
    fname = clip_filename or f"clip_{clip_index:03d}.mp4"
    is_long = "fortnite" in game.lower()
    clip_kind = "video longo no YouTube/TikTok" if is_long else "Shorts"
    return f"""Voce e copywriter SEO para o canal abobicaduco (gameplay PT-BR).
Gere metadados UNICOS e variados para um clipe de {game} ({clip_kind}).

Contexto:
- clip_index: {clip_index}
- parte/episodio: #{part_number:02d}
- arquivo: {fname}
- plataforma: {platform}
- canal: @abobicaduco
- idioma: portugues brasileiro (PT-BR)
- tom: terror, suspense, susto, gameplay real

Regras {platform}:
{platform_rules}

Use hooks variados inspirados em: {hooks}.
Nao repita exatamente o mesmo padrao de titulos anteriores.
Inclua "abobicaduco" ou "Granny 2" quando couber naturalmente.

Responda APENAS com JSON valido (sem markdown, sem texto extra):
{{
  "title": "titulo chamativo",
  "description": "corpo da descricao em PT-BR (2-4 frases + CTA inscricao)",
  "hashtags": "#abobicaduco #granny2 #horror #terror #gameplay #susto",
  "tags": ["granny 2", "horror", "gameplay", "abobicaduco", "terror", "shorts"]
}}

Para TikTok, tags deve ser lista vazia [].
JSON:"""


def _call_ollama(prompt: str) -> str:
    model = resolve_ollama_model()
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.85, "num_predict": 512},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{_ollama_base_url()}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_SEC) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("response") or "")


def generate_clip_metadata(
    clip_index: int,
    part_number: int,
    *,
    game: str = "Granny 2",
    platform: Literal["youtube", "tiktok"] = "youtube",
    clip_filename: Optional[str] = None,
    source_stem: str = "Granny 2 Parte 2",
    use_llm: bool = True,
) -> dict[str, Any]:
    """Return title, description, hashtags, tags (+ source: llm|template)."""
    if not use_llm or not is_ollama_available():
        return _template_metadata(
            part_number,
            game=game,
            platform=platform,
            source_stem=source_stem,
        )

    prompt = _build_prompt(
        clip_index=clip_index,
        part_number=part_number,
        game=game,
        platform=platform,
        clip_filename=clip_filename,
    )
    try:
        raw = _call_ollama(prompt)
        parsed = _extract_json_object(raw)
        title = _sanitize_title(str(parsed.get("title") or ""), max_len=100)
        description = str(parsed.get("description") or "").strip()
        if not description:
            description = generate_clip_description(part_number, source_stem, game=game)
        hashtags = _normalize_hashtags(parsed.get("hashtags"))
        tags = _normalize_tags(parsed.get("tags"))
        if platform == "youtube" and not tags:
            tags = list(DEFAULT_YOUTUBE_TAGS)
        if platform == "tiktok":
            tags = []
        if not title:
            title = generate_clip_title(part_number, source_stem, game=game)
        LOGGER.debug(
            "LLM metadata clip=%s part=%s platform=%s title=%r",
            clip_index,
            part_number,
            platform,
            title[:60],
        )
        return {
            "title": title,
            "description": description,
            "hashtags": hashtags,
            "tags": tags,
            "source": "llm",
        }
    except Exception as exc:
        LOGGER.warning(
            "Ollama metadata failed (clip=%s part=%s): %s — using template",
            clip_index,
            part_number,
            exc,
        )
        return _template_metadata(
            part_number,
            game=game,
            platform=platform,
            source_stem=source_stem,
        )


def build_youtube_description(body: str, hashtags: str, *, append_shorts: bool = True) -> str:
    parts: list[str] = []
    if body.strip():
        parts.append(body.strip())
    if hashtags.strip():
        parts.append(hashtags.strip())
    if append_shorts and "#Shorts" not in " ".join(parts):
        parts.append("#Shorts")
    return "\n\n".join(parts)


def build_tiktok_caption(title: str, hook: str, hashtags: str) -> str:
    parts: list[str] = []
    if title.strip():
        parts.append(title.strip())
    if hook.strip() and hook.strip() != title.strip():
        parts.append(hook.strip())
    if hashtags.strip():
        parts.append(hashtags.strip())
    return "\n\n".join(parts)


def manifest_path_for_dir(clips_dir: Path) -> Path:
    return clips_dir.resolve() / MANIFEST_FILENAME


def load_metadata_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        LOGGER.warning("Invalid metadata manifest %s: %s", path, exc)
        return {}


def save_metadata_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _manifest_clip_entry(
    manifest: dict[str, Any],
    clip_filename: str,
    platform: Literal["youtube", "tiktok"],
) -> Optional[dict[str, Any]]:
    clips = manifest.get("clips")
    if not isinstance(clips, dict):
        return None
    entry = clips.get(clip_filename)
    if not isinstance(entry, dict):
        return None
    platform_data = entry.get(platform)
    if isinstance(platform_data, dict):
        return platform_data
    if platform == "youtube" and any(k in entry for k in ("title", "description")):
        return entry
    return None


def resolve_clip_metadata(
    clip_index: int,
    part_number: int,
    *,
    game: str = "Granny 2",
    platform: Literal["youtube", "tiktok"],
    clip_path: Optional[Path] = None,
    source_stem: str = "Granny 2 Parte 2",
    use_llm: Optional[bool] = None,
    manifest: Optional[dict[str, Any]] = None,
    manifest_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Manifest first, then Ollama (if enabled), then template."""
    clip_filename = clip_path.name if clip_path else None

    if manifest is None and manifest_path and manifest_path.is_file():
        manifest = load_metadata_manifest(manifest_path)

    if manifest and clip_filename:
        cached = _manifest_clip_entry(manifest, clip_filename, platform)
        if cached:
            result = {
                "title": _sanitize_title(str(cached.get("title") or "")),
                "description": str(cached.get("description") or "").strip(),
                "hashtags": _normalize_hashtags(cached.get("hashtags")),
                "tags": _normalize_tags(cached.get("tags")),
                "source": "manifest",
            }
            if platform == "tiktok":
                result["tags"] = []
            if not result["title"]:
                result["title"] = generate_clip_title(part_number, source_stem, game=game)
            if not result["description"]:
                result["description"] = generate_clip_description(
                    part_number, source_stem, game=game
                )
            return result

    if use_llm is None:
        use_llm = is_ollama_available()

    return generate_clip_metadata(
        clip_index,
        part_number,
        game=game,
        platform=platform,
        clip_filename=clip_filename,
        source_stem=source_stem,
        use_llm=use_llm,
    )


def _part_from_clip_path(clip_path: Path) -> int:
    match = re.search(r"_(\d{3})\.mp4$", clip_path.name, re.IGNORECASE)
    if match:
        return int(match.group(1)) + 1
    return 1


def pregenerate_manifest(
    clips_dir: Path,
    *,
    game: str = "Granny 2",
    source_stem: str = "Granny 2 Parte 2",
    use_llm: bool = True,
    limit: Optional[int] = None,
) -> Path:
    clips = sorted(clips_dir.glob("*.mp4"))
    if limit is not None:
        clips = clips[:limit]

    manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": resolve_ollama_model() if use_llm and is_ollama_available() else "template",
        "ollama_url": _ollama_base_url(),
        "game": game,
        "source_stem": source_stem,
        "clips": {},
    }

    for clip_index, clip_path in enumerate(clips, start=1):
        part_number = _part_from_clip_path(clip_path)
        yt = generate_clip_metadata(
            clip_index,
            part_number,
            game=game,
            platform="youtube",
            clip_filename=clip_path.name,
            source_stem=source_stem,
            use_llm=use_llm,
        )
        tt = generate_clip_metadata(
            clip_index,
            part_number,
            game=game,
            platform="tiktok",
            clip_filename=clip_path.name,
            source_stem=source_stem,
            use_llm=use_llm,
        )
        manifest["clips"][clip_path.name] = {
            "clip_index": clip_index,
            "part_number": part_number,
            "youtube": yt,
            "tiktok": tt,
        }
        LOGGER.info(
            "[%s/%s] %s | yt=%s tt=%s",
            clip_index,
            len(clips),
            clip_path.name,
            yt.get("source"),
            tt.get("source"),
        )

    out_path = manifest_path_for_dir(clips_dir)
    save_metadata_manifest(out_path, manifest)
    LOGGER.info("Saved metadata manifest: %s (%s clips)", out_path, len(clips))
    return out_path


def _parse_use_llm_flags(use_llm: bool, no_llm: bool) -> Optional[bool]:
    if no_llm:
        return False
    if use_llm:
        return True
    return None


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    scripts_dir = Path(__file__).resolve().parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    p = argparse.ArgumentParser(
        description="Pre-generate clips_metadata.json via local Ollama (Llama).",
    )
    p.add_argument("--clips-dir", type=Path, required=True, help="Folder with clip_*.mp4")
    p.add_argument("--game", default="Granny 2")
    p.add_argument("--source-stem", default="Granny 2 Parte 2")
    p.add_argument("--limit", type=int, help="Max clips to process")
    p.add_argument("--use-llm", action="store_true", help="Force Ollama (fail -> template per clip)")
    p.add_argument("--no-llm", action="store_true", help="Template only")
    p.add_argument(
        "--sample",
        type=int,
        metavar="PART",
        help="Print sample metadata for part number (e.g. 3 for clip 003)",
    )

    args = p.parse_args(argv)
    use_llm = _parse_use_llm_flags(args.use_llm, args.no_llm)
    force_llm = use_llm if use_llm is not None else True

    if args.sample is not None:
        meta = generate_clip_metadata(
            args.sample,
            args.sample,
            game=args.game,
            platform="youtube",
            clip_filename=f"clip_sample_{args.sample:03d}.mp4",
            source_stem=args.source_stem,
            use_llm=force_llm if use_llm is not False else False,
        )
        print(json.dumps(meta, indent=2, ensure_ascii=False))
        return 0

    clips_dir = args.clips_dir.resolve()
    if not clips_dir.is_dir():
        LOGGER.error("Clips dir not found: %s", clips_dir)
        return 1

    available = is_ollama_available(force_check=True)
    LOGGER.info(
        "Ollama: %s | url=%s | model=%s",
        "online" if available else "offline",
        _ollama_base_url(),
        resolve_ollama_model() if available else "(n/a)",
    )

    effective_use_llm = force_llm if use_llm is not False else False
    if use_llm is None and not available:
        LOGGER.warning("Ollama offline — generating template metadata only")
        effective_use_llm = False

    pregenerate_manifest(
        clips_dir,
        game=args.game,
        source_stem=args.source_stem,
        use_llm=effective_use_llm,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
