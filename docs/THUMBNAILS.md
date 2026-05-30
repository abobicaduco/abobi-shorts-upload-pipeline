# Thumbnails workflow — YouTube (manual today, automation later)

> **EN + PT** · Custom thumbnails for [@abobicaduco](https://www.youtube.com/@abobicaduco) long-form and Shorts.  
> **No API keys or tokens in this repo.**

Related: [content/FORTNITE_MOBILE.md](content/FORTNITE_MOBILE.md) · [youtube/HANDOFF.md](youtube/HANDOFF.md) · [PLATFORMS.md](PLATFORMS.md)

---

## Current workflow (manual, Gemini paid)

1. After gameplay is recorded and batch files exist in inbox, open **Google Gemini** (paid tier) in the browser.
2. Generate **4 thumbnail variants** per video (or per batch day).
3. **Human review** — pick the best variant; adjust text/contrast if needed.
4. Export **1280×720** JPEG (YouTube custom thumbnail safe zone).
5. Save next to the batch (see naming below).
6. After upload, pipeline can call **YouTube Data API** `thumbnails.set` when `thumb_path` is set (see [API flow](#youtube-api-flow-conceptual)).

**Publish gate:** do not schedule/publich until the approved thumbnail file exists on disk (or you explicitly accept the YouTube auto-frame).

---

## File naming and folder

| Item | Convention |
|------|------------|
| **Folder** | `%USERPROFILE%\YOUTUBE\inbox\<batch_id>\thumbnails\` (sibling to MP4s and `manifest.csv`) |
| **Pattern** | `<batch_prefix>_<NN>_thumb.jpg` |
| **Example** | `fortnite_mobile_01_thumb.jpg` … `fortnite_mobile_04_thumb.jpg` |

Fortnite batch (`fortnite_mobile_20260530`):

```
inbox/fortnite_mobile_20260530/
├── fortnite_mobile_01.mp4
├── thumbnails/
│   ├── fortnite_mobile_01_thumb.jpg
│   └── …
├── batch.yaml
└── manifest.csv
```

**Optional batch default:** `thumbnail:` key in `batch.yaml` (see `scripts/youtube/templates/batch.example.yaml`).

**Per-clip override:** `thumb_path` / `thumbnail` column in manifest or `clips_metadata.json` (resolved in `scripts/youtube/manifest.py`).

---

## YouTube API flow (conceptual)

1. `videos.insert` — upload video (private until `publishAt` if scheduled).
2. `thumbnails.set` — upload JPEG/PNG with OAuth scope that includes YouTube upload access.
3. Implementation: `YouTubeUploader.set_thumbnail()` in `scripts/youtube/uploader.py` (retries on transient errors; upload still succeeds if thumb fails).

**Requirements (Google policy):**

- Channel verified for custom thumbnails (subscriber threshold).
- Image ≤ 2 MB, JPG/PNG, recommended **1280×720**.

**No credentials here** — OAuth token lives only under `%USERPROFILE%\.secrets\youtube_token.json` (gitignored).

---

## Wiring thumbnails into upload

| Method | How |
|--------|-----|
| **batch.yaml** | `thumbnail: "%USERPROFILE%/YOUTUBE/inbox/.../thumbnails/fortnite_mobile_01_thumb.jpg"` |
| **manifest.csv** | Add column or use metadata JSON with `thumb_path` per file |
| **Pipeline** | `ClipEntry.thumb_path` passed to uploader after `videos.insert` |

Dry-run logs `[DRY-RUN] Would set thumbnail: …` when path is valid.

---

## Automation — comparison (May 2026)

| Approach | Script | Auth | Works today? | Best for |
|----------|--------|------|--------------|----------|
| **Official API** | `generate_thumbnails.py` | AI Studio API key + billing | **Blocked** on YouTube GCP project (`API_KEY_SERVICE_BLOCKED`) | Stable pipelines once key is fixed |
| **Browser headed** | `gemini-thumbnails.py` | Google login → `gemini_storage_state.json` | **Yes** (Gemini Pro quota) | Batch thumbs without API billing |
| **Browser headless** | `gemini-thumbnails.py --headless` | Same `storage_state` | **Conditional** — Google may redirect to sign-in | Unattended runs after `--verify-session` |
| **Web RPC direct** | Not implemented | Cookie `SAPISIDHASH` | **No** — reverse-engineering only | Not recommended (ToS + fragility) |

Details: [GEMINI_API_VS_PRO.md](GEMINI_API_VS_PRO.md) · [gemini/WEB_API_RESEARCH.md](gemini/WEB_API_RESEARCH.md)

**Recommended path (current account):** use **`gemini-thumbnails.py`** (headed) until a new AI Studio key + billing is set up; then prefer **`generate_thumbnails.py`** for CI/batch stability.

---

## Browser automation (Gemini web)

**Scripts:** `scripts/gemini-thumbnails.py` (CLI) · `scripts/thumbnails/gemini_web.py` (core)

Uses **gemini.google.com** with your **Google AI Pro** subscription — **no** Generative Language API key. Session is saved like TikTok (`storage_state`), not shared with Cursor/Claude chat.

### Pros / cons vs API

| | Browser (Pro session) | Official API |
|--|----------------------|--------------|
| Cost | Already in Pro subscription | Per-image API billing |
| Setup | One-time `--auth-only` login | AI Studio key + billing |
| Stability | DOM selectors break on UI updates | SDK + model IDs |
| Headless | Often blocked after auth | N/A |
| ToS | Gray area (automation of consumer UI) | Supported |

### One-time auth

```powershell
python scripts/gemini-thumbnails.py --auth-only
```

1. Chrome opens `gemini.google.com/app`
2. Log in with your Google account (Gemini Pro)
3. Press **ENTER** in the terminal
4. Session saved to `%USERPROFILE%\.secrets\gemini_storage_state.json` (gitignored)

If launch fails with *Target.createTarget* / profile lock: close all Chrome windows, delete `Singleton*` files under `%USERPROFILE%\.secrets\browser-profile-gemini\` (Chrome closed), then re-run `--auth-only`.

### Verify headed vs headless

```powershell
python scripts/gemini-thumbnails.py --verify-session
```

If `headless_logged_in: False` but headed works, run batch **without** `--headless`.

### Batch generation

```powershell
python scripts/gemini-thumbnails.py `
  --faces-dir "$env:USERPROFILE\Pictures\faces" `
  --videos-dir "$env:USERPROFILE\YOUTUBE\inbox\fortnite_mobile_20260530" `
  --game "Fortnite Mobile"
```

| Flag | Purpose |
|------|---------|
| `--headless` | No visible window (test with `--verify-session` first) |
| `--sniff-network` | Log RPC URLs to `~/.secrets/gemini_network.log` (no auth headers) |
| `--dry-run` | Plan paths/prompts only |
| `--force` | Regenerate existing thumbs |

**Human gate:** same as API path — review PNGs before upload.

### Network research (internal web API)

Manual capture while you generate one image:

```powershell
python scripts/thumbnails/inspect_gemini_network.py
```

Documented patterns (batchexecute RPC, no secrets): [gemini/WEB_API_RESEARCH.md](gemini/WEB_API_RESEARCH.md).

### Playwright settings

- `headless=False` for `--auth-only`; `channel="chrome"`, `locale="pt-BR"`, viewport **1920×1080**, `--start-minimized`
- Batch: headed default; `--headless` optional (often blocked — use `--verify-session`)
- Profile: `%USERPROFILE%\.secrets\browser-profile-gemini\` (gitignored)
- `page.evaluate` fallbacks when Gemini UI selectors change (selectors are best-effort / TODO when UI shifts)

**Session isolation:** Cursor, Claude, and other agents **do not** inherit `gemini_storage_state.json` — only this local Python CLI uses it.

---

## API automation

**Script:** `scripts/generate_thumbnails.py` (core: `scripts/thumbnails/gemini_generate.py`)

### Google AI Pro (consumer) vs API key vs Vertex

| Surface | What it is | Programmatic image gen? |
|---------|------------|-------------------------|
| **Gemini app / Google AI Pro** (~R$90/mo) | Browser chat at [gemini.google.com](https://gemini.google.com) | **No** — subscription does **not** replace an API key for scripts |
| **Google AI Studio + API key** | [aistudio.google.com/api-keys](https://aistudio.google.com/api-keys) → `generativelanguage.googleapis.com` | **Yes** — this is what the pipeline uses |
| **Vertex AI (Google Cloud)** | Enterprise GCP billing, IAM, regions | **Yes** — separate SDK/billing; not required for this repo |

**Takeaway:** Google AI Pro helps you iterate prompts in the browser, but **automation needs an AI Studio API key** on the same Google account (or linked Cloud project). Paid API usage is metered per image/token — it is **not** bundled into the consumer Gemini subscription quota.

**Models (Nano Banana family, May 2026):**

| Model ID | Role |
|----------|------|
| `gemini-2.5-flash-image` | Default in script — fast, good for batches |
| `gemini-3.1-flash-image` | Higher volume / newer; supports reference images + 16:9 |
| `gemini-3-pro-image` | Best text rendering; higher cost |

Features used by the script:

- **16:9** via `ImageConfig(aspect_ratio="16:9")`
- **Face reference** — selfie sent as multimodal input (character consistency)
- Post-process resize to **1280×720** with Pillow (YouTube safe size)

### One-time setup (API key)

1. Open [Google AI Studio → API keys](https://aistudio.google.com/api-keys) (same Google account as Gemini Pro is fine).
2. **Create API key in new project** — avoid reusing the YouTube/AdSense GCP project (`warm-alliance-457415-d2`). See [GEMINI_API_VS_PRO.md](GEMINI_API_VS_PRO.md).
3. Prefer **Restrict to Gemini API only** when prompted.
4. Add to `%USERPROFILE%\.secrets\api-keys.json` (never commit):

```json
{
  "google": { "api_key": "YOUR_AI_STUDIO_KEY" }
}
```

Also supported (first match wins): env `GEMINI_API_KEY` / `GOOGLE_API_KEY`, keys `google_ai`, `gemini`, or `custom.google_gemini.api_key`.

4. Install deps: `pip install google-genai Pillow` (see root `requirements.txt`).

**Restrict the key** in AI Studio (HTTP referrer or IP) — unrestricted keys are being phased out in 2026.

### Troubleshooting

| Error | Likely cause | Fix |
|-------|--------------|-----|
| `API key missing` | No entry in api-keys / env | Follow setup above |
| `403 API_KEY_SERVICE_BLOCKED` | Chave/projeto GCP (ex.: `190666412179` / `warm-alliance-457415-d2`) **bloqueado** para `generativelanguage` — comum quando a chave veio do Console do projeto YouTube/AdSense | **Nova chave** em [AI Studio](https://aistudio.google.com/api-keys) → **projeto novo** (não reimportar o projeto OAuth). Ver [GEMINI_API_VS_PRO.md](GEMINI_API_VS_PRO.md) |
| `403 PERMISSION_DENIED` (billing) | Modelos de **imagem** não existem no free tier da API | AI Studio → **Set up billing** no projeto da chave (paid tier). Créditos Cloud do Pro (~US$10/mês) podem cobrir uso pequeno |
| `429 RESOURCE_EXHAUSTED` | Rate limit free tier | Backoff; ou billing para tier pago |
| `Need N distinct face photos` | Not enough selfies in `--faces-dir` | Add more images or lower `--count` |

**Reteste 2026-05-30:** chave em `google.api_key` → 403 em `ListModels`, `generateContent` texto e `gemini-2.5-flash-image`; `consumer: projects/190666412179`.

Consumer **Google AI Pro** (browser) **não** desbloqueia API — assinatura ≠ API key. Guia completo: [GEMINI_API_VS_PRO.md](GEMINI_API_VS_PRO.md).

### CLI usage

```powershell
python scripts/generate_thumbnails.py `
  --faces-dir "$env:USERPROFILE\Pictures\faces" `
  --videos-dir "$env:USERPROFILE\YOUTUBE\inbox\fortnite_mobile_20260530" `
  --game "Fortnite Mobile"
```

| Flag | Purpose |
|------|---------|
| `--faces-dir` | Folder of face selfies (jpg/png) — **one distinct face per video, no reuse in one run** |
| `--videos-dir` | Folder of MP4s; output goes to `videos-dir/thumbnails/{stem}_thumb.png` |
| `--game` | Prompt theme set (`Fortnite Mobile`, `Granny 2`, … — see `scripts/thumbnails/prompts.py`) |
| `--count N` | Override auto-count of `.mp4` files |
| `--dry-run` | Plan prompts/paths only — no API calls |
| `--force` | Regenerate even if thumb already exists |
| `--model` | Override Gemini image model ID |

**Human gate:** review generated PNGs before upload. Use `--approve-thumbs` on `fortnite_long_batch.py` to block YouTube upload until every expected thumb exists.

### Pipeline integration

```mermaid
flowchart LR
  A[Selfies + MP4 inbox] --> B[generate_thumbnails.py]
  B --> C[thumbnails/*_thumb.png]
  C --> D[Human review]
  D --> E[fortnite_long_batch --approve-thumbs]
  E --> F[YouTube thumbnails.set]
```

| Piece | Status |
|-------|--------|
| Prompt templates (PT-BR, Alanzoka/Bistecon) | `scripts/thumbnails/prompts.py` |
| Gemini API client + face reference | `scripts/thumbnails/gemini_generate.py` |
| Gemini web (Playwright + storage_state) | `scripts/thumbnails/gemini_web.py` |
| CLI — API path | `scripts/generate_thumbnails.py` |
| CLI — browser path | `scripts/gemini-thumbnails.py` |
| Network inspector | `scripts/thumbnails/inspect_gemini_network.py` |
| `fortnite_long_batch --generate-thumbs` | Calls API generator before copy/manifest |
| Frame grab (ffmpeg) | Not implemented — optional future |
| Gemini web Playwright (`gemini-thumbnails.py`) | Auth, batch, best-effort DOM automation (fragile) |

### API key storage

- **Canonical reference doc:** `AI_CREDENTIALS.md` (user home — lists *where* keys live, not values).
- **Local JSON:** `%USERPROFILE%\.secrets\api-keys.json` — e.g. `google.api_key`.
- **Env override:** `GEMINI_API_KEY` or `GOOGLE_API_KEY`.

Agents: **never** read or paste `api-keys.json` / `youtube_token.json` into chat or commits.

---

## Suggested prompt template (Fortnite Mobile, PT-BR, 1280×720)

Use as a **structure** — replace `{episode}`, `{hook}`, `{brand}`:

```text
Crie uma thumbnail de YouTube 1280x720 para gameplay de Fortnite Mobile.

Canal: {brand} (@abobicaduco)
Episódio: {episode}
Estilo: alto contraste, texto grande em português (máx. 4 palavras), rosto/personagem em destaque, fundo borrado do gameplay.
Cores: roxo/azul neon + amarelo para CTA.
Proibido: logos oficiais da Epic, blood/gore, texto ilegível, mais de 3 linhas de texto.
Entregue 4 variações com hooks diferentes: {hook}
```

**Human review checklist:**

- [ ] Text readable at mobile size  
- [ ] No trademark violations  
- [ ] Matches video title/topic  
- [ ] File name matches `fortnite_mobile_NN_thumb.jpg`  
- [ ] Approved file in `thumbnails/` before upload run  

---

## Security

| Never commit | Notes |
|--------------|--------|
| `youtube_token.json`, `youtube_client_secret.json` | OAuth |
| `gemini_storage_state.json`, `gemini_network.log`, `browser-profile-gemini/` | Gemini web session / capture |
| `api-keys.json` | Gemini / other APIs |
| `*.db` | Schedule state |
| Full-size thumbnail exports with personal email/watermarks | Optional `.gitignore` under inbox if syncing folder |

Use `%USERPROFILE%` and `~/.secrets/` in docs — not machine-specific drive letters except as examples in LOCAL_SETUP.

---

*Last updated: 2026-05-30*
