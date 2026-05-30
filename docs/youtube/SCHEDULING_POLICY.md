# YouTube scheduling policy — abobicaduco

> **Guard rail for all AI agents** (Cursor, Claude, Google Antigravity, Codex, etc.)  
> **Trava de segurança para agentes** — leia antes de agendar ou fazer upload.

Companion docs: [HANDOFF.md](HANDOFF.md) · [SCHEDULER.md](SCHEDULER.md)

---

## Português (Brasil)

### Regras de publicação (obrigatório)

| Tipo | Quantidade | Horários (America/Sao_Paulo) | Status no código |
|------|------------|------------------------------|------------------|
| **Shorts** | **3 por dia** | 16:00 · 18:00 · 21:00 | ✅ Implementado |
| **Vídeo longo** | **1 por dia** | **19:00** (`LONG_FORM_SLOT_HOUR`) | ✅ Via `scripts/fortnite_long_batch.py` |

- Shorts e vídeo longo são **contagens separadas**: 3 Shorts **+** até 1 longo no mesmo dia calendário (quando long-form existir).
- O calendário **pode estender meses à frente** — a regra diária continua valendo: **nunca mais de 3 Shorts por dia** nos slots 16/18/21.
- **Fonte da verdade:** SQLite em `%USERPROFILE%\.secrets\youtube_schedule.db` (override: `--db`).
- **Nunca double-book:** a view `daily_slot_occupancy` + `ScheduleDB.is_slot_taken()` bloqueiam `(slot_date, slot_hour)` ocupado.

### Estado atual (2026-05-30)

| Métrica | Valor |
|---------|-------|
| Total clipes Granny 2 Parte #2 | 51 |
| Alvo no YouTube | **51** rows `scheduled` |
| Long-form Fortnite | 4 vídeos — **1/dia** @ **19:00** — ver [../content/FORTNITE_MOBILE.md](../content/FORTNITE_MOBILE.md) |
| Auditoria | `python scripts/youtube-audit.py` se houver duplicatas ou Shorts privados fora do DB |

Não re-agendar manualmente — `--resume` usa os horários já gravados no SQLite.

---

### ▶ AMANHÃ — comando único (após reset de quota ~24h)

