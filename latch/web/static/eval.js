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
      line.append(p, el("span", "mono", (r.test_name || (r.proof_test && r.proof_test.name) || NR)));
      box.appendChild(line);
      // prove.py receipts carry base_result/head_result; fix-loop receipts carry initial.base_proof/head_proof
      const init = r.initial || {};
      const exit = (x) => (x && typeof x.returncode === "number" ? "exit " + x.returncode : NR);
      const assertion = (log) => (typeof log === "string" ? (log.split("\n").find((l) => /^E\s/.test(l)) || "").replace(/^E\s+/, "").slice(0, 240) : "");
      const logs = r.verdict_logs || {};
      const pairs = [
        ["Meaning", vi.meaning],
        ["Reason", vi.reason || m.why_not_proven || r.why_not_proven || (proven ? "The gate opened." : NR)],
        ["Base", exit(r.base_result || init.base_proof), true],
        ["Head", exit(r.head_result || init.head_proof), true],
      ];
      const failed = assertion(logs.head);
      if (failed) pairs.push(["Failure on the wrong patch", failed, true]);
      pairs.push(["Receipt file", s.featured_wrong_fix_receipt || NR, true]);
      box.appendChild(rows(pairs));
    } else {
      box.appendChild(el("p", "hint", s.featured_wrong_fix_receipt ? "The featured receipt file could not be read." : "No NOT PROVEN receipt for a wrong patch has been saved yet."));
    }
    return section("Featured wrong fix", box);
  }

  // The verdict cell: label first, the harness's own reason beneath. Cases with no verdict fall back to the outcome text.
  function caseVerdict(c) {
    // Schema v1 put the loop's own result (gate_open, gave_up, error) in `verdict`; that is not one of the six, so it is
    // shown as the outcome and never as a verdict.
    const v = window.LatchVerdict.VERDICTS[c.verdict];
    const cell = el("div", "case-verdict");
    if (!v) { cell.textContent = c.outcome || (c.status === "not run" ? "not run" : NR); return cell; }
    const tag = el("span", "pill " + (v.pass ? "pass" : "fail"), v.label, { "data-verdict": c.verdict });
    cell.appendChild(tag);
    if (c.verdict_source === "derived") cell.appendChild(el("span", "case-source", "derived from the receipt"));
    if (typeof c.verdict_reason === "string" && c.verdict_reason.trim()) cell.appendChild(el("span", "case-reason", c.verdict_reason.trim()));
    if (typeof c.loop_verdict === "string" && c.loop_verdict.trim()) cell.appendChild(el("span", "case-loop", "loop result: " + c.loop_verdict.replace(/_/g, " ")));
    return cell;
  }
  // Per-case rerun result. `flaky` is the receipt's flaky object; a bare boolean is also accepted.
  function caseFlaky(c) {
    const f = c.flaky;
    if (f && typeof f === "object") {
      if (f.ran !== true) return "not run";
      return (f.flaky === true ? "flaky" : "stable") + (isNum(f.flake_rate) ? ", " + pct(f.flake_rate) : "");
    }
    if (typeof f === "boolean") return f ? "flaky" : "stable";
    return c.status === "not run" ? "not run" : NR;
  }
  function median(xs) {
    const v = xs.filter(isNum).sort((a, b) => a - b);
    if (!v.length) return null;
    const m = v.length >> 1;
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  }

  // Verdicts across the cases (counted from the cases), the rerun check summary and the kill rate, side by side.
  function verdictSummary(s, cases) {
    const LV = window.LatchVerdict;
    const bd = LV.breakdown(cases);
    // Schema v2 carries the counts itself (`verdicts`); v1 summaries are counted from the cases. Never mix the two.
    const given = s.verdicts && typeof s.verdicts === "object" && LV.CODES.every((c) => isNum(s.verdicts[c])) ? s.verdicts : null;
    const counts = given || bd.counts;
    const list = el("ul", "breakdown");
    LV.CODES.forEach((code) => {
      const li = el("li", "breakdown-item" + (counts[code] ? "" : " is-zero"), null, { "data-verdict": code, "data-count": String(counts[code]) });
      li.append(el("span", "breakdown-label", LV.VERDICTS[code].label), el("span", "breakdown-count num", String(counts[code])));
      list.appendChild(li);
    });
    if (bd.none) {
      const li = el("li", "breakdown-item", null, { "data-verdict": "none", "data-count": String(bd.none) });
      li.append(el("span", "breakdown-label", "No verdict recorded"), el("span", "breakdown-count num", String(bd.none)));
      list.appendChild(li);
    }
    const fl = s.flaky && typeof s.flaky === "object" ? s.flaky : null;
    const caseRates = cases.map((c) => (c && c.mutation && isNum(c.mutation.kill_rate) ? c.mutation.kill_rate : c && isNum(c.kill_rate) ? c.kill_rate : null));
    const topRate = s.mutation && typeof s.mutation === "object" && isNum(s.mutation.median_kill_rate) ? s.mutation.median_kill_rate : isNum(s.median_kill_rate) ? s.median_kill_rate : null;
    const bm = s.benchmark && typeof s.benchmark === "object" && s.benchmark.mutation && typeof s.benchmark.mutation === "object" ? s.benchmark.mutation : null;
    const pooled = bm && isNum(bm.pooled_kill_rate) ? bm.pooled_kill_rate : null;
    const kr = pooled != null ? pooled : topRate != null ? topRate : median(caseRates);
    const krLabel = pooled != null ? "Mutants killed, pooled over cases" : "Median mutation kill rate";
    const facts = rows([
      ["Cases with a verdict", bd.total - bd.none + " of " + bd.total, true],
      ["Cases rerun for flakiness", fl ? frac(fl.n_cases_checked, bd.total) : NR, true],
      ["Flaky cases", fl ? int(fl.n_flaky) : NR, true],
      ["Median flake rate", fl ? pct(fl.median_flake_rate) : NR, true],
      [krLabel, kr != null ? pct(kr) : NR, true],
    ]);
    return section("Verdicts", list, facts,
      el("p", "hint", (given ? "Counts are the summary's own. " : "Counts come from the cases listed below. ") + "Only Validated is a pass. Cases with no verdict are counted separately, never as passes."));
  }

  // Schema v2 benchmark totals, read as stated: a ratio is {k, n, rate}. Anything missing is "not recorded".
  const ratio = (r) => (r && typeof r === "object" && isNum(r.k) && isNum(r.n) ? r.k + " of " + r.n + (isNum(r.rate) ? " (" + pct(r.rate) + ")" : "") : NR);
  function benchmarkSection(s) {
    const b = s.benchmark;
    if (!b || typeof b !== "object") return null;
    const wp = b.wrong_patch_rejection && typeof b.wrong_patch_rejection === "object" ? b.wrong_patch_rejection : {};
    const gate = b.gate_accepted_but_oracle_fails && typeof b.gate_accepted_but_oracle_fails === "object" ? b.gate_accepted_but_oracle_fails : null;
    const list = gate && Array.isArray(gate.cases) && gate.cases.length ? gate.cases.join(", ") : "none";
    return section("Benchmark totals",
      rows([
        ["Runs that finished", isNum(b.runs) ? b.runs + (isNum(b.errors) ? " (" + b.errors + " errored)" : "") + (isNum(b.not_run) ? ", " + b.not_run + " not run" : "") : NR, true],
        ["Real fixes validated", ratio(b.real_validated), true],
        ["Wrong patches rejected", ratio(wp), true],
        ["Without the contested cases", ratio(wp.without_contested), true],
        ["No-fix runs where the gate opened", ratio(b.nofix_gate_open), true],
        ["Gate accepted, oracle fails", gate && isNum(gate.n) ? gate.n + " (" + list + ")" : NR, true],
      ]),
      el("p", "hint", "Each ratio is counted from the runs that finished. Runs that errored or did not run are not counted as passes."));
  }

  // What produced this summary, and what was left out of it.
  function provenanceSection(s) {
    const dropped = Array.isArray(s.dropped_cases) ? s.dropped_cases : null;
    const sha = typeof s.latch_git_sha === "string" && /^[0-9a-f]{7,40}$/i.test(s.latch_git_sha) ? s.latch_git_sha : null;
    const pairs = [
      ["Latch commit", sha ? sha.slice(0, 12) : NR, true],
      ["Cases dropped before the run", dropped ? String(dropped.length) : NR, true],
    ];
    const nodes = [rows(pairs)];
    if (dropped && dropped.length) {
      const ul = el("ul", "dropped");
      dropped.forEach((d) => {
        const li = el("li", "dropped-item");
        li.append(el("span", "mono", String((d && d.id) || NR)), el("span", "dropped-reason", String((d && d.reason) || NR)));
        ul.appendChild(li);
      });
      nodes.push(ul);
    }
    nodes.push(el("p", "hint", "Dropped cases are listed with the reason they were left out, never silently removed."));
    return section("Run details", ...nodes);
  }

  function sideBySide(data) {
    const p = data.previous, d = data.diff;
    if (!p) return null;
    const s = data.summary;
    const h = (d && d.headline) || {};
    const pair = (x) => (x && x.before != null ? [String(x.before), String(x.after)] : [NR, NR]);
    const count = (x) => (Array.isArray(x) ? String(x.length) : int(x));
    const accepts = h.false_accepts ? [count(h.false_accepts.before), count(h.false_accepts.after)] : [NR, NR];
    const cost = h.cost_usd ? [usd(h.cost_usd.before), usd(h.cost_usd.after)] : [NR, NR];
    const body = [
      ["Real fixes validated", ...pair(h.real_validated)],
      ["Wrong patches failed by a valid proof test", ...pair(h.wrong_patches_failed_by_valid_test)],
      ["Wrong patches accepted", ...accepts],
      ["Proof tests that errored instead of asserting", ...pair(h.invalid_test)],
      ["Model cost, all runs", ...cost],
    ];
    const kids = [
      el("p", null, "The same 42 runs, twice. The repair run adds one round where the test writer sees its own test's error output and rewrites the test. The first run is kept exactly as it ran."),
      table(["Measure", "First run", "Repair run"], body, 1),
    ];
    const changed = d && Array.isArray(d.cases) ? d.cases.filter((c) => c.changed) : [];
    if (changed.length) {
      kids.push(el("h3", "section-sub", "Verdicts that changed"));
      kids.push(table(["Case", "Variant", "First run", "Repair run", "Test repaired"],
        changed.map((c) => [c.case || NR, c.variant || NR, c.verdict_before || NR, c.verdict_after || NR, c.test_repair ? "yes" : "no"]), 0));
    }
    if (d && d.note) kids.push(el("p", "hint", d.note));
    kids.push(el("p", "hint", "First run: Latch " + String(p.latch_git_sha || NR).slice(0, 7) + ". Repair run: Latch " + String(s.latch_git_sha || NR).slice(0, 7) + "."));
    return section("First run and repair run, side by side", ...kids);
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
    const cases = Array.isArray(s.cases) ? s.cases : [];
    const vt = wf.caught_by_valid_test;
    if (vt && isNum(vt.caught)) hero.appendChild(el("p", "eval-sub", frac(vt.caught, vt.n) + " were failed by a valid proof test; the rest never got a usable test, so the gate stayed shut by default."));
    const out = [hero, sideBySide(data), featured(data), verdictSummary(s, cases)].filter(Boolean);
    const bsec = benchmarkSection(s);
    if (bsec) out.push(bsec);

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
    out.push(provenanceSection(s));

    const hidden = [];
    const count = (k) => (s[k] && isNum(s[k].n) ? s[k].n : NR);
    hidden.push(["Validator rejections (vacuous or malformed tests thrown out)", count("validator_rejections")]);
    hidden.push(["Abstentions (gave up or did not reproduce)", count("abstentions")]);
    hidden.push(["Failures (errors, shown not hidden)", count("failures")]);
    hidden.push(["Not run", Array.isArray(s.not_run) ? String(s.not_run.length) : NR]);
    out.push(section("What did not go well", rows(hidden)));

    const body = cases.map((c) => [
      (c.case || NR) + (c.contested ? " (contested)" : ""), c.variant || NR, c.status || NR, caseVerdict(c), caseFlaky(c),
      isNum(c.iterations_used) ? String(c.iterations_used) : NR, secs(c.wall_s), usd(c.cost_usd),
    ]);
    const cs = table(["Case", "Variant", "Status", "Verdict", "Rerun", "Iterations", "Wall", "Est. cost"], body, 5);
    cs.querySelector("table").classList.add("eval-cases");
    out.push(section("Every case", cs));
    if (s.generated_at) out.push(el("p", "hint", "Summary generated " + s.generated_at + (s.source_run ? " from run " + s.source_run : "") + ", schema version " + int(s.schema_version) + "."));
    root.replaceChildren(...out);
  }

  fetch("/api/eval").then((r) => r.json()).then((data) => {
    if (data && data.available && data.summary) fullView(data); else pendingView(data && data.reason);
  }).catch(() => pendingView("The evaluation summary could not be loaded."));
})();
