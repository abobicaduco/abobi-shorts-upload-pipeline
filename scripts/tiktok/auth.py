# -*- coding: utf-8 -*-
"""Playwright session bootstrap for TikTok (login + storage_state export)."""
from __future__ import annotations

import logging
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .config import TIKTOK_LOGIN_URL, TIKTOK_UPLOAD_URL, TikTokSettings

LOGGER = logging.getLogger(__name__)

_AUTH_ONLY_ACTIVE = False

_SESSION_COOKIE_NAMES = frozenset(
    {
        "sessionid",
        "sessionid_ss",
        "sid_tt",
        "sid_guard",
        "uid_tt",
        "tt_chain_token",
    }
)

try:
    from playwright.sync_api import BrowserContext, Page, sync_playwright
except ImportError as exc:
    sync_playwright = None  # type: ignore[assignment,misc]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

_LOGGED_IN_JS = """
() => {
  const url = location.href.toLowerCase();
  if (url.includes('/login')) return false;
  if (url.includes('/foryou') || url.includes('/@') || url.includes('tiktokstudio')) return true;
  const cookie = document.cookie.toLowerCase();
  if (cookie.includes('sessionid=') || cookie.includes('sid_tt=')) return true;
  const sel = '[data-e2e="profile-icon"], [data-e2e="nav-profile"], [data-e2e="top-profile-avatar"]';
  const el = document.querySelector(sel);
  if (el && el.offsetParent !== null) return true;
  return false;
}
"""


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


def _metadata_has_session_cookies(context: BrowserContext) -> bool:
    try:
        names = {c.get("name", "").lower() for c in context.cookies()}
        return bool(names & _SESSION_COOKIE_NAMES)
    except Exception:
        return False


def _url_indicates_logged_in(url: str) -> bool:
    u = url.lower()
    if "/login" in u:
        return False
    if "/foryou" in u or "/@" in u or "tiktokstudio" in u or "/upload" in u:
        return True
    return False


def is_logged_in_passive(page: Page, context: BrowserContext) -> bool:
    """Detect login from current page state — never navigates."""
    try:
        if _url_indicates_logged_in(page.url):
            return True
        if _metadata_has_session_cookies(context):
            return True
        return bool(page.evaluate(_LOGGED_IN_JS))
    except Exception as exc:
        LOGGER.debug("Passive login check failed: %s", exc)
        return False


def is_logged_in(page: Page, context: BrowserContext, *, navigate: bool = False) -> bool:
    """Check login; navigate to upload page only when navigate=True (upload pipeline)."""
    if not navigate:
        return is_logged_in_passive(page, context)

    try:
        page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        if "login" in page.url.lower():
            return False
        if page.locator('input[type="file"]').count() > 0:
            return True
        if page.get_by_text("Select video", exact=False).count() > 0:
            return True
        if page.get_by_text("Selecionar video", exact=False).count() > 0:
            return True
        if page.get_by_text("Selecionar vídeo", exact=False).count() > 0:
            return True
        if page.locator('[data-e2e="upload-input"]').count() > 0:
            return True
        return "upload" in page.url.lower() and page.locator("video").count() > 0
    except Exception as exc:
        LOGGER.debug("Login check failed: %s", exc)
        return False


def run_auth_only(settings: TikTokSettings) -> bool:
    """Open Chrome once at tiktok.com/login; save storage_state after Enter. No upload navigation."""
    require_playwright()
    settings.browser_profile.mkdir(parents=True, exist_ok=True)
    settings.storage_state.parent.mkdir(parents=True, exist_ok=True)
    _kill_stale_chrome(settings.browser_profile)

    _set_auth_only_active(True)
    try:
        assert sync_playwright is not None
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(settings.browser_profile),
                headless=False,
                channel="chrome",
                locale="pt-BR",
                no_viewport=True,
                args=[
                    "--start-maximized",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
                ignore_default_args=["--enable-automation"],
            )
            try:
                for existing in list(context.pages):
                    try:
                        existing.close()
                    except Exception:
                        pass

                page = context.new_page()
                page.set_default_timeout(120_000)

                print(
                    "Faca login com QR code. NAO feche o navegador. "
                    "Quando terminar, volte ao terminal e pressione ENTER."
                )
                LOGGER.info("Auth-only: unica navegacao para %s", TIKTOK_LOGIN_URL)
                page.goto(TIKTOK_LOGIN_URL, wait_until="domcontentloaded", timeout=120_000)

                try:
                    input()
                except EOFError:
                    print("\nEntrada cancelada. Sessao nao salva.\n")
                    LOGGER.error("Entrada cancelada (stdin fechado). Sessao nao salva.")
                    return False

                storage_path = settings.storage_state.resolve()
                context.storage_state(path=str(storage_path))
                print(f"\nSessao salva em: {storage_path}\n")
                LOGGER.info("Sessao salva: storage_state=%s", storage_path)
                return True
            finally:
                try:
                    context.close()
                except Exception:
                    LOGGER.exception("Falha ao fechar browser apos auth-only.")
    finally:
        _set_auth_only_active(False)


run_interactive_login = run_auth_only


@contextmanager
def tiktok_browser(settings: TikTokSettings) -> Iterator[tuple[BrowserContext, Page]]:
    """Launch Chrome with persistent profile; optionally hydrate storage_state."""
    if is_auth_only_active():
        raise RuntimeError("tiktok_browser() nao pode rodar durante --auth-only.")

    require_playwright()
    settings.browser_profile.mkdir(parents=True, exist_ok=True)
    _kill_stale_chrome(settings.browser_profile)

    assert sync_playwright is not None
    with sync_playwright() as pw:
        kwargs: dict = {
            "user_data_dir": str(settings.browser_profile),
            "headless": settings.headless,
            "channel": "chrome",
            "slow_mo": 80,
            "locale": "pt-BR",
            "viewport": {"width": 1280, "height": 900},
            "args": [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
            "ignore_default_args": ["--enable-automation"],
        }
        context = pw.chromium.launch_persistent_context(**kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(180_000)
        try:
            yield context, page
        finally:
            try:
                context.storage_state(path=str(settings.storage_state))
            except Exception:
                LOGGER.debug("Could not export storage_state on close.")
            context.close()


def ensure_session(settings: TikTokSettings, page: Page, context: BrowserContext) -> None:
    if is_auth_only_active():
        raise RuntimeError("ensure_session() bloqueado durante --auth-only.")
    if is_logged_in_passive(page, context):
        return
    raise RuntimeError(
        "TikTok nao autenticado. Rode primeiro:\n"
        "  python scripts/tiktok-upload.py --auth-only\n"
        f"Profile: {settings.browser_profile}\n"
        f"Storage: {settings.storage_state}"
    )
