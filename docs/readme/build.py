"""Draws the README's animated SVGs from the committed receipts.

python3 docs/readme/build.py   # rewrites docs/readme/*.svg

Every figure on a graphic is read from latch/runs/, so a new run redraws them.
Animations are CSS inside the SVG (GitHub renders them through <img>); under
prefers-reduced-motion each graphic shows its final frame.
"""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNS = ROOT / "latch" / "runs"

BG, SURFACE, INSET = "#24201d", "#2e2925", "#1b1815"
LINE, LINE_SOFT = "#4a433d", "#393430"
INK, BODY, MUTED, FAINT = "#f4efe4", "#d8d0c0", "#b2a998", "#948b7c"
ACCENT, ON_ACCENT = "#dfe86a", "#23200f"
PASS, FAIL = "#86dba0", "#ff8f7c"
SANS = "'Mona Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "'Azeret Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

SHUT = '<path d="M5.5 11V7.5a3.5 3.5 0 0 1 7 0V11"/><rect x="3" y="11" width="12" height="9" rx="1.5"/>'
OPEN = '<path d="M5.5 8V5.5a3.5 3.5 0 0 1 7 0"/><rect x="3" y="11" width="12" height="9" rx="1.5"/>'


class Film:
    """One looping timeline: every cue is a CSS keyframe set on a T-second clock."""

    def __init__(self, T):
        self.T, self.css, self.n = T, [], 0

    def p(self, t):
        return f"{max(0.0, min(100.0, t / self.T * 100)):.2f}%"

    def cue(self, t, start, end="none", dur=0.45):
        """Class whose element moves from `start` CSS to its resting style at t, and back at loop end."""
        self.n += 1
        name = f"c{self.n}"
        self.css.append(
            f"@keyframes {name}{{0%,{self.p(t)}{{{start}}}"
            f"{self.p(t + dur)},{self.p(self.T - 0.6)}{{{end}}}100%{{{start}}}}}"
            f".{name}{{animation:{name} {self.T}s cubic-bezier(.2,.7,.2,1) infinite}}"
        )
        return name

    def show(self, t, dy=8):
        return self.cue(t, f"opacity:0;transform:translateY({dy}px)", "opacity:1;transform:none")

    def hide(self, t):
        return self.cue(t, "opacity:1", "opacity:0")

    def style(self):
        return (
            "<style>text{white-space:pre}" + "".join(self.css) +
            "@media (prefers-reduced-motion:reduce){*{animation:none!important}.rm-hide{display:none}}</style>"
        )


def svg(w, h, title, film, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'role="img" xml:space="preserve" aria-label="{escape(title)}"><title>{escape(title)}</title>{film.style()}'
        f'<rect width="{w}" height="{h}" rx="8" fill="{BG}"/>{body}</svg>\n'
    )


def text(x, y, s, size=15, fill=BODY, font=MONO, weight=400, cls="", anchor="start", extra=""):
    c = f' class="{cls}"' if cls else ""
    return (
        f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" fill="{fill}" '
        f'font-weight="{weight}" text-anchor="{anchor}"{c}{extra}>{escape(s)}</text>'
    )


def lock(x, y, open_, color, size=18, cls=""):
    c = f' class="{cls}"' if cls else ""
    s = size / 18
    return (
        f'<g{c} transform="translate({x} {y}) scale({s:.3f})" fill="none" stroke="{color}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{OPEN if open_ else SHUT}</g>'
    )


def short(sha):
    return sha[:7]


