# TikTok Schedule API / Network Research

> **Objetivo:** entender como o TikTok Creator Center (`tiktokstudio/upload`) agenda posts via web, para automatizar sem publicar ao vivo por engano.

**Status:** placeholders + procedimento de captura — endpoints reais dependem de HAR do navegador logado.

---

## Contexto

| Caminho | Agendamento |
|---------|-------------|
| **Playwright (este repo)** | Toggle + data/hora na UI de upload |
| **API oficial** (`open.tiktokapis.com`) | Direct Post **sem** endpoint nativo de schedule; terceiros guardam vídeo e publicam no horário |
| **Web Creator Center** | UI PT-BR: "Agendar" / switch + campos data/hora → provável XHR interno |

O módulo `scripts/tiktok/uploader_playwright.py` usa **somente UI** até mapearmos o XHR.

**Guarda de emergência:** `SCHEDULE_ONLY = True` — bloqueia `--post-now` e falha se a UI de agendamento não funcionar (sem fallback para publicação imediata).

---

## Fluxo observado na UI (Creator Center)

1. Login → `https://www.tiktok.com/tiktokstudio/upload`
2. Upload MP4 → processamento
3. Preencher caption
4. Ativar **Agendar publicação** (switch / label "Agendar")
5. Preencher **data** e **hora** (inputs `type=date` / `type=time` ou equivalentes PT-BR)
6. Clicar **Agendar** (não "Publicar" / "Publicar agora")

Se o passo 4–6 falhar, o script **aborta** — não clica em Publicar.

---

## Padrões de endpoint (hipóteses — validar com HAR)

Endpoints comuns em integrações web TikTok (nomes variam por versão):

| Padrão URL | Uso provável |
|------------|--------------|
| `https://www.tiktok.com/api/post/item/create/` | Criação / publicação imediata |
| `https://www.tiktok.com/api/post/schedule/` ou `.../post_schedule/` | Agendamento (placeholder) |
| `https://www.tiktok.com/tiktokstudio/api/...` | Creator Studio BFF |
| `https://apis.tiktok.com/...` | CDN / upload chunks |
| `https://open.tiktokapis.com/v2/post/publish/video/init/` | API oficial (OAuth, audit) |

**Payload esperado (hipótese UI web):** timestamp UTC ou local + timezone + `post_info` (caption, privacy).

> ⚠️ Não confiar nesta tabela sem captura real. TikTok muda rotas frequentemente.

---

## Como capturar Network (manual — recomendado)

1. Chrome logado no canal @abobicaduco
2. Abrir **DevTools → Network**
3. Filtrar: **Fetch/XHR**
4. Ir a `tiktokstudio/upload`
5. Subir um vídeo de teste **curto**
6. Ativar **Agendar**, escolher data/hora **≥ 2h no futuro**
7. Clicar **Agendar** (confirmar na UI que ficou agendado, não publicado)
8. No Network, procurar requests POST com:
   - `schedule`, `publish_time`, `post_mode`, `creation_id`
9. Botão direito na request → **Copy → Copy as cURL** (não colar tokens em git)
10. Anotar: URL, método, campos JSON relevantes (sem cookies/sessionid)

Salvar HAR (opcional): Network → Export HAR → `%USERPROFILE%\.secrets\tiktok_schedule_capture.har` (gitignored).

---

## Script auxiliar no repo

```powershell
python scripts/tiktok/inspect_schedule_network.py
```

- Abre a página de upload com perfil `browser-profile-tiktok`
- Registra todas as URLs de `request`/`response` (fetch/xhr) em arquivo de log
- **Você** faz login (se necessário), sobe vídeo, agenda manualmente, pressiona ENTER no terminal
- Saída: `%USERPROFILE%\.secrets\tiktok_schedule_network.log` (sem corpo de request com tokens)

---

## Playwright route (alternativa dry-run)

Em desenvolvimento futuro, adicionar em `uploader_playwright.py`:

```python
def _attach_network_logger(page):
    urls = []
    page.on("request", lambda r: urls.append(r.url) if r.resource_type in ("fetch", "xhr") else None)
    return urls
```

Rodar com `--dry-run` não dispara upload real; use `inspect_schedule_network.py` para captura com interação humana.

---

## API oficial (referência)

- [Content Posting API – Direct Post](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post)
- Init: `POST https://open.tiktokapis.com/v2/post/publish/video/init/`
- **Não há schedule nativo** na API pública documentada; agendamento = publicar no horário via job externo ou UI web.

Stub no repo: `scripts/tiktok/uploader_api.py` (quando audit OAuth passar).

---

## Próximos passos

1. Capturar HAR de um agendamento manual bem-sucedido
2. Atualizar esta doc com URL + campos JSON reais (redigir tokens)
3. Ajustar seletores em `uploader_playwright.py` conforme DOM PT-BR atual
4. Só então considerar `SCHEDULE_ONLY = False` para testes controlados com `--post-now`

---

## Changelog

| Data | Nota |
|------|------|
| 2026-05-29 | Doc criada; guard SCHEDULE_ONLY; script inspect_schedule_network.py |
