# -*- coding: utf-8 -*-
"""Generate YouTube thumbnails via gemini.google.com (browser + Gemini Pro session).

Uses Playwright with saved storage_state — no Generative Language API key required.
UI selectors are best-effort; page.evaluate fallbacks when locators fail.
"""
from __future__ import annotations

import argparse
import logging
import re
import subprocess
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import sys

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from thumbnails.gemini_generate import (
    TARGET_SIZE,
    _ensure_parent,
    _iter_media,
    _output_path_for_video,
    _resize_to_target,
    assign_faces,
)
from thumbnails.prompts import build_prompt, list_known_games

LOGGER = logging.getLogger(__name__)

GEMINI_APP_URL = "https://gemini.google.com/app"
GEMINI_HOME_URL = "https://gemini.google.com/"

_PW_WINDOW_WIDTH = 1920
_PW_WINDOW_HEIGHT = 1080

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

TRACKED_RESOURCE_TYPES = frozenset({"fetch", "xhr", "websocket"})
GEMINI_RPC_HOST_FRAGMENTS = (
    "gemini.google.com",
    "bard.google.com",
    "alkalimakersuite-pa.clients6.google.com",
    "generativelanguage.googleapis.com",
)
NOISE_URL_FRAGMENTS = ("google-analytics", "gstatic", "doubleclick", "googletagmanager")

_SENSITIVE_QUERY_KEYS = frozenset(
    {"key", "auth", "token", "at", "rt", "f.sid", "bl", "f.req"}
)
_SENSITIVE_HEADER_PREFIXES = ("authorization", "cookie", "x-goog-", "x-client-data")

_AUTH_ONLY_ACTIVE = False

try:
    from playwright.sync_api import BrowserContext, Page, sync_playwright
except ImportError as exc:
    sync_playwright = None  # type: ignore[assignment,misc]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def resolve_storage_state_path() -> Path:
    return Path.home() / ".secrets" / "gemini_storage_state.json"


def resolve_browser_profile() -> Path:
    return Path.home() / ".secrets" / "browser-profile-gemini"


def resolve_network_log_path() -> Path:
    return Path.home() / ".secrets" / "gemini_network.log"


_LOGGED_IN_JS = """
() => {
  const url = location.href.toLowerCase();
  if (url.includes('accounts.google.com/signin')) return false;
  if (url.includes('/app') && !url.includes('/signin')) return true;
  const sel = [
    'rich-textarea',
    'div[contenteditable="true"]',
    'textarea[aria-label]',
    '[data-test-id="prompt-textarea"]',
    '.ql-editor',
  ];
  for (const s of sel) {
    const el = document.querySelector(s);
    if (el && el.offsetParent !== null) return true;
  }
  const imgs = document.querySelectorAll('img[src*="googleusercontent"], img[alt*="Gemini"]');
  return imgs.length > 0 && url.includes('gemini.google.com');
}
"""

_FIND_PROMPT_INPUT_JS = """
() => {
  const candidates = [
    ...document.querySelectorAll('rich-textarea'),
    ...document.querySelectorAll('div[contenteditable="true"]'),
    ...document.querySelectorAll('textarea'),
    ...document.querySelectorAll('.ql-editor'),
  ];
  for (const el of candidates) {
    if (!el || el.offsetParent === null) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 20) continue;
    return el;
  }
  return null;
}
"""

_SET_PROMPT_JS = """
(el, text) => {
  if (!el) return false;
  el.focus();
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }
  if (el.isContentEditable) {
    el.textContent = text;
    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text }));
    return true;
  }
  return false;
}
"""

_SUBMIT_PROMPT_JS = """
() => {
  const labels = ['send', 'enviar', 'submit', 'gerar', 'generate'];
  const buttons = [...document.querySelectorAll('button, [role="button"]')];
  for (const btn of buttons) {
    const t = (btn.getAttribute('aria-label') || btn.textContent || '').toLowerCase();
    if (labels.some(l => t.includes(l))) {
      btn.click();
      return 'button';
    }
  }
  const form = document.querySelector('form');
  if (form) {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    return 'form';
  }
  return null;
}
"""

_FIND_FILE_INPUT_JS = """
() => {
  const inputs = [...document.querySelectorAll('input[type="file"]')];
  for (const inp of inputs) {
    if (inp.offsetParent !== null || inp.getAttribute('accept')) return inp;
  }
  return inputs[0] || null;
}
"""

