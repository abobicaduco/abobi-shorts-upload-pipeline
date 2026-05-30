# -*- coding: utf-8 -*-
"""CLI: Gemini web thumbnails (browser session, no API key). See docs/THUMBNAILS.md."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from thumbnails.gemini_web import main

if __name__ == "__main__":
    sys.exit(main())
