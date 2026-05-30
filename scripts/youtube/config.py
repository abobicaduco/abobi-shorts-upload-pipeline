# -*- coding: utf-8 -*-
"""Environment and path configuration for YouTube upload scripts."""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from shared.paths import PROJECT_SECRETS_DIR
from .secrets_store import API_KEYS_PATH, YOUTUBE_OAUTH_KEY, get_service_key

LOGGER = logging.getLogger(__name__)

# Default inbox (override with YOUTUBE_INBOX). E:/YOUTUBE/inbox on some machines.
_DEFAULT_INBOX = Path.home() / "YOUTUBE" / "inbox"

_ENV_FILE = _SCRIPTS_DIR / ".env"
_MODULE_SECRETS_DIR = Path(__file__).resolve().parent / ".secrets"
_USER_SECRETS_SCRIPTS = Path.home() / ".secrets" / "scripts"
_PROJECT_SECRETS = PROJECT_SECRETS_DIR

_DEFAULT_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
_DEFAULT_CERT_URL = "https://www.googleapis.com/oauth2/v1/certs"


def load_env_file() -> None:
    """Load KEY=VALUE lines from scripts/.env into os.environ (no overwrite)."""
    if not _ENV_FILE.is_file():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _path_from_env(name: str) -> Optional[Path]:
    raw = os.environ.get(name, "").strip()
    return Path(raw) if raw else None


def _first_existing(candidates: Sequence[Path]) -> Optional[Path]:
    for path in candidates:
        if path.is_file():
            return path
    return None


def get_youtube_oauth_entry() -> dict[str, Any] | None:
    """Return google_oauth_youtube from api-keys.json, or None."""
    return get_service_key(YOUTUBE_OAUTH_KEY)


def _client_secret_path_from_entry(entry: dict[str, Any]) -> Optional[Path]:
    raw = entry.get("client_secret_json")
    if isinstance(raw, str) and raw.strip():
        path = Path(raw.strip())
        return path if path.is_file() else None
    return None


def _client_secret_path_from_api_keys_legacy() -> Optional[Path]:
    """Legacy: google_oauth_adsense.client_secret_json path."""
    entry = get_service_key("google_oauth_adsense")
    if not entry:
        return None
    return _client_secret_path_from_entry(entry)


def _installed_block_from_flat(entry: dict[str, Any]) -> dict[str, Any] | None:
    client_id = str(entry.get("client_id", "")).strip()
    client_secret = str(entry.get("client_secret", "")).strip()
    if not client_id or not client_secret:
        return None
    project_id = str(entry.get("project_id", "")).strip()
    block: dict[str, Any] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": str(entry.get("auth_uri", _DEFAULT_AUTH_URI)).strip() or _DEFAULT_AUTH_URI,
        "token_uri": str(entry.get("token_uri", _DEFAULT_TOKEN_URI)).strip() or _DEFAULT_TOKEN_URI,
        "auth_provider_x509_cert_url": str(
            entry.get("auth_provider_x509_cert_url", _DEFAULT_CERT_URL)
        ).strip()
        or _DEFAULT_CERT_URL,
        "redirect_uris": entry.get("redirect_uris") or ["http://localhost"],
    }
    if project_id:
        block["project_id"] = project_id
    return block


