# Latch web redesign, 2026-10-29

Scope: `latch/web/` only. Goal: a UI that does not look like CAPE (light zinc, cool neutrals) and makes the verdict the hero.

## Verbs (what the page does for a visitor)
1. Paste a PR link. 2. See at once whether the fix is PROVEN or NOT PROVEN. 3. Check the evidence: the test written from the issue, and that same test failing on base and passing on head. 4. Share or download the receipt. 5. (Second tab) watch the fix loop keep the gate shut or open it.

## Steal list (taken from the research in /workspace/yt-research and the ui-craft references)
- One hero moment, sized for it: the verdict word at 56-88 px, tracking -0.02em, nothing else competes.
- Tinted neutrals (warm graphite), never pure black, never generic grey; semantic colour only on pass/fail; one accent.
- Ruled rows instead of cards in cards; borders over shadows; tabular-nums for every hash, count and time.
- Plain-English copy: say what happened ("The test failed on the base commit and passed on the head"), no jargon labels, no tiny all-caps eyebrows.
- State is visible without hover. Contrast computed, not eyeballed (matrix below). Motion only transform/opacity, reduced motion honoured.
- Three type sizes (verdict / body / mono small), hierarchy from weight, family and colour.

Where this departs from the skill text: the ui-craft default says "zinc/slate neutrals". That is the CAPE light spec. For Latch the brief is distinct, so neutrals are hue-70 warm graphite with chroma 0.008-0.012 (tinted, still not "default grey"). Recorded here so it is a decision, not drift.

## Three directions sketched
- **A. Evidence ledger (picked).** Dark warm graphite. A bordered verdict slab with the verdict as the hero, then a two-column ledger: the generated test on the left (line-numbered mono), base result stacked over head result on the right, facts as ruled key/value rows.
- **B. Docket / court record.** Warm dark paper tone, serif verdict stamped like a ruling, numbered exhibits (1 issue, 2 test, 3 base run, 4 head run) in a single column. Strong metaphor, but it needs a fourth font family and a long single column that buries the base/head pair below the fold.
- **C. CI console.** Mono-first pipeline strip (fetch, generate, base, head, verdict) over dense panes. Fits developers, but looks like every CI dashboard and makes the verdict one status chip among many.

## Pick and why
A. The product's whole claim is "the same test fails before and passes after", so the layout puts exactly that pair next to the test in mono, and the verdict is the largest thing on the screen. It needs no extra font, reads at 390 px by stacking in the same order, and it is visibly not CAPE (dark, warm, brass accent, ledger rules).

## Tokens
See `latch/web/DESIGN.md`. Contrast matrix (WCAG ratio, computed with OKLCH to sRGB in `/workspace/latch-redesign/contrast.py`):

| text colour | on bg | on surface | on inset |
| --- | --- | --- | --- |
| ink | 15.0 | 13.4 | 16.2 |
| muted | 7.8 | 6.9 | 8.4 |
| faint | 5.1 | 4.6 | 5.5 |
| pass | 10.2 | 9.1 | 10.9 |
| fail | 7.1 | 6.3 | 7.6 |
| accent | 10.5 | 9.4 | 11.3 |

Button text (bg on accent) 10.5. Every pair is at least 4.5.

## Hero moment
The verdict word (PROVEN in green, NOT PROVEN in red) at clamp(3rem, 9vw, 5.5rem), left aligned inside a bordered slab with a one-sentence reason and the receipt source. In the fail-closed state the slab says what was rejected and that no test was run.


## Reference critique (2026-10-30)

Read: Linear, Vercel, Mercury and Stripe DESIGN.md files (VoltAgent/awesome-design-md, copies in `refs/`), plus the uxkin no-ui-slop rules and the taste-skill "deal three, pick one" method. What each says about the current Latch page and what we took.

| Source | What it does well | Latch before | Latch now |
|---|---|---|---|
| Linear | A surface ladder separated by 1px hairlines, one accent, the product itself is the picture. | Light page, cobalt blue, bordered fact grid, soft shadows. | `--bg`, `--surface`, `--inset` ladder, hairlines only, one amber accent, the receipt is the hero. |
| Vercel | Mono for everything that is a machine value, type scale kept small. | Mono used for labels, not for evidence. | Mono and tabular-nums for commits, test, exit codes, token counts, cost. |
| Mercury | One solid primary action per group, quiet secondary buttons. | Four equal buttons under the receipt. | One primary per group (`Prove it`, `Copy permalink`), the rest ghost. |
| Stripe | Tabular numerals in every table, honest empty states. | Facts in a 4 column grid with small caps labels. | Ledger rows, a `not recorded` literal when a number is absent. |
| uxkin | Design every state, never invent data. | Success and error only. | Recorded, cached, live, queued, running, paused (credits), not proven, fail-closed, error, eval pending. |
| taste-skill | Three directions, pick one, check at three widths. | One direction, no width check at 390. | Three sketched, A picked, shots at 1440/768/390 per change. |

