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

## CSP

`style-src 'self'` plus Google Fonts: no inline `<style>` and no `style=""` attributes in HTML. Setting
`el.style.x` from JS is allowed. Scripts are `'self'` only, no inline scripts except the
`application/json` boot block.