_FILL_PROMPT_COMBINED_JS = """
(text) => {
  const candidates = [
    ...document.querySelectorAll('rich-textarea'),
    ...document.querySelectorAll('div[contenteditable="true"]'),
    ...document.querySelectorAll('textarea'),
    ...document.querySelectorAll('.ql-editor'),
  ];
  let el = null;
  for (const c of candidates) {
    if (!c || c.offsetParent === null) continue;
    const r = c.getBoundingClientRect();
    if (r.width < 80 || r.height < 20) continue;
    el = c;
    break;
  }
  if (!el) return false;
  el.focus();
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }
  if (el.isContentEditable) {
    el.textContent = text;
    el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text }));
    return true;
  }
  return false;
}
"""

_LATEST_IMAGE_JS = """
() => {
  const imgs = [...document.querySelectorAll('img')];
  const scored = imgs
    .map(img => {
      const src = img.currentSrc || img.src || '';
      if (!src || src.startsWith('data:image/svg')) return null;
      const r = img.getBoundingClientRect();
      if (r.width < 200 || r.height < 120) return null;
      return { img, area: r.width * r.height, src };
    })
    .filter(Boolean);
  scored.sort((a, b) => b.area - a.area);
  return scored.length ? scored[0].src : null;
}
"""


@dataclass
class GeminiWebSettings:
    storage_state: Path
    browser_profile: Path
    headless: bool = False
    sniff_network: bool = False
    network_log: Path = resolve_network_log_path()

    @classmethod
    def from_args(cls, *, headless: bool = False, sniff_network: bool = False) -> GeminiWebSettings:
        return cls(
            storage_state=resolve_storage_state_path(),
            browser_profile=resolve_browser_profile(),
            headless=headless,
            sniff_network=sniff_network,
        )


def require_playwright() -> None:
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        ) from _IMPORT_ERROR


def is_auth_only_active() -> bool:
    return _AUTH_ONLY_ACTIVE


def _set_auth_only_active(active: bool) -> None:
    global _AUTH_ONLY_ACTIVE
    _AUTH_ONLY_ACTIVE = active


def _kill_stale_chrome(profile_dir: Path) -> None:
    tag = profile_dir.name
    try:
        subprocess.run(
            f'wmic process where "Name=\'chrome.exe\' and CommandLine like \'%{tag}%\'" call terminate',
            shell=True,
            capture_output=True,
            timeout=8,
        )
        time.sleep(1.0)
    except Exception:
        pass
    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            lf = profile_dir / lock
            if lf.exists():
                lf.unlink()
        except OSError:
            pass


def _format_auth_browser_error(profile_dir: Path, detail: str) -> str:
    return (
        "Nao foi possivel abrir o navegador para login no Gemini.\n"
        "Tente:\n"
        "  1. Fechar todas as janelas do Google Chrome (incluindo em segundo plano).\n"
        "  2. Se o erro persistir, apague os arquivos Singleton* nesta pasta (com Chrome fechado):\n"
        f"     {profile_dir}\n"
        "  3. Rode de novo: python scripts/gemini-thumbnails.py --auth-only\n"
        f"Detalhe tecnico: {detail}"
    )