Rodar **no dia seguinte** à parada por quota (ex.: 2026-05-30 se parou em 2026-05-29):

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
python scripts/youtube-pipeline.py --resume --upload-limit 6 --until-done
```

| Flag | Por quê |
|------|---------|
| `--resume` | Só os 6 `pending`/`failed` — sem re-split |
| `--upload-limit 6` | Envia os 6 restantes numa sessão (quota ~6/dia) |
| `--until-done` | Repete lotes até `pending=0` ou quota esgotar de novo |

**Opcional antes do upload:** `--refresh-metadata` se quiser regenerar títulos.

### Depois do sucesso — verificar

```powershell
sqlite3 $env:USERPROFILE\.secrets\youtube_schedule.db "SELECT status, COUNT(*) FROM scheduled_uploads GROUP BY status;"
```

Esperado: `pending|0` e `scheduled|51`.

Próximos agendamentos:

```powershell
sqlite3 $env:USERPROFILE\.secrets\youtube_schedule.db "SELECT slot_date, slot_hour, title, status FROM scheduled_uploads WHERE status IN ('pending','scheduled') ORDER BY scheduled_at_utc LIMIT 10;"
```

Ocupação diária (nunca >1 por hora):

```powershell
sqlite3 $env:USERPROFILE\.secrets\youtube_schedule.db "SELECT slot_date, hour_16, hour_18, hour_21 FROM daily_slot_occupancy ORDER BY slot_date DESC LIMIT 14;"
```

### Quota YouTube API

| Erro / reason | Ação |
|---------------|------|
| `uploadLimitExceeded` | Parar. Aguardar **~24 horas**. Retomar com `--resume`. |
| `quotaExceeded` | Idem — limite diário da API. |
| Conta nova | ~6 uploads/dia na prática; pipeline usa `--upload-limit 3` por padrão em runs normais. |

**Nunca** usar `--upload-all` em conta com quota apertada sem confirmação explícita do usuário.

### SQLite — schema e anti-colisão

**Arquivo:** `C:\Users\carlo\.secrets\youtube_schedule.db`

**Tabela `scheduled_uploads`:** uma row por clip; chave lógica de slot = `(slot_date, slot_hour)`.

**View `daily_slot_occupancy`:** por dia, flags `hour_16`, `hour_18`, `hour_21` (0 ou 1).

Slot ocupado se `status IN ('pending','uploading','scheduled','uploaded')`.

### Futuro: `content_type` (short vs long)

Planejado — **não migrar ainda** sem pedido explícito:

```sql
-- FUTURO (não aplicado): ALTER TABLE scheduled_uploads ADD COLUMN content_type TEXT NOT NULL DEFAULT 'short';
-- Valores: 'short' | 'long'
-- Shorts: slots 16, 18, 21 (max 3/dia)
-- Long: slot separado (ex. 19:00) — max 1/dia, não conta nos 3 Shorts
```

Até a coluna existir, tratar **todos** os rows como Shorts nos slots 16/18/21.

### Guard para agentes de IA

1. **Leia este arquivo** antes de alterar agendamento ou rodar upload real.
2. **SQLite é a fonte da verdade** — não inventar horários fora do DB.
3. **Máximo 3 Shorts/dia** — default `--slots "16,18,21"`; não adicionar horas extras sem política nova.
4. **`--dry-run` primeiro** em fluxos novos ou após mudança de código.
5. **Não commitar** `youtube_schedule.db`, tokens OAuth, ou `api-keys.json`.
6. **Não fazer push** para GitHub salvo pedido explícito do usuário.
7. Vídeo **long-form 1/dia** @ **19:00** — usar `fortnite_long_batch.py` ou `plan_uploads(..., slots=(19,))`; não usar slots 16/18/21 para longos.

---

## English (US)

### Publishing rules (mandatory)

| Type | Count | Times (America/Sao_Paulo) | Code status |
|------|-------|---------------------------|-------------|
| **Shorts** | **3 per day** | 4pm · 6pm · 9pm (16, 18, 21) | ✅ Implemented |
| **Long-form** | **1 per day** | **7pm** (19:00 SP) | ✅ `fortnite_long_batch.py` / `LONG_FORM_SLOT_HOUR` |

- Shorts and long-form are **separate daily budgets**: 3 Shorts **plus** up to 1 long video on the same calendar day (when long-form ships).
- Schedule **may span months** — still **never more than 3 Shorts per day** in slots 16/18/21.
- **Source of truth:** SQLite at `%USERPROFILE%\.secrets\youtube_schedule.db` (`--db` override).
- **No double-booking:** `daily_slot_occupancy` view + `ScheduleDB.is_slot_taken()`.

### Current state (2026-05-30)

- **51** Shorts target `scheduled` on YouTube (Granny batch).
- **4** long-form Fortnite videos — 1/day at 19:00 SP — see [../content/FORTNITE_MOBILE.md](../content/FORTNITE_MOBILE.md).
- Run `youtube-audit.py` if duplicate uploads or metadata drift are suspected.

---

### ▶ TOMORROW — one command (after ~24h quota reset)

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
python scripts/youtube-pipeline.py --resume --upload-limit 6 --until-done
```

### After success — verify `pending=0`

```powershell
sqlite3 $env:USERPROFILE\.secrets\youtube_schedule.db "SELECT status, COUNT(*) FROM scheduled_uploads GROUP BY status;"
```

Expected: `pending|0`, `scheduled|51`.

### Quota

`uploadLimitExceeded` → stop, wait **24h**, `--resume` again.

### Future: `content_type` column

Planned `short` | `long` column on `scheduled_uploads` — not migrated yet. All current rows = Shorts at 16/18/21.

### AI agent guard rails

Same as PT section: read this file, trust SQLite, max 3 Shorts/day, `--dry-run` first, no secrets in git, no push unless user asks.

---

*Last updated: 2026-05-30 — Shorts + long-form (19:00) policies.*
