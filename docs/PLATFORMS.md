# Platforms — YouTube + TikTok automation

> **Bilingual index** for [@abobicaduco](https://www.youtube.com/@abobicaduco) / [@abobicaduco](https://www.tiktok.com/@abobicaduco).  
> **Índice bilíngue** — um repositório, duas automações separadas, SQLite distintos.

**Canonical repo:** `C:\Users\carlo\Projects\abobi-shorts-upload-pipeline`  
**Website repo:** `C:\Users\carlo\Projects\abobiferramentas`

---

## Quick comparison

| | **YouTube Shorts** | **TikTok** |
|---|-------------------|------------|
| **Module path** | `scripts/youtube/` | `scripts/tiktok/` |
| **CLI launchers** | `scripts/youtube-upload.py` · `scripts/youtube-pipeline.py` | `scripts/tiktok-upload.py` · `scripts/tiktok-pipeline.py` |
| **SQLite DB** | `%USERPROFILE%\.secrets\youtube_schedule.db` | `%USERPROFILE%\.secrets\tiktok_schedule.db` |
| **Auth** | OAuth → `youtube_client_secret.json` + `youtube_token.json` | Playwright → `tiktok_storage_state.json` + `scripts/browser-profile-tiktok/` |
| **Upload method** | YouTube Data API v3 (`publishAt`) | Playwright → `tiktok.com/tiktokstudio/upload` |
| **Policy** | Max **3 Shorts/day** @ 16/18/21 SP | Max **3 videos/day** @ 16/18/21 SP |
| **Handoff (paste for agents)** | [docs/youtube/HANDOFF.md](youtube/HANDOFF.md) | [docs/tiktok/HANDOFF.md](tiktok/HANDOFF.md) |
| **Scheduling policy** | [docs/youtube/SCHEDULING_POLICY.md](youtube/SCHEDULING_POLICY.md) | [docs/tiktok/SCHEDULING_POLICY.md](tiktok/SCHEDULING_POLICY.md) |
| **Shared clips folder** | `~/YOUTUBE/clips/abobicaduco_jogando_Granny_2_-_Parte_#2_tiktok/` (51 MP4) | Same folder |
| **Metadata (LLM)** | Ollama local → `scripts/shared/llm_metadata.py` | Same module + `clips_metadata.json` |
| **Long-form batch** | [docs/content/FORTNITE_MOBILE.md](content/FORTNITE_MOBILE.md) · `scripts/fortnite_long_batch.py` | Copies → `pending_tiktok/fortnite_mobile/` |
| **Thumbnails** | [docs/THUMBNAILS.md](THUMBNAILS.md) | Manual Gemini today; `thumbnails.set` after upload |

---

## Folder map

```
abobi-shorts-upload-pipeline/     # YouTube + TikTok automation only
├── scripts/
│   ├── youtube/                     # API upload, split, scheduler
│   ├── tiktok/                      # Playwright upload, scheduler
│   ├── shared/llm_metadata.py       # Ollama metadata (YouTube + TikTok)
│   ├── youtube-upload.py
│   ├── youtube-pipeline.py
│   ├── tiktok-upload.py
│   ├── tiktok-pipeline.py
│   └── browser-profile-tiktok/      # gitignored Chrome profile
├── docs/
│   ├── PLATFORMS.md                 # this file
│   ├── AI_CONTINUATION.md
│   ├── THUMBNAILS.md
│   ├── content/FORTNITE_MOBILE.md
│   ├── youtube/                     # HANDOFF, SCHEDULING_POLICY, SCHEDULER
│   └── tiktok/                      # HANDOFF, SCHEDULING_POLICY
├── AGENTS.md
├── LOCAL_SETUP.md
└── README.md / README.pt-BR.md

%USERPROFILE%\.secrets/              # NEVER in git
├── api-keys.json
├── youtube_client_secret.json
├── youtube_token.json
├── youtube_schedule.db
├── tiktok_schedule.db
└── tiktok_storage_state.json

%USERPROFILE%\YOUTUBE/
├── inbox/<batch_id>/                # long-form + manifest (see FORTNITE_MOBILE.md)
├── pending_youtube/                 # optional manual staging (workflow)
├── pending_tiktok/fortnite_mobile/  # TikTok copies awaiting pipeline
└── clips/..._tiktok/                # 51 split clips (both platforms)
```

---

## Daily commands (2026-05-30+)

### YouTube Shorts — Granny batch (51 scheduled)

If any rows are still `pending` after quota reset:

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
python scripts/youtube-pipeline.py --resume --upload-limit 6 --until-done
```

**Audit / duplicates:** `python scripts/youtube-audit.py` (channel scan + metadata; see [youtube/HANDOFF.md](youtube/HANDOFF.md)).

Verify:

```powershell
sqlite3 $env:USERPROFILE\.secrets\youtube_schedule.db "SELECT status, COUNT(*) FROM scheduled_uploads GROUP BY status;"
```

### YouTube long-form — Fortnite Mobile (4 videos, 1/day @ 19:00)

```powershell
python scripts/fortnite_long_batch.py --upload-limit 1
```

Details: [docs/content/FORTNITE_MOBILE.md](content/FORTNITE_MOBILE.md).

### TikTok — cap 30 scheduled; Granny + Fortnite pending

Run **once per day** (max 3 uploads per run):

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
python scripts/tiktok-pipeline.py --resume --upload-limit 3
```

Do **not** use `--until-done` unless TikTok UI/rate limits allow — respect 3/day editorial policy and **~30** scheduled cap ([tiktok/SCHEDULING_POLICY.md](tiktok/SCHEDULING_POLICY.md)).

Check DB:

```powershell
sqlite3 $env:USERPROFILE\.secrets\tiktok_schedule.db "SELECT status, COUNT(*) FROM scheduled_uploads GROUP BY status;"
```

---

## One-time setup

| Step | YouTube | TikTok |
|------|---------|--------|
| Dependencies | `pip install -r scripts/youtube/requirements.txt` | `pip install playwright` + `playwright install chromium` |
| Auth | `python scripts/youtube-upload.py --auth-only` | `python scripts/tiktok-upload.py --auth-only` |
| Plan all slots | `python scripts/youtube-pipeline.py --schedule-only ...` | `python scripts/tiktok-pipeline.py --schedule-only --clips-dir "...\..._tiktok"` |
| Dry-run | `--dry-run` on pipeline/upload | `--dry-run` on test-upload |

### Ollama (metadata local, zero custo API)

Pré-requisito: [Ollama](https://ollama.com/download) rodando com modelo leve (ex.: `llama3.2:3b`).

```powershell
ollama serve          # se nao estiver rodando
ollama pull llama3.2:3b
ollama list
```

Variáveis (opcional, em `scripts/.env`):

```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
```

**Pré-gerar metadados dos 51 clipes** (evita chamar Llama durante upload):

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
$clips = "$env:USERPROFILE\YOUTUBE\clips\abobicaduco_jogando_Granny_2_-_Parte_#2_tiktok"
python scripts/shared/llm_metadata.py --clips-dir $clips
# ou via pipeline:
python scripts/youtube-pipeline.py --pre-generate-metadata --output-dir $clips
python scripts/tiktok-pipeline.py --pre-generate-metadata --clips-dir $clips
```

Gera `clips_metadata.json` na pasta dos clipes. Pipelines usam manifest automaticamente se existir.

Flags: `--use-llm` (força Ollama), `--no-llm` (só templates de `video_splitter.py`). Padrão: Ollama se online, senão template (pipeline não quebra).

Amostra rápida (clip #003):

```powershell
python scripts/shared/llm_metadata.py --clips-dir $clips --sample 3
```

---

## Agent bootstrap

Paste into a new Cursor / Claude / Antigravity session:

1. [docs/PLATFORMS.md](PLATFORMS.md) (this file)
2. [docs/youtube/HANDOFF.md](youtube/HANDOFF.md) + [docs/tiktok/HANDOFF.md](tiktok/HANDOFF.md)
3. Both [SCHEDULING_POLICY.md](youtube/SCHEDULING_POLICY.md) files
4. [AGENTS.md](../AGENTS.md)

Shortcut: [docs/AI_CONTINUATION.md](AI_CONTINUATION.md)

---

## LinkedIn one-liner

**EN:** Free Brazilian online utilities (CPF/CNPJ, passwords, JSON, QR) plus Python pipelines for YouTube Shorts and TikTok — split, SQLite scheduling (3/day @ 16/18/21 BRT), and batch upload to [@abobicaduco](https://www.youtube.com/@abobicaduco).

**PT:** Ferramentas online gratuitas no Brasil + pipelines Python para YouTube Shorts e TikTok — corte, agendamento SQLite (3/dia às 16/18/21 BRT) e upload em lote para [@abobicaduco](https://www.youtube.com/@abobicaduco).

---

## Status snapshot (2026-05-30)

| Platform | Total | State | Notes |
|----------|-------|-------|-------|
| **YouTube Shorts** | 51 | **51 scheduled** (target) | Run audit if duplicate titles/IDs suspected |
| **YouTube long** | 4 | Inbox batch `fortnite_mobile_20260530` | 1 upload/day @ 19:00 SP |
| **TikTok** | 51 Granny + 4 Fortnite | **~16** Granny pending + Fortnite in `pending_tiktok` | **≤30** scheduled in UI/DB; 3/day resume |

*Updated: 2026-05-30*

---

## Security (all platforms)

| Never commit | Typical path |
|--------------|--------------|
| YouTube OAuth | `%USERPROFILE%\.secrets\youtube_client_secret.json`, `youtube_token.json` |
| TikTok session | `tiktok_storage_state.json`, `scripts/browser-profile-tiktok/` |
| API keys | `%USERPROFILE%\.secrets\api-keys.json` |
| SQLite | `youtube_schedule.db`, `tiktok_schedule.db` |
| Env with secrets | `scripts/.env` |

Prefer env vars and `%USERPROFILE%\.secrets\` — see [LOCAL_SETUP.md](../LOCAL_SETUP.md) and [THUMBNAILS.md](THUMBNAILS.md#security).
