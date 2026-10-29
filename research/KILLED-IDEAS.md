# Killed ideas, 2026-10-29

Decision: keep Latch, but narrow the proof from generic mutation repair to an issue-anchored bug-fix regression check.

## Killed

- **Generic mutation-guided test repair.** Crucible already runs a Tester/Critic loop, validates kills mechanically, records receipts, and offers a GitHub Action. SWE-Mutation studies the same mechanism at benchmark scale. More repository support would make Latch broader without making it distinct. Sources: https://github.com/Jott2121/crucible, https://github.com/Sunny4Coding/SWE-Mutation, https://aclanthology.org/2026.findings-acl.1976/.
- **A mutation-score dashboard or generic PR gate.** Crucible's action already reports scores, posts comments, and can fail a PR below a threshold. Stryker, mutmut, and Mutahunter make mutation generation and survivor reporting established infrastructure. Sources: https://github.com/Jott2121/crucible/blob/main/action.yml, https://github.com/boxed/mutmut, https://github.com/stryker-mutator/stryker-js, https://github.com/codeintegrity-ai/mutahunter.
- **Broad AI code review.** CodeRabbit and Qodo already sell review, test generation, and developer integrations. A Nemotron-backed review UI is a provider wrapper without a new user capability. Sources: https://www.coderabbit.ai/pricing/, https://www.qodo.ai/pricing/.
- **A Claude Code completion hook as the first product surface.** Stop hooks can block completion in the documented API, but the local Claude Code session returned HTTP 403 `oauth_not_allowed_for_organization` before a Stop event could be exercised. A synthetic hook invocation is not proof of a real agent integration. The local OpenCode models were callable, but its event API did not expose a verified blocking stop decision in this run. Sources: https://docs.anthropic.com/en/docs/claude-code/hooks, https://docs.opencode.ai/docs/plugins/.

## Kept, pending proof

- **Issue-anchored bug-fix proof.** Input: a user-reported bug, a Python repository, and its buggy base plus fixed patch. Output: a model-written regression test that reproduces the reported failure on the buggy base, passes on the patch, and has a JSON receipt with both commands and results. The issue description is the independent behavior oracle; mutation score alone is not.
- **User loop.** A Python maintainer invokes `latch prove` on each agent-authored bug-fix before merging. The receipt can be attached to the pull request. A successful run should be verifiable in under 90 seconds by opening the receipt and rerunning its two commands.
- **Kill shot.** The test may misread the issue. The gate must fail closed when the issue is absent, the base failure does not match the reported symptom, the patch test fails, the two refs do not differ, or model output cannot be parsed and executed.

## Evidence limits

The demand posts show a recurring test-trust problem, not willingness to pay for Latch. CodeRabbit and Qodo prices show spend in adjacent code-quality products, not demand for this exact proof. Crucible's GitHub repo showed 82 commits, 0 stars, and 1 fork when checked. That is implementation evidence, not adoption evidence. The issue-anchored loop remains a hackathon-sized hypothesis until a maintainer runs it on a real bug-fix repository.
