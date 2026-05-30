# AI continuation — start here

> **For Cursor, Claude, Google Antigravity, and other coding agents.**

## Paste this into a new session

1. **[docs/PLATFORMS.md](PLATFORMS.md)** — YouTube + TikTok index (paths, DBs, daily commands)
2. **[docs/youtube/HANDOFF.md](youtube/HANDOFF.md)** — YouTube bilingual handoff
3. **[docs/tiktok/HANDOFF.md](tiktok/HANDOFF.md)** — TikTok bilingual handoff
4. **[docs/youtube/SCHEDULING_POLICY.md](youtube/SCHEDULING_POLICY.md)** + **[docs/tiktok/SCHEDULING_POLICY.md](tiktok/SCHEDULING_POLICY.md)**

Portuguese README: [README.pt-BR.md](../README.pt-BR.md) · English: [README.md](../README.md)

## Quick pointers

| Topic | Document |
|-------|----------|
| Both platforms overview | [PLATFORMS.md](PLATFORMS.md) |
| YouTube upload + OAuth | [youtube/HANDOFF.md](youtube/HANDOFF.md) |
| TikTok Playwright upload | [tiktok/HANDOFF.md](tiktok/HANDOFF.md) |
| 3/day slot rules | Both `SCHEDULING_POLICY.md` files |
| Long-form Fortnite batch | [content/FORTNITE_MOBILE.md](content/FORTNITE_MOBILE.md) |
| Thumbnails (manual + future Gemini) | [THUMBNAILS.md](THUMBNAILS.md) |
| Split + schedule details | [youtube/SCHEDULER.md](youtube/SCHEDULER.md) |
| Channel audit / duplicates | `scripts/youtube-audit.py` · [youtube/HANDOFF.md](youtube/HANDOFF.md) |
| Agent convention | [AGENTS.md](../AGENTS.md) |
| Local paths + secrets | [LOCAL_SETUP.md](../LOCAL_SETUP.md) |
| Ollama clip metadata | `scripts/shared/llm_metadata.py` · [PLATFORMS.md](PLATFORMS.md#ollama-local-llama--captions) |
| TikTok schedule UI debug | [tiktok/SCHEDULE_UI.md](tiktok/SCHEDULE_UI.md) |
| Git commits as Caduco | `G:\My Drive\python\tools\caduco-git-commit\invoke.ps1` (see [AGENTS.md](../AGENTS.md)) |

## What to run next (2026-05-30+)

**YouTube Shorts** — if any `pending` remain:

```powershell
python scripts/youtube-pipeline.py --resume --upload-limit 6 --until-done
```

**YouTube audit** (duplicates / private Shorts not in DB):

```powershell
python scripts/youtube-audit.py --dry-run
```

**Fortnite long-form** (1 video per day):

```powershell
python scripts/fortnite_long_batch.py --upload-limit 1
```

**TikTok** (~16 Granny pending + Fortnite in `pending_tiktok`; max 3/day, ≤30 scheduled):

```powershell
python scripts/tiktok-pipeline.py --resume --upload-limit 3
```

**Thumbnails:** approve files in `inbox/<batch>/thumbnails/` before upload — [THUMBNAILS.md](THUMBNAILS.md).

**Never commit:** `client_secret*.json`, `youtube_token.json`, `tiktok_storage_state.json`, `api-keys.json`, `.env`, `*.db`, `browser-profile-tiktok/`.

*Updated: 2026-05-30*
