# YouTube batch upload (Shorts)

Upload de videos via **YouTube Data API v3** com OAuth de usuario (nao service account).

**Documentacao em ingles (LinkedIn / GitHub):** [README.en.md](README.en.md)  
**Handoff para agentes (Claude / Antigravity):** [docs/youtube/HANDOFF.md](../../docs/youtube/HANDOFF.md)

---

## Credenciais — armazenamento preferido

**Fonte canonica:** `C:\Users\<you>\.secrets\api-keys.json` -> chave `google_oauth_youtube`

Campos suportados (mesmo padrao de `google_oauth_adsense`):

| Campo | Descricao |
|-------|-----------|
| `client_secret_json` | Objeto JSON do OAuth Desktop (cole o download do Google Cloud) **ou** caminho `C:\...\client_secret.json` |
| `client_id`, `client_secret`, `project_id` | Alternativa ao JSON embutido |
| `refresh_token`, `token_uri`, `scopes` | Preenchidos automaticamente apos `python scripts/youtube-upload.py --auth-only` |
| `token_saved_at` | ISO UTC opcional; gravado no merge apos auth/refresh |

Outras chaves do arquivo (ex.: `google_oauth_adsense`) **nao sao alteradas** no merge.

Fallback em arquivo (compatibilidade):

- Client: `%USERPROFILE%\.secrets\scripts\youtube_client_secret.json`
- Token: `%USERPROFILE%\.secrets\scripts\youtube_token.json`

---

## Ordem de resolucao — client secret

1. `google_oauth_youtube` em api-keys (JSON embutido ou `client_id` + `client_secret`)
2. `YOUTUBE_CLIENT_SECRETS` (env ou `scripts/.env`)
3. `%USERPROFILE%\.secrets\scripts\youtube_client_secret.json`
4. `%USERPROFILE%\.secrets\scripts\client_secret.json`
5. `scripts/youtube/.secrets/client_secret.json` (local, nao versionar)
6. `google_oauth_adsense.client_secret_json` em api-keys (legado, so caminho)
7. Unico `client_secret*.json` em `Downloads`

## Ordem de resolucao — token

1. `google_oauth_youtube.refresh_token` em api-keys
2. `YOUTUBE_TOKEN_PATH` / `%USERPROFILE%\.secrets\scripts\youtube_token.json`
3. `scripts/youtube/.secrets/token.json`

Apos login ou refresh, o token e gravado no arquivo de fallback **e** fundido em `google_oauth_youtube`.

Escopos solicitados: `youtube.upload`, `youtube`.

---

## Primeira execucao vs ja autenticado

| Situacao | O que acontece |
|----------|----------------|
| **Sem** credenciais YouTube | Coloque client secret em api-keys ou em arquivo; rode `--auth-only`. |
| **Token com escopos YouTube** | Upload direto; refresh automatico se expirado. |
| **Token so AdSense/Sheets** | Escopos insuficientes -> novo login com escopos YouTube. |
| So validar OAuth | `python scripts/youtube-upload.py --auth-only` |

Habilite **YouTube Data API v3** no projeto Google Cloud do OAuth client.

---

## Setup rapido

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
pip install -r scripts/youtube/requirements.txt
copy scripts\youtube\.env.example scripts\.env

# Opcao A — api-keys (recomendado): edite ~/.secrets/api-keys.json
#   "google_oauth_youtube": { "client_secret_json": { "installed": { ... } } }

# Opcao B — arquivo:
#   C:\Users\carlo\.secrets\scripts\youtube_client_secret.json

python scripts/youtube-upload.py --auth-only
```

Inbox padrao: `%USERPROFILE%\YOUTUBE\inbox` (override: `YOUTUBE_INBOX`).

---

## Uso

```powershell
# Um video
python scripts/youtube-upload.py clip.mp4 --title "Titulo" --description "Texto"

# Inbox: manifest.csv + batch.yaml
python scripts/youtube-upload.py --inbox

# Assistir pasta
python scripts/youtube-upload.py --inbox --watch

# Pipeline: cortar + agendar + upload (dry-run)
python scripts/youtube-upload.py --pipeline --split-input "D:\Videos\live.mp4" --dry-run

# Pipeline: subir 3 clips (quota-safe)
python scripts/youtube-pipeline.py --split-input "D:\Videos\live.mp4" --upload-limit 3

# Retomar pending/failed no SQLite
python scripts/youtube-upload.py --pipeline --resume --upload-limit 3
```

Slots padrao: 16h, 18h, 21h (`America/Sao_Paulo`). SQLite: `~/.secrets/youtube_schedule.db`.  
Detalhes: [SCHEDULER.md](../../docs/youtube/SCHEDULER.md)

Templates: [templates/manifest.example.csv](templates/manifest.example.csv), [templates/batch.example.yaml](templates/batch.example.yaml)

---

## Seguranca

- Nao commitar `api-keys.json`, `token.json`, `client_secret.json` nem `scripts/.env`.
- `api-keys.json` fica fora do repositorio em `~/.secrets/`.
- Tokens de fallback: `%USERPROFILE%\.secrets\scripts\`.
- Detalhes completos: [HANDOFF.md](../../docs/youtube/HANDOFF.md)