def client_config_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Build InstalledAppFlow client config from api-keys entry fields."""
    raw = entry.get("client_secret_json")
    if isinstance(raw, dict):
        if "installed" in raw or "web" in raw:
            return raw
        installed = _installed_block_from_flat(raw)
        return {"installed": installed} if installed else None

    path = _client_secret_path_from_entry(entry)
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    installed = _installed_block_from_flat(entry)
    return {"installed": installed} if installed else None


@dataclass
class OAuthClientSource:
    """Resolved OAuth client: inline config and/or secrets file path."""

    config: dict[str, Any] | None = None
    secrets_file: Path | None = None
    candidates: list[Path] = field(default_factory=list)
    source: str = "none"

    @property
    def is_available(self) -> bool:
        if self.config is not None:
            return True
        return self.secrets_file is not None and self.secrets_file.is_file()


def resolve_oauth_client() -> OAuthClientSource:
    """Resolve OAuth client: env → api-keys youtube → files → api-keys adsense → Downloads."""
    env_path = _path_from_env("YOUTUBE_CLIENT_SECRETS")
    if env_path is not None:
        return OAuthClientSource(secrets_file=env_path, candidates=[env_path], source="env")

    youtube_entry = get_youtube_oauth_entry()
    if youtube_entry:
        inline = client_config_from_entry(youtube_entry)
        if inline is not None:
            path_hint = _client_secret_path_from_entry(youtube_entry)
            candidates = [path_hint] if path_hint else []
            return OAuthClientSource(
                config=inline,
                secrets_file=path_hint,
                candidates=candidates,
                source="api-keys.youtube",
            )

    candidates: list[Path] = [
        _PROJECT_SECRETS / "youtube_client_secret.json",
        _USER_SECRETS_SCRIPTS / "youtube_client_secret.json",
        _USER_SECRETS_SCRIPTS / "client_secret.json",
        _MODULE_SECRETS_DIR / "client_secret.json",
    ]
    from_adsense = _client_secret_path_from_api_keys_legacy()
    if from_adsense is not None:
        candidates.append(from_adsense)
    dl = _downloads_client_secret_glob()
    if dl is not None:
        candidates.append(dl)

    found = _first_existing(candidates)
    default = candidates[0]
    chosen = found if found is not None else default
    source = "file"
    if found is not None and from_adsense is not None and found == from_adsense:
        source = "api-keys.adsense"
    return OAuthClientSource(secrets_file=chosen, candidates=candidates, source=source)


def _downloads_client_secret_glob() -> Optional[Path]:
    downloads = Path.home() / "Downloads"
    if not downloads.is_dir():
        return None
    matches = sorted(downloads.glob("client_secret*.json"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        LOGGER.debug(
            "Multiple client_secret*.json in Downloads; set YOUTUBE_CLIENT_SECRETS explicitly."
        )
    return None


def resolve_client_secrets() -> tuple[Path, list[Path]]:
    """Backward-compatible path resolver (prefer resolve_oauth_client for auth)."""
    source = resolve_oauth_client()
    if source.secrets_file is not None:
        return source.secrets_file, source.candidates
    return source.candidates[0] if source.candidates else _USER_SECRETS_SCRIPTS / "youtube_client_secret.json", source.candidates


def resolve_token_path() -> tuple[Path, list[Path]]:
    """Resolve OAuth token JSON path: env → user secrets → module .secrets."""
    env_path = _path_from_env("YOUTUBE_TOKEN_PATH")
    if env_path is not None:
        return env_path, [env_path]

    candidates: list[Path] = [
        _PROJECT_SECRETS / "youtube_token.json",
        _USER_SECRETS_SCRIPTS / "youtube_token.json",
        _MODULE_SECRETS_DIR / "token.json",
    ]
    found = _first_existing(candidates)
    default = candidates[0]
    return (found if found is not None else default), candidates


@dataclass
class YouTubeSettings:
    inbox: Path
    uploaded_dir: Path
    client_secrets: Path
    token_path: Path
    log_to_uploaded_dir: bool = True

    @classmethod
    def from_env(cls) -> YouTubeSettings:
        load_env_file()
        inbox = _path_from_env("YOUTUBE_INBOX") or _DEFAULT_INBOX
        uploaded = _path_from_env("YOUTUBE_UPLOADED_DIR") or (inbox / "uploaded")
        client_secrets, _ = resolve_client_secrets()
        token_path, _ = resolve_token_path()
        return cls(
            inbox=inbox,
            uploaded_dir=uploaded,
            client_secrets=client_secrets,
            token_path=token_path,
        )


@dataclass
class BatchConfig:
    """Shared settings from batch.yaml applied to every clip."""

    hashtags: str = ""
    tags: List[str] = field(default_factory=list)
    privacy: str = "public"
    playlist_id: Optional[str] = None
    category_id: str = "20"
    append_shorts_hashtag: bool = False
    default_thumb: Optional[Path] = None

    def build_description(self, base: str) -> str:
        parts: list[str] = []
        if base.strip():
            parts.append(base.strip())
        if self.hashtags.strip():
            parts.append(self.hashtags.strip())
        if self.append_shorts_hashtag and "#Shorts" not in " ".join(parts):
            parts.append("#Shorts")
        return "\n\n".join(parts) if parts else ""


__all__ = [
    "API_KEYS_PATH",
    "BatchConfig",
    "OAuthClientSource",
    "YOUTUBE_OAUTH_KEY",
    "YouTubeSettings",
    "client_config_from_entry",
    "get_youtube_oauth_entry",
    "load_env_file",
    "resolve_client_secrets",
    "resolve_oauth_client",
    "resolve_token_path",
]
