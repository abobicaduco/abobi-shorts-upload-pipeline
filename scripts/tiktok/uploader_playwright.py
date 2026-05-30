# -*- coding: utf-8 -*-
"""TikTok web upload via Playwright (free; no paid third-party APIs)."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PWTimeout

from .auth import ensure_session, is_auth_only_active, tiktok_browser
from .config import TIKTOK_UPLOAD_URL, TikTokSettings

LOGGER = logging.getLogger(__name__)

# Emergency guard: never publish immediately unless explicitly allowed AND flag disabled.
SCHEDULE_ONLY = True
SCHEDULE_UI_TIMEOUT_SEC = 30
DEBUG_DIR = Path.home() / ".secrets" / "tiktok_debug"
NETWORK_LOG_PATH = Path.home() / ".secrets" / "tiktok_schedule_upload_network.log"

CAPTION_SELECTORS = (
    '[data-e2e="caption-editor"] div[contenteditable="true"]',
    'div.public-DraftEditor-content[contenteditable="true"]',
    'div[contenteditable="true"][role="textbox"]',
    '[data-e2e="video-caption"] div[contenteditable="true"]',
)

FILE_INPUT_SELECTORS = (
    'input[type="file"][accept*="video"]',
    'input[type="file"]',
    '[data-e2e="upload-input"] input[type="file"]',
)

SCHEDULE_TOGGLE_SELECTORS = (
    '[data-e2e="schedule-switch"]',
    '[data-e2e="schedule-switch-container"] input[type="checkbox"]',
    '[data-e2e="schedule-toggle"]',
    '[role="switch"][aria-label*="Schedule" i]',
    '[role="switch"][aria-label*="Agendar" i]',
    '[role="switch"][aria-label*="Programar" i]',
    'label:has-text("Schedule")',
    'label:has-text("Agendar publicação")',
    'label:has-text("Agendar publicacao")',
    'label:has-text("Agendar")',
    'label:has-text("Programar")',
)

SCHEDULE_RADIO_PATTERNS = (
    r"^Schedule$",
    r"^Agendar$",
    r"^Programar$",
    r"Schedule video",
    r"Agendar publica",
    r"Programar publica",
)

POST_NOW_RADIO_PATTERNS = (
    r"Post now",
    r"Publicar agora",
    r"Publish now",
    r"Publicar já",
    r"Publicar ja",
)

SCHEDULE_DATE_SELECTORS = (
    '[data-e2e="schedule-date-input"]',
    'input[type="date"]',
    'input[placeholder*="date" i]',
    'input[placeholder*="data" i]',
    'input[aria-label*="data" i]',
    'input[aria-label*="date" i]',
)

SCHEDULE_TIME_SELECTORS = (
    '[data-e2e="schedule-time-input"]',
    'input[type="time"]',
    'input[placeholder*="time" i]',
    'input[placeholder*="hora" i]',
    'input[aria-label*="hora" i]',
    'input[aria-label*="time" i]',
)

SCHEDULE_CONFIRM_BUTTON_SELECTORS = (
    '[data-e2e="schedule-post-button"]',
    '[data-e2e="schedule_post_button"]',
    '[data-e2e="schedule-button"]',
)

IMMEDIATE_POST_BUTTON_SELECTORS = (
    '[data-e2e="post_video_button"]',
    'button:has-text("Post now")',
    'button:has-text("Publicar agora")',
    'button:has-text("Post")',
    'button:has-text("Publicar")',
    'button:has-text("Publish")',
)

IMMEDIATE_POST_LABEL_RE = re.compile(
    r"(post\s*now|publicar\s*agora|publish\s*now|publicar\s*j[aá]|^post$|^publicar$|^publish$)",
    re.I,
)

SCHEDULE_SUBMIT_LABEL_RE = re.compile(
    r"(^schedule$|^agendar$|^programar$|schedule\s*post|agendar\s*publica|programar\s*publica)",
    re.I,
)


@dataclass
class UploadResult:
    ok: bool
    post_id: Optional[str] = None
    error: Optional[str] = None
    posted_immediately: bool = False


@dataclass
class _NetworkCapture:
    lines: list[str] = field(default_factory=list)

    def attach(self, page: Page) -> None:
        tracked = frozenset({"fetch", "xhr"})

        def on_request(request) -> None:
            if request.resource_type not in tracked:
                return
            url = request.url
            if any(x in url.lower() for x in ("google", "gstatic", "facebook", "doubleclick")):
                return
            line = f"{datetime.now().isoformat(timespec='seconds')} REQ {request.method} {url}"
            self.lines.append(line)
            LOGGER.debug("Network REQ: %s", url[:120])

        def on_response(response) -> None:
            req = response.request
            if req.resource_type not in tracked:
                return
            url = response.url
            if any(x in url.lower() for x in ("google", "gstatic", "facebook", "doubleclick")):
                return
            line = (
                f"{datetime.now().isoformat(timespec='seconds')} "
                f"RES {response.status} {req.method} {url}"
            )
            self.lines.append(line)

        page.on("request", on_request)
        page.on("response", on_response)

    def flush(self) -> None:
        if not self.lines:
            return
        NETWORK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        header = [
            f"# TikTok schedule upload network log",
            f"# ended={datetime.now().isoformat(timespec='seconds')}",
            "",
        ]
        existing = ""
        if NETWORK_LOG_PATH.is_file():
            existing = NETWORK_LOG_PATH.read_text(encoding="utf-8")
        NETWORK_LOG_PATH.write_text(
            existing + "\n".join(header + self.lines) + "\n",
            encoding="utf-8",
        )
        LOGGER.info("Network log appended: %s (%s lines)", NETWORK_LOG_PATH, len(self.lines))


def _screenshot_on_failure(page: Page, label: str) -> Path:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]+", "_", label)[:80]
    path = DEBUG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        LOGGER.error("Screenshot salvo: %s", path)
    except Exception as exc:
        LOGGER.warning("Falha ao salvar screenshot (%s): %s", label, exc)
    return path


def _wait_upload_page_loaded(page: Page, *, timeout_sec: int = 60) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        _dismiss_popups(page)
        url = page.url.lower()
        if "tiktokstudio/upload" in url or "upload" in url:
            if _first_visible(page, FILE_INPUT_SELECTORS, timeout_ms=800):
                return
            if page.locator('input[type="file"]').count():
                return
        page.wait_for_timeout(500)
    raise RuntimeError(f"Pagina de upload nao carregou em {timeout_sec}s (url={page.url}).")


def _first_visible(page: Page, selectors: tuple[str, ...], *, timeout_ms: int = 1500):
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible(timeout=timeout_ms):
                return loc
        except PWTimeout:
            continue
        except Exception:
            continue
    return None


def _dismiss_popups(page: Page) -> None:
    for text in (
        "Got it",
        "Entendi",
        "OK",
        "Accept",
        "Aceitar",
        "Allow",
        "Permitir",
        "Not now",
        "Agora nao",
        "Agora não",
    ):
        try:
            btn = page.get_by_role("button", name=re.compile(text, re.I)).first
            if btn.is_visible(timeout=800):
                btn.click(timeout=3000)
                page.wait_for_timeout(500)
        except Exception:
            pass


def _wait_upload_processed(page: Page, *, timeout_sec: int = 300) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        _dismiss_popups(page)
        if page.get_by_text(re.compile(r"uploaded successfully|carregado|pronto para publicar", re.I)).count():
            break
        if page.locator('[data-e2e="post_video_button"]').count():
            try:
                btn = page.locator('[data-e2e="post_video_button"]').first
                if btn.is_enabled(timeout=1000):
                    break
            except Exception:
                pass
        if page.get_by_text(re.compile(r"processing|processando|uploading|carregando", re.I)).count():
            page.wait_for_timeout(2000)
            continue
        page.wait_for_timeout(1500)
    page.wait_for_timeout(2000)


def _fill_caption(page: Page, caption: str) -> None:
    editor = _first_visible(page, CAPTION_SELECTORS)
    if editor is None:
        raise RuntimeError("Campo de descricao/caption nao encontrado na pagina de upload.")
    editor.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")
    page.keyboard.type(caption[:4000], delay=5)
    LOGGER.info("Caption preenchida (%s chars).", len(caption))


def _round_time_to_five_min(when_local: datetime) -> datetime:
    minute = (when_local.minute // 5) * 5
    return when_local.replace(minute=minute, second=0, microsecond=0)


def _fill_input_if_visible(page: Page, selectors: tuple[str, ...], value: str) -> bool:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible(timeout=1200):
                loc.click(timeout=2000)
                loc.fill(value)
                page.wait_for_timeout(300)
                current = loc.input_value(timeout=2000)
                if current and value[:4] in current:
                    return True
                loc.press("Control+A")
                loc.type(value, delay=30)
                return True
        except Exception:
            continue
    for label in (re.compile(r"date", re.I), re.compile(r"data", re.I), re.compile(r"time", re.I), re.compile(r"hora", re.I)):
        try:
            loc = page.get_by_label(label).first
            if loc.count() and loc.is_visible(timeout=800):
                loc.click(timeout=2000)
                loc.fill(value)
                return True
        except Exception:
            continue
    return False


def _set_time_via_dropdowns(page: Page, when_local: datetime) -> bool:
    """TikTok Studio often uses hour/minute select/combobox instead of type=time."""
    hour_str = f"{when_local.hour:02d}"
    minute_str = f"{when_local.minute:02d}"
    hour_ok = minute_ok = False

    for pattern in (re.compile(r"hora", re.I), re.compile(r"hour", re.I)):
        try:
            sel = page.get_by_label(pattern).first
            if sel.count() and sel.is_visible(timeout=600):
                sel.select_option(value=hour_str)
                hour_ok = True
                break
        except Exception:
            continue

    for pattern in (re.compile(r"minuto", re.I), re.compile(r"minute", re.I)):
        try:
            sel = page.get_by_label(pattern).first
            if sel.count() and sel.is_visible(timeout=600):
                sel.select_option(value=minute_str)
                minute_ok = True
                break
        except Exception:
            continue

    if not hour_ok:
        for sel in page.locator("select").all()[:10]:
            try:
                if not sel.is_visible(timeout=400):
                    continue
                opts = sel.locator("option").all_inner_texts()
                if any(hour_str in o or o.strip() == str(when_local.hour) for o in opts):
                    sel.select_option(value=hour_str)
                    hour_ok = True
                    break
            except Exception:
                continue

    if not minute_ok:
        for sel in page.locator("select").all()[:10]:
            try:
                if not sel.is_visible(timeout=400):
                    continue
                opts = sel.locator("option").all_inner_texts()
                if any(minute_str in o for o in opts):
                    sel.select_option(value=minute_str)
                    minute_ok = True
                    break
            except Exception:
                continue

    if hour_ok or minute_ok:
        page.wait_for_timeout(400)
    return hour_ok and minute_ok


def _set_date_via_calendar(page: Page, when_local: datetime) -> bool:
    day_num = when_local.day
    month_names_pt = (
        "janeiro", "fevereiro", "março", "marco", "abril", "maio", "junho",
        "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
    )
    month_name = month_names_pt[when_local.month - 1]

    for trigger in (
        '[data-e2e="schedule-date-input"]',
        'input[placeholder*="data" i]',
        'input[aria-label*="data" i]',
        'button[aria-label*="data" i]',
    ):
        try:
            loc = page.locator(trigger).first
            if loc.count() and loc.is_visible(timeout=800):
                loc.click(timeout=2000)
                page.wait_for_timeout(500)
                break
        except Exception:
            continue

    try:
        day_btn = page.get_by_role("button", name=re.compile(rf"^{day_num}$")).first
        if day_btn.count() and day_btn.is_visible(timeout=1200):
            day_btn.click(timeout=2000)
            return True
    except Exception:
        pass

    try:
        if page.get_by_text(re.compile(month_name, re.I)).count():
            cell = page.locator(f'td:has-text("{day_num}"), div:has-text("{day_num}")').first
            if cell.is_visible(timeout=800):
                cell.click(timeout=2000)
                return True
    except Exception:
        pass
    return False


def _ensure_programar_radio(page: Page) -> None:
    """PT-BR TikTok Studio: 'Quando publicar' -> radio Programar (nao Agora)."""
    for pattern in (r"^Programar$", r"^Agendar$", r"^Schedule$"):
        try:
            radio = page.get_by_role("radio", name=re.compile(pattern, re.I)).first
            if radio.count() and radio.is_visible(timeout=1200):
                if not radio.is_checked(timeout=500):
                    radio.check(timeout=3000)
                    page.wait_for_timeout(600)
                LOGGER.info("Radio '%s' selecionado (Quando publicar).", pattern)
                return
        except Exception:
            continue


def _set_datetime_via_combobox_display(page: Page, when_local: datetime) -> tuple[bool, bool]:
    """Click visible date/time combobox values (YYYY-MM-DD and HH:MM) used in PT-BR Studio."""
    date_target = when_local.strftime("%Y-%m-%d")
    time_target = when_local.strftime("%H:%M")
    date_ok = time_ok = False

    for loc in page.get_by_text(re.compile(r"^\d{4}-\d{2}-\d{2}$")).all():
        try:
            if not loc.is_visible(timeout=500):
                continue
            loc.scroll_into_view_if_needed(timeout=2000)
            loc.click(timeout=2000)
            page.wait_for_timeout(500)
            for picker in (
                page.get_by_text(date_target, exact=True).first,
                page.get_by_role("option", name=date_target).first,
                page.locator(f'[data-value="{date_target}"]').first,
            ):
                try:
                    if picker.count() and picker.is_visible(timeout=1500):
                        picker.click(timeout=2000)
                        date_ok = True
                        break
                except Exception:
                    continue
            if date_ok:
                break
            page.keyboard.press("Escape")
        except Exception:
            continue

    page.wait_for_timeout(400)

    for loc in page.get_by_text(re.compile(r"^\d{1,2}:\d{2}$")).all():
        try:
            if not loc.is_visible(timeout=500):
                continue
            loc.scroll_into_view_if_needed(timeout=2000)
            loc.click(timeout=2000)
            page.wait_for_timeout(500)
            for picker in (
                page.get_by_text(time_target, exact=True).first,
                page.get_by_role("option", name=time_target).first,
                page.get_by_text(re.compile(rf"^{when_local.hour:02d}:{when_local.minute:02d}$")).first,
            ):
                try:
                    if picker.count() and picker.is_visible(timeout=1500):
                        picker.click(timeout=2000)
                        time_ok = True
                        break
                except Exception:
                    continue
            if time_ok:
                break
            page.keyboard.press("Escape")
        except Exception:
            continue

    return date_ok, time_ok
    """Scroll post form — schedule controls are often below caption/privacy."""
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        page.wait_for_timeout(400)
        for _ in range(8):
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(350)
    except Exception:
        pass
    for pattern in (
        r"agendar publica",
        r"^agendar$",
        r"^schedule$",
        r"programar",
        r"when to post",
        r"quando publicar",
    ):
        try:
            loc = page.get_by_text(re.compile(pattern, re.I)).first
            if loc.count() and loc.is_visible(timeout=800):
                loc.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _save_debug_artifact(page: Page, tag: str) -> None:
    out_dir = Path.home() / ".secrets"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"tiktok_schedule_debug_{tag}_{int(time.time())}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        LOGGER.error("Screenshot de debug salvo: %s", path)
    except Exception as exc:
        LOGGER.error("Falha ao salvar screenshot: %s", exc)


def _schedule_toggle_active(page: Page) -> bool:
    for sel in (
        '[data-e2e="schedule-switch"][aria-checked="true"]',
        '[data-e2e="schedule-toggle"][aria-checked="true"]',
    ):
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible(timeout=800):
                return True
        except Exception:
            continue
    for label in ("Schedule", "Agendar", "Programar", "Agendar publicação", "Agendar publicacao"):
        try:
            sw = page.get_by_role("switch", name=re.compile(label, re.I)).first
            if sw.count() and sw.is_visible(timeout=800):
                if (sw.get_attribute("aria-checked") or "").lower() == "true":
                    return True
        except Exception:
            continue
    for pattern in SCHEDULE_RADIO_PATTERNS:
        try:
            radio = page.get_by_role("radio", name=re.compile(pattern, re.I)).first
            if radio.count() and radio.is_checked(timeout=500):
                return True
        except Exception:
            continue
    if page.locator(SCHEDULE_DATE_SELECTORS[0]).count():
        try:
            if page.locator(SCHEDULE_DATE_SELECTORS[0]).first.is_visible(timeout=800):
                return True
        except Exception:
            pass
    if page.get_by_text(re.compile(r"agendado para|scheduled for|data de publicação|data de publicacao", re.I)).count():
        return True
    return False


def _schedule_ui_visible(page: Page) -> bool:
    if _schedule_toggle_active(page):
        return True
    if _first_visible(page, SCHEDULE_TOGGLE_SELECTORS, timeout_ms=500):
        return True
    for pattern in SCHEDULE_RADIO_PATTERNS:
        try:
            radio = page.get_by_role("radio", name=re.compile(pattern, re.I)).first
            if radio.count() and radio.is_visible(timeout=500):
                return True
        except Exception:
            continue
    for text in ("Agendar publicação", "Agendar publicacao", "Schedule", "Agendar", "Programar"):
        try:
            loc = page.get_by_text(re.compile(f"^{re.escape(text)}$", re.I)).first
            if loc.count() and loc.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def _click_schedule_by_text(page: Page) -> bool:
    for text in (
        "Agendar publicação",
        "Agendar publicacao",
        "Schedule",
        "Agendar",
        "Programar",
    ):
        try:
            loc = page.get_by_text(re.compile(f"^{re.escape(text)}$", re.I)).first
            if loc.count() and loc.is_visible(timeout=1200):
                loc.scroll_into_view_if_needed(timeout=3000)
                loc.click(timeout=3000)
                page.wait_for_timeout(800)
                _dismiss_popups(page)
                if _schedule_toggle_active(page):
                    return True
        except Exception:
            continue
    return False


def _select_schedule_radio(page: Page) -> bool:
    for pattern in POST_NOW_RADIO_PATTERNS:
        try:
            post_now = page.get_by_role("radio", name=re.compile(pattern, re.I)).first
            if post_now.count() and post_now.is_checked(timeout=500):
                LOGGER.warning("Radio 'Publicar agora' estava selecionado — trocando para agendamento.")
        except Exception:
            pass

    for pattern in SCHEDULE_RADIO_PATTERNS:
        try:
            radio = page.get_by_role("radio", name=re.compile(pattern, re.I)).first
            if radio.count() and radio.is_visible(timeout=1200):
                radio.check(timeout=3000)
                page.wait_for_timeout(800)
                _dismiss_popups(page)
                return True
        except Exception:
            continue
    return False


def _click_schedule_toggle(page: Page) -> bool:
    toggle = _first_visible(page, SCHEDULE_TOGGLE_SELECTORS)
    if toggle is None:
        return False
    try:
        aria = (toggle.get_attribute("aria-checked") or "").lower()
        if aria != "true":
            toggle.click(timeout=3000)
            page.wait_for_timeout(1000)
            _dismiss_popups(page)
        if not _schedule_toggle_active(page):
            toggle.click(force=True, timeout=3000)
            page.wait_for_timeout(800)
            _dismiss_popups(page)
        return _schedule_toggle_active(page)
    except Exception as exc:
        LOGGER.warning("Falha ao clicar toggle de agendamento: %s", exc)
        return False


def _wait_for_schedule_ui(page: Page, *, timeout_sec: int = SCHEDULE_UI_TIMEOUT_SEC) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        _dismiss_popups(page)
        if _schedule_ui_visible(page):
            return
        page.wait_for_timeout(500)
    raise RuntimeError(
        f"UI de agendamento nao encontrada em {timeout_sec}s — abortando (SCHEDULE_ONLY, sem publicar)."
    )


def _enable_schedule_mode(page: Page) -> None:
    _scroll_to_schedule_section(page)
    _wait_for_schedule_ui(page)

    if _select_schedule_radio(page):
        LOGGER.info("Modo agendamento ativado via radio.")
        return

    if _click_schedule_toggle(page):
        LOGGER.info("Modo agendamento ativado via toggle/switch.")
        return

    if _click_schedule_by_text(page):
        LOGGER.info("Modo agendamento ativado via texto/label.")
        return

    _screenshot_on_failure(page, "enable_failed")
    raise RuntimeError(
        "Nao foi possivel ativar modo agendamento (toggle/radio). "
        "Verifique conta Creator/Business e docs/tiktok/SCHEDULE_UI.md."
    )


def _set_schedule_datetime(page: Page, when_local: datetime) -> None:
    when_local = _round_time_to_five_min(when_local)
    date_str = when_local.strftime("%Y-%m-%d")
    date_str_br = when_local.strftime("%d/%m/%Y")
    time_str = when_local.strftime("%H:%M")

    _ensure_programar_radio(page)
    page.wait_for_timeout(400)

    date_ok = _fill_input_if_visible(page, SCHEDULE_DATE_SELECTORS, date_str)
    if not date_ok:
        date_ok = _fill_input_if_visible(page, SCHEDULE_DATE_SELECTORS, date_str_br)
    if not date_ok:
        date_ok = _set_date_via_calendar(page, when_local)

    time_ok = _fill_input_if_visible(page, SCHEDULE_TIME_SELECTORS, time_str)
    if not time_ok:
        time_ok = _set_time_via_dropdowns(page, when_local)

    if not date_ok or not time_ok:
        combo_date, combo_time = _set_datetime_via_combobox_display(page, when_local)
        date_ok = date_ok or combo_date
        time_ok = time_ok or combo_time

    if not date_ok or not time_ok:
        raise RuntimeError(
            f"Campos data/hora nao preenchidos (date_ok={date_ok}, time_ok={time_ok}, "
            f"alvo={date_str} {time_str})."
        )

    LOGGER.info("Agendamento configurado para %s %s (America/Sao_Paulo).", date_str, time_str)


def _button_label(btn) -> str:
    try:
        return (btn.inner_text(timeout=2000) or "").strip()
    except Exception:
        return ""


def _is_immediate_post_label(label: str) -> bool:
    return bool(IMMEDIATE_POST_LABEL_RE.search(label))


def _is_schedule_submit_label(label: str) -> bool:
    if _is_immediate_post_label(label):
        return False
    return bool(SCHEDULE_SUBMIT_LABEL_RE.search(label))


def _find_schedule_submit_button(page: Page):
    for sel in SCHEDULE_CONFIRM_BUTTON_SELECTORS:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible(timeout=1500):
                label = _button_label(loc)
                if label and not _is_schedule_submit_label(label):
                    LOGGER.warning("Ignorando seletor %s — label inesperado: %r", sel, label)
                    continue
                return loc, label or sel
        except Exception:
            continue

    for name_pattern in (
        r"^Schedule$",
        r"^Agendar$",
        r"^Programar$",
        r"Schedule post",
        r"Agendar publica",
        r"Programar publica",
    ):
        try:
            btn = page.get_by_role("button", name=re.compile(name_pattern, re.I)).first
            if btn.count() and btn.is_visible(timeout=1200):
                label = _button_label(btn)
                if _is_immediate_post_label(label):
                    continue
                if _is_schedule_submit_label(label) or label.lower() in ("agendar", "programar", "schedule"):
                    return btn, label
        except Exception:
            continue

    try:
        btn = page.locator('button:has-text("Agendar")').first
        if btn.count() and btn.is_visible(timeout=1200):
            label = _button_label(btn)
            if not _is_immediate_post_label(label):
                return btn, label or "Agendar"
    except Exception:
        pass

    return None, ""


def _click_schedule_submit(page: Page) -> None:
    btn, label = _find_schedule_submit_button(page)
    if btn is None:
        immediate = _first_visible(page, IMMEDIATE_POST_BUTTON_SELECTORS, timeout_ms=800)
        if immediate is not None:
            bad_label = _button_label(immediate)
            raise RuntimeError(
                f"Botao de publicacao imediata visivel ('{bad_label}') — "
                "botao Agendar/Schedule nao encontrado. Abortando."
            )
        raise RuntimeError(
            "Botao Agendar/Schedule nao encontrado apos configurar data/hora — abortando."
        )

    if _is_immediate_post_label(label):
        raise RuntimeError(f"Refusing to click immediate-post button: '{label}'")

    LOGGER.info("Clicando botao de agendamento: %r", label)
    btn.click(timeout=5000)
    page.wait_for_timeout(3000)
    _dismiss_popups(page)


def _click_post_now(page: Page) -> None:
    btn = _first_visible(page, IMMEDIATE_POST_BUTTON_SELECTORS)
    if btn is None:
        raise RuntimeError("Botao Publicar/Post nao encontrado.")
    label = _button_label(btn)
    LOGGER.info("Clicando publicacao imediata (--post-now): %r", label)
    btn.click(timeout=5000)
    page.wait_for_timeout(3000)
    _dismiss_popups(page)


def _verify_schedule_confirmation(page: Page, when_local: datetime, *, timeout_sec: int = 15) -> bool:
    """Return True if UI shows scheduled/agendado confirmation or leaves upload form."""
    date_hint = when_local.strftime("%d/%m")
    hour_hint = when_local.strftime("%H:%M")
    deadline = time.time() + timeout_sec
    confirm_re = re.compile(
        r"scheduled|agendado|agendamento|programado|successfully scheduled|"
        r"publicação agendada|publicacao agendada|video scheduled",
        re.I,
    )
    while time.time() < deadline:
        _dismiss_popups(page)
        try:
            if page.get_by_text(confirm_re).count():
                LOGGER.info("Toast/texto de confirmacao de agendamento detectado.")
                return True
        except Exception:
            pass
        try:
            body = page.locator("body").inner_text(timeout=2000)
            if confirm_re.search(body):
                LOGGER.info("Confirmacao de agendamento encontrada no body.")
                return True
            if date_hint in body and hour_hint in body and "agend" in body.lower():
                return True
        except Exception:
            pass
        try:
            if "tiktokstudio/content" in page.url.lower():
                return True
        except Exception:
            pass
        page.wait_for_timeout(800)
    return False


def _apply_schedule(page: Page, when_local: datetime) -> None:
    """Enable schedule UI and set date/time. Raises on failure — never falls back to post-now."""
    try:
        _enable_schedule_mode(page)
        page.wait_for_timeout(500)
        _set_schedule_datetime(page, when_local)
    except Exception as exc:
        _screenshot_on_failure(page, "apply_schedule_failed")
        raise RuntimeError(f"Falha ao aplicar agendamento na UI: {exc}") from exc


def upload_video_playwright(
    settings: TikTokSettings,
    video_path: Path,
    caption: str,
    *,
    dry_run: bool = False,
    post_now: bool = False,
    schedule_at_local: Optional[datetime] = None,
) -> UploadResult:
    video_path = video_path.resolve()
    if not video_path.is_file():
        return UploadResult(ok=False, error=f"Arquivo nao encontrado: {video_path}")

    if SCHEDULE_ONLY and post_now:
        return UploadResult(
            ok=False,
            error=(
                "Publicacao imediata bloqueada (SCHEDULE_ONLY=True). "
                "Use agendamento via SQLite; --post-now exige SCHEDULE_ONLY=False."
            ),
        )

    if not post_now and schedule_at_local is None:
        return UploadResult(
            ok=False,
            error="schedule_at_local obrigatorio quando post_now=False (modo agendado).",
        )

    if dry_run:
        when = schedule_at_local
        if when is not None:
            when = _round_time_to_five_min(when)
        LOGGER.info(
            "[DRY-RUN] Upload TikTok: %s | post_now=%s | scheduled for %s | caption=%s...",
            video_path.name,
            post_now,
            when.isoformat() if when else None,
            caption[:80],
        )
        return UploadResult(ok=True, post_id="dry-run", posted_immediately=post_now)

    if is_auth_only_active():
        return UploadResult(
            ok=False,
            error="Upload bloqueado: --auth-only em execucao. Conclua o login primeiro.",
        )

    with tiktok_browser(settings) as (ctx, page):
        net = _NetworkCapture()
        net.attach(page)
        try:
            ensure_session(settings, page, ctx)
            page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            _wait_upload_page_loaded(page)
            _dismiss_popups(page)

            file_input = _first_visible(page, FILE_INPUT_SELECTORS)
            if file_input is None:
                file_input = page.locator('input[type="file"]').first
            if file_input.count() == 0:
                _screenshot_on_failure(page, "no_file_input")
                net.flush()
                return UploadResult(ok=False, error="Input de arquivo de video nao encontrado.")

            LOGGER.info("Enviando arquivo: %s (%.1f MB)", video_path.name, video_path.stat().st_size / 1_048_576)
            file_input.set_input_files(str(video_path))
            _wait_upload_processed(page)
            _fill_caption(page, caption)
            _scroll_to_schedule_section(page)

            if post_now:
                _click_post_now(page)
                net.flush()
                return UploadResult(ok=True, post_id=f"tiktok-{int(time.time())}", posted_immediately=True)

            assert schedule_at_local is not None
            when = _round_time_to_five_min(schedule_at_local)
            LOGGER.info(
                "Modo agendado: scheduled for %s %s (nao publicar agora).",
                when.strftime("%Y-%m-%d"),
                when.strftime("%H:%M"),
            )
            _apply_schedule(page, when)
            _click_schedule_submit(page)

            if not _verify_schedule_confirmation(page, when):
                _screenshot_on_failure(page, "no_schedule_confirmation")
                net.flush()
                return UploadResult(
                    ok=False,
                    error=(
                        "Botao Agendar clicado mas confirmacao agendado/scheduled nao detectada — "
                        "abortando. Verifique .secrets/tiktok_debug/"
                    ),
                )

            post_id = f"tiktok-sched-{int(time.time())}"
            LOGGER.info(
                "Upload concluido — scheduled for %s %s (post_id=%s).",
                when.strftime("%Y-%m-%d"),
                when.strftime("%H:%M"),
                post_id,
            )
            net.flush()
            return UploadResult(ok=True, post_id=post_id, posted_immediately=False)
        except Exception as exc:
            _screenshot_on_failure(page, "upload_exception")
            net.flush()
            return UploadResult(ok=False, error=str(exc))
