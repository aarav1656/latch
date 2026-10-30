---
name: Latch web, the shear line
direction: Warp (agentic terminal, warm charcoal) adapted into a hardware-lock register. Replaces the earlier evidence-ledger system.
macrostructure: "Tumbler gate (headline and PR form left, a four-pin tumbler drawn from the recorded receipt right, evidence scoreboard strip below, receipt as a stacked sheet)"
colors:
  bg: "#24201d"
  surface: "#2e2925"
  inset: "#1b1815"
  line: "#4a433d"
  line-soft: "#393430"
  ink: "#f4efe4"
  body: "#d8d0c0"
  muted: "#b2a998"
  faint: "#948b7c"
  accent: "#dfe86a"
  on-accent: "#23200f"
  pass: "#86dba0"
  pass-field: "#1d3b2b"
  fail: "#ff8f7c"
  fail-field: "#4b2520"
typography:
  display: { family: "Mona Sans (variable, wdth 112-125, wght 560-660), self-hosted", tracking: "-0.02em", use: "h1, verdict word, hero figures" }
  body: { family: "Mona Sans wdth 100, wght 400/560", size: "17px / 1.55" }
  mono: { family: "Azeret Mono 400/500 (the face Warp loads), self-hosted", size: "13px", use: "code, receipts, hashes, numbers, nav and button labels", features: "tabular-nums" }
  scale: "12 / 13 / 15 / 17 / 22 / 32 / 56-88 (hero, clamp)"
rounded: { control: "3px", panel: "4px", pill: "none" }
spacing: "4 / 8 / 12 / 16 / 24 / 32 / 48 / 72 / 112"
---

# Latch web design: the shear line

Latch's argument is a padlock only the harness can open. A pin tumbler lock opens when every pin sits on the
shear line. Latch's four pins are the four checks: red on the base commit, green on the fix, red again when the
fix is reverted, mutants killed. The first screen draws that lock from the recorded Click receipt, and the
same drawing is the spine of every receipt and of the evidence page.

## Decisions

- **Surface**: warm charcoal `--bg`, raised panels one tone step up (`--surface`), code and terminals one step
  down (`--inset`). Never pure black, never white. Separation is a tone step, not a box around everything.
- **Ink**: cream `--ink` for headings and numbers, `--body` for running text, `--muted` and `--faint` for
  secondary notes (both clear 4.5:1 on `--bg`).
- **One accent**: `--accent` (citron, the colour of a machined brass bolt catching light). It is the primary
  action, focus ring, the open bolt and links. Nothing else is coloured.
- **Verdict colours are meaning only.** Green (`--pass`) means a check passed or a case was proven. Red
  (`--fail`) means a check failed or a patch is not proven. They appear as flat fields and as the pins.
  Colour is never the only signal: every state also has a word and a glyph.
- **Type**: Mona Sans carries display and body (width axis does the display work, no second family), Azeret
  Mono carries code, receipts, numbers and the small control labels (Warp sets its nav and buttons in a
  mono). All figures are tabular. Fonts are self-hosted from `/static/fonts` (CSP `font-src 'self'`).
- **Shape**: 3px radius controls, 4px panels, no pills, no glow, no gradients, no shadows at rest.
- **Motion**: one move, the bolt sliding into the keeper when a receipt opens, `transform` only, 360ms,
  removed under `prefers-reduced-motion`. Buttons press with a 1px translate.

## Macrostructure

1. **Bar**: the Latch mark (a bolt in a keeper) and the wordmark, the three pages in mono caps, the current
   page marked with `aria-current="page"`.
2. **First screen** (`/`): left, the claim in display type and the PR form (one primary action) with the link
   to the recorded Click receipt. Right, the tumbler for pallets/click #3299 drawn from the recorded receipt.
   Under it, the scoreboard: wrong patches accepted and real fixes proven, read from `/api/eval`.
3. **Receipt**: a flat verdict field (green or red) beside the tumbler for that receipt, then the generated
   test and the base and head terminals, then the mutation cells, rerun, tautology, models and the rest.
4. **Evidence** (`/eval`): two huge standalone figures with tally strips (nine wrong patches, 21 real fixes),
   then the tables.
5. **Use in CI** (`/ship`): two columns on desktop, instructions left, the code pane right.

## Primitives

`.btn` (mono caps 13px, 3px radius), `.btn.primary` (accent fill), `.btn.ghost` (outline); `.section` and
`.section-title`; `.lede`; `.hint` (sans, muted); `.mono` and `.num`; `.rows` (key and value); `.pane` (a
terminal: `.pane-head` plus `pre`); `.verdict` (flat field, `.is-pass`, `.is-fail`); `.pill.pass`, `.pill.fail`
(glyph plus word); `.ledger-table`; `.gate` (the tumbler, built by `gate.js` from receipt fields).

## Honesty labels kept

"Recorded run", "Cached receipt", "Live run" and "not recorded" are produced by the same code as before.
A pin whose check is missing from the receipt is drawn dashed and labelled "not recorded", never as passed.
