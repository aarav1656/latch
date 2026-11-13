# Latch: go-to-market

## Positioning

**One line:** Your coding agent's tests are green. Latch checks whether they could ever have been red.

**Category:** a merge gate for agent-written pull requests. Not an AI reviewer (those comment, Latch executes) and not a test generator (those chase coverage, Latch proves one test can fail).

**The proof point to lead with everywhere:** 0 of 9 plausible-but-wrong patches accepted, $2.22 for 42 live runs. Nobody else in the category publishes a wrong-patch acceptance rate.

**The thesis, with outside evidence:** agent tests copy the code they test, so they copy its bugs. Latch writes its test from the issue instead. An independent experiment found exactly this lever: given only the code, Claude Sonnet 5 wrote suites that passed on the bug 53 of 54 times; with a written spec, detection rose to 96% ([Dik Rana, 2026](https://dikrana.dev/blog/agent-tests-lock-in-bugs/)). 80.2% of 86,156 agent-authored test patches had a weak or missing oracle ([arXiv 2606.18168](https://arxiv.org/abs/2606.18168)).

## Who to reach first

| Segment | Why they convert | Where they are |
|---|---|---|
| Maintainers of popular Python libraries receiving agent PRs | Review load is their bottleneck; a free Action costs them nothing | GitHub, Python Discord, PyPA/PSF forums, Mastodon (fosstodon) |
| Teams running Claude Code, Codex, Copilot agent, Devin in CI | They already pay for agents and already distrust the tests | r/ClaudeCode, r/ClaudeAI, r/ExperiencedDevs, HN, LinkedIn eng leads |
| Agent-tooling builders (harnesses, orchestrators) | A "verified done" step is a feature they can ship | GitHub, X, Discord servers of agent frameworks |

## Channels, ranked by leverage

1. **GitHub Marketplace listing for the Action.** Zero-install for the core user. Name and tagline: "Latch: prove the PR's test can fail". Marketplace only lists an `action.yml` at a repository root, and today's lives at `.github/actions/latch/` with no `branding` block: publish it from a small `latch-action` repo (root `action.yml`, `branding: {icon: lock, color: yellow}`) and tag a release.
2. **Receipts as content.** Run Latch on recently merged agent-authored PRs in well-known Python repos and publish the receipts on the hosted site. A `FIX_FAILS_TEST` on a real merged PR is a story; a `VALIDATED` is a free endorsement. Share the receipt with the maintainer privately first; never post on their PR uninvited.
3. **Show HN.** Title: "Show HN: Latch, a merge gate that checks whether your agent's tests can fail". Lead with the hole animation and the 0 of 9 number, link the Click receipt. Post Tuesday to Thursday morning US Eastern.
4. **Answer the existing complaints.** The demand is already posted in public; reply with a receipt, not a pitch:
   - [r/ClaudeCode: tests that patched the app at runtime](https://www.reddit.com/r/ClaudeCode/comments/1rug14a/claude_wrote_playwright_tests_that_secretly/)
   - [r/ClaudeAI: fake tests and demo data](https://www.reddit.com/r/ClaudeAI/comments/1mgzyg7/fake_tests_and_demo_data_claude_codes_biggest/)
   - [anthropics/claude-code#33781](https://github.com/anthropics/claude-code/issues/33781), [#35042](https://github.com/anthropics/claude-code/issues/35042)
   - LinkedIn: [Viljami Kuosmanen](https://www.linkedin.com/posts/anttiviljami_caught-claude-code-red-handed-again-asked-activity-7469105276210532352-mLSJ), [Neha Chawla](https://www.linkedin.com/posts/nehachawla15_testautomation-playwright-claudecode-activity-7489255046212382720-LdS-)
   - X: [@NatureBlueee](https://x.com/NatureBlueee/status/2115186551407944177), [@wmertens](https://x.com/wmertens/status/2115473040624554360), [@DYoung_AI](https://x.com/DYoung_AI/status/2115470900808102089)
5. **Collaborate with the researchers.** Dik Rana's experiment and the arXiv 2606.18168 authors measured the problem Latch gates. Offer to run Latch over their dataset and co-publish the result. A third-party number beats a self-reported one.
6. **Sponsor channels.** NVIDIA (Nemotron) and Nebius (Token Factory) both run developer showcases and cookbooks. Latch is a real, cheap, measured Nemotron workload: pitch a cookbook entry "Gate agent PRs with Nemotron for $0.018 a run".
7. **Agent-native distribution.** Ship a Claude Code skill / hook and an MCP tool: "before claiming a fix done, run `latch prove`". The agent itself becomes the install channel.

## Content calendar, first 30 days

| Week | Ship | Post |
|---|---|---|
| 1 | Marketplace listing, release `v0.1.0` | Short launch thread on X and LinkedIn with `hole.svg` as the image |
| 2 | 10 receipts on merged agent PRs from known repos | Blog: "We ran Latch on 10 merged agent PRs. Here is what the tests could not catch." |
| 3 | Claude Code skill and MCP tool | Show HN |
| 4 | Dataset run with an outside researcher | Co-authored write-up; submit to Python Weekly, PyCoder's Weekly, TLDR Dev |

## What to measure

- Action installs (repos with `latch.yml`), receipts generated per week.
- Share of receipts that are `FIX_FAILS_TEST` on PRs that CI marked green: the headline metric, because each one is a bug Latch caught that CI did not.
- Maintainer replies to private receipt shares (target: 1 in 5).

## Pricing path

Free and MIT today, bring your own Token Factory key. When teams ask for it: a hosted runner with a dashboard of receipts across repos, priced per proven PR rather than per seat, since the cost per run is already published.
