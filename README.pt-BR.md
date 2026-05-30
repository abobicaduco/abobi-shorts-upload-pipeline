# AboBI Shorts Upload Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](scripts/youtube/)

> **LinkedIn:** Pipelines Python para YouTube Shorts e TikTok — split ffmpeg, agendamento SQLite (3/dia @ 16/18/21 BRT), upload em lote para [@abobicaduco](https://www.youtube.com/@abobicaduco).

**Repositório:** [github.com/abobicaduco/abobi-shorts-upload-pipeline](https://github.com/abobicaduco/abobi-shorts-upload-pipeline)  
**English:** [README.md](README.md)

---

## O que é este projeto

Automação de **YouTube Shorts** e **TikTok** para o canal [@abobicaduco](https://www.youtube.com/@abobicaduco):

- Upload via OAuth/API (YouTube) e Playwright (TikTok)
- Divisão de vídeos com ffmpeg
- Schedulers SQLite separados — máximo **3 posts/dia** às 16/18/21 `America/Sao_Paulo`

**Não inclui:** o site [AboBI Ferramentas](https://abobiferramentas.com) está em [abobiferramentas](https://github.com/abobicaduco/abobiferramentas).

---

## Início rápido

```powershell
cd C:\Users\carlo\Projects\abobi-shorts-upload-pipeline
pip install -r requirements.txt
playwright install chromium
```

### YouTube

```powershell
python scripts/youtube-upload.py --auth-only
python scripts/youtube-upload.py --inbox --dry-run
python scripts/youtube-pipeline.py --resume --upload-limit 3
```

### TikTok

```powershell
python scripts/tiktok-upload.py --auth-only
python scripts/tiktok-pipeline.py --schedule-only
python scripts/tiktok-pipeline.py --resume --upload-limit 3
```

---

## Documentação

| Documento | Propósito |
|-----------|-----------|
| [docs/PLATFORMS.md](docs/PLATFORMS.md) | **Índice** — caminhos, DBs, comandos diários |
| [scripts/youtube/README.md](scripts/youtube/README.md) | Módulo YouTube (Português) |
| [scripts/youtube/README.en.md](scripts/youtube/README.en.md) | Módulo YouTube (English) |
| [docs/youtube/HANDOFF.md](docs/youtube/HANDOFF.md) | Handoff IA YouTube |
| [docs/tiktok/HANDOFF.md](docs/tiktok/HANDOFF.md) | Handoff IA TikTok |
| [docs/youtube/SCHEDULING_POLICY.md](docs/youtube/SCHEDULING_POLICY.md) | Política 3 Shorts/dia |
| [docs/tiktok/SCHEDULING_POLICY.md](docs/tiktok/SCHEDULING_POLICY.md) | TikTok 3/dia + cap 30 |
| [docs/AI_CONTINUATION.md](docs/AI_CONTINUATION.md) | Bootstrap de sessão para agentes |
| [docs/content/FORTNITE_MOBILE.md](docs/content/FORTNITE_MOBILE.md) | Lote long-form Fortnite Mobile (2026-05-30) |
| [docs/THUMBNAILS.md](docs/THUMBNAILS.md) | Miniaturas (Gemini manual + API futura) |
| [AGENTS.md](AGENTS.md) | Instruções para agentes |
| [LOCAL_SETUP.md](LOCAL_SETUP.md) | Caminhos canônicos + secrets |

**Secrets ficam fora do repo** em `%USERPROFILE%\.secrets\` — veja HANDOFF para caminhos (nunca valores).

---

## Licença

MIT — veja [LICENSE](LICENSE).
