# -*- coding: utf-8 -*-
"""Windows-safe stdio for CLI logging (UTF-8 when supported)."""
from __future__ import annotations

import sys


def configure_stdio_utf8() -> None:
    """Prefer UTF-8 on Windows consoles; fall back silently."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass
