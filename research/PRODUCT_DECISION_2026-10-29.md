# Product decision, 2026-10-29

## Decision and deadline

Keep one entry, Latch, for the Coding and Agentic Engineering track. Narrow the next build to an issue-anchored regression proof for Python bug-fix changes. The official deadline is 2026-10-30 10:00 PDT, or 17:00 UTC. At the start of this research pass, about 33 hours remained.

Official judging is a pass/fail theme and API-fit screen followed by four equally weighted scores: technological implementation, design, potential impact, and idea quality. The rules require a working project, public repository with open-source license and setup instructions, working demo URL, public YouTube video under three minutes, platform/model explanation, tool feedback, and a significant-update note only if the project predated the submission period. The official project gallery is unpublished, so there is no visible live submission scoreboard. The Berlin Builders & Brews event in the old decision document is a separate event and is only a nearest-event proxy. Sources: https://nebiusglobalaihackathon.devpost.com/rules, https://nebiusglobalaihackathon.devpost.com/project-gallery.

## Objective and user

The user is a Python maintainer reviewing an agent-authored bug fix. Their job is to establish that the reported behavior is fixed, not merely that the current test suite is green. The fast action is `latch prove` with an issue statement, buggy base ref, and patch ref. The recurring trigger is each agent-authored bug fix. The share artifact is a JSON receipt attached to the PR. The proof is a generated regression test that reproduces the issue's reported failure against the buggy base and passes against the patch.

## Independent blank seeds

- Why can tests pass after an AI-authored code change that is wrong?
- What do reviewers do when a bug-fix PR has green tests but no regression test?
- How do teams verify that an AI-authored test checks behavior rather than shape or execution?
- Which local, CI, and agent-runtime checks can establish red-on-old-code and green-on-fixed-code?
- Which failure modes make mutation scores misleading?
- What do maintainers pay for when code review and test generation are the bottleneck?

The supplied Latch/Flawd links were validation inputs, not the initial search map.

## Research lanes and tools

- **Official/ecosystem:** official Devpost rules, Nebius Token Factory docs/API, NVIDIA model documentation, Claude Code hook reference, and OpenCode plugin docs.
- **GitHub/implementation:** independent search found Crucible, SWE-Mutation, mutmut, Mutahunter, Stryker, and Cosmic Ray. Crucible source and GitHub Action were inspected, not just its README.
- **Demand/community:** X, Hacker News threads and comments, Reddit discussions, and recent engineering commentary. Search, `dr`, ChatGPT Research, and independent agent reads were used.
- **Academic/evidence:** five studies/reports on mutation-guided LLM tests, test-generation under software changes, real-world agent tests, and test quality.
- **Product/launch:** Product Hunt, Show HN, Reddit, BetaList, Indie Hackers, CodeRabbit, Qodo, Stryker, and Mutahunter product/pricing pages.
- **Treg:** `treg.web.extract` fetched full text for the Devpost rules, Crucible repository, and mutation-testing paper. Each call used `X-Treg-Route-Waterfall: 0`, max route cost $0.01, and was served by crawl4ai for $0.00015.
- **Model review:** ChatGPT Research CLI synthesized the blank-seed question and returned 25 source URLs. OpenCode Nemotron 3.5 Lightning answered a short review prompt. OpenCode DeepSeek v4.1 Flash free was started but timed out. Qwen38 failed twice with upstream HTTP 429 risk control. Hermes over SSH to the mini returned HTTP 429 after three retries. Claude Code 2.1.285 is installed but its CLI request returned HTTP 403 `oauth_not_allowed_for_organization` before a Stop hook could run. The Nebius Token Factory live endpoint already produced the project's test-generation proof in `latch/runs/latest.json`.

## Source coverage

The research agents report reading 41 distinct full-text URLs across these lanes. Search snippets are excluded. Source inventory:

| Lane | Full-text URLs | What was read |
|---|---:|---|
| Official and ecosystem | 7 | Rules, platform API/model sources, agent hook/plugin references |
| GitHub implementation | 13 | Crucible files and action, SWE-Mutation code, mutation tools and docs |
| Academic | 7 | Mutation, test generation, software evolution, and real-world agent-test studies |
| Long-form/product | 6 | Three Substack essays and paid code-quality product/pricing pages |
| Community | 8 | X, HN threads/comments, Reddit product/problem threads |

