# AboBI Shorts Upload Pipeline

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](scripts/youtube/)

> **LinkedIn one-liner:** Python YouTube Shorts and TikTok pipelines — ffmpeg split, SQLite scheduling (3/day @ 16/18/21 BRT), batch upload to [@abobicaduco](https://www.youtube.com/@abobicaduco).

**Repository:** [github.com/abobicaduco/abobi-shorts-upload-pipeline](https://github.com/abobicaduco/abobi-shorts-upload-pipeline)  
**Português:** [README.pt-BR.md](README.pt-BR.md)

---

## What this project is

Automation for **YouTube Shorts** and **TikTok** for the [@abobicaduco](https://www.youtube.com/@abobicaduco) channel:

- OAuth/API (YouTube) and Playwright (TikTok) upload
- ffmpeg video splitting
- Separate SQLite schedulers — max **3 posts/day** at 16/18/21 `America/Sao_Paulo`

**Not included:** the [AboBI Tools](https://abobiferramentas.com) website lives in [abobiferramentas](https://github.com/abobicaduco/abobiferramentas).

---

## Quick start

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

## Documentation

| Document | Purpose |
|----------|---------|
| [docs/PLATFORMS.md](docs/PLATFORMS.md) | **Index** — paths, DBs, daily commands |
| [scripts/youtube/README.en.md](scripts/youtube/README.en.md) | YouTube module (English) |
| [scripts/youtube/README.md](scripts/youtube/README.md) | YouTube module (Português) |
| [docs/youtube/HANDOFF.md](docs/youtube/HANDOFF.md) | YouTube AI handoff |
| [docs/tiktok/HANDOFF.md](docs/tiktok/HANDOFF.md) | TikTok AI handoff |
| [docs/youtube/SCHEDULING_POLICY.md](docs/youtube/SCHEDULING_POLICY.md) | 3 Shorts/day policy |
| [docs/tiktok/SCHEDULING_POLICY.md](docs/tiktok/SCHEDULING_POLICY.md) | TikTok 3/day + 30 cap |
| [docs/AI_CONTINUATION.md](docs/AI_CONTINUATION.md) | Agent session bootstrap |
| [AGENTS.md](AGENTS.md) | Agent instructions |
| [LOCAL_SETUP.md](LOCAL_SETUP.md) | Canonical paths + secrets |

**Secrets stay outside the repo** under `%USERPROFILE%\.secrets\` — see HANDOFF for paths (never values).

---

## License

MIT — see [LICENSE](LICENSE).