def _persistent_auth_context_kwargs(profile_dir: Path) -> dict[str, Any]:
    return {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "locale": "pt-BR",
        "viewport": {"width": _PW_WINDOW_WIDTH, "height": _PW_WINDOW_HEIGHT},
        "args": [
            "--start-minimized",
            f"--window-size={_PW_WINDOW_WIDTH},{_PW_WINDOW_HEIGHT}",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
        "ignore_default_args": ["--enable-automation"],
    }


def _launch_gemini_auth_context(pw: Any, profile_dir: Path) -> BrowserContext:
    """Persistent context: installed Chrome first, then bundled Chromium."""
    base = _persistent_auth_context_kwargs(profile_dir)
    errors: list[str] = []
    for label, channel in (("chrome", "chrome"), ("chromium", None)):
        kwargs = dict(base)
        if channel:
            kwargs["channel"] = channel
        try:
            return pw.chromium.launch_persistent_context(**kwargs)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            LOGGER.warning("Auth-only launch failed (%s): %s", label, exc)
    raise RuntimeError(_format_auth_browser_error(profile_dir, "; ".join(errors)))


def _auth_only_page(context: BrowserContext) -> Page:
    """Single tab for auth-only — reuse default page; avoid close-all + new_page."""
    open_pages = [p for p in context.pages if not p.is_closed()]
    if open_pages:
        return open_pages[0]
    return context.new_page()


def _save_auth_storage_state(context: BrowserContext, path: Path) -> bool:
    try:
        context.storage_state(path=str(path))
        return True
    except Exception as exc:
        detail = str(exc).lower()
        if "target" in detail and "closed" in detail:
            LOGGER.error("Browser closed before storage_state could be saved.")
            print(
                "\nO navegador foi fechado antes de salvar a sessao.\n"
                "Rode novamente: python scripts/gemini-thumbnails.py --auth-only\n"
            )
        else:
            LOGGER.exception("Failed to save storage_state: %s", exc)
            print(f"\nNao foi possivel salvar a sessao: {exc}\n")
        return False


def _sanitize_url(url: str) -> str:
    """Strip sensitive query params from logged URLs."""
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url
        params = parse_qs(parsed.query, keep_blank_values=True)
        redacted = {
            k: (["<redacted>"] if k.lower() in _SENSITIVE_QUERY_KEYS else v)
            for k, v in params.items()
        }
        flat = [(k, v[0] if len(v) == 1 else v) for k, v in redacted.items()]
        new_query = urlencode(flat, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url.split("?", 1)[0]


def _is_gemini_rpc_url(url: str) -> bool:
    lower = url.lower()
    if any(n in lower for n in NOISE_URL_FRAGMENTS):
        return False
    return any(h in lower for h in GEMINI_RPC_HOST_FRAGMENTS) or "batchexecute" in lower


def attach_network_logger(
    page: Page,
    *,
    log_path: Optional[Path] = None,
    echo: bool = False,
) -> tuple[list[str], Callable[[], None]]:
    """Capture Gemini RPC URLs (no auth headers/cookies). Returns (lines, flush_fn)."""
    lines: list[str] = []
    started = datetime.now().isoformat(timespec="seconds")

    def on_request(request) -> None:
        if request.resource_type not in TRACKED_RESOURCE_TYPES:
            return
        url = _sanitize_url(request.url)
        if not _is_gemini_rpc_url(url):
            return
        line = f"{datetime.now().isoformat(timespec='seconds')} REQ {request.method} {url}"
        lines.append(line)
        if echo:
            print(line)

    def on_response(response) -> None:
        req = response.request
        if req.resource_type not in TRACKED_RESOURCE_TYPES:
            return
        url = _sanitize_url(response.url)
        if not _is_gemini_rpc_url(url):
            return
        line = (
            f"{datetime.now().isoformat(timespec='seconds')} "
            f"RES {response.status} {req.method} {url}"
        )
        lines.append(line)
        if echo:
            print(line)

    page.on("request", on_request)
    page.on("response", on_response)

    def flush() -> None:
        if not log_path or not lines:
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "# Gemini web network capture (URLs only — no auth headers)",
            f"# started={started}",
            f"# ended={datetime.now().isoformat(timespec='seconds')}",
            "",
        ]
        log_path.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
        LOGGER.info("Network log saved: %s (%s lines)", log_path, len(lines))

    return lines, flush


def is_logged_in_passive(page: Page, context: BrowserContext) -> bool:
    try:
        url = page.url.lower()
        if "accounts.google.com/signin" in url:
            return False
        if "gemini.google.com/app" in url:
            return True
        return bool(page.evaluate(_LOGGED_IN_JS))
    except Exception as exc:
        LOGGER.debug("Passive login check failed: %s", exc)
        return False


def ensure_session(settings: GeminiWebSettings, page: Page, context: BrowserContext) -> None:
    if is_auth_only_active():
        raise RuntimeError("ensure_session() blocked during --auth-only.")
    if not settings.storage_state.is_file():
        raise RuntimeError(
            "Gemini session missing. Run first:\n"
            "  python scripts/gemini-thumbnails.py --auth-only\n"
            f"Expected: {settings.storage_state}"
        )
    if is_logged_in_passive(page, context):
        return
    raise RuntimeError(
        "Gemini not authenticated (storage_state expired or headless blocked).\n"
        "Re-run: python scripts/gemini-thumbnails.py --auth-only\n"
        f"Storage: {settings.storage_state}"
    )


def run_auth_only(settings: Optional[GeminiWebSettings] = None) -> bool:
    """Open Chrome at gemini.google.com; save storage_state after Enter."""
    require_playwright()
    settings = settings or GeminiWebSettings.from_args()
    settings.browser_profile.mkdir(parents=True, exist_ok=True)
    settings.storage_state.parent.mkdir(parents=True, exist_ok=True)
    _kill_stale_chrome(settings.browser_profile)

    _set_auth_only_active(True)
    try:
        assert sync_playwright is not None
        with sync_playwright() as pw:
            context: Optional[BrowserContext] = None
            try:
                context = _launch_gemini_auth_context(pw, settings.browser_profile)
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    _format_auth_browser_error(settings.browser_profile, str(exc))
                ) from exc

            try:
                try:
                    page = _auth_only_page(context)
                except Exception as exc:
                    raise RuntimeError(
                        _format_auth_browser_error(
                            settings.browser_profile,
                            f"Falha ao abrir aba (Target.createTarget): {exc}",
                        )
                    ) from exc

                page.set_default_timeout(300_000)

                print(
                    "Faca login no Google (conta com Gemini Pro).\n"
                    "Navegue ate gemini.google.com/app e confirme que o chat abre.\n"
                    "NAO feche o navegador. Volte ao terminal e pressione ENTER.\n"
                    f"Perfil local (nao compartilhe): {settings.browser_profile}"
                )
                LOGGER.info("Auth-only: navigating to %s", GEMINI_APP_URL)
                page.goto(GEMINI_APP_URL, wait_until="domcontentloaded", timeout=120_000)

                try:
                    input()
                except EOFError:
                    print("\nEntrada cancelada. Sessao nao salva.\n")
                    return False

                storage_path = settings.storage_state.resolve()
                if not _save_auth_storage_state(context, storage_path):
                    return False
                print(f"\nSessao salva em: {storage_path}\n")
                LOGGER.info("Session saved: storage_state=%s", storage_path)
                return True
            finally:
                with suppress(Exception):
                    if context is not None:
                        context.close()
    finally:
        _set_auth_only_active(False)


