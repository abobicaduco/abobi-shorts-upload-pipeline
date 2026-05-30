# -*- coding: utf-8 -*-
"""Shared utilities for YouTube and TikTok automation."""

from shared.paths import (
    HOME_SECRETS_DIR,
    PROJECT_LOGS_DIR,
    PROJECT_ROOT,
    PROJECT_SECRETS_DIR,
    ensure_project_secrets_dir,
    project_secret,
    project_secret_dir_with_fallbacks,
    project_secret_with_home_fallback,
    resolve_api_keys_path,
)

__all__ = [
    "HOME_SECRETS_DIR",
    "PROJECT_LOGS_DIR",
    "PROJECT_ROOT",
    "PROJECT_SECRETS_DIR",
    "ensure_project_secrets_dir",
    "project_secret",
    "project_secret_dir_with_fallbacks",
    "project_secret_with_home_fallback",
    "resolve_api_keys_path",
]
