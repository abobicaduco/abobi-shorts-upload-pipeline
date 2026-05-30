# -*- coding: utf-8 -*-
"""Launcher for TikTok schedule + upload pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from tiktok.pipeline import run_pipeline
from youtube.stdio import configure_stdio_utf8

if __name__ == "__main__":
    configure_stdio_utf8()
    sys.exit(run_pipeline())