Slop we removed from the old page: tiny all-caps eyebrow ("ISSUE-ANCHORED PROOF"), light-blue wash, a heavy bordered fact grid, badge text at 10px, a button row of equal weight, hover-only titles.

## Honesty rules (from the 2026-10-30 scorecard)

1. A banner can never contradict the card. `/r/<owner>/<repo>/<issue number>` redirects (302, no-store) to the PR receipt that closes it, so `/r/pallets/click/3298` lands on #3299. Commit `d3b6f59`, tests `IssueNumberTests`.
2. No horizontal overflow at 390px. Playwright asserts `scrollWidth <= clientWidth` for every scene at 390 (see Verification).
3. Credits exhausted (HTTP 402) is a state, not an error. `LATCH_CREDITS_EXHAUSTED=1` starts the app with live runs paused; `/api/config` reports live off with the reason, the recorded receipt and the loop example still load, and the page shows a calm "Live runs are paused: model credits" note. Tests `CreditsExhaustedAtStartTests`.
4. The Click receipt is labelled Recorded, with its recorded date and completion id `chatcmpl-99d6e5a92020c804`. A POST of #3299 returns the cached receipt and the UI says cached, never live. No "16.1 s live" claim exists in the repo (searched README, site, research); the one timing sentence in `latch/web/README.md` is about an emulated amd64 container and is a measured note, not a receipt claim.

## Engine contract the site reads (latch-loop, 2026-10-30)

Receipts may carry `model_calls[]` (`role` repo_map|triage|test_writer|fixer, `model`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `completion_id`, `cost_usd`, `status`), `model_cost_usd`, `repo_map`, `triage`, `revert_check`. Step events are `{step, status started|done|failed, ts, detail}` for `fetch, repo_map, test_writer, base_run, head_run, triage, fix, revert_check, verdict`. The site maps them to a step ledger and never fills a gap: the committed Click receipt (`latch/runs/click-3298.json`) predates all of them, so its model panel says `not recorded` for tokens, latency and cost.

Eval page source: `latch/runs/eval-summary.json` (`upstream`, `swebench_lite`, `wrong_fixes`, `median_wall_s`, `median_cost_usd`, `baselines` with sources, `caveat`, `cases[]`, `featured_wrong_fix_receipt`). File absent today, so `/eval` shows "eval pending". Baselines (Otter 31.4%, AssertFlip 43.6%) are shown with their sources and the caveat that the benchmarks differ and are not like for like.


## What shipped (2026-10-30)

Pages: `/` (landing, paste a PR, live step ledger, receipt, recent proofs, Fix loop tab), `/r/owner/repo/pr` (permalink, copy button), `/eval` (evidence, reads `/api/eval`), `/ship` (CLI and GitHub Action). Shared tokens in `tokens.css`, primitives in `app.css`, system in `latch/web/DESIGN.md`.

Eval schema v1 (`latch/loop/eval/RESULTS.md`) is read exactly: `wrong_fixes {n, caught, without_contested}` is the hero, then suites (`upstream`, `swebench_lite`, `nemotron_fix`), medians (null renders `not recorded`, cost labelled an upper bound), baselines with `source_url` (https and an allow list of hosts), `comparison`, `caveat`, `featured_wrong_fix_receipt`, failures, abstentions, validator rejections, not run, and every case. With no file the page says `Eval pending` plus the published Otter 31.4% and AssertFlip 43.6% rows and the "not like for like" caveat. The layout was checked with a synthetic fixture marked LAYOUT FIXTURE in `/tmp`, never committed.

## Verification

