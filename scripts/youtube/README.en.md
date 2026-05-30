# YouTube Shorts batch upload & pipeline

Upload Shorts and clips to YouTube via **YouTube Data API v3** with user OAuth (Desktop app — not a service account).

**Channel tested:** [abobicaduco](https://www.youtube.com/@abobicaduco)  
**Handoff for AI agents:** [docs/youtube/HANDOFF.md](../../docs/youtube/HANDOFF.md)  
**Scheduler details:** [docs/youtube/SCHEDULER.md](../../docs/youtube/SCHEDULER.md)  
**Portuguese docs:** [README.md](README.md)

---

## What it does

- **Single upload** — one MP4 with `--title` / `--description`
- **Batch upload** — CSV manifest + shared YAML (`hashtags`, `tags`, `privacy`, playlist)
- **Inbox workflow** — drop files in a folder; optional `--watch` for new clips
- **Pipeline** — split long video → SQLite slot planning → scheduled upload (`publishAt`)
- **OAuth** — browser login once; token stored locally (never in git)
- **Idempotent** — `.uploaded.json` sidecars; SQLite tracks scheduled slots

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| Python 3.12+ | Tested on Windows 11 |
| Google Cloud project | Enable **YouTube Data API v3** |
| OAuth 2.0 Client ID | Type **Desktop app**; download JSON |
| ffmpeg | PATH, `FFMPEG_PATH`, or `pip install imageio-ffmpeg` |
| Local secrets | Outside the repo — see [HANDOFF](../../docs/youtube/HANDOFF.md) |

---

## Quick start

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
pip install -r scripts/youtube/requirements.txt

# Authenticate (once):
python scripts/youtube-upload.py --auth-only

# Inbox batch (default: %USERPROFILE%\YOUTUBE\inbox)
python scripts/youtube-upload.py --inbox --dry-run

# Pipeline: split + schedule (dry-run)
python scripts/youtube-upload.py --pipeline --split-input "D:\Videos\live.mp4" --dry-run
```

### Pipeline (split + schedule + upload)

```powershell
# Plan only
python scripts/youtube-pipeline.py --split-input "D:\Videos\live.mp4" --dry-run

# Upload 3 clips this run (quota-safe)
python scripts/youtube-pipeline.py --split-input "D:\Videos\live.mp4" --upload-limit 3

# Resume pending/failed from SQLite
python scripts/youtube-upload.py --pipeline --resume --upload-limit 3
```

Default slots: **16:00, 18:00, 21:00** (`America/Sao_Paulo`). SQLite: `~/.secrets/youtube_schedule.db`.

### Single video

```powershell
python scripts/youtube-upload.py clip.mp4 --title "My Short" --description "Caption text"
```

### Inbox layout

```
YOUTUBE/inbox/
  manifest.csv      # file_path, title, description
  batch.yaml        # shared hashtags, tags, privacy
  clip_01.mp4
  uploaded/         # moved after success
```

Templates: [templates/manifest.example.csv](templates/manifest.example.csv), [templates/batch.example.yaml](templates/batch.example.yaml)

---

## Environment variables (names only)

| Variable | Purpose |
|----------|---------|
| `YOUTUBE_INBOX` | Input folder for MP4 + manifest |
| `YOUTUBE_UPLOADED_DIR` | Destination after upload (default: `{inbox}/uploaded`) |
| `YOUTUBE_CLIENT_SECRETS` | Path to Desktop OAuth JSON (fallback) |
| `YOUTUBE_TOKEN_PATH` | Path to saved token JSON (fallback) |
| `FFMPEG_PATH` | ffmpeg executable (optional) |

Preferred: `%USERPROFILE%\.secrets\api-keys.json` key `google_oauth_youtube` (see HANDOFF).

---

## CLI reference

```
python scripts/youtube-upload.py --help
python scripts/youtube-pipeline.py --help
```

| Flag | Description |
|------|-------------|
| `--auth-only` | Run OAuth and exit |
| `--inbox` | Process inbox folder |
| `--watch` | Poll inbox (with `--inbox`) |
| `--pipeline` | Split + schedule flow |
| `--split-input` | Source MP4 for pipeline |
| `--resume` | Retry pending/failed from SQLite |
| `--dry-run` | Log only, no upload |
| `--schedule-only` | Skip split; use existing clips |
| `--upload-limit N` | Max uploads this run (default 3) |
| `--upload-all` | Upload all planned clips |
| `--slots "16,18,21"` | Local publish hours |
| `--no-skip-uploaded` | Ignore `.uploaded.json` sidecars |

---

## Security

- **Never commit** `client_secret*.json`, `youtube_token.json`, `api-keys.json`, `.env`, or `*.db`
- Secrets live under `%USERPROFILE%\.secrets\` (outside this repo)
- Rotate OAuth credentials if they were ever exposed

---

## Related repo

The [AboBI Tools](https://abobiferramentas.com) website lives in [abobiferramentas](https://github.com/abobicaduco/abobiferramentas).
