# Research

Everything read, fetched, and tested before and during the Latch build for the Nebius x NVIDIA Global AI Hackathon.

## Start here

`INDEPENDENT_DISCOVERY_2026-10-29.md` is the decision log: blank seeds, the scoreboard from the Berlin Build Week, the ideas that were killed and why, the four-model review, prior art, and the build notes.

The binding pre-code decision is `../docs/WIN-CONDITIONS.md`. The demand posts it cites are verified in `../docs/signals/`.

## Folders

`token-factory/` holds the platform facts the code depends on.

- `models.json`: live `GET /v1/models` result. 30 models, five NVIDIA ids.
- `deprecations.json`: the November 2026 removal page. Nano and Super serverless ids leave on 2026-11-09, before judging.
- `api.md`, `api-pages.json`, `quickstart-llms.json`: chat completions request shape, auth header, base URL.
- `catalog.json`, `cookbook.json`, `cookbook2.json`, `search*.json`: model catalog and cookbook reads used to pick Ultra and Lightning.

`prior-art/` holds the two Flawd pages fetched through the treg TinyFish lane. The study page has the 10-project mutation table, including TypeORM at 72.6%. The home page describes `flawd handoff`, which packages survivors for a coding agent and makes no Token Factory call.

`model-reviews/` holds what other models said about the design.

- `boundary.md`: GPT on the only false success, an assertion that reaches the test file without coming from Ultra.
- `kill.md`: Grok on the stale Open page after a timeout. Latch now paints Shut first.
- `chatgpt.txt`: count a kill only when the flipped run fails with AssertionError.
- `qwen*.txt`: three qwen38 attempts, all blocked upstream.

`spikes/mutate.py` is the first symmetric versus asymmetric mutation spike.
