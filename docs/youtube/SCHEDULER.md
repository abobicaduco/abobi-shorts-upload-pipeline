# YouTube scheduler — split, slots & SQLite

> Companion to [HANDOFF.md](HANDOFF.md). PT-first; EN summary at bottom.

---

## Português

### Visão geral

O agendador evita colisão de horários e persiste estado entre execuções:

1. **`video_splitter.py`** — gera `clip_01.mp4`, `clip_02.mp4`, … (~50 por default).
2. **`scheduler.py`** — encontra slots livres, gera título/descrição, chama upload com `publishAt`.
3. **`schedule_db.py`** — SQLite WAL em `~/.secrets/youtube_schedule.db`.

### Slots padrão

| Hora (SP) | Uso |
|-----------|-----|
| 16:00 | Short #1 do dia |
| 18:00 | Short #2 do dia |
| 21:00 | Short #3 do dia |

Timezone: `America/Sao_Paulo`. Lead mínimo: **20 minutos** antes do publish (`min_lead_minutes`).

Override: `--slots "16,18,21"` · `--timezone Europe/Lisbon` · `--start-date 2026-06-01`.

### Ciclo de status

```
pending → uploading → scheduled (+ video_id)
                   ↘ failed (retry_count++, max 3)
```

- **`scheduled`** — vídeo no YouTube com `publishAt` futuro (privado até publicar).
- **`uploaded`** — reservado para uso futuro pós-publicação.
- Slot ocupado se status ∈ `pending | uploading | scheduled | uploaded`.

### Comandos típicos

```powershell
# 1) Simular tudo (split real, upload fake)
python scripts/youtube-pipeline.py --split-input "D:\live.mp4" --dry-run

# 2) Split + agendar + subir 3 clips (quota-safe)
python scripts/youtube-pipeline.py --split-input "D:\live.mp4" --upload-limit 3

# 3) Clips já existem — só planejar/enviar
python scripts/youtube-pipeline.py --split-input "D:\live.mp4" --schedule-only --upload-limit 3

# 4) Dia seguinte — retomar fila
python scripts/youtube-upload.py --pipeline --resume --upload-limit 3
```

### Saída do split

Default: `%USERPROFILE%\YOUTUBE\clips\<video_stem>\`

- `clip_001.mp4`, `clip_002.mp4`, …
- `split_manifest.json` (metadados do corte)

Re-split: `--force-split`. Reutiliza clips existentes se pasta já tiver arquivos.

### batch.yaml no pipeline

Se `--batch` omitido, usa defaults Granny 2 (hashtags `#abobicaduco`, privacy `private`, category `20`).

### ffmpeg

Ordem: `FFMPEG_PATH` → `ffmpeg` no PATH → bundle `imageio-ffmpeg` (pip).

### Consultas SQLite úteis

Ver seção SQLite em [HANDOFF.md](HANDOFF.md).

**Slots livres hoje (manual):**

```sql
-- Substituir DATE por hoje YYYY-MM-DD
SELECT 16 AS hour, NOT hour_16 AS free FROM daily_slot_occupancy WHERE slot_date = '2026-05-29'
UNION ALL
SELECT 18, NOT hour_18 FROM daily_slot_occupancy WHERE slot_date = '2026-05-29'
UNION ALL
SELECT 21, NOT hour_21 FROM daily_slot_occupancy WHERE slot_date = '2026-05-29';
```

Se não houver row para a data, todos os slots estão livres.

### Quota YouTube

Contas novas: ~6 unidades upload/dia. Pipeline avisa se restam `pending`/`failed`. Estratégia recomendada:

- Dia 1: `--upload-limit 3`
- Dias seguintes: `--resume --upload-limit 3`
- Ou `--upload-all` quando quota aumentar

---

## English

### Overview

The scheduler tracks slot occupancy in SQLite (`~/.secrets/youtube_schedule.db`), splits long MP4s with ffmpeg, and uploads with future `publishAt` timestamps at 4pm / 6pm / 9pm São Paulo by default.

### Key modules

| Module | Role |
|--------|------|
| `video_splitter.py` | ffmpeg clip generation |
| `scheduler.py` | Slot allocation + upload orchestration |
| `schedule_db.py` | Schema, occupancy, retries |
| `pipeline.py` | CLI wiring |

### Status flow

`pending` → `uploading` → `scheduled` (or `failed` with up to 3 retries).

See PT section for commands and SQL examples. Full handoff: [HANDOFF.md](HANDOFF.md).
