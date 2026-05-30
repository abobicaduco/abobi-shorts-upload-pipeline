# Gemini Pro (browser) vs Gemini API — guia prático

> **PT-BR** · Para automação de thumbnails (`generate_thumbnails.py`) e scripts que chamam `generativelanguage.googleapis.com`.  
> **Sem segredos neste repo.** Chaves ficam em `%USERPROFILE%\.secrets\api-keys.json`.

Relacionado: [THUMBNAILS.md](THUMBNAILS.md) · [AI_CREDENTIALS.md](file:///C:/Users/carlo/AI_CREDENTIALS.md) (referência local)

---

## Resposta rápida (2026)

| Pergunta | Resposta |
|----------|----------|
| O **Google AI Pro** (~R$100/mês no gemini.google.com) inclui API para scripts? | **Não.** É produto de consumidor (app, Gmail, Antigravity). A API é cobrada/limitada **por projeto** no AI Studio / Cloud Billing. |
| Dá para automatizar **sem pagar nada além** da assinatura Pro? | **Condicional.** Texto: sim, no **free tier** da API (limites baixos). **Imagens (Nano Banana): não no free tier** — exige tier pago (billing ligado). Os **US$ 10/mês de créditos Cloud** do Pro podem cobrir uso pequeno de API se você ligar billing na mesma conta. |
| A chave do YouTube OAuth serve para Gemini? | **Não.** YouTube usa `refresh_token` OAuth. Gemini usa **API key** (`AIzaSy…`) do AI Studio. |
| Erro `API_KEY_SERVICE_BLOCKED` no projeto `190666412179`? | Chave/projeto **warm-alliance-457415-d2** não está autorizado para `generativelanguage.googleapis.com`. **Crie chave nova no AI Studio** (idealmente em **projeto novo**), não só “habilitar API” no Console do projeto do YouTube. |

---

## Três superfícies diferentes (não confundir)

| Superfície | Onde | Autenticação | Incluído no Gemini Pro? |
|------------|------|--------------|-------------------------|
| **Gemini app / gemini.google.com** | Browser | Login Google | **Sim** — limites do plano (imagens no chat) |
| **Google AI Studio + Gemini Developer API** | [aistudio.google.com](https://aistudio.google.com) | API key → `generativelanguage.googleapis.com` | **Não** — free tier próprio + paid tier com billing |
| **Vertex AI (GCP)** | Cloud Console | IAM / service account / ADC | **Não** — billing GCP enterprise |

Documentação oficial:

- [API keys (AI Studio)](https://ai.google.dev/gemini-api/docs/api-key)
- [Billing / tiers](https://ai.google.dev/gemini-api/docs/billing)
- [Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Image generation (Nano Banana)](https://ai.google.dev/gemini-api/docs/image-generation)

---

## Tabela: Browser Pro vs API

| | Gemini Pro (browser) | Gemini API (AI Studio) |
|--|----------------------|-------------------------|
| **Uso** | Chat, imagens manuais, Deep Research | Scripts, pipeline, `generate_thumbnails.py` |
| **Custo** | Assinatura ~R$100/mês | Free tier (texto) + **paid tier (imagens)** |
| **Imagens programáticas** | Só manual no site | Modelos Nano Banana via REST/SDK |
| **Chave necessária** | Nenhuma | `google.api_key` ou `GEMINI_API_KEY` |
| **Projeto GCP** | N/A | Cada chave ligada a um projeto |
| **Dados no free tier** | Política do app | Podem ser usados para melhorar produtos Google |
| **Créditos Cloud do Pro** | Não substituem API key | Podem pagar API **depois** de ligar billing (~US$10/mês inclusos no Pro) |

---

## Modelos de imagem e billing (maio 2026)

| Modelo | ID API | Free tier (API) | Paid tier |
|--------|--------|-----------------|-----------|
| Nano Banana | `gemini-2.5-flash-image` | **Não disponível** | ~US$ 0,039/imagem |
| Nano Banana 2 | `gemini-3.1-flash-image` | **Não disponível** | ~US$ 0,045–0,151/imagem |
| Nano Banana Pro | `gemini-3-pro-image` | **Não disponível** | Mais caro, melhor texto |
| Imagen 4 | Vertex / Imagen API | **Não no free tier Gemini** | Por imagem no GCP |
| Gemini 2.0 Flash | `gemini-2.0-flash` | Depreciado — shutdown **1/jun/2026** | Migrar para 2.5 |

**Conclusão para thumbnails:** mesmo com API funcionando, **geração de imagem exige projeto com billing (paid tier)**. Ligar cartão **não** cobra automaticamente além do uso; no plano Prepay (desde mar/2026) pode ser necessário saldo mínimo (~US$10). Créditos mensais do Google AI Pro podem ajudar se estiverem na mesma conta de billing.

Modelos de **texto** (`gemini-2.5-flash`, etc.) têm free tier sem cartão, com RPM/RPD limitados.

---

## Free tier da Generative Language API

- Existe **free tier** para vários modelos de texto ([pricing](https://ai.google.dev/gemini-api/docs/pricing)).
- Criar chave em [AI Studio → API keys](https://aistudio.google.com/api-keys) **sem cartão** é suportado para prototipagem.
- **Imagens:** coluna “Free Tier” = “Not available” nos modelos Nano Banana.
- AI Studio no browser (playground) permanece gratuito para testes manuais ([billing FAQ](https://ai.google.dev/gemini-api/docs/billing)).

---

## Por que `API_KEY_SERVICE_BLOCKED` (projeto 190666412179)?

Erro típico retestado em 2026-05-30:

```json
{
  "reason": "API_KEY_SERVICE_BLOCKED",
  "metadata": {
    "consumer": "projects/190666412179",
    "service": "generativelanguage.googleapis.com"
  }
}
```

**Projeto:** `warm-alliance-457415-d2` (número `190666412179`) — mesmo projeto dos OAuth YouTube/AdSense.

**Causas comuns (não são “falta de Gemini Pro”):**

1. Chave criada no **Cloud Console** genérico, sem fluxo AI Studio / sem restrição “Gemini API only”.
2. Projeto **importado** no AI Studio mas API não ativada pelo caminho correto.
3. Chave **irrestrita** ou **dormante** — Google passou a bloquear ([docs](https://ai.google.dev/gemini-api/docs/api-key): restrições obrigatórias até jun/2026).
4. Billing tier “Unavailable” no AI Studio para aquele projeto.
5. Conta/região com bloqueio temporário (fórum Google: apelar em [discuss.ai.google.dev](https://discuss.ai.google.dev)).

**Habilitar só “Generative Language API” no GCP Console no projeto do YouTube muitas vezes NÃO resolve** se a chave não foi emitida pelo AI Studio para esse serviço.

---

## Passo a passo: chave AI Studio (mesma conta abobicarlo@gmail.com)

### A) Projeto novo (recomendado — separar de YouTube/AdSense)

1. Abra [aistudio.google.com/api-keys](https://aistudio.google.com/api-keys) logado como **abobicarlo@gmail.com**.
2. **Create API key** → **Create API key in new project** (não reutilize `warm-alliance-457415-d2`).
3. Na criação, escolha **Restrict to Gemini API only** (quando aparecer).
4. Copie a chave **uma vez** → `%USERPROFILE%\.secrets\api-keys.json`:

   ```json
   { "google": { "api_key": "SUA_CHAVE_AI_STUDIO" } }
   ```

5. Teste (PowerShell, sem imprimir a chave):

   ```powershell
   $k = (Get-Content "$env:USERPROFILE\.secrets\api-keys.json" | ConvertFrom-Json).google.api_key
   Invoke-RestMethod -Uri "https://generativelanguage.googleapis.com/v1beta/models" -Headers @{ "x-goog-api-key" = $k }
   ```

   Sucesso = lista de modelos (HTTP 200). Falha 403 com outro `consumer` = anote o número do projeto na mensagem.

### B) Para thumbnails (imagens) — billing

1. No AI Studio → **Projects** → projeto da chave nova → **Set up billing**.
2. Use a conta de billing onde entram os **US$ 10/mês** do Google AI Pro (se ainda não linkou).
3. Plano **Prepay** (2026): pode pedir crédito mínimo ~US$10; usage de imagem debita desse saldo.
4. Rode `generate_thumbnails.py --dry-run` e depois um teste com 1 imagem.

### C) Se ainda 403

- [ ] Chave criada **no AI Studio**, não só em Credentials do GCP
- [ ] Projeto diferente do OAuth YouTube (`190666412179`)
- [ ] Tag “Blocked” ou “Unrestricted” na chave → gerar chave nova restrita
- [ ] AI Studio → Projects → billing tier não “Unavailable”
- [ ] API key restrictions = **Generative Language API** only
- [ ] Região/conta: testar em navegador anônimo ou apelar no fórum Google

---

## OAuth / service account / ADC

| Método | Serve para `generativelanguage`? |
|--------|-----------------------------------|
| **API key (AI Studio)** | **Sim** — caminho oficial do pipeline |
| **OAuth pessoal (YouTube token)** | **Não** para esta API REST |
| **Service account** | **Não** no Gemini Developer API consumer; use Vertex AI |
| **`gcloud auth application-default`** | Vertex / GCP; **não** substitui API key no AI Studio |

Service account `abobiferramentas@warm-alliance-457415-d2.iam.gserviceaccount.com` é para outros APIs GCP, não para Nano Banana via AI Studio.

---

## Checklist: corrigir 403 na chave atual

1. **Não** reutilizar chave do projeto YouTube — criar projeto novo no AI Studio.
2. Atualizar `google.api_key` em `api-keys.json` (nunca commitar).
3. Confirmar `ListModels` retorna 200.
4. Para imagens: **Set up billing** no projeto da chave nova.
5. Manter YouTube em `google_oauth_youtube` — chaves separadas, propósitos separados.

---

## Alternativas se não quiser billing na API

| Opção | Prós | Contras |
|-------|------|---------|
| **Manual no gemini.google.com** | Já pago no Pro; imagens funcionam | Sem automação |
| **Free tier só texto** | US$ 0 | Não gera thumbnails |
| **Outro provedor de imagem** | Pode ter free tier | Mudar script |
| **US$ 10 Cloud credits do Pro** | Pode cobrir dezenas de thumbs/mês | Ainda precisa billing ligado + chave válida |

---

## Onde guardar a chave (local)

Ordem de resolução em `scripts/thumbnails/gemini_generate.py`:

1. Env `GEMINI_API_KEY` / `GOOGLE_API_KEY`
2. `api-keys.json`: `google_ai`, `gemini`, `google.api_key`
3. `custom.google_gemini.api_key`

Referência: `C:\Users\carlo\AI_CREDENTIALS.md`

---

*Última atualização: 2026-05-30 — reteste local: 403 `API_KEY_SERVICE_BLOCKED` em `projects/190666412179`.*
