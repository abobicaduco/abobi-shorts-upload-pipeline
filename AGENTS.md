# Agent instructions

For **Cursor**, **Claude**, **Google Antigravity**, and other AI coding agents working on this repo.

## Start here

1. **[docs/PLATFORMS.md](docs/PLATFORMS.md)** — YouTube + TikTok index (paths, DBs, daily commands)
2. **[docs/youtube/HANDOFF.md](docs/youtube/HANDOFF.md)** — bilingual source of truth (changelog, architecture, secrets *names/paths only*, all CLI commands, SQLite, pre-push checklist)
3. **[docs/tiktok/HANDOFF.md](docs/tiktok/HANDOFF.md)** — TikTok upload (Playwright, 3/day, separate SQLite)
4. **[docs/youtube/SCHEDULING_POLICY.md](docs/youtube/SCHEDULING_POLICY.md)** — publishing rules (3 Shorts/day), SQLite guard, quota
5. **[docs/tiktok/SCHEDULING_POLICY.md](docs/tiktok/SCHEDULING_POLICY.md)** — TikTok 3/day slots + 30 scheduled cap
6. **[docs/AI_CONTINUATION.md](docs/AI_CONTINUATION.md)** — what to paste when switching agents
7. **[scripts/youtube/README.en.md](scripts/youtube/README.en.md)** — English YouTube module docs

## Rules

- **Never more than 3 Shorts per day** (16/18/21 America/Sao_Paulo) — see [SCHEDULING_POLICY.md](docs/youtube/SCHEDULING_POLICY.md).
- Read local secrets from `%USERPROFILE%\.secrets\` — **never** commit or echo real tokens.
- Use `--dry-run` before real YouTube uploads.
- Do not push to GitHub unless the user explicitly asks.

## Git commits as Caduco

Use the Caduco identity script (never commit secrets):

```powershell
& "G:\My Drive\python\tools\caduco-git-commit\invoke.ps1" `
  -RepoPath "C:\Users\carlo\Projects\abobi-shorts-upload-pipeline" `
  -Message "feat: your message"
```

## Scope

- **YouTube automation:** Python in `scripts/youtube/` — pipeline = split + SQLite schedule + upload
- **TikTok automation:** Python in `scripts/tiktok/` — Playwright upload + SQLite schedule (3/day)
- **Website:** NOT in this repo — see [abobiferramentas](https://github.com/abobicaduco/abobiferramentas)
