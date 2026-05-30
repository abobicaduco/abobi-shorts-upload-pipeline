# -*- coding: utf-8 -*-
"""OAuth 2.0 for YouTube Data API v3 — first run opens browser, token saved to disk."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import (
    OAuthClientSource,
    get_youtube_oauth_entry,
    resolve_oauth_client,
    resolve_token_path,
)
from .secrets_store import YOUTUBE_OAUTH_KEY, update_service_key

LOGGER = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _missing_secrets_message(client: OAuthClientSource) -> str:
    lines = [
        "OAuth client credentials not found.",
        "",
        "Preferred: ~/.secrets/api-keys.json -> google_oauth_youtube with either:",
        "  - client_secret_json: { ... } (paste Desktop OAuth JSON), or",
        "  - client_id + client_secret + project_id, or",
        "  - client_secret_json: \"C:\\\\path\\\\to\\\\client_secret.json\"",
        "",
        "Or set YOUTUBE_CLIENT_SECRETS or place Desktop OAuth JSON at one of:",
    ]
    for path in client.candidates:
        lines.append(f"  - {path}")
    lines.extend(
        [
            "",
            "Google Cloud Console -> APIs & Services -> Credentials ->",
            "OAuth 2.0 Client ID (Desktop) -> Download JSON.",
            "",
            "After placing credentials, run:",
            "  python scripts/youtube-upload.py --auth-only",
        ]
    )
    return "\n".join(lines)


def _scopes_sufficient(creds: Credentials) -> bool:
    granted = set(creds.scopes or [])
    if not granted and creds.valid:
        return True
    return set(SCOPES).issubset(granted)


def _credentials_from_api_keys_entry(entry: dict[str, Any]) -> Credentials | None:
    refresh_token = str(entry.get("refresh_token", "")).strip()
    if not refresh_token:
        return None
    client_id = str(entry.get("client_id", "")).strip() or None
    client_secret = str(entry.get("client_secret", "")).strip() or None
    token_uri = str(entry.get("token_uri", "")).strip() or "https://oauth2.googleapis.com/token"
    scopes = entry.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        scopes = list(SCOPES)
    token = entry.get("token")
    return Credentials(
        token=token,
        refresh_token=refresh_token,
        token_uri=token_uri,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )


def _credentials_from_token_file(token_path: Path) -> Credentials | None:
    if not token_path.is_file():
        return None
    return Credentials.from_authorized_user_file(str(token_path), SCOPES)


def _persist_credentials(creds: Credentials, token_path: Path) -> None:
    """Save token to file (fallback) and merge into api-keys google_oauth_youtube."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    LOGGER.info("Token saved to %s", token_path)

    try:
        token_data = json.loads(creds.to_json())
    except json.JSONDecodeError:
        LOGGER.warning("Could not serialize credentials for api-keys merge.")
        return

    updates: dict[str, Any] = {
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": token_data.get("token_uri"),
        "scopes": token_data.get("scopes") or list(SCOPES),
        "token_saved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    if token_data.get("client_id"):
        updates["client_id"] = token_data["client_id"]
    if token_data.get("client_secret"):
        updates["client_secret"] = token_data["client_secret"]
    if token_data.get("token"):
        updates["token"] = token_data["token"]

    entry = get_youtube_oauth_entry() or {}
    if not updates.get("client_id") and entry.get("client_id"):
        updates["client_id"] = entry["client_id"]
    if not updates.get("client_secret") and entry.get("client_secret"):
        updates["client_secret"] = entry["client_secret"]
    if not updates.get("project_id") and entry.get("project_id"):
        updates["project_id"] = entry["project_id"]

    update_service_key(YOUTUBE_OAUTH_KEY, updates, merge=True)
    LOGGER.info("Token merged into api-keys.json -> %s", YOUTUBE_OAUTH_KEY)


def _run_oauth_flow(client: OAuthClientSource) -> Credentials:
    if client.config is not None:
        LOGGER.info("Starting OAuth flow from api-keys config (browser will open)...")
        flow = InstalledAppFlow.from_client_config(client.config, SCOPES)
        return flow.run_local_server(port=0, open_browser=True)

    if client.secrets_file is not None and client.secrets_file.is_file():
        LOGGER.info("Starting OAuth flow from %s (browser will open)...", client.secrets_file)
        flow = InstalledAppFlow.from_client_secrets_file(str(client.secrets_file), SCOPES)
        return flow.run_local_server(port=0, open_browser=True)

    raise FileNotFoundError(_missing_secrets_message(client))


def get_credentials(
    client_secrets: Path | None = None,
    token_path: Path | None = None,
    *,
    force_refresh: bool = False,
) -> Credentials:
    """Load or obtain OAuth credentials; refresh if expired."""
    client = resolve_oauth_client()
    if client_secrets is not None:
        if client.config is None and client_secrets.is_file():
            client = OAuthClientSource(
                secrets_file=client_secrets,
                candidates=[client_secrets],
                source="caller",
            )
        elif client.config is None:
            client = OAuthClientSource(
                secrets_file=client_secrets,
                candidates=[client_secrets, *client.candidates],
                source="caller",
            )

    if token_path is None:
        token_path, _ = resolve_token_path()

    token_path.parent.mkdir(parents=True, exist_ok=True)
    creds: Credentials | None = None

    if not force_refresh:
        entry = get_youtube_oauth_entry()
        if entry:
            creds = _credentials_from_api_keys_entry(entry)
        if creds is None:
            creds = _credentials_from_token_file(token_path)
        if creds and not _scopes_sufficient(creds):
            LOGGER.warning(
                "Saved token does not include YouTube scopes (e.g. only AdSense/Sheets). "
                "Re-authenticating with youtube.upload..."
            )
            creds = None

    if creds and creds.expired and creds.refresh_token:
        LOGGER.info("Refreshing OAuth token...")
        creds.refresh(Request())
        _persist_credentials(creds, token_path)
        return creds

    if creds and creds.valid:
        return creds

    if not client.is_available:
        raise FileNotFoundError(_missing_secrets_message(client))

    creds = _run_oauth_flow(client)
    _persist_credentials(creds, token_path)
    return creds


def get_youtube_service(
    client_secrets: Path | None = None,
    token_path: Path | None = None,
) -> Any:
    """Build authenticated YouTube API v3 client."""
    if token_path is None:
        token_path, _ = resolve_token_path()
    creds = get_credentials(client_secrets, token_path)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)
