# -*- coding: utf-8 -*-
"""CLI entry: generate YouTube thumbnails with Gemini (see docs/THUMBNAILS.md).

Default --faces-dir: FACES_DIR env, .secrets/thumbnail_faces/, or %USERPROFILE%/Pictures/EU
(thumbnail selfies only — scripts/shared/paths.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from thumbnails.gemini_generate import main

if __name__ == "__main__":
    sys.exit(main())
