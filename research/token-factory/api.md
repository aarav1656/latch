# Token Factory serverless chat API (2026-10-29)

Source of truth: https://docs.tokenfactory.nebius.com/model-deprecations-november-2026.md
Also read: https://docs.tokenfactory.nebius.com/quickstart.md
Auth: https://docs.tokenfactory.nebius.com/api-reference/introduction.md

## Call

- POST path: `/v1/chat/completions`
- Full URL: `https://api.tokenfactory.nebius.com/v1/chat/completions`
- Auth header name: `Authorization`
- Auth value: `Bearer $NEBIUS_API_KEY`
- Body: OpenAI chat-completions JSON, `model` set to one id below

Quickstart curl posts that URL with `Authorization: Bearer $NEBIUS_API_KEY`.

## Ids to use (still current)

- `nvidia/Nemotron-3-Ultra-550b-a55b`
- `nvidia/Nemotron-3_5-Lightning`

Neither id is in the November 2026 deprecation table. Lightning is the listed replacement for Nano.

## Removed on 2026-11-09

Yes. From Token Factory Serverless (API and Playground), not Dedicated Endpoints:

- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` → replace with `nvidia/Nemotron-3_5-Lightning`
- `nvidia/nemotron-3-super-120b-a12b` → replace with `nvidia/Nemotron-3.5-Super-VL`

Quote from the deprecation page:

> "These models will be removed from Token Factory Serverless on November 9, 2026."

After that date, those two ids cannot be selected in Playground or sent in API requests. Token Factory does not reroute them.

## Pages that disagree

- Official Nemotron cookbook README (https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md) still lists Super 120B as available and still links Playground `nvidia/nemotron-3-super-120b-a12b`. Deprecation page says that serverless id is removed on 2026-11-09.
- Ultra cookbook sample (https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/nemotron3-ultra-550b-a55b.md) uses the same Ultra id but `https://api.tokenfactory.us-central1.nebius.com/v1/`, not the global host above. Official quickstart uses the global host. Docs do not say Ultra is missing from the global host.
- Catalog HTML at `tokenfactory.nebius.com/models/catalog/...` returned a JS shell with no model ids. Do not treat it as a model list.

Quickstart example model is `deepseek-ai/DeepSeek-R1-0528`. That is a sample, not a Nemotron replacement.

No prices recorded.