URLs read in full or inspected deeply:

- Official: https://nebiusglobalaihackathon.devpost.com/rules ; https://nebiusglobalaihackathon.devpost.com/ ; https://api.tokenfactory.nebius.com/docs ; https://dev.nebius.com/token-factory ; https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4 ; https://docs.anthropic.com/en/docs/claude-code/hooks ; https://docs.opencode.ai/docs/plugins/.
- GitHub/code: https://github.com/Jott2121/crucible ; https://github.com/Jott2121/crucible/blob/main/src/crucible/loop.py ; https://github.com/Jott2121/crucible/blob/main/src/crucible/engine.py ; https://github.com/Jott2121/crucible/blob/main/src/crucible/receipts.py ; https://github.com/Jott2121/crucible/blob/main/action.yml ; https://github.com/Sunny4Coding/SWE-Mutation ; https://github.com/Sunny4Coding/SWE-Mutation/blob/main/framework/self_play.py ; https://github.com/Sunny4Coding/SWE-Mutation/blob/main/evaluation/evaluate.py ; https://github.com/boxed/mutmut ; https://github.com/boxed/mutmut/tree/main/src/mutmut/mutation ; https://github.com/boxed/mutmut/tree/main/src/mutmut/runners ; https://github.com/codeintegrity-ai/mutahunter ; https://stryker-mutator.io/docs/.
- Papers/reports: https://aclanthology.org/2026.findings-acl.1976/ ; https://arxiv.org/abs/2406.09843 ; https://doi.org/10.1109/TSE.2026.3682975 ; https://arxiv.org/abs/2609.24341 ; https://arxiv.org/abs/2603.23443 ; https://arxiv.org/abs/2607.12068 ; https://andrehora.github.io/pub/2026-msr-agents-over-mocked-tests.pdf.
- Long-form/products: https://srikanthdevarajan.substack.com/p/who-tests-the-tester-mutation-testing ; https://developertips.substack.com/p/code-is-cheap-correctness-is-not ; https://yellingatrobots.substack.com/p/agents-10xd-our-dev-then-qa-called ; https://www.coderabbit.ai/review ; https://www.coderabbit.ai/pricing/ ; https://www.qodo.ai/pricing/.
- Community: https://x.com/NatureBlueee/status/2115186551407944177 ; https://x.com/wmertens/status/2115473040624554360 ; https://x.com/DYoung_AI/status/2115470900808102089 ; https://news.ycombinator.com/item?id=48558949 ; https://news.ycombinator.com/item?id=49534948 ; https://news.ycombinator.com/item?id=40910603 ; https://www.reddit.com/r/Agentic_Coding/comments/1wce8p7/why_does_ai_write_tests_that_dont_actually_test/ ; https://www.reddit.com/r/codex/comments/1wjqc8h/i_made_codex_prove_its_own_tests_before_it_can/.

Video transcripts were not used. The decision turns on executable code, official rules, papers, and practitioner threads; no talk transcript was needed to judge the chosen bug-fix loop. A public demo video is still a required submission artifact and remains to be produced.

## Evidence and contradictions

- **Problem evidence:** one X report documents 1,621 tests remaining green across five deliberate breaks. Other X, HN, and Reddit posts describe weak agent-authored tests or costly manual verification. These are problem signals, not willingness-to-pay evidence.
- **Direct alternative:** Crucible is a close implementation with iterative test generation, mechanical mutation verdicts, receipts, and a GitHub Action. The repo showed 82 commits, 0 stars, and 1 fork at the time checked. That demonstrates implementation, not adoption.
- **Academic prior art:** SWE-Mutation and MUTGEN directly study mutation-guided test generation. Test quality papers show that generated tests can be unexecutable or poorly aligned with semantic changes. Therefore Latch must not claim that mutation sensitivity establishes correct intent.
- **Adjacent paid products:** CodeRabbit and Qodo sell review/test workflows. Their pricing shows budget in adjacent code-quality tools, not demand for Latch's exact capability.
- **Product research failures:** Product Hunt returned a CAPTCHA, BetaList found no relevant launch, and Indie Hackers search is retired. Reddit direct API requests returned 403 in one lane, but full threads were available through browser/search routes. TinyFish credentials were absent in the rs sweep; Exa returned 429 for OpenCode; Qwen38, Hermes, and Claude Code had the failures above.
- **Contradiction:** generic red/green test generation is both a well-documented developer pain and a crowded product/research mechanism. The only remaining wedge is using the real issue as an external oracle and the actual buggy/fixed Git states as the execution proof. This is a narrower workflow claim, not an algorithm novelty claim.