def hero():
    r = json.loads((RUNS / "click-3298.json").read_text())
    killed, total = r["mutation"]["killed"], r["mutation"]["total"]
    base_tail = r["verdict_logs"]["base"].strip().splitlines()[-1]
    head_tail = r["verdict_logs"]["head"].strip().splitlines()[-1]
    runs = r["flaky"]["runs"]
    f = Film(12)
    W, H = 1200, 460
    b = []
    b.append(text(48, 64, "PALLETS/CLICK #3299  ·  RECORDED RECEIPT", 12, FAINT, weight=500, extra=' letter-spacing="1.5"'))
    b.append(text(48, 118, "Green is not proof.", 44, INK, SANS, 650, extra=' letter-spacing="-0.8"'))
    b.append(text(48, 156, "Latch opens only when the harness watches a new test", 18, BODY, SANS))
    b.append(text(48, 180, "fail on the bug, pass on the fix, and fail again on revert.", 18, BODY, SANS))

    # terminal
    b.append(f'<rect x="48" y="212" width="560" height="208" rx="4" fill="{INSET}" stroke="{LINE_SOFT}"/>')
    for i, c in enumerate((FAIL, ACCENT, PASS)):
        b.append(f'<circle cx="{68 + i * 16}" cy="230" r="4" fill="{c}" opacity=".55"/>')
    b.append(text(128, 234, "latch prove", 12, FAINT))
    lines = [
        (0.4, [("$ ", FAINT), (f"latch prove --base {short(r['base_sha'])} --head {short(r['head_sha'])}", BODY)]),
        (1.6, [("base    ", FAINT), (short(r["base_sha"]) + "  ", MUTED), ("✗ " + base_tail[:30], FAIL)]),
        (3.0, [("head    ", FAINT), (short(r["head_sha"]) + "  ", MUTED), ("✓ " + head_tail, PASS)]),
        (4.4, [("revert  ", FAINT), ("fix undone  ", MUTED), ("✗ red again", FAIL)]),
        (5.8, [("mutants ", FAINT), ("on the fix  ", MUTED), (f"{killed} of {total} killed", PASS)]),
        (7.2, [("rerun   ", FAINT), (f"{runs}x each   ", MUTED), ("stable", PASS)]),
    ]
    for i, (t, parts) in enumerate(lines):
        y = 272 + i * 24
        spans = "".join(f'<tspan fill="{c}">{escape(s)}</tspan>' for s, c in parts)
        b.append(f'<text x="68" y="{y}" font-family="{MONO}" font-size="14" class="{f.show(t, 4)}">{spans}</text>')
    vy = 272 + 6 * 24 + 6
    b.append(f'<g class="{f.show(8.4, 4)}"><rect x="66" y="{vy - 17}" width="150" height="24" rx="3" fill="{ACCENT}"/>'
             + text(78, vy, r["verdict"], 14, ON_ACCENT, weight=600) + "</g>")

    # tumbler: four pins, one per check, each set onto the shear line in turn
    hx, hy, hw, shear = 670, 70, 400, 236
    b.append(f'<rect x="{hx}" y="{hy}" width="{hw}" height="230" rx="4" fill="{SURFACE}" stroke="{LINE}"/>')
    b.append(f'<rect x="{hx + 16}" y="{shear}" width="{hw - 32}" height="52" rx="26" fill="{INSET}" stroke="{LINE}"/>')
    labels = [("base red", 1.6, -26), ("fix green", 3.0, 20), ("revert red", 4.4, -16), ("mutants", 5.8, 26)]
    for i, (lab, t, dy) in enumerate(labels):
        cx = hx + 70 + i * 88
        b.append(f'<rect x="{cx - 17}" y="{hy + 18}" width="34" height="{shear - hy - 18 + 44}" rx="3" fill="{INSET}" opacity=".7"/>')
        spring = " ".join(f"{cx + (8 if k % 2 else -8)},{hy + 22 + k * 5}" for k in range(9))
        b.append(f'<polyline points="{spring}" fill="none" stroke="{FAINT}" stroke-width="1.5"/>')
        move = f.cue(t, f"transform:translateY({dy}px)", "transform:none", 0.5)
        tint = f.cue(t + 0.3, f"fill:{FAINT}", f"fill:{ACCENT}", 0.3)
        b.append(f'<g class="{move}"><rect x="{cx - 13}" y="{shear - 64}" width="26" height="62" rx="3" fill="{MUTED}"/>'
                 f'<rect x="{cx - 13}" y="{shear + 2}" width="26" height="40" rx="3" fill="{ACCENT}" class="{tint}"/>'
                 f'<path d="M{cx - 13} {shear + 42} l13 10 l13 -10z" fill="{FAINT}"/></g>')
        b.append(text(cx, shear + 92, lab, 12, MUTED, anchor="middle"))
        b.append(f'<g class="{f.show(t + 0.4, 0)}">' + text(cx, shear + 112, "held", 12, PASS, weight=500, anchor="middle") + "</g>")
    b.append(f'<line x1="{hx + 8}" y1="{shear}" x2="{hx + hw - 8}" y2="{shear}" stroke="{ACCENT}" stroke-width="1.5" stroke-dasharray="5 5"/>')
    b.append(text(hx + hw + 8, shear - 8, "shear line", 11, FAINT))

    # bolt and keeper
    ky = shear + 6
    b.append(f'<rect x="{hx + hw + 46}" y="{ky - 10}" width="44" height="60" rx="3" fill="none" stroke="{LINE}" stroke-width="2"/>')
    slide = f.cue(8.4, "transform:translateX(-58px)", "transform:none", 0.36)
    b.append(f'<rect x="{hx + hw - 6}" y="{ky + 6}" width="92" height="28" rx="2" fill="{ACCENT}" class="{slide}"/>')
    shut_w = f.cue(8.4, "opacity:1", "opacity:0", 0.2)
    b.append(f'<g class="{shut_w} rm-hide">' + lock(hx + hw + 18, 360, False, FAIL, 30)
             + text(hx + hw + 60, 390, "SHUT", 22, FAIL, SANS, 650) + "</g>")
    b.append(f'<g class="{f.show(8.5, 6)}">' + lock(hx + hw + 18, 360, True, ACCENT, 30)
             + text(hx + hw + 60, 390, "OPEN", 22, ACCENT, SANS, 650) + "</g>")
    b.append(text(hx, 440, "Each pin is one check from the receipt. Only the harness slides the bolt.", 13, FAINT, SANS))
    (OUT / "hero.svg").write_text(svg(W, H, "Latch proving pallets/click #3299: red on base, green on fix, red on revert, mutants killed, gate open", f, "".join(b)))


