---
name: Latch web, evidence ledger
direction: A (evidence ledger), dark warm graphite
colors:
  bg: "oklch(20.5% 0.008 70)"
  surface: "oklch(25% 0.009 70)"
  inset: "oklch(16.5% 0.008 70)"
  line: "oklch(35% 0.010 70)"
  ink: "oklch(94% 0.008 85)"
  muted: "oklch(74% 0.012 80)"
  pass: "oklch(80% 0.15 155)"
  fail: "oklch(74% 0.17 28)"
  accent: "oklch(83% 0.12 82)"
typography:
  hero: { family: "Space Grotesk 600", size: "clamp(3rem, 9vw, 5.5rem)", tracking: "-0.02em" }
  base: { family: "Source Sans 3 400/600 (headings Space Grotesk 600)", size: "17px" }
  small: { family: "JetBrains Mono 400/500", size: "13px", features: "tabular-nums" }
rounded: { all: "4px" }
---

# Latch web design: evidence ledger

Latch's claim is one sentence: the test written from the issue fails before the fix and passes after it.
The page is built to make that sentence checkable at a glance. The verdict is the hero. The generated
test and the base/head result pair sit side by side in mono. Everything else is a ruled ledger row.

## Rules

- Three type sizes only: `--t-hero` (verdict, one hero number per page), `--t-base` (17px, body and
  headings, headings are weight 600 Space Grotesk), `--t-small` (13px mono, tabular-nums, for code,
  hashes, numbers, meta). No tiny all-caps eyebrows; labels are sentence case.
- Colour is meaning. `--pass` and `--fail` appear only on pass/fail facts. One accent (`--accent`, brass)
  for the single primary action per group and focus rings. Nothing else is coloured.
- Surfaces: `--bg` page, `--surface` raised panes, `--inset` code. Separation by 1px hairlines
  (`--line`), not shadows. No nested cards, no glass, no gradients, no bento grids.
- Radius 4px everywhere. Motion is transform/opacity only, short, and off under
  `prefers-reduced-motion`. Nothing is hover-only. No timed fade-ins. No emoji.
- Every number that is not in the data renders as "not recorded". Never invent a value.

## Page chrome (all pages)

```html
<a class="skip" href="#main">Skip to content</a>
<header class="bar"><div class="bar-in">
  <a class="mark" href="/">Latch</a>
  <nav class="nav" aria-label="Pages">
    <a href="/">Prove a PR</a><a href="/eval">Evidence</a><a href="/ship">Use in CI</a>
  </nav>
</div></header>
<main id="main" class="page"> ... </main>
<footer class="foot"> ... </footer>
```
The current page gets `aria-current="page"`. Stylesheets, in order: `/static/tokens.css`, `/static/app.css`,
then the page file (`loop.css` on `/`, `eval.css` on `/eval`, `ship.css` on `/ship`). Page files define
only classes prefixed by their page (`tl-`, `eval-`, `ship-`) and use tokens plus the shared primitives.

## Shared primitives (defined in app.css)

`.btn` (neutral, bordered), `.btn.primary` (accent fill, one per group), `.btn.ghost`; `.section`
with `.section-title`; `.lede` (62ch measure); `.mono` and `.num` (13px mono, tabular-nums); `.hint`
(muted small); `.rows` (ruled key/value list: `.rows > .row > dt + dd`); `.pane` (inset code pane,
`.pane-head` + `pre`); `.verdict` slab with `.verdict.is-pass`, `.verdict.is-fail`; `.pill.pass`,
`.pill.fail` (bordered, text + icon, never colour alone); `.ledger-table` (ruled table, right-aligned
tabular numbers); `.hero-num` (hero size, for the single headline figure on a page).

## Verdict, rerun check and mutation check (receipt contract, `latch/verdict.py`)

