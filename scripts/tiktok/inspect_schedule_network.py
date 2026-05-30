# -*- coding: utf-8 -*-
"""Log TikTok Creator Center fetch/XHR while user schedules a video manually.

Usage:
    python scripts/tiktok/inspect_schedule_network.py

Steps:
    1. Browser opens tiktokstudio/upload
    2. Log in if needed, upload a short test video
    3. Enable Schedule (Agendar), pick date/time, click Agendar
    4. Return to terminal and press ENTER to save log and exit

Output: ~/.secrets/tiktok_schedule_network.log (URLs only, no auth headers)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.paths import project_secret
from tiktok.auth import ensure_session, tiktok_browser
from tiktok.config import TIKTOK_UPLOAD_URL, TikTokSettings, load_env_file
from youtube.stdio import configure_stdio_utf8

LOG_PATH = project_secret("tiktok_schedule_network.log")
TRACKED_TYPES = frozenset({"fetch", "xhr", "document"})


def main() -> int:
    configure_stdio_utf8()
    load_env_file()
    settings = TikTokSettings.from_env()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    started = datetime.now().isoformat(timespec="seconds")

    def on_request(request) -> None:
        if request.resource_type not in TRACKED_TYPES:
            return
        url = request.url
        if any(x in url.lower() for x in ("google", "gstatic", "facebook", "doubleclick")):
            return
        line = f"{datetime.now().isoformat(timespec='seconds')} REQ {request.method} {url}"
        lines.append(line)
        print(line)

    def on_response(response) -> None:
        req = response.request
        if req.resource_type not in TRACKED_TYPES:
            return
        url = response.url
        if any(x in url.lower() for x in ("google", "gstatic", "facebook", "doubleclick")):
            return
        line = (
            f"{datetime.now().isoformat(timespec='seconds')} "
            f"RES {response.status} {req.method} {url}"
        )
        lines.append(line)

    print(
        "TikTok schedule network inspector\n"
        f"Log file: {LOG_PATH}\n"
        "1) Faca upload manual + agende um video\n"
        "2) Pressione ENTER aqui para salvar e fechar\n"
    )

    with tiktok_browser(settings) as (ctx, page):
        page.on("request", on_request)
        page.on("response", on_response)
        ensure_session(settings, page, ctx)
        page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded")
        try:
            input()
        except EOFError:
            print("Entrada cancelada — salvando log parcial.")

    header = [
        f"# TikTok schedule network capture",
        f"# started={started}",
        f"# ended={datetime.now().isoformat(timespec='seconds')}",
        f"# upload_url={TIKTOK_UPLOAD_URL}",
        "",
    ]
    LOG_PATH.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    print(f"\nSalvo: {LOG_PATH} ({len(lines)} linhas)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
