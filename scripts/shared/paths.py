# -*- coding: utf-8 -*-
"""Project-root paths for local runtime data (gitignored .secrets/)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# scripts/shared/paths.py -> scripts -> repo root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
PROJECT_SECRETS_DIR = PROJECT_ROOT / ".secrets"
HOME_SECRETS_DIR = Path.home() / ".secrets"
PROJECT_LOGS_DIR = PROJECT_ROOT / ".local" / "logs"

# Thumbnail reference selfies only — not a general photo library.
DEFAULT_FACES_DIR = Path.home() / "Pictures" / "EU"
FACE_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})


def thumbnail_faces_dir() -> Path:
    """Canonical default folder for thumbnail face reference photos (dedicated selfies)."""
    return DEFAULT_FACES_DIR


def resolve_faces_dir(cli: Optional[Path] = None) -> Path:
    """Resolve faces-dir: CLI > FACES_DIR env > .secrets/thumbnail_faces > DEFAULT_FACES_DIR."""
    if cli is not None:
        return Path(cli).expanduser().resolve()
    env = os.environ.get("FACES_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return project_secret_dir_with_fallbacks("thumbnail_faces", DEFAULT_FACES_DIR)


def validate_faces_dir(faces_dir: Path) -> None:
    """Fail fast if faces-dir is unset, missing, or has no jpg/png (batch thumbnail refs)."""
    if not str(faces_dir).strip():
        raise ValueError(
            "--faces-dir is empty. Pass --faces-dir, set FACES_DIR, add jpg/png under "
            f".secrets/thumbnail_faces/, or use {DEFAULT_FACES_DIR} "
            "(thumbnail selfies only — see docs/THUMBNAILS.md)."
        )
    if not faces_dir.is_dir():
        raise FileNotFoundError(
            f"Faces directory not found: {faces_dir}\n"
            f"Create it and add thumbnail selfie references (jpg/png). "
            f"Default on this machine: {DEFAULT_FACES_DIR}"
        )
    faces = [
        p
        for p in sorted(faces_dir.iterdir())
        if p.is_file() and p.suffix.lower() in FACE_IMAGE_EXTENSIONS
    ]
    if not faces:
        raise FileNotFoundError(
            f"No jpg/png face images in {faces_dir}\n"
            "Add one thumbnail selfie per video (batch). "
            "This folder is for thumbnail generation only — not general photos."
        )


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


def project_secret_with_home_fallback(name: str, *, sync_from_home: bool = True) -> Path:
    """Prefer project .secrets/; copy home legacy file into project when missing."""
    project = PROJECT_SECRETS_DIR / name
    home = HOME_SECRETS_DIR / name
    if project.is_file():
        return project
    if home.is_file():
        if sync_from_home:
            ensure_project_secrets_dir()
            project.write_bytes(home.read_bytes())
            return project
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