The harness decides the verdict; the page only displays it. `static/verdict.js` is the single place that
maps a receipt to a headline, a one-line meaning and pass or fail (`window.LatchVerdict.info`). There are six
verdicts, in the harness precedence order: INVALID_TEST, FLAKY, NO_REGRESSION_FOUND, FIX_FAILS_TEST,
MUTATION_SURVIVED, VALIDATED. Only VALIDATED is a pass. Each fail has its own plain-English meaning line plus
the harness `verdict_reason`; colour stays pass/fail, never one hue per verdict. FIX_FAILS_TEST is where wrong
patches land, so it is what the wrong-fix demo (the /eval featured receipt and the fix-loop `gate_shut`
pill) shows. A verdict that disagrees with `proven`, or one the page does not recognise, fails closed.
Receipts without `verdict` render as before (Proven / Not proven), with the rerun and mutation sections
"not run".

- Base and head panes show the `verdict_logs.base` and `verdict_logs.head` tails; `verdict_logs.flake` folds
  into a "Flake log" disclosure.
- "Rerun check" (`receipt.flaky`) shows runs, base fail rate, head pass rate and flake rate in tabular
  numerals, plus the per-run outcomes and the note. `ran` false or absent shows "not run".
- "Mutation check" (`receipt.mutation`) shows `killed/total`, the percentage only when `kill_rate` is a number
  (null is "not recorded", and with `ok` false it reads as could not complete), the threshold, what each
  mutant changed, and the note. Survivors come first (`.mutant.is-survived`: fail rule on the left edge, diff
  visible); killed mutants fold their diff away.
- "Tautology check" (`receipt.tautology`, `latch/tautology.py`) comes first, since it runs before any test: changed
  symbols, asserted symbols, callers affected and mode, with "rejected before any run" in the fail colour and the
  reason quoted (it starts with `tautology check: `) when `ok` is false. The unchecked placeholder has no
  `affected_symbols` or `mode`, so every key is optional; an absent `tautology` reads "not run".
- /eval (summary schema v2, v1 still loads): a Verdicts section with the summary's own `verdicts` counts (v1:
  counted from `cases[].verdict`), cases rerun, flaky cases, median flake rate (top-level `flaky`), the pooled
  mutant kill rate (`benchmark.mutation.pooled_kill_rate`), a Benchmark totals section, a Run details section
  (`latch_git_sha`, `dropped_cases` with each reason), and a Verdict and Rerun column on the cases table. A case
  with `verdict_source: "derived"` says "derived from the receipt"; `loop_verdict` (gate_open, gave_up, error)
  is shown as "loop result", never as a verdict. In v1 `verdict` held the loop result, so a value that is not
  one of the six is shown as the outcome text.
- Never shown on /eval: `oracle_baseline` (the no-model answer key, 100% by construction; the API strips it),
  `slopgate_comparison` (third-party numbers on a different task), and any summary with `mode` other than
  `live`, `fixture: true`, `dev_only: true` or a provider other than Token Factory / Nebius.
- The `mutation` step event detail is `{killed, total, kill_rate}`; the `verdict` step event is
  `{verdict, reason}`. Fix-loop events carrying `verdict` or `verdict_code` get a verdict pill.
- Fixtures for all of this are built from the real `latch.verdict` in `test_verdict.py`.

## What the site reads from `latch/runs/`

Fixed paths only, nothing is globbed: `click-3298.json` (the recorded example), `loop-demo-events.jsonl`,
`eval-summary.json`, and the one receipt that `eval-summary.json` names under `eval/`. `latch/runs/dev/`,
`latch/runs/eval-dryrun*/` and `eval-oracle-baseline.*` are never read and are excluded from the Docker context.
Receipts and summaries with `dev_only: true`, or a `provider` other than `tokenfactory` or `nebius`, are skipped
by the store, the gallery, the fix-loop example and /eval (`provenance.py`). A record that names no provider is
accepted. `test_eval_v2.py` pins each of these.

## CSP

`style-src 'self'` plus Google Fonts: no inline `<style>` and no `style=""` attributes in HTML. Setting
`el.style.x` from JS is allowed. Scripts are `'self'` only, no inline scripts except the
`application/json` boot block.
