# Devpost: Latch

Track: Coding and Agentic Engineering, Nebius Global AI Hackathon.
Hosted URL: https://latch-mauve.vercel.app
Repo: https://github.com/aarav1656/latch (MIT)
Demo video: PASTE_VIDEO_URL

Every number below traces to a committed file listed under "Evidence".

---

## Project name

Latch

## Elevator pitch (200 characters max)

Agents write the code and the tests in one PR, and green proves nothing. Latch has Nemotron write a test from the issue and opens only when the harness sees it fail on the bug and pass on the fix.

## About the project

### Inspiration

Coding agents now ship the fix and the tests in the same pull request. The suite goes green, the reviewer sees green, and it merges. We kept seeing the same quiet failure in public threads: a test that calls the changed function but cannot fail. One verifier flipped a condition in a PR and all 12 of its tests still passed. Running the tests is not enough. The tests have to be able to fail.

### What it does

Paste a GitHub pull request that closes an issue. Latch reads the issue as the expected behavior and asks Nemotron Ultra on Nebius Token Factory for one focused pytest. Then the harness, not a model, decides:

1. The test must fail on the base commit with a real assertion, not an import error or a crash.
2. It must pass on the fix, with the repo's own suite still green.
3. It must give the same answer over 5 reruns on each side.
4. It must fail again when the harness reverts the fix.
5. It must kill at least 60% of AST mutants of the exact lines the fix changed.

Only then does the padlock open, with a named verdict (`VALIDATED`, `FIX_FAILS_TEST`, `INVALID_TEST`, `NO_REGRESSION_FOUND`, `FLAKY`, `MUTATION_SURVIVED`) and a JSON receipt holding the generated test, both commit hashes, every model call with its completion id, token counts and cost, and both test outputs.

When the gate shuts on an agent's patch, the fix loop hands Nemotron the failing proof test and lets it repair the code, while the harness blocks any edit to tests. Latch also ships as a CLI (`latch prove`, `latch loop`), a GitHub Action that keeps one PR comment up to date, and a hosted site with shareable receipts at `/r/owner/repo/pr`.

### Results: 42 live runs on Token Factory

| Measure | Result |
|---|---|
| Real bug fixes proven (9 upstream, 12 SWE-bench Lite sympy) | 10 of 21 (48%) |
| Hand-built wrong patches accepted | 0 of 9 |
| Wrong patches failed by a valid proof test | 6 of 9 |
| Runs where Nemotron wrote the fix and the gate opened on a fix the hidden tests reject | 0 of 12 |
| Mutants of proven fixes killed by the proof test | 28 of 31 |
| Cost for all 42 runs at list prices | $2.22 |

For context on a different benchmark with a looser fail-to-pass condition: Otter 31.4%, AssertFlip 43.6%.

### How we built it

Pure Python 3.10+, standard library only on the gate path, so it runs anywhere pytest does.

- **Nemotron Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`) writes the proof test and the fixes. It reads the issue, a repository map and the changed files.
- **Nemotron Lightning** (`nvidia/Nemotron-3_5-Lightning`) builds the repository map and triages whether the base failure actually reproduces the issue. Two models because the jobs differ: Lightning is the fast reader, Ultra is the careful writer.
- Both run on Nebius Token Factory through its OpenAI-compatible chat completions API. Every call's completion id, latency and token usage lands in the receipt.
- The harness archives each commit with `git archive` into a temporary directory, so it never checks out or edits your repo. Mutation testing walks the AST of the changed lines only. On the hosted site, PR test code runs under a stripped environment with no secrets, resource limits and a process-group kill, with network isolation where the host allows it.
- The benchmark (`latch eval`) pins models, prompt hashes, dataset revision and repo SHAs in a manifest, validates every case against its upstream oracle before spending a token, and writes the summary, a report and every receipt.

### Challenges we ran into

The first live benchmark proved 7 of 21. Reading the receipts showed the gate was doing its job and the tests were the bottleneck: Ultra often wrote a test that let the bug's own exception escape instead of asserting on it. We added one repair round where the test writer sees only its own test's error output and rewrites it; the rewritten test goes through every check again. The rerun proved 10 of 21 and caught the one wrong patch that had slipped through. Both runs are committed side by side, case by case.

### Accomplishments that we're proud of

- Zero wrong patches accepted across the live repair run, and zero gates opened on a Nemotron fix the hidden tests reject.
- A real upstream receipt: Click issue #3298 and fix #3299, proven on Token Factory, linkable at `/r/pallets/click/3299`.
- Every number on the evidence page is read from a committed file; anything missing renders as "not recorded".

### What we learned

Mutation testing on the changed lines is the check that separates a test that exercises a fix from a test that pins it. And a harness that refuses to guess is worth more than a smarter prompt: every verdict the model could have fudged is decided by a process exit code.

### What's next for Latch

Latch becomes a required check on agent pull requests: the GitHub Action posts the receipt on every PR, and the hosted gate runs live proofs on the Nebius container endpoint the repo already deploys to.

## Built with

python, pytest, git, nvidia-nemotron, nemotron-ultra, nemotron-lightning, nebius-token-factory, github-actions, vercel

## Nebius platform and model use

All model calls go to Nebius Token Factory serverless at `https://api.tokenfactory.nebius.com/v1/chat/completions`. Ultra writes tests and fixes; Lightning maps repositories and triages. In the live repair run Ultra answered 109 calls with a median latency of 12.6 s and Lightning 60 calls at 6.1 s. The container deploy script (`latch/web/deploy.sh`) targets a Nebius serverless AI endpoint with the key held in MysteryBox.

## Feedback on the tools

- The OpenAI-compatible API made the integration a single standard-library HTTP call, and the returned completion ids gave every receipt a verifiable model trail.
- Usage numbers on every response let us price each run exactly; a published per-model price table on the API docs would let tools quote cost without hard-coding list prices.
- The November 2026 deprecation page was clear about which Nemotron ids leave on 2026-11-09 and what replaces them. The token-factory-cookbook README still lists Super 120B as available, which is worth syncing.
- Ultra's tests improved sharply when it saw its own pytest error output. A documented recommendation for tool-output feedback loops in the Nemotron cookbook would help other builders find that faster.

## Evidence

- `latch/runs/eval-summary-repair.json`, `latch/runs/eval-report-repair.md`: the live repair run.
- `latch/runs/eval-summary.json`, `latch/runs/eval-diff-repair.md`: the first run and the per-case diff.
- `latch/runs/eval-repair/*.json`: every receipt, with model calls, latencies and costs.
- `latch/runs/click-3298.json`: the Click receipt.
- `latch/loop/eval/RESULTS.md`: method, cases, baselines.