def hole():
    r = json.loads((RUNS / "latest.json").read_text())
    ultra = [ln.strip() for ln in r["assertion"].splitlines()[1:] if ln.strip()]
    f = Film(13)
    W, H = 1200, 440
    b = []
    b.append(text(48, 56, "THE HOLE, IN THE BUNDLED FIXTURE", 12, FAINT, weight=500, extra=' letter-spacing="1.5"'))
    b.append(text(48, 98, "Move the line. The agent's tests stay green.", 30, INK, SANS, 650, extra=' letter-spacing="-0.5"'))

    # source pane, the boundary flips at t=2.2
    b.append(f'<rect x="48" y="128" width="500" height="150" rx="4" fill="{INSET}" stroke="{LINE_SOFT}"/>')
    b.append(text(68, 154, "billing.py", 12, FAINT))
    b.append(text(68, 188, "def discount_applies(seats, annual):", 15, BODY))
    b.append(text(68, 214, "    if not annual: return False", 15, MUTED))
    b.append(f'<rect x="64" y="226" width="300" height="26" rx="3" fill="{ACCENT}" opacity=".12" class="{f.show(2.2, 0)}"/>')
    b.append(f'<g class="{f.hide(2.2)} rm-hide">' + text(68, 244, "    return seats >= 10", 15, INK, weight=500) + "</g>")
    b.append(f'<g class="{f.show(2.2, -6)}">' + text(68, 244, "    return seats > 10", 15, ACCENT, weight=500)
             + text(290, 244, "← moved", 12, ACCENT) + "</g>")

    # shipped suite
    tests = [("test_monthly_has_no_discount", False), ("test_twelve_seats_annual", False),
             ("test_three_seats_annual", False), ("test_ten_seats_ran", True)]
    b.append(f'<rect x="580" y="128" width="572" height="150" rx="4" fill="{SURFACE}" stroke="{LINE}"/>')
    b.append(text(600, 154, "shipped suite", 12, FAINT))
    b.append(f'<g class="{f.hide(2.2)} rm-hide">' + text(1132, 154, "on >=   4 passed", 12, PASS, anchor="end") + "</g>")
    b.append(f'<g class="{f.show(2.6, 0)}">' + text(1132, 154, "on >    4 passed, still green", 12, PASS, anchor="end") + "</g>")
    for i, (name, weak) in enumerate(tests):
        y = 184 + i * 24
        b.append(text(600, y, "✓", 14, PASS) + text(624, y, name, 14, FAIL if weak else BODY))
    b.append(f'<g class="{f.show(4.0, 0)}"><rect x="596" y="{184 + 3 * 24 - 17}" width="230" height="24" rx="3" fill="none" stroke="{FAIL}" stroke-width="1.5"/>'
             + text(840, 184 + 3 * 24, "assertIs(applied, applied)", 13, FAIL) + "</g>")

    # Lightning names it, Ultra writes the test that can fail
    b.append(f'<g class="{f.show(4.6)}">'
             + text(48, 320, "LIGHTNING", 12, ACCENT, weight=600, extra=' letter-spacing="1.2"')
             + text(150, 320, "test_ten_seats_ran asserts a value equals itself. It cannot fail.", 15, BODY, SANS) + "</g>")
    b.append(f'<g class="{f.show(6.4)}">'
             + text(48, 356, "ULTRA", 12, ACCENT, weight=600, extra=' letter-spacing="1.2"')
             + text(150, 356, ultra[0], 14, INK) + text(150, 378, ultra[1], 14, INK) + "</g>")
    b.append(f'<g class="{f.show(8.2)}"><rect x="760" y="338" width="190" height="26" rx="3" fill="{FAIL}" opacity=".16"/>'
             + text(772, 356, "✗ AssertionError on >", 13, FAIL, weight=500) + "</g>")
    b.append(f'<g class="{f.show(9.4)}"><rect x="960" y="338" width="192" height="26" rx="3" fill="{PASS}" opacity=".16"/>'
             + text(972, 356, "✓ passes on >= again", 13, PASS, weight=500) + "</g>")
    b.append(f'<g class="{f.show(10.4, 4)}">' + text(48, 418, f"Recorded live: Ultra completion {r['completion_id']}, HTTP {r['http_status']}. The padlock reads Open.", 13, FAINT, SANS) + "</g>")
    (OUT / "hole.svg").write_text(svg(W, H, "The fixture: moving seats >= 10 to seats > 10 leaves the shipped suite green; Latch's new test fails on the moved line and passes on the original", f, "".join(b)))


