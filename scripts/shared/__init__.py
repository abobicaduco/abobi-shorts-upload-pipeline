# -*- coding: utf-8 -*-
"""Shared utilities for YouTube and TikTok automation."""

from shared.paths import (
    DEFAULT_FACES_DIR,
    FACE_IMAGE_EXTENSIONS,
    HOME_SECRETS_DIR,
    PROJECT_LOGS_DIR,
    PROJECT_ROOT,
    PROJECT_SECRETS_DIR,
    ensure_project_secrets_dir,
    project_secret,
    project_secret_dir_with_fallbacks,
    project_secret_with_home_fallback,
    resolve_api_keys_path,
    resolve_faces_dir,
    thumbnail_faces_dir,
    validate_faces_dir,
)

__all__ = [
    "DEFAULT_FACES_DIR",
    "FACE_IMAGE_EXTENSIONS",
    "HOME_SECRETS_DIR",
    "PROJECT_LOGS_DIR",
    "PROJECT_ROOT",
    "PROJECT_SECRETS_DIR",
    "ensure_project_secrets_dir",
    "project_secret",
    "project_secret_dir_with_fallbacks",
    "project_secret_with_home_fallback",
    "resolve_api_keys_path",
    "resolve_faces_dir",
    "thumbnail_faces_dir",
    "validate_faces_dir",
]
