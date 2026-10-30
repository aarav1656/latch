/* The gate: a pin tumbler drawn from a receipt. Four pins are the four checks (red on base, green on the fix,
   red again when the fix is reverted, mutants killed). The bolt opens only when the harness verdict is a pass.
   A check the receipt does not carry is drawn dashed and labelled "not recorded", never as held. */
(() => {
  "use strict";
  const SVGNS = "http://www.w3.org/2000/svg";
  const NR = "not recorded";
  const isNum = (x) => typeof x === "number" && isFinite(x);

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function svg(tag, attrs) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
    return n;
  }
  const exitOf = (x) => (x && typeof x.returncode === "number" ? x.returncode : null);

  // receipt -> four pins. Works for prove receipts (base_result) and fix-loop receipts (initial.base_proof).
  function fromReceipt(receipt) {
    const r = receipt && typeof receipt === "object" ? receipt : {};
    const init = r.initial && typeof r.initial === "object" ? r.initial : {};
    const bx = exitOf(r.base_result || init.base_proof);
    const hx = exitOf(r.head_result || init.head_proof);
    const rc = r.revert_check && typeof r.revert_check === "object" ? r.revert_check : null;
    const mu = r.mutation && typeof r.mutation === "object" ? r.mutation : null;

    const base = bx == null ? { state: "unknown", text: NR }
      : bx === 0 ? { state: "stuck", text: "Passes, exit 0" }
      : r.base_failure_is_expected === false ? { state: "stuck", text: "Errors, exit " + bx }
      : { state: "set", text: "Fails, exit " + bx };
    const head = hx == null ? { state: "unknown", text: NR }
      : hx === 0 ? { state: "set", text: "Passes, exit 0" }
      : { state: "stuck", text: "Fails, exit " + hx };
    const revert = !rc ? { state: "unknown", text: NR }
      : rc.ran !== true ? { state: "unknown", text: "Not run" }
      : rc.ok === true ? { state: "set", text: "Fails again" }
      : { state: "stuck", text: "Still passes" };
    let mutants = { state: "unknown", text: NR };
    if (mu && mu.ran === false) mutants = { state: "unknown", text: "Not run" };
    else if (mu && isNum(mu.killed) && isNum(mu.total)) {
      const frac = mu.killed + "/" + mu.total + " killed";
      mutants = mu.incomplete === true ? { state: "unknown", text: frac + ", incomplete" }
        : mu.ok === true ? { state: "set", text: frac }
        : mu.ok === false ? { state: "stuck", text: frac }
        : { state: "unknown", text: frac };
    }
    return [
      Object.assign({ key: "base", name: "Base commit" }, base),
      Object.assign({ key: "head", name: "The fix" }, head),
      Object.assign({ key: "revert", name: "Fix reverted" }, revert),
      Object.assign({ key: "mutants", name: "Mutants" }, mutants),
    ];
  }

  function pinSvg(state) {
    const s = svg("svg", { viewBox: "0 0 64 156", class: "gate-pin-svg", "aria-hidden": "true", focusable: "false" });
    const drop = state === "stuck" ? 26 : 0;  // a stuck pin sits across the shear line
    s.appendChild(svg("rect", { x: 22, y: 6, width: 20, height: 66 + drop, rx: 2, class: "gate-driver" }));
    s.appendChild(svg("rect", { x: 22, y: 80 + drop, width: 20, height: 66 - drop, rx: 2, class: "gate-key" }));
    s.appendChild(svg("line", { x1: 0, y1: 76, x2: 64, y2: 76, class: "gate-shear" }));
    return s;
  }
  const MARK = { set: "Held", stuck: "Stuck", unknown: NR };
  const GLYPH = {
    set: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
    stuck: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    unknown: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"/></svg>',
  };

  // pins: from fromReceipt(); open: the harness verdict is a pass.
  function build(pins, open, opts) {
    const o = opts || {};
    const box = el("div", "gate" + (o.compact ? " is-compact" : ""));
    box.setAttribute("data-state", open ? "open" : "shut");
    box.setAttribute("data-ui", "");
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", "Gate " + (open ? "open" : "shut") + ": " + pins.map((p) => p.name + " " + MARK[p.state].toLowerCase()).join(", "));
    const list = el("ol", "gate-pins");
    pins.forEach((p, i) => {
      const li = el("li", "gate-pin");
      li.setAttribute("data-state", p.state);
      li.setAttribute("data-pin", p.key);
      const mark = el("span", "gate-pin-mark");
      const g = el("span", "gate-glyph"); g.innerHTML = GLYPH[p.state];
      mark.append(g, document.createTextNode(MARK[p.state]));
      li.append(pinSvg(p.state), el("span", "gate-pin-name", (i + 1) + ". " + p.name));
      if (p.text !== NR) li.appendChild(el("span", "gate-pin-text", p.text));
      li.appendChild(mark);
      list.appendChild(li);
    });
    box.appendChild(list);
    const row = el("div", "gate-bolt-row");
    const track = el("div", "gate-track");
    track.setAttribute("aria-hidden", "true");
    track.append(el("span", "gate-keeper"), el("span", "gate-bolt"));
    const state = el("p", "gate-state");
    const lock = el("span", "gate-lock");
    lock.innerHTML = '<svg viewBox="0 0 18 22" width="34" height="42" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (open ? OPEN : SHUT) + "</svg>";
    state.append(lock, el("strong", null, open ? "Gate open" : "Gate shut"),
      el("span", null, open ? "Every pin held, and the harness slid the bolt." : "Only the harness moves the bolt, and a pin is not held."));
    row.append(track, state);
    box.appendChild(row);
    return box;
  }

  const SHUT = '<path d="M5.5 11V7.5a3.5 3.5 0 0 1 7 0V11"/><rect x="3" y="11" width="12" height="9" rx="1.5"/>';
  const OPEN = '<path d="M5.5 8V5.5a3.5 3.5 0 0 1 7 0"/><rect x="3" y="11" width="12" height="9" rx="1.5"/>';
  // total padlocks, the first `openCount` open. tone: colour of the open ones ("pass" or "fail").
  function tally(total, openCount, tone, label) {
    const row = el("div", "tally");
    row.setAttribute("role", "img");
    row.setAttribute("aria-label", label);
    for (let i = 0; i < total; i++) {
      const isOpen = i < openCount;
      const cell = el("span", "tally-cell " + (isOpen ? "is-open is-" + tone : "is-shut"));
      cell.innerHTML = '<svg viewBox="0 0 18 22" width="18" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (isOpen ? OPEN : SHUT) + "</svg>";
      row.appendChild(cell);
    }
    return row;
  }

  window.LatchGate = { fromReceipt, build, tally };
})();
