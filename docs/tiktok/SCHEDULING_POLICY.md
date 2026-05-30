# TikTok scheduling policy — abobicaduco

> **Guard rail for all AI agents** — read before scheduling or uploading TikTok clips.

Companion: [HANDOFF.md](HANDOFF.md) · YouTube policy: [../youtube/SCHEDULING_POLICY.md](../youtube/SCHEDULING_POLICY.md)

---

## Português (Brasil)

### Regras de publicação (obrigatório)

| Tipo | Quantidade | Horários (America/Sao_Paulo) |
|------|------------|------------------------------|
| **Clipes TikTok** | **3 por dia** | 16:00 · 18:00 · 21:00 |

- **Fonte da verdade:** SQLite em `%USERPROFILE%\.secrets\tiktok_schedule.db` (override: `--db`).
- **Separado do YouTube:** mesmo conteúdo Granny 2, bancos distintos (`youtube_schedule.db` vs `tiktok_schedule.db`).
- **Nunca double-book:** `ScheduleDB.is_slot_taken()` + view `daily_slot_occupancy`.
- **Cap ~30 agendados:** TikTok Creator Center limita vídeos em estado *scheduled*; `fortnite_long_batch.py` não insere novas rows no SQLite quando `scheduled` ≥ 30 (arquivos ficam em `pending_tiktok/`).

### Comportamento padrão do upload (CRÍTICO)

| Modo | Comportamento |
|------|----------------|
| **`--resume` / pipeline normal** | Abre TikTok Studio → preenche caption → **ativa Schedule/Agendar** → data/hora de `scheduled_at` (SP) → clica **Agendar** |
| **`--test-upload`** | Igual: agenda no slot do DB (ou próximo slot livre se clipe ainda não estiver no DB) |
| **`--post-now`** | Exceção explícita: publica imediatamente (ignora UI de agendamento) |

**Nunca** publicar imediatamente sem `--post-now`. Se a UI de agendamento falhar, o script **aborta** (não faz fallback para Post).

Conta **Creator** ou **Business** no TikTok é necessária para o toggle Schedule aparecer no desktop.

### Estado atual (2026-05-30)

| Métrica | Valor |
|---------|-------|
| Granny batch | 51 clipes |
| `pending` (aprox.) | **~16** + uploads diários |
| Fortnite long | 4 em `pending_tiktok/fortnite_mobile/` quando cap 30 |
| Slots | 16/18/21 SP; long batch usa **19:00** quando há vaga no DB |

Esperado: ~3 agendamentos por execução (`--upload-limit 3`).

### Comando diário (após planejar)

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
python scripts/tiktok-pipeline.py --resume --upload-limit 3
```

| Flag | Por quê |
|------|---------|
| `--resume` | Só `pending`/`failed` — não replaneja slots ocupados |
| `--upload-limit 3` | Respeita política 3/dia por execução (3 agendamentos na UI por execução) |

Status no SQLite após sucesso na UI:

| Status DB | Significado |
|-----------|-------------|
| `scheduled` | Vídeo submetido ao TikTok com data/hora futura (slot reservado) |
| `uploaded` | Publicado imediatamente (`--post-now` ou exceção manual) |

### Planejar todos os clipes (1×)

```powershell
python scripts/tiktok-pipeline.py --schedule-only --clips-dir "C:\Users\carlo\YOUTUBE\clips\abobicaduco_jogando_Granny_2_-_Parte_#2_tiktok"
```

Esperado: 51 rows `pending` distribuídas ~17 dias (3 slots/dia).

### Verificar ocupação

```powershell
sqlite3 $env:USERPROFILE\.secrets\tiktok_schedule.db "SELECT slot_date, hour_16, hour_18, hour_21 FROM daily_slot_occupancy ORDER BY slot_date LIMIT 14;"
```

```powershell
sqlite3 $env:USERPROFILE\.secrets\tiktok_schedule.db "SELECT status, COUNT(*) FROM scheduled_uploads GROUP BY status;"
```

### Teste único (fora do cron diário)

Agenda no próximo slot livre (ou slot já atribuído no DB):

```powershell
python scripts/tiktok-upload.py --test-upload "...\clip_..._003.mp4"
```

Dry-run (sem browser):

```powershell
python scripts/tiktok-upload.py --test-upload "...\clip_..._003.mp4" --dry-run
```

Publicar agora **só** com flag explícita:

```powershell
python scripts/tiktok-upload.py --test-upload "...\clip.mp4" --post-now
```

### Exceção conhecida (2026-05-29)

O clipe `clip_..._050.mp4` foi publicado **imediatamente** num teste antigo (`--test-upload` com `post_now` implícito). Está marcado `uploaded` no DB. Todos os demais pendentes devem usar **Schedule** na UI.

---

## English

- Max **3 TikTok uploads per calendar day** at 16:00, 18:00, 21:00 `America/Sao_Paulo`.
- SQLite: `~/.secrets/tiktok_schedule.db` (not shared with YouTube DB).
- **Default:** Playwright sets TikTok Creator Center **Schedule** date/time from `PlannedUpload.scheduled_at` (local TZ). Use `--post-now` only to publish immediately.
- Daily batch: `python scripts/tiktok-pipeline.py --resume --upload-limit 3`.
- On success: DB status `scheduled` (future publish) vs `uploaded` (immediate / `--post-now`).