@contextmanager
def gemini_browser(settings: GeminiWebSettings) -> Iterator[tuple[BrowserContext, Page]]:
    """Launch Chrome with storage_state hydration."""
    if is_auth_only_active():
        raise RuntimeError("gemini_browser() cannot run during --auth-only.")

    require_playwright()
    settings.browser_profile.mkdir(parents=True, exist_ok=True)
    _kill_stale_chrome(settings.browser_profile)

    assert sync_playwright is not None
    kwargs: dict[str, Any] = {
        "headless": settings.headless,
        "channel": "chrome",
        "locale": "pt-BR",
        "viewport": {"width": _PW_WINDOW_WIDTH, "height": _PW_WINDOW_HEIGHT},
        "args": [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
        "ignore_default_args": ["--enable-automation"],
    }
    if settings.headless:
        kwargs["args"].append("--headless=new")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**kwargs)
        context_kwargs: dict[str, Any] = {}
        if settings.storage_state.is_file():
            context_kwargs["storage_state"] = str(settings.storage_state)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(300_000)
        flush_network: Callable[[], None] = lambda: None

        if settings.sniff_network:
            _, flush_network = attach_network_logger(
                page,
                log_path=settings.network_log,
                echo=LOGGER.isEnabledFor(logging.DEBUG),
            )

        try:
            yield context, page
        finally:
            flush_network()
            try:
                if not settings.headless and settings.storage_state.parent.exists():
                    context.storage_state(path=str(settings.storage_state))
            except Exception:
                LOGGER.debug("Could not refresh storage_state on close.")
            context.close()
            browser.close()


def verify_session(settings: GeminiWebSettings) -> dict[str, Any]:
    """Test storage_state in headed vs headless modes. Returns status dict."""
    result: dict[str, Any] = {
        "storage_state_exists": settings.storage_state.is_file(),
        "headed_logged_in": None,
        "headless_logged_in": None,
        "headed_url": None,
        "headless_url": None,
    }
    if not result["storage_state_exists"]:
        return result

    for mode, key_url, key_ok in (
        (False, "headed_url", "headed_logged_in"),
        (True, "headless_url", "headless_logged_in"),
    ):
        mode_settings = GeminiWebSettings(
            storage_state=settings.storage_state,
            browser_profile=settings.browser_profile,
            headless=mode,
        )
        try:
            with gemini_browser(mode_settings) as (_ctx, page):
                page.goto(GEMINI_APP_URL, wait_until="domcontentloaded", timeout=90_000)
                page.wait_for_timeout(3000)
                result[key_url] = page.url
                result[key_ok] = is_logged_in_passive(page, _ctx)
        except Exception as exc:
            LOGGER.warning("%s session check failed: %s", "Headless" if mode else "Headed", exc)
            result[key_ok] = False

    return result


