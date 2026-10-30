(() => {
  "use strict";
  const boot = JSON.parse(document.getElementById("boot").textContent);
  const $ = (id) => document.getElementById(id);
  const form = $("form"), input = $("url"), runBtn = $("run"), exampleBtn = $("example");
  const urlError = $("url-error"), liveNote = $("live-note");
  const progress = $("progress"), stepperEl = $("stepper"), detailEl = $("detail");
  const noticeEl = $("notice"), errorEl = $("error"), receiptEl = $("receipt");
  const recentEl = $("recent"), recentList = $("recent-list");
  const CLICK_URL = "https://github.com/pallets/click/pull/3299";
  const NR = "not recorded";
  const LV = window.LatchVerdict;
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

  // The step ledger. `step_event` frames from the engine fill it by name; the older `step` frames map in.
  const LEDGER = [
    ["fetch", "Read the pull request and issue", true],
    ["repo_map", "Map the repository (Lightning)", false],
    ["test_writer", "Write the test from the issue (Ultra)", true],
    ["base_run", "Run on base, expect it to fail", true],
    ["head_run", "Run on head, expect it to pass", true],
    ["triage", "Triage the base failure (Lightning)", false],
    ["fix", "Fix the change (agent loop)", false],
    ["flake_check", "Rerun the test, expect the same result (harness)", false],
    ["revert_check", "Revert the fix, expect it to fail again", false],
    ["mutation_check", "Mutation check (harness)", false],
    ["verdict", "Decide the verdict (harness)", true],
  ];
  const STEP_ALIAS = { "mutation": "mutation_check" };  // the draft contract's step name
  const LEGACY = { "fetching": "fetch", "fetching-commits": "fetch", "generating-test": "test_writer", "model": "test_writer", "base-test": "base_run", "head-test": "head_run", "receipt": "verdict" };
  let config = boot.config || {};
  let source = null, poll = null, busy = false;
  let steps = {}, eventMode = false;

  function el(tag, cls, text, attrs) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    if (attrs) for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function safeHref(url) {
    try { const u = new URL(url); return u.protocol === "https:" && u.hostname === "github.com" ? u.href : null; } catch (_) { return null; }
  }
  function link(url, label) {
    const href = safeHref(url);
    if (!href) return el("span", null, label || url || "");
    return el("a", null, label || url, { href, target: "_blank", rel: "noopener noreferrer" });
  }
  function row(label, content, mono) {
    const dt = el("dt", null, label), dd = el("dd");
    if (content instanceof Node) dd.appendChild(content);
    else { dd.textContent = content; if (mono) dd.className = "mono"; }
    const wrap = el("div", "row"); wrap.append(dt, dd);
    return wrap;
  }
  function short(sha) { return sha ? String(sha).slice(0, 10) : "?"; }
  function modelName(m) { return String(m || "").replace(/^nvidia\//, ""); }
  function day(iso) {
    const d = new Date(iso);
    return isNaN(d) ? null : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }
  function secs(ms) { return (ms / 1000).toFixed(1) + " s"; }
  function isNum(x) { return typeof x === "number" && isFinite(x); }
  function usd(x) { return isNum(x) ? "$" + x.toFixed(x < 0.01 ? 5 : 4) : NR; }

  const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  const CROSS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  function icon(svg) { const s = el("span"); s.innerHTML = svg; return s.firstChild; }

  // ---- receipt ----
  function pill(ok, text) {
    const p = el("span", "pill " + (ok ? "pass" : "fail"));
    p.append(icon(ok ? CHECK : CROSS), document.createTextNode(text));
    p.firstChild.setAttribute("width", "12"); p.firstChild.setAttribute("height", "12");
    return p;
  }
  function pane(cls, title, badge, body, label) {
    const box = el("div", "pane " + cls);
    const head = el("div", "pane-head");
    head.appendChild(el("h3", null, title));
    if (badge) head.appendChild(badge);
    box.append(head, el("pre", null, body || "(no output)", { tabindex: "0", role: "region", "aria-label": label || title }));
    return box;
  }
  function resultText(res) {
    return res ? ((res.stdout || "") + (res.stderr ? "\n" + res.stderr : "")).trim() : "";
  }

  // What the receipt says about where it came from. A cached live run is never shown as live.
  function provenance(m, cached) {
    const meta = el("div", "verdict-meta");
    const when = m.created_at ? day(m.created_at) : null;
    if (m.source === "recorded") {
      meta.appendChild(el("span", "tag", "Recorded run"));
      meta.appendChild(el("span", null, "saved " + (when || "date unknown") + ". Not a live run."));
    } else if (cached || m.source === "cached") {
      meta.appendChild(el("span", "tag", "Cached receipt"));
      meta.appendChild(el("span", null, "run here on " + (when || "an earlier date") + (isNum(m.duration_s) ? ", took " + m.duration_s.toFixed(1) + " s" : "") + ". Nothing was re-run."));
    } else {
      meta.appendChild(el("span", "tag", "Live run"));
      meta.appendChild(el("span", null, (when || "just now") + (isNum(m.duration_s) ? ", took " + m.duration_s.toFixed(1) + " s" : "")));
    }
    return meta;
  }

  function modelsSection(r) {
    const sec = el("section", "section");
    sec.appendChild(el("h3", "section-title", "Which model did what"));
    const calls = Array.isArray(r.model_calls) ? r.model_calls : null;
    const wrap = el("div", "scroll-x");
    const table = el("table", "ledger-table stack");
    const head = el("tr");
    ["Role", "Model", "Tokens in", "Tokens out", "Latency", "Est. cost"].forEach((h, i) => head.appendChild(el("th", i > 1 ? "r" : null, h)));
    const thead = el("thead"); thead.appendChild(head); table.appendChild(thead);
    const body = el("tbody");
    const ROLE = { repo_map: "Repo map", triage: "Triage", test_writer: "Test writer", fixer: "Fixer" };
    const LABELS = ["Role", "Model", "Tokens in", "Tokens out", "Latency", "Est. cost"];
    const add = (role, model, a, b, ms, cost) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, role));
      tr.appendChild(el("td", null, modelName(model) || NR));
      tr.appendChild(el("td", "r", isNum(a) ? a.toLocaleString() : NR));
      tr.appendChild(el("td", "r", isNum(b) ? b.toLocaleString() : NR));
      tr.appendChild(el("td", "r", isNum(ms) ? secs(ms) : NR));
      tr.appendChild(el("td", "r", usd(cost)));
      Array.from(tr.children).forEach((td, i) => td.setAttribute("data-label", LABELS[i]));
      body.appendChild(tr);
    };
    if (calls && calls.length) {
      calls.forEach((c) => add(ROLE[c.role] || c.role || NR, c.model, c.prompt_tokens, c.completion_tokens, c.latency_ms, c.cost_usd));
    } else if (r.model) {
      add("Test writer", r.model, null, null, null, null);
    }
    table.appendChild(body);
    wrap.appendChild(table);
    sec.appendChild(wrap);
    const lines = [];
    if (calls && calls.length) {
      lines.push("Total estimated cost " + usd(r.model_cost_usd) + ". Cost is an upper-bound estimate from Token Factory list prices, without cached-input discounts.");
    } else {
      lines.push("This receipt predates per-call accounting. Tokens, latency, cost and the Lightning calls are " + NR + ".");
    }
    sec.appendChild(el("p", "hint", lines.join(" ")));
    return sec;
  }

  // ---- mutation check and log excerpts (draft receipt contract) ----
  function mutantFile(mu) { return (mu.file || NR) + (isNum(mu.line) ? ":" + mu.line : ""); }
  function diffPre(text) {
    const pre = el("pre", "diff", null, { tabindex: "0", role: "region", "aria-label": "Mutant diff" });
    String(text).split("\n").forEach((ln, i, all) => {
      const cls = ln.startsWith("+") && !ln.startsWith("+++") ? "add" : ln.startsWith("-") && !ln.startsWith("---") ? "del" : ln.startsWith("@@") ? "hunk" : null;
      pre.appendChild(cls ? el("span", cls, ln) : document.createTextNode(ln));
      if (i < all.length - 1) pre.appendChild(document.createTextNode("\n"));
    });
    return pre;
  }
  // A mutant is killed, survived, timed out (counted as killed by the harness) or errored (never counted as killed).
  function mutantState(mu) {
    if (mu.not_run === true) return "not run (budget)";  // never reached: neither killed nor survived
    if (mu.timed_out === true) return "timed out";
    if (mu.killed !== true && typeof mu.error === "string" && mu.error.trim()) return "error";
    return mu.killed === true ? "killed" : "survived";
  }
  const CAUTION = "Mutation check incomplete: this verdict is not mutation-backed.";
  const isIncomplete = (r) => !!(r && r.mutation && typeof r.mutation === "object" && r.mutation.incomplete === true);
  function neutralPill(text) { return el("span", "pill neutral", text); }
  function mutantItem(mu) {
    const state = mutantState(mu);
    const notRun = state === "not run (budget)";
    const killed = mu.killed === true && !notRun;
    const li = el("li", "mutant " + (notRun ? "is-notrun" : killed ? "is-killed" : "is-survived"), null, { "data-killed": String(killed), "data-state": state.replace(" ", "-") });
    const head = el("div", "mutant-head");
    head.append(
      el("span", "mutant-op", mu.operator || NR),
      el("span", "mutant-where", mutantFile(mu)),
      notRun ? neutralPill(state) : pill(killed, state),
    );
    li.appendChild(head);
    if (notRun) li.appendChild(el("p", "mutant-what", "Not run: the time budget ran out before this mutant was reached. It says nothing about the test."));
    if (state === "error") li.appendChild(el("p", "mutant-what", "error: " + String(mu.error).trim()));
    if (mu.what) li.appendChild(el("p", "mutant-what", String(mu.what)));
    if (mu.diff && !killed) li.appendChild(diffPre(mu.diff));  // survivors show the change; killed mutants fold it away
    if (mu.diff && killed) {
      const dd = el("details");
      dd.append(el("summary", null, "Diff"), diffPre(mu.diff));
      li.appendChild(dd);
    }
    if (mu.output_excerpt) {
      const d = el("details");
      d.append(el("summary", null, "Output excerpt"), el("pre", null, String(mu.output_excerpt), { tabindex: "0" }));
      li.appendChild(d);
    }
    return li;
  }
  function mutationSection(r) {
    const sec = el("section", "section mutation", null, { "data-mutation": "" });
    sec.appendChild(el("h3", "section-title", "Mutation check"));
    const mu = r.mutation;
    if (!mu || typeof mu !== "object") {
      sec.setAttribute("data-mutation", "not-run");
      sec.appendChild(el("p", "hint", "not run. This receipt has no mutation check, so how hard the test is to fool is " + NR + "."));
      return sec;
    }
    let list = Array.isArray(mu.mutants) ? mu.mutants.filter((x) => x && typeof x === "object") : [];
    // verdict_logs.survivors carries the survivors even when the full mutant list was not kept.
    const logged = r.verdict_logs && Array.isArray(r.verdict_logs.survivors) ? r.verdict_logs.survivors.filter((x) => x && typeof x === "object") : [];
    if (!list.length && logged.length) list = logged.map((x) => Object.assign({}, x, { killed: false }));
    const unreached = list.filter((x) => x.not_run === true);
    const reached = list.filter((x) => x.not_run !== true);
    const killed = isNum(mu.killed) ? mu.killed : reached.filter((x) => x.killed === true).length;
    const total = isNum(mu.total) ? mu.total : reached.length;  // total counts the mutants that ran
    const notRunN = isNum(mu.not_run) ? mu.not_run : unreached.length;
    const incomplete = mu.incomplete === true;
    const survived = reached.filter((x) => x.killed !== true);
    const errored = survived.filter((x) => mutantState(x) === "error");
    const notRun = mu.ran === false;  // the harness could not run the check: fail closed, never a pass
    const failed = survived.length > 0 || mu.ok === false || notRun;
    sec.setAttribute("data-mutation", notRun ? "not-run" : incomplete ? "incomplete" : total === 0 && !failed ? "empty" : failed ? "survived" : "killed");
    const score = el("p", "mutation-score");
    score.append(el("span", "mutation-frac num", killed + "/" + total), el("span", null, notRunN ? " killed of the mutants that ran," : " mutants killed"));
    if (notRunN) score.appendChild(el("span", "mutation-notrun num", notRunN + " not run"));
    if (isNum(mu.kill_rate)) score.appendChild(el("span", "mutation-rate num", Math.round(mu.kill_rate * 100) + "%"));
    sec.appendChild(score);
    const facts = el("dl", "rows mutation-facts");
    if (!isNum(mu.kill_rate)) facts.appendChild(row("Kill rate", NR, true));
    facts.appendChild(row("Threshold", isNum(mu.threshold) ? Math.round(mu.threshold * 100) + "%" : NR, true));
    facts.appendChild(row("Result", mu.ok === true ? "met the threshold" : mu.ok === false ? "below the threshold or could not complete" : NR));
    sec.appendChild(facts);
    if (incomplete) sec.appendChild(el("p", "caution mutation-caution", CAUTION));
    if (typeof mu.note === "string" && mu.note.trim()) sec.appendChild(el("p", "hint mutation-note", mu.note.trim()));
    const passedMutants = survived.length - errored.length;
    sec.appendChild(el("p", "hint", notRun
      ? "The mutation check did not run, so how hard the test is to fool is " + NR + ". This is not a pass."
      : incomplete
      ? "The budget ran out before enough mutants were run, so the check is incomplete and does not block. " + notRunN + " mutant" + (notRunN === 1 ? " was" : "s were") + " not run."
      : total === 0 && !list.length
      ? "No mutable lines: no mutants were generated, so this check says nothing about the test."
      : survived.length
        ? (passedMutants ? passedMutants + " changed version" + (passedMutants === 1 ? "" : "s") + " of the fix still passed the test. " : "")
          + (errored.length ? errored.length + " mutant" + (errored.length === 1 ? "" : "s") + " could not be run and " + (errored.length === 1 ? "is" : "are") + " not counted as killed. " : "") + "These are listed first."
        : mu.ok === false ? "The check did not reach its threshold." : "Every changed version of the fix was caught by the test."));
    if (list.length && !notRun) {  // a check that did not run has no mutants worth listing
      const ordered = survived.concat(reached.filter((x) => x.killed === true), unreached);
      const ul = el("ol", "mutants");
      ordered.forEach((x) => ul.appendChild(mutantItem(x)));
      sec.appendChild(ul);
    }
    return sec;
  }

  // Rerun check: the frozen test run several times on base and on head (receipt.flaky).
  function outcomeRun(list, passWord, failWord) {
    return Array.isArray(list) && list.length ? list.map((p) => (p ? passWord : failWord)).join(" ") : NR;
  }
  function flakySection(r) {
    const sec = el("section", "section rerun", null, { "data-rerun": "" });
    sec.appendChild(el("h3", "section-title", "Rerun check"));
    const f = r.flaky;
    if (!f || typeof f !== "object" || f.ran !== true) {
      sec.setAttribute("data-rerun", "not-run");
      const why = f && typeof f === "object" && typeof f.note === "string" && f.note.trim() ? " " + f.note.trim() : "";
      sec.appendChild(el("p", "hint", "not run." + why + " Whether the test gives the same result every time is " + NR + "."));
      return sec;
    }
    sec.setAttribute("data-rerun", f.flaky === true ? "flaky" : "stable");
    const pc = (x) => (isNum(x) ? Math.round(x * 1000) / 10 + "%" : NR);
    const facts = el("dl", "rows rerun-facts");
    facts.append(
      row("Runs on each side", isNum(f.runs) ? String(f.runs) : NR, true),
      row("Base fail rate", pc(f.base_fail_rate), true),
      row("Head pass rate", pc(f.head_pass_rate), true),
      row("Flake rate", pc(f.flake_rate), true),
      row("Result", f.flaky === true ? "inconsistent across reruns" : "consistent across reruns"),
    );
    const o = f.outcomes && typeof f.outcomes === "object" ? f.outcomes : null;
    if (o) {
      facts.append(row("Base runs", outcomeRun(o.base_passed, "pass", "fail"), true), row("Head runs", outcomeRun(o.head_passed, "pass", "fail"), true));
    }
    sec.appendChild(facts);
    if (typeof f.note === "string" && f.note.trim()) sec.appendChild(el("p", "hint", f.note.trim()));
    return sec;
  }
  // receipt.tautology: the harness's pre-run check that the proof test asserts on code this change touched.
  function symbolList(list, cap) {
    const names = Array.isArray(list) ? list.filter((x) => typeof x === "string" && x) : [];
    if (!names.length) return null;
    const box = el("span", "symbols");
    names.slice(0, cap).forEach((n) => box.appendChild(el("code", "symbol", n)));
    if (names.length > cap) box.appendChild(el("span", "symbols-more", "and " + (names.length - cap) + " more"));
    return box;
  }
  function tautologySection(r) {
    const sec = el("section", "section tautology", null, { "data-tautology": "" });
    sec.appendChild(el("h3", "section-title", "Tautology check"));
    const t = r.tautology;
    if (!t || typeof t !== "object") {
      sec.setAttribute("data-tautology", "not-run");
      sec.appendChild(el("p", "hint", "not run. This receipt has no tautology check, so whether the test asserts on the changed code is " + NR + "."));
      return sec;
    }
    const checked = t.checked === true, rejected = checked && t.ok === false;
    sec.setAttribute("data-tautology", !checked ? "unchecked" : rejected ? "rejected" : "ok");
    const facts = el("dl", "rows tautology-facts");
    facts.append(
      row("Changed symbols", symbolList(t.changed_symbols, 12) || (checked ? "none recorded" : NR)),
      row("Asserted symbols", symbolList(t.asserted_symbols, 12) || (checked ? "none: the test asserts on none of them" : NR)),
    );
    const callers = symbolList(t.affected_symbols, 12);
    if (callers) facts.appendChild(row("Callers affected", callers));
    const res = row("Result", !checked ? "not checked" : rejected ? "rejected before any run" : "the test asserts on changed code");
    res.classList.add("tautology-result");
    facts.appendChild(res);
    if (typeof t.mode === "string" && t.mode) facts.appendChild(row("Mode", t.mode === "repo" ? "repository (any imported code counts)" : t.mode === "changed" ? "changed symbols only" : t.mode));
    sec.appendChild(facts);
    // The reason is always shown when the check did not pass, and for an unchecked run it says why.
    if (typeof t.reason === "string" && t.reason.trim() && (rejected || !checked)) sec.appendChild(el("p", "tautology-reason", t.reason.trim()));
    return sec;
  }
  // verdict_logs.flake: the log of the reruns, when the harness kept one.
  function logExcerpts(r) {
    const flake = r.verdict_logs && typeof r.verdict_logs.flake === "string" ? r.verdict_logs.flake.trim() : "";
    if (!flake) return null;
    const d = el("details", "logs");
    d.appendChild(el("summary", null, "Flake log"));
    d.appendChild(el("pre", null, flake, { tabindex: "0", role: "region", "aria-label": "Flake log" }));
    return d;
  }


  function checksSection(r) {
    const rows = el("dl", "rows");
    const tri = r.triage;
    rows.appendChild(row("Triage (Lightning)", tri && tri.verdict ? String(tri.verdict).replace(/_/g, " ") + (tri.reason ? ". " + tri.reason : "") : NR));
    const rm = r.repo_map;
    rows.appendChild(row("Repo map (Lightning)", rm && rm.status ? (rm.status === "ok" ? (Array.isArray(rm.files) ? rm.files.length + " files fed to the test writer" : "ok") : rm.status + (rm.detail ? ": " + rm.detail : "")) : NR));
    const rc = r.revert_check;
    rows.appendChild(row("Revert check", rc ? (rc.ran ? (rc.ok ? "passed. " : "failed. ") : "not run. ") + (rc.summary || rc.skipped || "") : NR));
    return rows;
  }

  function renderReceipt(envelope, opts = {}) {
    const r = envelope.receipt, m = envelope.meta || {};
    const vi = LV.info(r, m);
    const proven = vi.pass;
    const baseSha = r.base_sha || r.base, headSha = r.head_sha || r.head;
    clear(receiptEl);

    const verdict = el("div", "verdict " + (proven ? "is-pass" : "is-fail"), null, { "data-verdict": vi.code || (proven ? "proven" : "not_proven") });
    const word = el("h2", "verdict-word");
    word.append(icon(proven ? CHECK : CROSS), document.createTextNode(vi.label));
    verdict.append(word);
    if (vi.code) verdict.appendChild(el("p", "verdict-code", vi.code));
    verdict.appendChild(el("p", "verdict-why", vi.meaning));
    if (vi.reason) verdict.appendChild(el("p", "verdict-reason", vi.reason));
    if (isIncomplete(r)) verdict.appendChild(el("p", "caution verdict-caution", CAUTION));  // beside the verdict, never hidden
    verdict.appendChild(provenance(m, opts.cached));
    const idLine = el("p", "verdict-meta");
    idLine.append(el("span", null, "completion"), el("span", "id", r.completion_id || NR));
    verdict.appendChild(idLine);
    receiptEl.appendChild(verdict);
    const quiet = [m.test_attempts_note, m.model_retries_note].filter(Boolean).join(" ");
    if (quiet) receiptEl.appendChild(el("p", "hint", quiet));

    const vl = r.verdict_logs && typeof r.verdict_logs === "object" ? r.verdict_logs : {};
    const tail = (v, res) => (typeof v === "string" && v.trim() ? v : resultText(res));
    const ran = !!r.test && ((r.base_result != null && r.head_result != null) || (typeof vl.base === "string" && typeof vl.head === "string"));
    if (ran) {
      const pair = el("div", "pair");
      const testPane = pane("test", "Generated test" + (r.test_name ? ": " + r.test_name : ""), null, r.test || "", "Generated test source");
      const stack = el("div", "stack");
      const baseOk = (r.base_result || {}).returncode;
      const headOk = (r.head_result || {}).returncode === 0;
      stack.append(
        pane("base", "Base " + short(baseSha), pill(false, (baseOk === 0 ? "passes" : "fails") + ", exit " + (typeof baseOk === "number" ? baseOk : "?")), tail(vl.base, r.base_result), "Base output, tail"),
        pane("head " + (headOk ? "is-pass" : "is-fail"), "Head " + short(headSha), pill(headOk, (headOk ? "passes" : "fails") + ", exit " + (typeof (r.head_result || {}).returncode === "number" ? r.head_result.returncode : "?")), tail(vl.head, r.head_result), "Head output, tail"),
      );
      pair.append(testPane, stack);
      receiptEl.appendChild(pair);
      if (r.base_failure_type) {
        receiptEl.appendChild(el("p", "hint", "Base failure type: " + r.base_failure_type + (r.base_failure_is_expected ? ", accepted as the issue's failure." : ", not accepted.")));
      }
    } else {
      receiptEl.appendChild(el("p", "hint", "No test was run on base or head, so there is no test output to show."));
    }

    const facts = el("dl", "rows");
    const prLink = r.pull_request_url ? link(r.pull_request_url, r.pull_request_title || r.pull_request_url) : (r.pull_request_title || "Pull request");
    facts.appendChild(row("Pull request", prLink));
    facts.appendChild(row("Issue (the oracle)", r.issue_url ? link(r.issue_url, r.issue_title || r.issue_url) : (r.issue_title || "Linked issue")));
    facts.appendChild(row("Base commit", short(baseSha) + (r.base_branch ? " (" + r.base_branch + ")" : ""), true));
    facts.appendChild(row("Head commit", short(headSha) + (r.head_branch ? " (" + r.head_branch + ")" : ""), true));
    facts.appendChild(row("Test runner", r.test_runner || m.runner || NR));
    receiptEl.appendChild(facts);

    receiptEl.appendChild(tautologySection(r));
    receiptEl.appendChild(flakySection(r));
    receiptEl.appendChild(mutationSection(r));
    const logs = logExcerpts(r);
    if (logs) receiptEl.appendChild(logs);
    receiptEl.appendChild(modelsSection(r));
    receiptEl.appendChild(checksSection(r));

    if (r.issue) {
      const d = el("details");
      d.append(el("summary", null, "Issue text the model saw"), el("p", null, r.issue));
      receiptEl.appendChild(d);
    }
    const rejected = (r.test_attempts || r.proof_test_attempts || []).filter((a) => a && a.valid === false && a.source);
    if (rejected.length) {
      const d = el("details");
      d.appendChild(el("summary", null, "Rejected test attempts (" + rejected.length + ")"));
      rejected.forEach((a) => {
        d.appendChild(el("p", "hint", "Attempt " + a.attempt + ": " + (a.rejection || "rejected")));
        d.appendChild(el("pre", null, String(a.source), { tabindex: "0" }));
      });
      receiptEl.appendChild(d);
    }

    const actions = el("div", "actions");
    const flash = el("span", "flash", "", { role: "status" });
    const permalink = m.permalink || (m.repo && m.number ? "/r/" + m.repo + "/" + m.number : null);
    if (permalink) {
      const cp = button("Copy permalink", () => copy(location.origin + permalink, flash, "Link copied"));
      cp.classList.remove("ghost"); cp.classList.add("primary");
      actions.appendChild(cp);
    }
    actions.appendChild(button("Copy JSON", () => copy(JSON.stringify(envelope, null, 2), flash, "JSON copied")));
    actions.appendChild(button("Download JSON", () => download(envelope)));
    if (r.pull_request_url) {
      const live = button("Run live", () => submit(r.pull_request_url, true));
      live.id = "run-live";
      if (!config.live) live.disabled = true;
      actions.appendChild(live);
    }
    actions.appendChild(flash);
    receiptEl.appendChild(actions);
    if (permalink) {
      const pl = el("p", "permalink");
      pl.append(el("span", "hint", "Permalink"), el("span", "mono", location.origin + permalink));
      receiptEl.appendChild(pl);
    }
  }

  function button(label, onclick) {
    const b = el("button", "btn ghost small", label, { type: "button" });
    b.addEventListener("click", onclick);
    return b;
  }
  async function copy(text, flash, message) {
    try { await navigator.clipboard.writeText(text); flash.textContent = message; } catch (_) { flash.textContent = "Copy failed"; }
    setTimeout(() => { flash.textContent = ""; }, 2000);
  }
  function download(envelope) {
    const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: "application/json" });
    const a = el("a", null, "", { href: URL.createObjectURL(blob), download: "latch-receipt-" + short(envelope.receipt.head_sha || envelope.receipt.head) + ".json" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---- recent proofs (real cached receipts only) ----
  function renderRecent(items) {
    clear(recentList);
    const real = (items || []).filter((x) => x && x.permalink && x.verdict);
    recentEl.hidden = real.length === 0;
    real.forEach((x) => {
      const li = el("li");
      const what = el("div", "what");
      what.appendChild(el("a", null, (x.repo || "") + " #" + (x.number || "?"), { href: x.permalink }));
      if (x.title) what.appendChild(el("span", "sub", x.title));
      const v = LV.fromCode(x.verdict_code, x.verdict === "proven");
      const when = el("span", "when", (x.source === "recorded" ? "recorded " : x.source === "live" ? "run here " : "") + (day(x.created_at) || ""));
      li.append(what, pill(v.pass, v.label), when);
      recentList.appendChild(li);
    });
  }
  async function refreshRecent() {
    try { const j = await (await fetch("/api/recent")).json(); renderRecent(j.items || j.recent || j); } catch (_) { /* keep what is shown */ }
  }

  // ---- step ledger ----
  function resetSteps() {
    steps = {}; eventMode = false;
    LEDGER.forEach(([k]) => { steps[k] = { state: "pending" }; });
  }
  function detailText(d) {
    if (d == null) return "";
    if (typeof d === "string") return LV.VERDICTS[d] ? LV.VERDICTS[d].label : d;
    if (typeof d === "object" && typeof d.verdict === "string" && LV.VERDICTS[d.verdict]) {
      return LV.VERDICTS[d.verdict].label + (typeof d.reason === "string" && d.reason ? ": " + d.reason : "");
    }
    if (typeof d === "object" && isNum(d.killed) && isNum(d.total)) {
      return d.killed + "/" + d.total + " mutants killed" + (isNum(d.kill_rate) ? ", " + Math.round(d.kill_rate * 100) + "%" : "");
    }
    try { return JSON.stringify(d); } catch (_) { return ""; }
  }

  function clock(ts) { const d = new Date(ts); return isNaN(d) ? "" : d.toLocaleTimeString(undefined, { hour12: false }); }
  function drawSteps() {
    clear(stepperEl);
    let n = 0;
    LEDGER.forEach(([key, label, core]) => {
      const s = steps[key];
      if (!core && (!s || s.state === "pending")) return;
      n++;
      const li = el("li", null, null, { "data-step": key, "data-state": s.state });
      const words = { pending: "waiting", active: "running", done: "done", failed: "failed" };
      let st = words[s.state];
      if (s.state === "done" && s.t0 && s.t1) st = "done " + secs(s.t1 - s.t0);
      li.append(el("span", "n", String(n)), el("span", "lbl", label), el("span", "ts", s.ts ? clock(s.ts) : ""), el("span", "st", st));
      const sub = detailText(s.detail);
      if (sub) li.appendChild(el("span", "sub", sub.length > 160 ? sub.slice(0, 157) + "..." : sub));
      stepperEl.appendChild(li);
    });
  }
  function applyEvent(d) {
    if (STEP_ALIAS[d.step]) d = Object.assign({}, d, { step: STEP_ALIAS[d.step] });
    const s = steps[d.step];
    if (!s) return;
    if (!eventMode) LEDGER.forEach(([k]) => { steps[k].state = "pending"; });  // legacy hints ran ahead of the engine's own events
    eventMode = true;
    const t = new Date(d.ts).getTime();
    if (d.status === "started") { s.state = "active"; s.t0 = isNaN(t) ? null : t; s.ts = d.ts; }
    else { s.state = d.status === "failed" ? "failed" : "done"; s.t1 = isNaN(t) ? null : t; s.ts = s.ts || d.ts; }
    if (d.detail != null) s.detail = d.detail;
    drawSteps();
  }
  function applyLegacy(name) {
    if (eventMode) return;
    const key = LEGACY[name];
    if (!key) return;
    const order = LEDGER.map((x) => x[0]);
    order.forEach((k, i) => {
      if (i < order.indexOf(key) && steps[k].state !== "failed" && LEDGER[i][2]) steps[k].state = "done";
    });
    steps[key].state = "active";
    drawSteps();
  }
  function finishSteps() { LEDGER.forEach(([k, , core]) => { if (core && steps[k].state !== "failed") steps[k].state = "done"; }); drawSteps(); }

  // ---- ui state ----
  function setBusy(on) {
    busy = on; runBtn.disabled = on; exampleBtn.disabled = on;
    runBtn.textContent = on ? "Working..." : "Prove it";
  }
  function showNotice(text) { noticeEl.hidden = !text; noticeEl.textContent = text || ""; }
  function showError(err) {
    clear(errorEl);
    if (!err) { errorEl.hidden = true; return; }
    errorEl.append(el("h2", null, "Nothing was proven"), el("p", null, err.message || "Something went wrong."));
    if (err.code) errorEl.appendChild(el("p", "code", err.code + (err.retry_after ? ", retry in " + err.retry_after + " s" : "")));
    errorEl.hidden = false;
  }
  function fieldError(text) {
    urlError.hidden = !text; urlError.textContent = text || "";
    input.setAttribute("aria-invalid", text ? "true" : "false");
  }
  function applyConfig() {
    const paused = !config.live;
    liveNote.hidden = !paused;
    liveNote.textContent = paused
      ? (config.live_reason || "Live runs are paused.") + " The recorded Click receipt, saved proofs and the fix-loop example still load."
      : "";
    const live = $("run-live");
    if (live) live.disabled = paused;
    runBtn.title = paused ? "Saved proofs open instantly. A new pull request needs a live run." : "";
  }
  function endRun() { closeStreams(); setBusy(false); receiptEl.hidden = false; }
  function closeStreams() {
    if (source) { source.close(); source = null; }
    if (poll) { clearInterval(poll); poll = null; }
  }
  // The step event for a mutation check that ran nothing reads {0, 0, null} whether there were no mutable lines or the
  // budget ran out, so the saved receipt decides which one the ledger row says.
  function mutationStepNote(r) {
    const mu = r && r.mutation;
    if (!mu || typeof mu !== "object" || mu.ran === false) return null;
    if (mu.incomplete === true) {
      const n = isNum(mu.not_run) ? mu.not_run : (Array.isArray(mu.mutants) ? mu.mutants.filter((x) => x && x.not_run === true).length : 0);
      return "incomplete: " + (isNum(mu.killed) && isNum(mu.total) ? mu.killed + "/" + mu.total + " ran and killed, " : "") + n + " not run (budget). Not mutation-backed.";
    }
    if (mu.total === 0 && !(Array.isArray(mu.mutants) && mu.mutants.length)) return "no mutable lines, so no mutants were generated";
    return null;
  }
  function onResult(data) {
    const note = mutationStepNote(data.receipt);
    if (note && steps.mutation_check) steps.mutation_check.detail = note;
    finishSteps();
    progress.hidden = true;
    showError(null); showNotice(null);
    renderReceipt({ receipt: data.receipt, meta: data.meta });
    if (data.meta && data.meta.permalink) history.replaceState(null, "", data.meta.permalink);
    endRun();
    refreshRecent();
    receiptEl.focus({ preventScroll: false });
  }
  function onError(err) {
    const active = Object.keys(steps).find((k) => steps[k].state === "active");
    if (active) { steps[active].state = "failed"; drawSteps(); }
    showError(err);
    detailEl.textContent = "";
    endRun();
    refreshConfig();
  }
  async function refreshConfig() {
    try { config = await (await fetch("/api/config")).json(); applyConfig(); } catch (_) { /* keep last */ }
  }

  // ---- live stream ----
  function watch(jobId) {
    resetSteps(); drawSteps();
    progress.hidden = false;
    receiptEl.hidden = true;
    progress.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "center" });
    detailEl.textContent = "Waiting for the worker...";
    let finished = false;
    const done = () => { finished = true; };
    source = new EventSource("/api/proof/" + jobId + "/events");
    const listen = (name, fn) => source.addEventListener(name, (e) => { try { fn(JSON.parse(e.data)); } catch (_) {} });
    const queued = (d) => { detailEl.textContent = d.position ? "Queued. " + d.position + " run(s) ahead." : "Starting..."; };
    listen("queued", queued); listen("queue", queued);
    listen("step", (d) => applyLegacy(d.step));
    listen("step_event", applyEvent);
    listen("detail", (d) => { detailEl.textContent = d.message; });
    listen("result", (d) => { done(); onResult(d); });
    listen("error", (d) => { done(); onError(d); });
    source.onerror = () => {
      if (finished) return;
      if (!poll) poll = setInterval(async () => {
        try {
          const j = await (await fetch("/api/proof/" + jobId)).json();
          if (j.status === "done") { done(); onResult(j); }
          else if (j.status === "error" || j.error) { done(); onError(j.error || { message: "The run failed." }); }
          else if (j.step) applyLegacy(j.step);
        } catch (_) { /* keep polling */ }
      }, 2500);
    };
  }

  async function submit(url, live) {
    if (busy) return;
    showError(null); showNotice(null); fieldError(null);
    if (!/^https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/pull\/\d+\/?$/.test(url.trim())) {
      fieldError("Enter a GitHub pull request URL like " + CLICK_URL);
      input.focus();
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/api/proof", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pull_request_url: url.trim(), live: !!live }),
      });
      const data = await res.json().catch(() => ({ error: { message: "The server returned an unreadable response." } }));
      if (!res.ok) { onError(data.error || { message: "Request failed (" + res.status + ")." }); return; }
      if (data.cached) {
        progress.hidden = true;
        renderReceipt({ receipt: data.receipt, meta: data.meta }, { cached: true });
        showNotice(data.note || (data.meta.source === "recorded"
          ? "This is the recorded receipt, returned instantly. Nothing was run. Press Run live to reproduce it."
          : "This pull request was already proven here, so the saved receipt is shown. Nothing was re-run. Press Run live to run it again."));
        if (data.permalink) history.replaceState(null, "", data.permalink);
        endRun();
        return;
      }
      watch(data.job_id);
    } catch (_) {
      onError({ message: "Could not reach the server. Check your connection and try again.", code: "network" });
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); submit(input.value, false); });
  exampleBtn.addEventListener("click", () => {
    input.value = CLICK_URL;
    fieldError(null); showError(null);
    if (boot.example) {
      progress.hidden = true;
      renderReceipt(boot.example);
      showNotice("This is the recorded Click receipt, not a live run. Paste any pull request above to prove your own.");
      history.replaceState(null, "", "/r/pallets/click/3299");
      receiptEl.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "start" });
    }
  });

  applyConfig();
  renderRecent(boot.recent);
  setInterval(() => { if (!document.hidden && !busy) refreshConfig(); }, 60000);
  if (boot.initial) {
    renderReceipt(boot.initial);
    const u = boot.initial.receipt.pull_request_url;
    if (u) input.value = u;
  } else if (boot.example) {
    renderReceipt(boot.example);
    showNotice(boot.notice || "");
  }
  if (boot.notice && boot.initial) showNotice(boot.notice);
})();
