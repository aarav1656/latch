# Independent discovery 2026-10-29

Decision: build one entry, Latch, on the Coding and Agentic Engineering track.
Deadline: 2026-10-30 10:00 PDT. Judging: 2026-12-01 to 2026-12-15. Winners on or around 2027-01-11.

## Blank seeds

Queries before naming Latch: agent that writes and runs tests, private assistant that takes an action, model cascade to cut cost, embodied agent without a robot, what a prior Nebius or NVIDIA hackathon actually crowned.

## Commands

- `decide doctor` exit 0. Taste JSONL files missing. Warned, did not invent them.
- `decide brief f7031009-42b3-45f5-9c1e-e54b906d0aa1` and `3ec05286-11eb-4e25-a77f-490d16673da3`. Both apply to the same Devpost. Quotable verb: "Build a working AI system..."
- `decide hacklist` showed both listings, deadline 2026-10-30.
- `python -m social_cli.cli search` on account kamal. `python -m social_cli.cli tweet 2115186551407944177`.
- `python -m social_cli.cli bookmarks -m 15 -a kamal`. Fundraising and other hackathons. No product pick.
- `decide taste` not treated as passed. Cache files are still absent.
- `xsignals verify docs/signals` then `decide gate` : PASS Latch, 3 outside users.
- `bhn deepsurge status`: STOPPED. No browser scrape of X.

## Lanes