- Shots at 1440, 768 and 390 for: first screen (recorded Click), `/r/pallets/click/3298` redirect, credits paused, not proven fail-closed, not proven head fails, proven with retry note, live progress, fix loop (recorded and live), `/eval` pending and with a fixture, `/ship`. 36 images in `/workspace/latch-redesign/after/`; before images in `/workspace/latch-redesign/before/`.
- Every scene asserts `scrollWidth <= clientWidth` at 390 and collects console messages: no horizontal overflow, no console errors in the final run. The redirect scene fails if the page says "No saved receipt" or lacks the Recorded label and `chatcmpl-99d6e5a92020c804`.
- Overflow bugs found and fixed on the way: CSS grids with an `auto` column grew to the width of a `pre` or table (fixed with `minmax(0, 1fr)`), and long diff lines in the loop timeline.
- `slop-check.sh` exits 0 (two warnings: font family set through a CSS variable, and a web3 explorer link that does not apply).
- Tests: `python3 -m pytest -q` from the repository root, 209 passed, 3 skipped at the last full run (211 collected; `python3 -m unittest discover -s latch -t .` runs 192). Web only: `python3 -m pytest -q latch/web`, 72 passed, 1 skipped. The judge's 81 is not reproduced by any of these commands.
- Image: `latch-web:amd64` rebuilt for linux/amd64, saved to `/mnt/data/nvdia/latch/latch-web-amd64.tar`, reloaded from the tar and smoke tested with `LATCH_LIVE=0`: `/healthz`, `/`, `/eval`, `/ship`, `/api/*`, `/r/pallets/click/3298` and the static files all 200. A first rebuild exposed that `Dockerfile.dockerignore` excluded `tokens.css` through the `*token*` secrets rule; fixed and covered by `ImageContextTests`.

## Review rounds

An earlier pass was a self review. On 2026-10-30 a genuine fresh-context external review was run: `codex exec --ephemeral --ignore-user-config --ignore-rules -s read-only` from an empty directory, given only eight screenshots (first, eval_pending, ship, notproven_failclosed at 1440 and 390), the slop bans and the evidence-ledger direction. No repo, env or secrets were passed. Two rounds, scores 6/10 then 6.5/10.

Round 1 critiques and what was done:

1. Verdict arrives late on receipt pages (form above it). Declined: the verdict is inside the first viewport at 1440 and 390; moving the form would be a restructure.
2. Model accounting table fragments at 390. Fixed: tables under 40rem become one labelled block per row (`data-label`, `.ledger-table.stack`).
3. Evidence table on /eval clipped at 390 ("Reporte d"). Fixed by the same stacking.
4. Test and failure panes look cut off. Partly fixed: code panes get a visible thin scrollbar; the 26rem cap stays on receipts.
5. No compact proof summary. Declined: base and head results already sit side by side directly under the verdict.
6. Secondary text too small and dim. Fixed: `--t-small` 13px to 14px, `--muted` lightened.
7. "Eval pending" is as loud as a verdict. Fixed: a restrained status block, duplicated sentence removed.
8. Ship page workflow truncated. Real bug found: `.pane pre` had `max-height: 26rem`, which clipped the YAML. Fixed: no cap on the ship page.
9. "Exceeds three type sizes". Declined: three tokens are used (`--t-hero`, `--t-base`, `--t-small`).

Round 2 (fresh session, new screenshots) raised: provenance beside the verdict, collapse accounting, expandable code panes, flat heading hierarchy, dim secondary data, workflow dominates /ship, competitor numbers outweigh Latch's pending state, inconsistent measures across pages, ambiguous fix-loop tab label. Not acted on (cap of two rounds, and each is a layout restructure or taste call): the action bar move, a details wrapper for accounting, expand controls, the shared shell width, the tab sub-label. Kept as follow-ups.

Live PR runs: `latch.github_pr.run_pull_request` now accepts `on_step_event=None` and forwards it to `prove()` (additive; `runner=` and `on_step` unchanged; test in `latch/test_github_pr.py`). The web service already passed the callback when the runner accepts it, so live runs now stream `step_event`s into the ledger. The engine's own `fetch` events arrive after the legacy hints, so `app.js` resets the ledger on the first engine event.

Recent proofs: only real receipts in the store are listed. In the built image `/data` is an empty volume and `/api/recent` returns only the recorded Click seed; no file under `/app` or `/data` contains "acme". `ImageContextTests` asserts `latch/web/.data` and test files are ignored and that no shipped file mentions the screenshot fixture. The acme/widgets entries in screenshots come from the dev fixture server, not the image; the `first` screenshots now use a bare server.

Tests at the end: `pytest -q` 213 passed, 3 skipped; `unittest discover` 197 tests OK (skipped=3).

Known gaps: `latch/runs/eval-summary.json` is absent so `/eval` is pending; the committed Click receipt has no `model_calls`; set `LATCH_CREDITS_EXHAUSTED=1` in production while credit is out.