def pipeline():
    f = Film(10)
    W, H = 1200, 330
    b = []
    stations = [
        ("Issue + PR", "the issue is the oracle", "base and head commits", None),
        ("Lightning", "maps the repo, triages", "the base failure", "Nemotron-3.5-Lightning"),
        ("Ultra", "writes one pytest", "from the issue and diff", "Nemotron-3-Ultra 550B"),
        ("Harness", "base, head, revert,", "mutants, 5x rerun", "no model"),
        ("Receipt", "one named verdict", "and the PR comment", "JSON, every call logged"),
    ]
    x0, bw, gap, y = 48, 196, 30, 120
    b.append(text(48, 52, "MODELS PROPOSE", 12, FAINT, weight=500, extra=' letter-spacing="1.5"'))
    split = x0 + 3 * (bw + gap) - gap / 2
    b.append(text(split + 14, 52, "THE HARNESS DECIDES", 12, ACCENT, weight=600, extra=' letter-spacing="1.5"'))
    b.append(f'<line x1="{split}" y1="36" x2="{split}" y2="300" stroke="{ACCENT}" stroke-width="1" stroke-dasharray="3 5" opacity=".7"/>')
    for i, (name, l1, l2, tag) in enumerate(stations):
        x = x0 + i * (bw + gap)
        t = 0.3 + i * 1.5
        lit = f.cue(t, f"stroke:{LINE}", f"stroke:{ACCENT}", 0.3)
        b.append(f'<rect x="{x}" y="{y - 40}" width="{bw}" height="150" rx="4" fill="{SURFACE}" stroke="{LINE}" stroke-width="1.5" class="{lit}"/>')
        b.append(text(x + 18, y - 12, f"0{i + 1}", 12, FAINT))
        b.append(text(x + 18, y + 22, name, 24, INK, SANS, 650))
        b.append(text(x + 18, y + 54, l1, 14, BODY, SANS))
        b.append(text(x + 18, y + 74, l2, 14, BODY, SANS))
        if tag:
            b.append(text(x + 18, y + 98, tag, 11, ACCENT if i >= 3 else MUTED))
        if i < len(stations) - 1:
            ax = x + bw + 2
            flow = f.cue(t + 0.4, f"opacity:.25", "opacity:1", 0.3)
            b.append(f'<g class="{flow}"><line x1="{ax}" y1="{y + 35}" x2="{ax + gap - 8}" y2="{y + 35}" stroke="{ACCENT}" stroke-width="2"/>'
                     f'<path d="M{ax + gap - 10} {y + 29} l7 6 l-7 6" fill="none" stroke="{ACCENT}" stroke-width="2"/></g>')
    b.append(f'<g class="{f.show(7.4, 4)}">' + text(48, 290, "A model response alone never opens the gate. A timeout, import error or crash leaves the receipt unproven.", 14, MUTED, SANS) + "</g>")
    (OUT / "pipeline.svg").write_text(svg(W, H, "Latch pipeline: issue and PR, Lightning maps and triages, Ultra writes one test, the harness runs base, head, revert and mutants, the receipt carries one verdict", f, "".join(b)))