Official: [rules](https://nebiusglobalaihackathon.devpost.com/rules), [judging update](https://nebiusglobalaihackathon.devpost.com/updates/46204-here-s-how-judging-works), [prizes](https://nebiusglobalaihackathon.devpost.com/updates/46206-did-someone-say-prizes), [FAQ](https://nebiusglobalaihackathon.devpost.com/details/faqs), [resources](https://nebiusglobalaihackathon.devpost.com/resources), [dev.nebius.com](https://dev.nebius.com/), [builders](https://dev.nebius.com/builders), [November deprecation](https://docs.tokenfactory.nebius.com/model-deprecations-november-2026.md), [sandboxes](https://docs.tokenfactory.nebius.com/sandboxes/overview.md). Model catalog and cookbook index were read by the platform lane.

GitHub lane read source beyond READMEs in SWE-agent, Aider, OpenHands, NVIDIA/Nemotron-CORTEXA, NousResearch/hermes-agent, NVIDIA/NemoClaw, nebius/token-factory-cookbook. NemoClaw issue 3279 was not re-fetched here: GitHub API rate limit.

Demand: GitHub issue [anthropics/claude-code#35042](https://github.com/anthropics/claude-code/issues/35042) (title and body opened). X posts listed in `docs/signals/signals.md`. HN and Reddit quotes came from the demand lane and were not re-opened in this process, except where a URL is in that lane's report.

Papers cited by the demand lane, not re-read end to end here: SWE-bench (arXiv 2310.06770), SWE-agent (arXiv 2405.15793), FrugalGPT (arXiv 2305.05176).

Long-form: Berlin recap on [Tech Europe](https://hackathons.techeurope.io/events/nebius-build-week-hackathon-in-partnership-with-nvidia). LinkedIn posts from Ahmed Sohail and Aaron Nowak were search results, not full-page reads.

Video transcripts: none opened. Gap.

## Scoreboard

Berlin Build Week, 2026-10-18, 74 projects. Grand champion: Little Big Questions. Asset: a LoRA trained toward 1960s Zagreb Film's Professor Balthazar, plus a Tavily, Nemotron, FLUX, Blender pipeline. Usage number: not published.

ShipGuard, same event, SAP challenge: reproduce a bug with a failing test, then patch, canary, rollback. It did not take the grand prize.

This global gallery is unpublished. Registrations on the Devpost page: 28926. That is not a submission count.

## Kills

- Sponsor cookbooks: deep research plus Tavily, invoice extraction, OpenCode, agentic cost benchmark, OpenClaw on Token Factory.
- Personal assistant on Hermes, NemoClaw, or OpenClaw. Those products already exist.
- A second kids news show. Little Big Questions won the closest event 11 days ago.
- Physical simulation. Published credits are Token Factory, not AI Cloud. Sandboxes are beta and require an access request.
- A model router. The cost cookbook already bake-offs Ultra, Super, and Lightning offline.
- A generic coding agent that runs pytest only if the model chooses to.

## Models that still exist when judges test

Serverless removal on 2026-11-09, before judging: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and `nvidia/nemotron-3-super-120b-a12b`. No automatic reroute.

Use `nvidia/Nemotron-3-Ultra-550b-a55b` for the patch and `nvidia/Nemotron-3_5-Lightning` for the mutation proposal.

## Second pass, 2026-10-29 11:40 IST

Tools that ran: `dr showhn`, `dr gh`, `dr hncomments 49308665`, `grokweb research --turns 2` (grok-3 on x.com), `freecode` on an isolated scratch repo. `chatgpt doctor` returned HTTP 401. `phunt search` hit a Product Hunt bot check. `dr discover` returned an empty Product Hunt block. `freecode` muse failed twice with `err_3285f525` and `err_5c637bbe`. deepseek passed on attempt 1.

Show HN already has the category. Flawd, 2026-09-02, 4 points: https://fixture.dev/flawd and https://news.ycombinator.com/item?id=49536607. mutmut is BSD, 1513 stars. Flawd releases: 0 stars, 21 downloads of the macOS binary. https://github.com/fixture-dev/flawd-releases

Four models, four jobs:

- Sonnet: RESHAPE. Scores 3, 2, 3, 3. A rule can flip `==`. Design is the weak score.
- GPT: filled. A mutation CLI would clone Flawd. TypeORM killed 72.6% of Flawd mutants in their 10-project study.
- Gemini: the Berlin winner is a 3D bedroom and a cartoon. Its other wedge cited HN 49308665. That comment asks which tools human reviewers use. It is not a buyer for a screenshot agent.
- Grok: Flawd repo 0 stars, August 2026, 21 downloads. The non-author line is that the trial form was broken.

`grokweb` said ship a test-aware mutant the current suite misses, then have the model write the assertion that kills it. Refuse another syntactic mutator.

## Treg read, 2026-10-29 12:02 IST

`TREG_TOKEN` from `~/.zshrc` is accepted. Team `dev-21`. Two `treg.web.extract` calls, cap `X-Treg-Route-Max-Cost: 0.01`, both served by `crawl4ai.web.scrape` at 150 micro-USD each.

https://fixture.dev/writing/we-mutation-tested-10-projects (Frank O'Hara, 2026-09-01). TypeORM 72.6% is in the table: 146 mutants, full pool, score = killed / (killed + survived). The unit-test tree only. Range in that table is 72.6% (TypeORM) to 100% (Celery, Vector). The page says a surviving mutant plus the tests that should have caught it is a mechanical prompt.

https://fixture.dev/flawd. `flawd handoff` already packages each survivor (diff, covering tests, fix guidance) for a coding agent to write the missing tests. Local binary. No Token Factory call.

Freecode proof, `research/spikes/mutate.py`: total 2 done 1 prints `SYMMETRIC 1 1 PASS`. total 3 done 1 prints `ASYMMETRIC 1 2 FAIL`. The counts are `total - done` and `done`.

## Build, 2026-10-29 13:20 IST

`NEBIUS_API_KEY` is set. `GET /v1/models` returned HTTP 200 with 30 models, saved as `research/token-factory/models.json`. The ChatGPT CLI works again: its review is `research/model-reviews/chatgpt.txt` and became the AssertionError-only rule. qwen38 hit Alibaba risk control (HTTP 429) on every call, see `research/model-reviews/qwen*.txt`.

The fixture moved from a planted 3-line `admits()` to an annual-discount pull request in `latch/fixture/billing.py`. The live gate run is `latch/runs/latest.json`: suite green on the original line, still green on `seats > 10`, Lightning named `test_ten_seats_ran`, Ultra wrote `test_ten_seats_annual_discount` (completion `chatcmpl-87fee6d9c6662143`), which failed with AssertionError on the change and passed after restore.
