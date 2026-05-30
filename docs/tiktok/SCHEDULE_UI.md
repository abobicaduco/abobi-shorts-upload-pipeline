# TikTok Schedule UI — Verificação manual e debug

> **Objetivo:** garantir que o Playwright clica **Agendar/Schedule**, nunca **Publicar agora / Post now**.

---

## Guarda no código

| Constante | Valor | Efeito |
|-----------|-------|--------|
| `SCHEDULE_ONLY` | `True` | Bloqueia `--post-now` e impede fallback para publicação imediata |
| `SCHEDULE_UI_TIMEOUT_SEC` | `30` | Aborta se toggle/radio de agendamento não aparecer em 30s |

Arquivo: `scripts/tiktok/uploader_playwright.py`

---

## Fluxo esperado (Creator Center)

1. Abrir https://www.tiktok.com/tiktokstudio/upload (conta logada, Creator/Business)
2. Upload MP4 → aguardar processamento
3. Preencher caption
4. **Ativar agendamento** — uma destas UIs:
   - Switch/toggle "Schedule" / "Agendar"
   - Radio **Agendar** (não "Publicar agora")
5. Preencher **data** e **hora** (timezone = relógio do PC, America/Sao_Paulo)
6. Clicar botão final **Agendar** / **Schedule** / **Programar**
7. Confirmar mensagem "agendado" / "scheduled" — **não** deve ir ao ar imediatamente

### Labels PT-BR e EN (busca no código)

| Tipo | Textos |
|------|--------|
| Publicação imediata (BLOQUEADO) | `Publicar agora`, `Post now`, `Publicar`, `Post`, `Publish` |
| Agendamento (OK) | `Agendar`, `Schedule`, `Programar`, `Agendar publicação` |
| Radio imediato (evitar) | `Publicar agora`, `Post now`, `Publish now` |

---

## Verificação manual passo a passo

### A. Antes de rodar automação

```powershell
# 1. Sessão válida
python scripts/tiktok-pipeline.py --auth-only

# 2. Dry-run (sem browser de upload real)
python scripts/tiktok-pipeline.py --test-upload "C:\Users\carlo\YOUTUBE\clips\...\tiktok_003.mp4" --dry-run
```

Log esperado:

```text
[DRY-RUN] ... | post_now=False | scheduled for 2026-05-30T21:00:00 ...
```

**Não** deve aparecer `post_now=True` nem `publicando imediatamente`.

### B. Teste real (1 clipe, menor pending, não tiktok_050)

```powershell
python scripts/tiktok-pipeline.py --test-upload "C:\Users\carlo\YOUTUBE\clips\...\tiktok_003.mp4"
```

Log esperado:

```text
Modo agendado: scheduled for 2026-05-30 21:00 (nao publicar agora).
Agendamento configurado para 2026-05-30 21:00 (America/Sao_Paulo).
Clicando botao de agendamento: 'Agendar'
Upload concluido — scheduled for 2026-05-30 21:00
```

Se falhar:

```text
UI de agendamento nao encontrada em 30s — abortando
```

→ **Nenhum vídeo deve ser publicado.** Corrija UI/sessão antes de retomar.

### C. Confirmar no TikTok (calendário / posts agendados)

1. Abrir https://www.tiktok.com/tiktokstudio/content  
   ou perfil → **Scheduled posts** / **Agendados**
2. O vídeo de teste deve aparecer com data/hora do slot SQLite
3. **Não** deve aparecer como post publicado no feed imediatamente

Comando rápido para abrir Studio:

```powershell
start https://www.tiktok.com/tiktokstudio/content
```

---

## Inspecionar SQLite

Consultar `%USERPROFILE%\.secrets\tiktok_schedule.db`:

| status DB | Significado |
|-----------|-------------|
| `scheduled` | Agendado na UI TikTok (correto) |
| `uploaded` | Publicado ao vivo (só deveria ocorrer com `--post-now` + `SCHEDULE_ONLY=False`) |
| `pending` | Ainda não enviado ao TikTok |

---

## Captura Network (opcional)

```powershell
python scripts/tiktok/inspect_schedule_network.py
```

1. Browser abre página de upload
2. Faça login se pedido
3. Suba vídeo curto, ative **Agendar**, escolha data ≥ 2h no futuro
4. Clique **Agendar** (não Publicar agora)
5. Pressione ENTER no terminal → log em `%USERPROFILE%\.secrets\`

Ver também: [SCHEDULE_API_RESEARCH.md](SCHEDULE_API_RESEARCH.md)

---

## Root cause conhecido (2026-05-29)

Versão anterior: quando o botão "Agendar" não era encontrado, o código **caía no fallback** `IMMEDIATE_POST_BUTTON_SELECTORS` e clicava **"Publicar"** (sem "agora" no texto) → publicação imediata.

Correção: **zero fallback** — se agendamento UI falhar, `RuntimeError` e abort.

---

## Pipeline — flags

| Flag | Padrão | Notas |
|------|--------|-------|
| (nenhuma) | agenda via UI | `SCHEDULE_MODE=True` força `post_now=False` |
| `--post-now` | bloqueado | erro enquanto `SCHEDULE_ONLY=True` |
| `--dry-run` | simula log | seguro para CI/local |
| `--schedule-only` | só SQLite | não abre browser de upload |