def scoreboard():
    s = json.loads((RUNS / "eval-summary-repair.json").read_text())
    bm = s["benchmark"]
    wrong, real = bm["wrong_patch_rejection"], bm["real_validated"]
    accepted = wrong["n"] - wrong["k"]
    mut, nofix, fl = bm["mutation"], bm["nofix_gate_open"], s["flaky"]
    f = Film(11)
    W, H = 1200, 400
    b = []
    b.append(text(48, 56, f"{bm['runs']} LIVE RUNS ON NEBIUS TOKEN FACTORY  ·  latch/runs/eval-summary-repair.json", 12, FAINT, weight=500, extra=' letter-spacing="1.5"'))

    def block(x, label, big, total, opened, tone, t0, note):
        out = [text(x, 100, label, 14, MUTED, SANS, 500), text(x, 176, big, 72, INK, SANS, 650, extra=' letter-spacing="-2"')]
        per_row = 11
        for i in range(total):
            cx, cy = x + (i % per_row) * 30, 210 + (i // per_row) * 36
            is_open = i < opened
            out.append(lock(cx, cy, is_open, tone if is_open else FAINT, 22, f.show(t0 + i * 0.12, 6)))
        out.append(text(x, 210 + ((total - 1) // per_row + 1) * 36 + 18, note, 13, FAINT, SANS))
        return "".join(out)

    b.append(block(48, "Wrong patches accepted", f"{accepted} / {wrong['n']}", wrong["n"], accepted, FAIL, 0.3,
                   f"{wrong['by_valid_test']['k']} of {wrong['n']} failed by a valid proof test; the rest kept the gate shut"))
    b.append(block(440, "Real fixes proven", f"{real['k']} / {real['n']}", real["n"], real["k"], PASS, 1.8,
                   "red on base, green on fix, suite green, stable, revert and mutants"))
    b.append(f'<line x1="830" y1="80" x2="830" y2="360" stroke="{LINE_SOFT}"/>')
    side = [
        (f"{mut['mutants_killed']} / {mut['mutants_total']}", f"mutants killed across the {mut['runs_with_data']} fixes mutated"),
        (f"{nofix['k']} / {nofix['n']}", "gates opened on a Nemotron fix the hidden tests reject"),
        (f"{fl['n_flaky']} / {fl['n_cases_checked']}", "proof tests flaky on rerun"),
        (f"${bm['cost_usd']:.2f}", f"for all {bm['runs']} runs, {bm['model_calls']} model calls"),
    ]
    for i, (n, lab) in enumerate(side):
        y = 116 + i * 68
        b.append(f'<g class="{f.show(5.2 + i * 0.6)}">' + text(862, y, n, 32, ACCENT if i == 0 else INK, SANS, 650)
                 + text(862, y + 24, lab, 13, MUTED, SANS) + "</g>")
    (OUT / "scoreboard.svg").write_text(svg(W, H, f"Results: {accepted} of {wrong['n']} wrong patches accepted, {real['k']} of {real['n']} real fixes proven, {mut['mutants_killed']} of {mut['mutants_total']} mutants killed, ${bm['cost_usd']:.2f} for {bm['runs']} runs", f, "".join(b)))


if __name__ == "__main__":
    hero()
    hole()
    pipeline()
    scoreboard()
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.svg"))))
