# Local setup — shorts upload pipeline

**Canonical development tree:**

`C:\Users\carlo\Projects\abobi-shorts-upload-pipeline`

**GitHub:**

`https://github.com/abobicaduco/abobi-shorts-upload-pipeline`

This repo contains **only** YouTube + TikTok upload automation:

- **YouTube** — `scripts/youtube/` (API, OAuth, SQLite)
- **TikTok** — `scripts/tiktok/` (Playwright, separate SQLite)
- **Shared** — `scripts/shared/` (pipeline lock, LLM metadata)

The [AboBI Tools](https://abobiferramentas.com) website is a separate repo:

`C:\Users\carlo\Projects\abobi-shorts-upload-pipeline`

## Secrets (never in repo)

Keep credentials only under:

`C:\Users\carlo\.secrets\`

| File | Platform |
|------|----------|
| `api-keys.json` | Shared API keys |
| `youtube_client_secret.json` | YouTube OAuth |
| `youtube_token.json` | YouTube OAuth token |
| `youtube_schedule.db` | YouTube slot state |
| `tiktok_schedule.db` | TikTok slot state |
| `tiktok_storage_state.json` | TikTok Playwright session |

Do **not** copy secrets into the project tree or commit them.

## Media folders

| Path | Purpose |
|------|---------|
| `%USERPROFILE%\YOUTUBE\inbox` | Long-form videos for YouTube split |
| `%USERPROFILE%\YOUTUBE\clips\..._tiktok\` | Split clips (YouTube + TikTok) |

## Docs for agents

Start at [docs/PLATFORMS.md](docs/PLATFORMS.md) — links YouTube + TikTok handoffs, policies, and daily commands.

- [docs/youtube/HANDOFF.md](docs/youtube/HANDOFF.md)
- [docs/tiktok/HANDOFF.md](docs/tiktok/HANDOFF.md)
- [AGENTS.md](AGENTS.md)
