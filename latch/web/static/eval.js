(() => {
  "use strict";
  const root = document.getElementById("eval-root");
  const NR = "not recorded";
  const HOSTS = ["arxiv.org", "github.com", "tokenfactory.nebius.com"];
  function el(tag, cls, text, attrs) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    if (attrs) for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  }
  function safeLink(url, label) {
    try {
      const u = new URL(url);
      if (u.protocol === "https:" && HOSTS.includes(u.hostname)) return el("a", null, label || url, { href: u.href, target: "_blank", rel: "noopener noreferrer" });
    } catch (_) { /* fall through */ }
    return el("span", null, label || NR);
  }
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const pct = (x) => (isNum(x) ? (x * 100).toFixed(1) + "%" : NR);
  const int = (x) => (isNum(x) ? String(x) : NR);
  const frac = (a, b) => (isNum(a) && isNum(b) ? a + " of " + b : NR);
  const usd = (x) => (isNum(x) ? "$" + x.toFixed(4) : NR);
  const secs = (x) => (isNum(x) ? x.toFixed(1) + " s" : NR);
  function section(title, ...kids) {
    const s = el("section", "section");
    s.appendChild(el("h2", "section-title", title));
    kids.forEach((k) => k && s.appendChild(k));
    return s;
  }
  function rows(pairs) {
    const dl = el("dl", "rows");
    pairs.forEach(([k, v, mono]) => {
      const r = el("div", "row"); const dt = el("dt", null, k); const dd = el("dd", mono ? "mono" : null);
      if (v instanceof Node) dd.appendChild(v); else dd.textContent = v;
      r.append(dt, dd); dl.appendChild(r);
    });
    return dl;
  }
  function table(headers, body, rightFrom) {
    const wrap = el("div", "eval-scroll"); const t = el("table", "ledger-table stack");
    const hr = el("tr");
    headers.forEach((h, i) => hr.appendChild(el("th", rightFrom != null && i >= rightFrom ? "r" : null, h)));
    const th = el("thead"); th.appendChild(hr); t.appendChild(th);
    const tb = el("tbody");
    body.forEach((cells) => {
      const tr = el("tr");
      cells.forEach((c, i) => { const td = el("td", rightFrom != null && i >= rightFrom ? "r" : null); if (c instanceof Node) td.appendChild(c); else td.textContent = c; td.setAttribute("data-label", headers[i] || ""); tr.appendChild(td); });
      tb.appendChild(tr);
    });
    t.appendChild(tb); wrap.appendChild(t);
    return wrap;
  }

  const PUBLISHED = [
    { name: "Otter (GPT-4o)", metric: "fail-to-pass", value: 0.314, benchmark: "TDD-Bench-Verified, 449 issues", source_url: "https://arxiv.org/abs/2502.05368", note: "Otter++ reaches 37.0%" },
    { name: "AssertFlip", metric: "fail-to-pass", value: 0.436, benchmark: "SWT-Bench-Verified, 189 of 433", source_url: "https://arxiv.org/abs/2507.17542", note: "" },
  ];
  const CAVEAT = "These are not like-for-like. The benchmarks differ, and Latch's proven also needs a green repository suite and a revert check that fails the test again without the fix.";

  function baselines(summary) {
    const list = summary && Array.isArray(summary.baselines) && summary.baselines.length ? summary.baselines : PUBLISHED;
    const body = list.map((b) => [b.name || NR, b.metric || NR, isNum(b.value) ? pct(b.value) : NR, b.benchmark || NR, safeLink(b.source_url, "source")]);
    const nodes = [table(["System", "Metric", "Reported", "Benchmark", "Source"], body, 2)];
    nodes.push(el("p", "lede", (summary && (summary.comparison || "")) || ""));
    nodes.push(el("p", "hint", (summary && summary.caveat) ? summary.caveat : CAVEAT));
    return section("Against published numbers", ...nodes.filter((n) => n.textContent !== "" || n.tagName === "DIV"));
  }

  function pendingView(reason) {
    const hero = el("section", "eval-hero");
    hero.append(el("h2", "eval-state", "Eval pending"), el("p", null, String(reason || "The evaluation summary has not been committed yet.").replace(/^Eval pending:\s*/i, "")));
    hero.appendChild(el("p", "eval-sub", "No Latch number is shown because none exists yet. Model credit ran out before the run (Token Factory HTTP 402)."));
    const demo = section("What exists today",
      rows([
        ["Wrong-fix demo", (() => { const a = el("a", null, "Open the recorded fix loop", { href: "/#fix-loop" }); return a; })()],
        ["Recorded proof", (() => { const a = el("a", null, "Click PR 3299, a recorded receipt", { href: "/r/pallets/click/3299" }); return a; })()],
      ]),
      el("p", "hint", "The fix loop is a recorded run on a constructed demo. It is not an upstream result and not part of the eval."));
    root.replaceChildren(hero, demo, baselines(null));
  }

  function suiteRow(name, s) {
    return [name, int(s && s.n), int(s && s.proven), pct(s && s.proven_rate), int(s && s.errors), int(s && s.not_run)];
  }

  function featured(data) {
    const s = data.summary || {}, f = data.featured;
    const box = el("div", "eval-featured");
    if (s.featured_wrong_fix_note) box.appendChild(el("p", null, s.featured_wrong_fix_note));
    if (f && f.receipt) {
      const r = f.receipt, m = f.meta || {};
      const vi = window.LatchVerdict.info(r, m);
      const proven = vi.pass;
      const line = el("div", "verdict-line");
      const p = el("span", "pill " + (proven ? "pass" : "fail"), vi.label);
      p.setAttribute("data-verdict", vi.code || (proven ? "proven" : "not_proven"));
      line.append(p, el("span", "mono", (r.test_name || NR)));
      box.appendChild(line);
      box.appendChild(rows([
        ["Reason", vi.reason || m.why_not_proven || r.why_not_proven || (proven ? "The gate opened." : NR)],
        ["Base", (r.base_result && typeof r.base_result.returncode === "number") ? "exit " + r.base_result.returncode : NR, true],
        ["Head", (r.head_result && typeof r.head_result.returncode === "number") ? "exit " + r.head_result.returncode : NR, true],
        ["Receipt file", s.featured_wrong_fix_receipt || NR, true],
      ]));
    } else {
      box.appendChild(el("p", "hint", s.featured_wrong_fix_receipt ? "The featured receipt file could not be read." : "No NOT PROVEN receipt for a wrong patch has been saved yet."));
    }
    return section("Featured wrong fix", box);
  }

  function caseOutcome(c) {
    const v = window.LatchVerdict.VERDICTS[c.verdict];
    const base = c.outcome || (c.status === "not run" ? "not run" : NR);
    return v ? v.label + (c.outcome ? ", " + c.outcome : "") : base;
  }

  function fullView(data) {
    const s = data.summary;
    const wf = s.wrong_fixes || {};
    const wo = wf.without_contested || {};
    const hero = el("section", "eval-hero " + (isNum(wf.n) && wf.n > 0 && wf.caught === wf.n ? "is-pass" : ""));
    hero.append(
      el("p", "hero-num", isNum(wf.caught) && isNum(wf.n) ? wf.caught + " of " + wf.n : NR),
      el("p", null, "constructed wrong patches stopped by the gate before any repair."),
      el("p", "eval-sub", "Without the contested cases: " + frac(wo.caught, wo.n) + ". Wrong patches accepted: " + (Array.isArray(wf.false_accepts) ? wf.false_accepts.length : NR) + "."),
    );
    if (wf.rule) hero.appendChild(el("p", "hint", wf.rule));
    if (wf.contested_note) hero.appendChild(el("p", "hint", wf.contested_note));
    const out = [hero, featured(data)];

    const suites = s.suites || {};
    out.push(section("Real fixes proven",
      table(["Suite", "Cases run", "Proven", "Rate", "Errors", "Not run"], Object.entries(suites).map(([k, v]) => suiteRow(k, v)), 1),
      el("p", "hint", "Cases that did not run are counted in Not run, never as passes. Every case is listed below.")));

    const nf = suites.swebench_lite && suites.swebench_lite.nemotron_fix;
    if (nf) {
      out.push(section("When Nemotron writes the fix itself",
        rows([
          ["Cases", int(nf.n)], ["Gate opened", int(nf.gate_open)], ["Passed the hidden oracle", int(nf.oracle_pass)],
          ["Green but wrong", Array.isArray(nf.green_but_wrong) && nf.green_but_wrong.length ? nf.green_but_wrong.join(", ") : "none"],
        ]), nf.note ? el("p", "hint", nf.note) : null));
    }
    if (wf.repaired_by_loop) {
      out.push(section("Fix loop repairs", rows([["Shut gates repaired", int(wf.repaired_by_loop.n)], ["Repairs that also pass the real test", int(wf.repaired_by_loop.oracle_pass)]])));
    }

    out.push(section("Cost and time",
      rows([
        ["Median wall time", secs(s.median_wall_s), true],
        ["Median estimated cost", usd(s.median_cost_usd), true],
        ["Runs with a known cost", frac(s.runs_with_known_cost, s.runs), true],
      ]), el("p", "hint", "Cost is an upper bound from list prices; cached-token discounts are not applied.")));

    out.push(baselines(s));

    const hidden = [];
    const count = (k) => (s[k] && isNum(s[k].n) ? s[k].n : NR);
    hidden.push(["Validator rejections (vacuous or malformed tests thrown out)", count("validator_rejections")]);
    hidden.push(["Abstentions (gave up or did not reproduce)", count("abstentions")]);
    hidden.push(["Failures (errors, shown not hidden)", count("failures")]);
    hidden.push(["Not run", Array.isArray(s.not_run) ? String(s.not_run.length) : NR]);
    out.push(section("What did not go well", rows(hidden)));

    const cases = Array.isArray(s.cases) ? s.cases : [];
    const body = cases.map((c) => [
      (c.case || NR) + (c.contested ? " (contested)" : ""), c.variant || NR, c.status || NR, caseOutcome(c),
      isNum(c.iterations_used) ? String(c.iterations_used) : NR, secs(c.wall_s), usd(c.cost_usd),
    ]);
    const cs = table(["Case", "Variant", "Status", "Outcome", "Iterations", "Wall", "Est. cost"], body, 4);
    cs.querySelector("table").classList.add("eval-cases");
    out.push(section("Every case", cs));
    if (s.generated_at) out.push(el("p", "hint", "Summary generated " + s.generated_at + (s.source_run ? " from run " + s.source_run : "") + ", schema version " + int(s.schema_version) + "."));
    root.replaceChildren(...out);
  }

  fetch("/api/eval").then((r) => r.json()).then((data) => {
    if (data && data.available && data.summary) fullView(data); else pendingView(data && data.reason);
  }).catch(() => pendingView("The evaluation summary could not be loaded."));
})();
