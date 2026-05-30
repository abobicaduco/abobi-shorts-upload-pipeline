# Gemini web — internal RPC pattern (research notes)

> **PT-BR** · Notas de captura de rede para automação via `gemini.google.com` (sem API key paga).  
> **Nunca commitar:** `gemini_storage_state.json`, cookies, headers `Authorization`/`Cookie`, valores de `f.req`/`at`/`rt`.

Relacionado: [THUMBNAILS.md](../THUMBNAILS.md) · `scripts/thumbnails/gemini_web.py` · `scripts/thumbnails/inspect_gemini_network.py`

---

## Por que existe este doc

A **Generative Language API** (`generativelanguage.googleapis.com`) exige API key + billing para imagens. A assinatura **Google AI Pro** no browser **não** desbloqueia essa API.

Alternativa: reutilizar a sessão do browser (`storage_state`) ou, em teoria, chamar os mesmos RPCs que o chat web usa — **não documentado oficialmente**, sujeito a ToS e quebras de UI.

---

## Superfícies comparadas

| Abordagem | Auth | Imagens | Automação | Fragilidade |
|-----------|------|---------|-----------|-------------|
| **API oficial** (`generate_thumbnails.py`) | `AIzaSy…` AI Studio | Sim (paid tier) | Alta | Baixa (SDK estável) |
| **Browser headed** (`gemini-thumbnails.py`) | Login Google + `storage_state` | Sim (cota Pro) | Média | Alta (selectors DOM) |
| **Browser headless** | Mesmo `storage_state` | Condicional | Média | Alta + risco anti-bot |
| **RPC web direto** (não implementado) | Cookies `SAPISID` + `SAPISIDHASH` | Teórico | Baixa | Muito alta |

---

## Padrão RPC observado (Gemini / Bard web)

O chat em `gemini.google.com` **não** expõe REST JSON público. O frontend usa **Google batchexecute** — POST com corpo `f.req` (protobuf/JSON encadeado) e respostas em streaming.

### Endpoints típicos (URLs sanitizadas)

| Padrão | Método | Papel |
|--------|--------|-------|
| `https://gemini.google.com/_/BardChatUi/data/batchexecute?rpcid=<ID>&source-path=%2Fapp` | POST | RPC principal do chat (texto + multimodal) |
| `https://gemini.google.com/_/BardChatUi/...` | GET/POST | Assets / bootstrap UI |
| `https://alkalimakersuite-pa.clients6.google.com/...` | POST | Serviços auxiliares (upload/media em algumas builds) |
| `https://lh3.googleusercontent.com/...` | GET | Imagens geradas (download final) |

**Query params sensíveis (redigir em logs):** `at`, `rt`, `f.sid`, `bl`, corpo `f.req`.

### Autenticação (não replicar em código versionado)

- Cookies de sessão Google: `SID`, `HSID`, `SSID`, **`SAPISID`**
- Header derivado: **`Authorization: SAPISIDHASH <timestamp>_<hash>`** (calculado a partir de `SAPISID` + origin + timestamp)
- Playwright `storage_state` já carrega cookies — **não** extrair nem logar valores

### Corpo `f.req`

- Array JSON serializado (as vezes duplamente encoded) com `rpcid`, conversation id, prompt, anexos
- Resposta: linhas `)]}'` + JSON incremental (snapshots acumulados, não tokens delta puros)
- **Imagem:** URLs `googleusercontent.com` aparecem nos snapshots após RPC de geração

Implementação direta exigiria engenharia reversa contínua — fora do escopo deste repo por enquanto.

---

## Como capturar tráfego localmente

### Script do repo

```powershell
python scripts/thumbnails/inspect_gemini_network.py
```

Ou durante batch:

```powershell
python scripts/gemini-thumbnails.py --faces-dir ... --videos-dir ... --game "Fortnite Mobile" --sniff-network
```

Log: `%USERPROFILE%\.secrets\gemini_network.log` — **apenas** método + URL sanitizada (sem headers).

### Playwright route (CDP)

`gemini_web.attach_network_logger()` registra `page.on("request")` / `page.on("response")` filtrando:

- `resource_type` ∈ `fetch`, `xhr`, `websocket`
- host contém `gemini.google.com`, `batchexecute`, ou `alkalimakersuite`

Para inspeção manual: DevTools → Network → filtrar `batchexecute` → copiar **Request URL** e **Initiator**, nunca copiar Request Headers completos para o repo.

---

## Headed vs headless (2026-05-30)

| Modo | Comportamento esperado |
|------|------------------------|
| **Headed + storage_state** | Caminho recomendado após `--auth-only`. Google aceita sessão exportada. |
| **Headless + storage_state** | Pode funcionar para navegação inicial; **frequente** redirect para `accounts.google.com` ou CAPTCHA. |
| **Headless sem perfil** | Falha — login interativo obrigatório. |

Verificar localmente:

```powershell
python scripts/gemini-thumbnails.py --verify-session
```

Saída esperada após auth bem-sucedida:

```
storage_state_exists: True
headed_logged_in: True
headless_logged_in: True|False  ← se False, usar headed para batch
```

Mitigações headless (best-effort no script):

- `channel="chrome"`, `ignore_default_args=["--enable-automation"]`
- `--headless=new` (Chromium) apenas em batch com `--headless`
- Opcional: `--disable-blink-automation` se login headed falhar

Se headless falhar: rodar batch **sem** `--headless` (janela minimizada manualmente).

---

## Fallbacks JavaScript (`page.evaluate`)

Quando seletores Playwright quebram, `gemini_web.py` tenta:

1. **`_FIND_PROMPT_INPUT_JS`** — `rich-textarea`, `contenteditable`, `textarea`
2. **`_SET_PROMPT_JS`** — dispara `input`/`change` events
3. **`_SUBMIT_PROMPT_JS`** — botões Send/Enviar ou submit de form
4. **`_FIND_FILE_INPUT_JS`** + `set_input_files` — selfie de referência
5. **`_LATEST_IMAGE_JS`** — maior `<img>` com `googleusercontent`

Todos marcados como **best-effort** — falhas devem gerar mensagem clara pedindo `--auth-only` ou inspeção manual.

---

## Recomendação operacional

1. **Curto prazo (conta Pro, API bloqueada):** `gemini-thumbnails.py` em modo **headed**, sessão `--auth-only` mensal ou quando expirar.
2. **Médio prazo:** criar **API key AI Studio em projeto novo** + billing → voltar a `generate_thumbnails.py` (estável, scriptável).
3. **Não recomendado:** cliente HTTP direto para `batchexecute` — manutenção alta, risco ToS, tokens em risco.

---

## Segurança

| Nunca commitar | Onde fica |
|----------------|-----------|
| `gemini_storage_state.json` | `%USERPROFILE%\.secrets\` |
| `gemini_network.log` (se contiver tokens acidentais) | `%USERPROFILE%\.secrets\` |
| `scripts/browser-profile-gemini/` | Perfil Chrome local |
| Headers/cookies copiados do DevTools | — |

Agents: Cursor/Claude **não** herdam a sessão do browser do usuário — só o Python local com `storage_state` salvo.

---

*Última atualização: 2026-05-30*