def _try_set_prompt(page: Page, prompt: str) -> bool:
    """Fill prompt via locators, then page.evaluate fallback."""
    selectors = (
        "rich-textarea",
        'div[contenteditable="true"]',
        "textarea",
        ".ql-editor",
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.click(timeout=5000)
            loc.fill(prompt, timeout=8000)
            return True
        except Exception:
            LOGGER.debug("Locator %s failed for prompt", sel)

    try:
        return bool(page.evaluate(_FILL_PROMPT_COMBINED_JS, prompt))
    except Exception:
        LOGGER.debug("evaluate prompt fallback failed", exc_info=True)
        return False


def _try_submit(page: Page) -> bool:
    for label in ("Enviar", "Send", "Submit"):
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if btn.count() > 0:
                btn.first.click(timeout=5000)
                return True
        except Exception:
            pass
    try:
        return bool(page.evaluate(_SUBMIT_PROMPT_JS))
    except Exception:
        return False


def _try_attach_face(page: Page, face_path: Path) -> bool:
    """Attach reference face via file input (locator or evaluate discovery)."""
    try:
        file_input = page.locator('input[type="file"]').first
        if file_input.count() > 0:
            file_input.set_input_files(str(face_path.resolve()))
            page.wait_for_timeout(1500)
            return True
    except Exception:
        LOGGER.debug("Locator file input failed", exc_info=True)

    try:
        has_input = page.evaluate(_FIND_FILE_INPUT_JS)
        if has_input:
            page.locator('input[type="file"]').first.set_input_files(str(face_path.resolve()))
            page.wait_for_timeout(1500)
            return True
    except Exception:
        LOGGER.debug("evaluate file input fallback failed", exc_info=True)

    LOGGER.warning(
        "Could not attach face image — continuing with prompt only. "
        "TODO: map Gemini upload button selectors when UI changes."
    )
    return False


def _wait_for_image(page: Page, timeout_ms: int = 120_000) -> Optional[str]:
    """Poll for a large generated image URL."""
    deadline = time.time() + timeout_ms / 1000.0
    last_src: Optional[str] = None
    while time.time() < deadline:
        try:
            src = page.evaluate(_LATEST_IMAGE_JS)
            if src and src != last_src and "googleusercontent" in src:
                return str(src)
            last_src = src
        except Exception:
            pass
        page.wait_for_timeout(2000)
    return None


def _download_image(page: Page, src: str, output_path: Path) -> None:
    _ensure_parent(output_path)
    if src.startswith("data:"):
        import base64

        header, b64 = src.split(",", 1)
        output_path.write_bytes(base64.b64decode(b64))
        return

    response = page.request.get(src)
    if not response.ok:
        raise RuntimeError(f"Failed to download image: HTTP {response.status}")
    output_path.write_bytes(response.body())


def generate_thumbnail(
    *,
    settings: GeminiWebSettings,
    face_path: Path,
    prompt: str,
    output_path: Path,
    dry_run: bool = False,
) -> bool:
    if dry_run:
        LOGGER.info(
            "[DRY-RUN] Would generate %s | face=%s | headless=%s",
            output_path.name,
            face_path.name,
            settings.headless,
        )
        return True

    with gemini_browser(settings) as (context, page):
        ensure_session(settings, page, context)
        page.goto(GEMINI_APP_URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(2500)

        _try_attach_face(page, face_path)
        if not _try_set_prompt(page, prompt):
            raise RuntimeError(
                "Could not find Gemini prompt input. UI may have changed — "
                "re-run with --auth-only or inspect DOM manually."
            )
        page.wait_for_timeout(500)
        if not _try_submit(page):
            raise RuntimeError("Could not submit prompt (Send button not found).")

        img_src = _wait_for_image(page, timeout_ms=180_000)
        if not img_src:
            raise RuntimeError(
                "Timed out waiting for generated image. "
                "Try headed mode (--headless not set) or verify Gemini Pro image quota."
            )

        _download_image(page, img_src, output_path)
        _resize_to_target(output_path)
        LOGGER.info("Saved thumbnail: %s (headless=%s)", output_path, settings.headless)
        return True


def run_generation(
    *,
    faces_dir: Path,
    videos_dir: Path,
    game: str,
    count: Optional[int] = None,
    output_dir: Optional[Path] = None,
    dry_run: bool = False,
    skip_existing: bool = True,
    headless: bool = False,
    sniff_network: bool = False,
) -> list[Path]:
    faces = _iter_media(faces_dir, IMAGE_EXTENSIONS)
    videos = _iter_media(videos_dir, VIDEO_EXTENSIONS)
    n = count if count is not None else len(videos)
    if n > len(videos):
        LOGGER.warning("Count %s > videos %s — using %s videos", n, len(videos), len(videos))
        n = len(videos)

    selected_videos = videos[:n]
    selected_faces = assign_faces(faces, n)
    out_root = output_dir or videos_dir
    settings = GeminiWebSettings.from_args(headless=headless, sniff_network=sniff_network)

    if not dry_run and not settings.storage_state.is_file():
        raise RuntimeError(
            "Gemini browser session missing. Run:\n"
            "  python scripts/gemini-thumbnails.py --auth-only"
        )

    written: list[Path] = []
    for idx, (video, face) in enumerate(zip(selected_videos, selected_faces)):
        dest = _output_path_for_video(video, out_root)
        if skip_existing and dest.is_file() and not dry_run:
            LOGGER.info("Skip existing: %s", dest.name)
            written.append(dest)
            continue

        prompt = build_prompt(game=game, slot_index=idx, video_stem=video.stem)
        ok = generate_thumbnail(
            settings=settings,
            face_path=face,
            prompt=prompt,
            output_path=dest,
            dry_run=dry_run,
        )
        if ok:
            written.append(dest)

    return written


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate YouTube thumbnails via gemini.google.com (Gemini Pro browser session).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/gemini-thumbnails.py --auth-only\n"
            "  python scripts/gemini-thumbnails.py --verify-session\n"
            "  python scripts/gemini-thumbnails.py --faces-dir ... --videos-dir ... --game \"Fortnite Mobile\"\n"
            "  python scripts/gemini-thumbnails.py ... --headless --sniff-network\n"
        ),
    )
    p.add_argument("--auth-only", action="store_true", help="Login once; save storage_state")
    p.add_argument(
        "--verify-session",
        action="store_true",
        help="Test storage_state in headed + headless (no generation)",
    )
    p.add_argument("--faces-dir", type=Path, help="Folder with face selfie images")
    p.add_argument("--videos-dir", type=Path, help="Folder with MP4 videos")
    p.add_argument("--game", help=f'Game name (known: {", ".join(list_known_games())})')
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--output-dir", type=Path, default=None)
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run without visible window (may be blocked by Google after auth)",
    )
    p.add_argument(
        "--sniff-network",
        action="store_true",
        help="Log Gemini RPC URLs to ~/.secrets/gemini_network.log (no auth headers)",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    settings = GeminiWebSettings.from_args(
        headless=args.headless,
        sniff_network=args.sniff_network,
    )

    if args.auth_only:
        ok = run_auth_only(settings)
        return 0 if ok else 1

    if args.verify_session:
        status = verify_session(settings)
        print("Gemini session verification:")
        for k, v in status.items():
            print(f"  {k}: {v}")
        if not status.get("storage_state_exists"):
            print("\nRun --auth-only first.")
            return 1
        if status.get("headless_logged_in") is False and status.get("headed_logged_in"):
            print(
                "\nNote: headless may be blocked while headed works — "
                "prefer headed batch runs or see docs/gemini/WEB_API_RESEARCH.md"
            )
        return 0 if status.get("headed_logged_in") else 1

    if not args.faces_dir or not args.videos_dir or not args.game:
        LOGGER.error("--faces-dir, --videos-dir and --game are required for generation.")
        return 2

    try:
        paths = run_generation(
            faces_dir=args.faces_dir.resolve(),
            videos_dir=args.videos_dir.resolve(),
            game=args.game,
            count=args.count,
            output_dir=args.output_dir.resolve() if args.output_dir else None,
            dry_run=args.dry_run,
            skip_existing=not args.force,
            headless=args.headless,
            sniff_network=args.sniff_network,
        )
    except Exception as exc:
        LOGGER.error("%s", exc)
        return 1

    LOGGER.info(
        "Done — %s thumbnail(s) %s",
        len(paths),
        "planned" if args.dry_run else "written",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
