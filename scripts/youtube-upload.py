# -*- coding: utf-8 -*-
"""Thin launcher: python scripts/youtube-upload.py [args...]"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from youtube.stdio import configure_stdio_utf8
from youtube.upload import main

if __name__ == "__main__":
    configure_stdio_utf8()
    sys.exit(main())
