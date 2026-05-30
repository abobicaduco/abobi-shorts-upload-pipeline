# Fortnite Mobile — long-form batch (2026-05-30)

> **EN + PT** · Batch ingest for **4 long gameplay videos** (not Shorts).  
> **Script:** `scripts/fortnite_long_batch.py` · **Batch ID:** `fortnite_mobile_20260530`

Companion: [../PLATFORMS.md](../PLATFORMS.md) · [../THUMBNAILS.md](../THUMBNAILS.md) · [../youtube/SCHEDULING_POLICY.md](../youtube/SCHEDULING_POLICY.md)

---

## Source files (recording)

| Item | Value |
|------|--------|
| **Pattern** | `XRecorder_YYYYMMDD_NN.mp4` (example: `XRecorder_20260530_01.mp4` … `_04.mp4`) |
| **Typical folder** | `%USERPROFILE%\Videos` (Windows screen recorder export) |
| **Override** | `--sources` on the batch script (one or more full paths) |

**Do not** hardcode personal paths in docs or commits — use `%USERPROFILE%\Videos` or `--sources`.

Example (PowerShell):

```powershell
$v = "$env:USERPROFILE\Videos"
python scripts/fortnite_long_batch.py --sources `
  "$v\XRecorder_20260530_01.mp4" `
  "$v\XRecorder_20260530_02.mp4" `
  "$v\XRecorder_20260530_03.mp4" `
  "$v\XRecorder_20260530_04.mp4"
```

---

## Long-form vs Shorts policy

| | **Shorts (Granny batch)** | **Long-form (this batch)** |
|---|---------------------------|----------------------------|
| **Count / day** | Max **3** @ 16 / 18 / 21 SP | Max **1** @ **19:00** SP |
| **Slot constant** | `DEFAULT_SHORTS_SLOTS` | `LONG_FORM_SLOT_HOUR` (= 19) |
| **Hashtag** | Often `#Shorts` via `append_shorts_hashtag` | `append_shorts_hashtag: false` in `batch.yaml` |
| **Typical length** | ~60s clips from ffmpeg split | Full XRecorder exports (multi-minute) |
| **YouTube API** | `publishAt` on Shorts-sized uploads | Same API; one video per calendar day in long slot |
| **TikTok** | 3/day @ 16/18/21 (Playwright) | Copies under `pending_tiktok/`; **19:00** slot when DB has room |

Shorts and long-form use the **same** `youtube_schedule.db` slot model `(slot_date, slot_hour)` — long videos must use hour **19**, not 16/18/21, so they do not consume Shorts quota.

---

## Folder layout

All under `%USERPROFILE%\YOUTUBE\` (not in git):

```
YOUTUBE/
├── inbox/
│   └── fortnite_mobile_20260530/          # batch_id
│       ├── fortnite_mobile_01.mp4 … _04.mp4
│       ├── batch.yaml
│       ├── manifest.csv
│       └── clips_metadata.json
├── pending_youtube/                       # optional manual hold (not required by script)
│   └── <batch_id>/                        # copy here before ingest if you stage offline
├── pending_tiktok/
│   └── fortnite_mobile/                   # TikTok copies + manifest.csv
│       ├── fortnite_mobile_01.mp4 …
│       └── manifest.csv
└── clips/                                 # Shorts batches (Granny, etc.)
```

| Folder | Role |
|--------|------|
| **inbox / batch_id** | Canonical YouTube ingest: renamed MP4s + YAML/CSV/JSON metadata |
| **pending_youtube** | Optional staging before running the batch script (workflow only) |
| **pending_tiktok / fortnite_mobile** | Files + captions ready for `tiktok-pipeline.py --resume` |

---

## `batch.yaml` format

Written by the batch script (or copy from template). Key fields for this batch:

```yaml
hashtags: "#abobicaduco #fortnite #fortnitemobile #gameplay #battleroyale #victoryroyale"
append_shorts_hashtag: false
tags:
  - fortnite
  - fortnite mobile
  - gameplay
  - abobicaduco