## Candidates and hostile kill pass

1. **Generic mutation repair:** killed. Crucible already has the product loop and PR action; SWE-Mutation establishes direct research prior art.
2. **Mutation-score dashboard/CI wrapper:** killed. Stryker, mutmut, Mutahunter, and Crucible already cover this surface.
3. **Broad AI code reviewer:** killed. CodeRabbit and Qodo are direct paid alternatives; a model-provider swap adds no capability.
4. **Agent lifecycle stop hook:** killed for this submission. The documented Claude hook could block completion, but the real local runtime returned 403 before the hook fired. A synthetic hook test would not satisfy the judge-visible proof gate.
5. **Issue-anchored bug-fix proof:** keep for one narrow build. For a real Python bug-fix, use the issue statement plus actual base and patch commits, generate one regression test, and accept only if the harness reproduces the issue-specific failure on base and succeeds on patch. This remains killable if a real repository cannot be exercised safely or the test is not traceable to the issue.

## Product gate and technical primitive

- **User:** Python maintainer reviewing an agent-authored bug fix.
- **Buyer:** engineering team accepting coding-agent bug fixes.
- **Action:** run `latch prove --repo ... --base ... --head ... --issue ...` on a bug-fix.
- **Return trigger:** each agent-generated fix.
- **Share trigger:** attach the JSON receipt to the pull request.
- **Under-90-second proof:** receipt shows issue, repository/ref hashes, generated test, issue-specific base failure, patch pass, and rerunnable commands.
- **Technical primitive:** issue-conditioned test generation from Nemotron, checked against the real before/after code by a local harness.
- **Kill shot:** test intent can be misunderstood; the gate must fail closed for ambiguous issues, base failures that do not match the issue symptom, base tests that pass, or patch failures.
- **Never build:** generic mutation scores, broad AI review, arbitrary language support, hosted accounts, and lifecycle hooks without a verified runtime.

## Build result

- The real-system spike confirmed Click issue #3298 with Nemotron 3 Ultra and actual `semver.Version` behavior. The base produced the reported ValueError and the fix passed.
- `latch/prove.py` now implements the issue, diff, base, head, generated test, dual-snapshot run, and JSON receipt path. It leaves the source checkout untouched.
- The live CLI proof used Click base `04ef3a6f473deb2499721a8d11f92a7d2c0912f2` and fix `d340b0c1202284a1b9d0ca892549208527d586ce`. Receipt is `latch/runs/click-3298.json`, completion `chatcmpl-99d6e5a92020c804`, with base exit 1, head exit 0, and `proven: true`.
- The pytest failure classifier accepts only the generated test's own failure summary when it is an AssertionError or the explicit unexpected-operation failure. A mutation that accepted every base failure was killed, then the test suite passed after restore.
- The existing browser screen remains the billing fixture. It does not accept a PR or render the real-issue receipt. The real issue workflow is currently a CLI and JSON artifact.
- The repository is local. It has not been pushed to a public forge, deployed to a public URL, or recorded as a demo video.
- Demand evidence remains qualitative. There is no willingness-to-pay evidence for Latch itself.

## Remaining submission work

1. Decide whether to add a browser flow for entering a repository, issue, and commit refs, or demonstrate the CLI directly.
2. Provide a public code-hosting URL and working demo URL.
3. Record and publish the required short demo video and submit through Devpost.

## Models used in research

- Codex subagents: official/ecosystem, GitHub implementation, demand/community, academic, and product/launch lanes.
- ChatGPT Research CLI: web-enabled product kill pass.
- OpenCode Nemotron 3.5 Lightning free: returned `PING` on a short direct call.
- OpenCode DeepSeek v4.1 Flash free: web-search requests hit Exa HTTP 429; the subsequent direct review was still running at the time this file was written.
- Qwen38: two calls rejected by upstream Alibaba risk control with HTTP 429.
- Hermes on the Mac mini over SSH: HTTP 429 after three retries. No code or secret was sent.
- Nebius Token Factory: existing live Nemotron proof in `latch/runs/latest.json`.
