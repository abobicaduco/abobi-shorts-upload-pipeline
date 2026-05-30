# -*- coding: utf-8 -*-
"""Project-root paths for local runtime data (gitignored .secrets/)."""
from __future__ import annotations

from pathlib import Path

# scripts/shared/paths.py -> scripts -> repo root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
PROJECT_SECRETS_DIR = PROJECT_ROOT / ".secrets"
HOME_SECRETS_DIR = Path.home() / ".secrets"
PROJECT_LOGS_DIR = PROJECT_ROOT / ".local" / "logs"


def ensure_project_secrets_dir() -> Path:
    PROJECT_SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    return PROJECT_SECRETS_DIR


def resolve_api_keys_path() -> Path:
    """Canonical api-keys.json: %USERPROFILE%\\.secrets first, then project .secrets/."""
    home = HOME_SECRETS_DIR / "api-keys.json"
    if home.is_file():
        return home
    project = PROJECT_SECRETS_DIR / "api-keys.json"
    if project.is_file():
        return project
    return home


def project_secret(name: str) -> Path:
    """Default path under repo .secrets/ (for new session files and DBs)."""
    return PROJECT_SECRETS_DIR / name


def project_secret_with_home_fallback(name: str) -> Path:
    """Prefer project .secrets/; use home legacy copy if project file missing."""
    project = PROJECT_SECRETS_DIR / name
    home = HOME_SECRETS_DIR / name
    if project.is_file():
        return project
    if home.is_file():
        return home
    return project


def project_secret_dir_with_fallbacks(name: str, *legacy_dirs: Path) -> Path:
    """Directory under project .secrets/; fall back to legacy locations if populated."""
    project = PROJECT_SECRETS_DIR / name
    if project.is_dir() and any(project.iterdir()):
        return project
    home = HOME_SECRETS_DIR / name
    if home.is_dir() and any(home.iterdir()):
        return home
    for legacy in legacy_dirs:
        if legacy.is_dir() and any(legacy.iterdir()):
            return legacy
    return project