privacy: public
category_id: "20"
content_type: long   # documentation marker; SQLite column may come later
```

Template reference: `scripts/youtube/templates/batch.example.yaml`.

---

## `manifest.csv` format

Generated in the inbox folder. Columns:

| Column | Purpose |
|--------|---------|
| `file_path` | Basename under inbox (e.g. `fortnite_mobile_01.mp4`) |
| `title` | YouTube title |
| `description` | Full description (hashtags appended per batch rules) |
| `tags` | Pipe-separated tags (`fortnite\|gameplay\|…`) |
| `tiktok_caption` | Title + body + hashtags for TikTok UI |

Example row shape (placeholders):

```csv
file_path,title,description,tags,tiktok_caption
fortnite_mobile_01.mp4,<title>,<description>,<tag1|tag2>,<caption text>
```

Also see `scripts/youtube/templates/manifest.example.csv` (Shorts example with fewer columns).

**Sidecar:** `clips_metadata.json` — per-file YouTube + TikTok metadata from Ollama or templates (`scripts/shared/llm_metadata.py`).

---

## YouTube scheduling (1 long / day)

- Planner: `plan_uploads(..., slots=(19,), tz_name=America/Sao_Paulo)`.
- Default upload: **one** long video per run (`--upload-limit 1`) to respect API quota.
- **Resume:** rows already in `%USERPROFILE%\.secrets\youtube_schedule.db` keep their slots; use `--schedule-only` to plan without upload.

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline

# Plan + copy only
python scripts/fortnite_long_batch.py --schedule-only --dry-run

# Plan DB + upload 1 video
python scripts/fortnite_long_batch.py --upload-limit 1

# Custom first slot day
python scripts/fortnite_long_batch.py --start-date 2026-05-31 --upload-limit 1
```

Verify YouTube DB (no secrets in output):

```powershell
sqlite3 $env:USERPROFILE\.secrets\youtube_schedule.db `
  "SELECT slot_date, slot_hour, title, status FROM scheduled_uploads WHERE file_path LIKE '%fortnite_mobile%' ORDER BY slot_date;"
```

---

## TikTok (30 scheduled cap + long videos)

| Rule | Detail |
|------|--------|
| **Studio cap** | ~**30** videos in “scheduled” state on TikTok — script warns and **skips** new TikTok DB inserts when `scheduled` count ≥ 30 |
| **Long batch slot** | **19:00** SP when inserts are allowed |
| **If cap hit** | MP4s still copied to `pending_tiktok/fortnite_mobile/`; `manifest.csv` notes `pending_quota_or_cap` |

Resume TikTok after Granny queue frees slots:

```powershell
python scripts/tiktok-pipeline.py --resume --upload-limit 3
```

Optional: point at pending folder via existing `--clips-dir` / pipeline flags (see [../tiktok/HANDOFF.md](../tiktok/HANDOFF.md)).

---

## Commands cheat sheet

| Goal | Command |
|------|---------|
| Dry-run ingest | `python scripts/fortnite_long_batch.py --dry-run` |
| Plan only (YT + TT DB) | `python scripts/fortnite_long_batch.py --schedule-only` |
| Upload 1 long to YouTube | `python scripts/fortnite_long_batch.py --upload-limit 1` |
| No Ollama (templates) | `python scripts/fortnite_long_batch.py --no-llm` |
| Custom DB paths | `--db` / `--tiktok-db` → paths under `%USERPROFILE%\.secrets\` |
| Resume Granny Shorts | `python scripts/youtube-pipeline.py --resume --upload-limit 3` |
| Resume TikTok | `python scripts/tiktok-pipeline.py --resume --upload-limit 3` |

---

## Security (this batch)

**Never commit:**

| Artifact | Example location |
|----------|------------------|
| OAuth client secret | `%USERPROFILE%\.secrets\youtube_client_secret.json` |
| OAuth token | `%USERPROFILE%\.secrets\youtube_token.json` |
| API keys | `%USERPROFILE%\.secrets\api-keys.json` |
| Schedule DBs | `youtube_schedule.db`, `tiktok_schedule.db` |
| TikTok session | `tiktok_storage_state.json` |
| Browser profile | `scripts/browser-profile-tiktok/` |

Use env vars / `scripts/.env` for non-secret defaults (Ollama host, etc.). Canonical agent pattern: local `AI_CREDENTIALS.md` on the dev machine (paths only, **no values** in git).

---

## Channel state snapshot (2026-05-30, no secrets)

| Platform | State | Next action |
|----------|--------|-------------|
| **YouTube Shorts** | **51** clips in `scheduled` (Granny batch) | Run [audit](../youtube/HANDOFF.md) if duplicates suspected; see below |
| **YouTube long** | 4 videos in inbox batch; **1/day** @ 19:00 | `fortnite_long_batch.py --upload-limit 1` per day |
| **TikTok** | **30** max scheduled in UI/DB policy; **~16** Granny pending + Fortnite in `pending_tiktok` | `--resume --upload-limit 3` daily |

**Duplicates / audit (YouTube):** use `python scripts/youtube-audit.py` (wrapper) to list channel videos, align metadata, and schedule **private** Shorts not yet in SQLite — see `scripts/youtube/audit_and_schedule.py` docstring. Do not re-upload clips already linked in DB.

---

*Last updated: 2026-05-30*
