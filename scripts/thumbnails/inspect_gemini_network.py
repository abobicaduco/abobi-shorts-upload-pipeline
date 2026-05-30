# -*- coding: utf-8 -*-
"""Log Gemini web fetch/XHR while user generates an image manually.

Usage:
    python scripts/thumbnails/inspect_gemini_network.py

Steps:
    1. Browser opens gemini.google.com/app (uses saved storage_state if present)
    2. Attach a face photo, paste a thumbnail prompt, wait for image
    3. Return to terminal and press ENTER to save log and exit

Output: ~/.secrets/gemini_network.log (URLs only — query tokens redacted, no headers)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from thumbnails.gemini_web import (
    GEMINI_APP_URL,
    attach_network_logger,
    ensure_session,
    gemini_browser,
    resolve_network_log_path,
    GeminiWebSettings,
)


def main() -> int:
    settings = GeminiWebSettings.from_args(headless=False, sniff_network=False)
    log_path = resolve_network_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")

    print(
        "Gemini network inspector\n"
        f"Log file: {log_path}\n"
        "1) Gere uma imagem manualmente no chat (anexe selfie + prompt)\n"
        "2) Pressione ENTER aqui para salvar e fechar\n"
    )

    lines: list[str] = []

    with gemini_browser(settings) as (ctx, page):
        captured, _flush = attach_network_logger(page, log_path=None, echo=True)
        try:
            ensure_session(settings, page, ctx)
        except RuntimeError as exc:
            print(f"\n{exc}\n")
            print("Continuando sem sessao — faca login manual no browser.\n")

        page.goto(GEMINI_APP_URL, wait_until="domcontentloaded")
        try:
            input()
        except EOFError:
            print("Entrada cancelada — salvando log parcial.")

        lines = captured

    header = [
        "# Gemini web network capture",
        f"# started={started}",
        f"# ended={datetime.now().isoformat(timespec='seconds')}",
        f"# app_url={GEMINI_APP_URL}",
        "# NOTE: auth uses browser cookies (SAPISIDHASH) — never log Cookie headers",
        "",
    ]
    log_path.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    print(f"\nSalvo: {log_path} ({len(lines)} linhas)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
