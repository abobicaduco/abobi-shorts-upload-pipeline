# Local setup — shorts upload pipeline

**Canonical development tree:**

`C:\Users\carlo\Projects\abobi-shorts-upload-pipeline`

**GitHub:**

`https://github.com/abobicaduco/abobi-shorts-upload-pipeline`

This repo contains **only** YouTube + TikTok upload automation:

- **YouTube** — `scripts/youtube/` (API, OAuth, SQLite)
- **TikTok** — `scripts/tiktok/` (Playwright, separate SQLite)
- **Shared** — `scripts/shared/` (`paths.py`, pipeline lock, LLM metadata)

The [AboBI Tools](https://abobiferramentas.com) website is a separate repo.

## Local runtime data (gitignored, under project)

Session files, SQLite DBs, and browser profiles live in **`<repo>/.secrets/`** (never committed).

```
abobi-shorts-upload-pipeline/
├── .secrets/                          # gitignored — create on first run
│   ├── gemini_storage_state.json      # Gemini web session
│   ├── browser-profile-gemini/        # Playwright Chrome profile (Gemini)
│   ├── chrome-debug-gemini/           # CDP debug profile (--auth-cdp)
│   ├── gemini_network.log             # optional RPC sniff log
│   ├── youtube_schedule.db            # YouTube slot state
│   ├── tiktok_schedule.db             # TikTok slot state
│   ├── tiktok_storage_state.json      # TikTok Playwright session
│   ├── browser-profile-tiktok/        # TikTok Chrome profile
│   ├── tiktok_debug/                  # upload debug screenshots
│   ├── youtube_token.json             # optional OAuth token (fallback)
│   └── youtube_client_secret.json     # optional OAuth client (fallback)
├── .local/
│   └── logs/                          # optional pipeline logs
└── scripts/
```

Path resolution: `scripts/shared/paths.py` (`PROJECT_ROOT`, `PROJECT_SECRETS_DIR`).

### API keys (home canonical)

`api-keys.json` stays at **`%USERPROFILE%\.secrets\api-keys.json`** when you already use that location. Scripts read home first, then `<repo>/.secrets/api-keys.json` as fallback. **Do not commit either copy.**

| File | Location | Platform |
|------|----------|----------|
| `api-keys.json` | `%USERPROFILE%\.secrets\` (preferred) | Shared API keys + OAuth inline |
| `youtube_schedule.db` | `<repo>/.secrets/` | YouTube slots |
| `tiktok_schedule.db` | `<repo>/.secrets/` | TikTok slots |
| `gemini_storage_state.json` | `<repo>/.secrets/` | Gemini thumbnails |
| `tiktok_storage_state.json` | `<repo>/.secrets/` | TikTok upload session |

### One-time migration from `%USERPROFILE%\.secrets\`

If you previously stored session/DB files in the home folder, copy once (PowerShell, adjust repo path):

```powershell
$repo = "C:\Users\carlo\Projects\abobi-shorts-upload-pipeline"
$homeSecrets = "$env:USERPROFILE\.secrets"
New-Item -ItemType Directory -Force -Path "$repo\.secrets" | Out-Null

@(
  "gemini_storage_state.json",
  "tiktok_storage_state.json",
  "youtube_schedule.db",
  "tiktok_schedule.db",
  "gemini_network.log"
) | ForEach-Object {
  $src = Join-Path $homeSecrets $_
  if (Test-Path $src) { Copy-Item $src "$repo\.secrets\" -Force; Write-Host "Copied $_" }
}

@("browser-profile-gemini", "browser-profile-tiktok", "chrome-debug-gemini") | ForEach-Object {
  $src = Join-Path $homeSecrets $_
  if (Test-Path $src) {
    Copy-Item $src "$repo\.secrets\" -Recurse -Force
    Write-Host "Copied folder $_"
  }
}

# Legacy profile under scripts/ (if present)
$legacy = Join-Path $repo "scripts\browser-profile-gemini"
if (Test-Path $legacy) {
  Copy-Item $legacy "$repo\.secrets\browser-profile-gemini" -Recurse -Force
  Write-Host "Copied scripts/browser-profile-gemini"
}
```

Scripts auto-fallback to home copies until project files exist.

## Media folders (still under home — not in repo)

| Path | Purpose |
|------|---------|
| `%USERPROFILE%\YOUTUBE\inbox\<batch_id>\` | Long-form ingest + manifest (see [docs/content/FORTNITE_MOBILE.md](docs/content/FORTNITE_MOBILE.md)) |
| `%USERPROFILE%\YOUTUBE\pending_tiktok\` | TikTok copies awaiting Playwright upload |
| `%USERPROFILE%\YOUTUBE\clips\..._tiktok\` | Split clips (YouTube + TikTok) |
| `%USERPROFILE%\Pictures\EU\` | Face selfies for thumbnails (machine-specific — see `docs/LOCAL_USER_PATHS.md`, gitignored) |

## Docs for agents

Start at [docs/PLATFORMS.md](docs/PLATFORMS.md) — links YouTube + TikTok handoffs, policies, and daily commands.

- [docs/youtube/HANDOFF.md](docs/youtube/HANDOFF.md)
- [docs/tiktok/HANDOFF.md](docs/tiktok/HANDOFF.md)
- [docs/THUMBNAILS.md](docs/THUMBNAILS.md)
- [AGENTS.md](AGENTS.md)
