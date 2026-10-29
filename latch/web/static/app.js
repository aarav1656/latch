(() => {
  "use strict";
  const boot = JSON.parse(document.getElementById("boot").textContent);
  const $ = (id) => document.getElementById(id);
  const form = $("form"), input = $("url"), runBtn = $("run"), exampleBtn = $("example");
  const urlError = $("url-error"), liveNote = $("live-note");
  const progress = $("progress"), stepperEl = $("stepper"), detailEl = $("detail");
  const noticeEl = $("notice"), errorEl = $("error"), receiptEl = $("receipt");
  const CLICK_URL = "https://github.com/pallets/click/pull/3299";
  const STEPS = [
    ["fetching", "Read the pull request"],
    ["fetching-commits", "Fetch base and head"],
    ["model", "Write the test from the issue"],
    ["base-test", "Run on base (should fail)"],
    ["head-test", "Run on head (should pass)"],
    ["receipt", "Write the receipt"],
  ];
  let config = boot.config || {};
  let current = null; // envelope on screen
  let source = null; // EventSource
  let poll = null;
  let busy = false;

  // ---- tiny DOM helpers (all untrusted text goes through textContent) ----
  function el(tag, cls, text, attrs) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    if (attrs) for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  }
  function safeHref(url) {
    try {
      const u = new URL(url);
      return u.protocol === "https:" && u.hostname === "github.com" ? u.href : null;
    } catch (_) { return null; }
  }
  function link(url, label) {
    const href = safeHref(url);
    if (!href) return el("span", null, label || url || "");
    return el("a", null, label || url, { href, target: "_blank", rel: "noopener noreferrer" });
  }
  function fact(label, content, mono) {
    const dt = el("dt", null, label);
    const dd = el("dd");
    if (typeof content === "string") { dd.textContent = content; if (mono) dd.className = "mono"; }
    else if (content) dd.appendChild(content);
    const wrap = el("div", "fact"); wrap.append(dt, dd);
    return wrap;
  }
  function when(iso) {
    if (!iso) return "unknown";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) + " (" + iso + ")";
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  // ---- receipt view ----
  const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  const CROSS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  function icon(svg) { const s = el("span"); s.innerHTML = svg; return s.firstChild; }
  function short(sha) { return sha ? String(sha).slice(0, 10) : "?"; }

  function outputBlock(kind, title, result, ok) {
    const box = el("div", "run " + kind + (kind === "head" && !ok ? " bad-head" : ""));
    const h = el("h3", null, title);
    const code = result && typeof result.returncode === "number" ? result.returncode : "?";
    h.appendChild(el("span", "status", (kind === "base" ? "failed" : ok ? "passed" : "failed") + " · exit " + code));
    const text = result ? ((result.stdout || "") + (result.stderr ? "\n" + result.stderr : "")).trim() : "";
    const pre = el("pre", null, text || "(no output)", { tabindex: "0", role: "region", "aria-label": title + " output" });
    box.append(h, pre);
    return box;
  }

  function renderReceipt(envelope, opts = {}) {
    current = envelope;
    const r = envelope.receipt, m = envelope.meta || {};
    const proven = r.proven === true;
    clear(receiptEl);

    const verdict = el("div", "verdict " + (proven ? "proven" : "not-proven"));
    const stamp = el("div", "stamp");
    stamp.append(icon(proven ? CHECK : CROSS), document.createTextNode(proven ? "Proven" : "Not proven"));
    const why = proven
      ? "The test written from the issue fails on the base commit and passes on the pull request head."
      : (m.why_not_proven || "The test did not show the issue failing on base and passing on head.");
    verdict.append(stamp, el("p", "verdict-text", why));
    const tags = { recorded: "Recorded run", live: "Live run", cached: "Cached receipt" };
    verdict.appendChild(el("span", "tag", tags[opts.cached && m.source === "live" ? "cached" : m.source] || "Receipt"));
    receiptEl.appendChild(verdict);

    const facts = el("dl", "facts");
    const prTitle = r.pull_request_title || "Pull request";
    facts.appendChild(fact("Pull request", r.pull_request_url ? (() => { const d = el("div"); d.appendChild(link(r.pull_request_url, prTitle)); return d; })() : prTitle));
    facts.appendChild(fact("Issue (the oracle)", r.issue_url ? (() => { const d = el("div"); d.appendChild(link(r.issue_url, r.issue_title || r.issue_url)); return d; })() : (r.issue_title || "Linked issue")));
    facts.appendChild(fact("Base commit", short(r.base) + (r.base_branch ? "  (" + r.base_branch + ")" : ""), true));
    facts.appendChild(fact("Head commit", short(r.head) + (r.head_branch ? "  (" + r.head_branch + ")" : ""), true));
    facts.appendChild(fact("Model", r.model || "unknown", true));
    facts.appendChild(fact("Completion id", r.completion_id || "unknown", true));
    facts.appendChild(fact("Recorded", when(m.created_at)));
    facts.appendChild(fact("Test runner", r.test_runner || m.runner || "unknown"));
    receiptEl.appendChild(facts);

    if (r.issue) {
      const d = el("details", "issue");
      d.append(el("summary", null, "Issue text the model saw"), el("p", null, r.issue));
      receiptEl.appendChild(d);
    }

    const test = el("div", "block");
    const th = el("h3", null, "Generated test");
    if (r.test_name) th.appendChild(el("small", null, r.test_name));
    test.append(th, el("pre", null, r.test || "", { tabindex: "0", role: "region", "aria-label": "Generated test source" }));
    receiptEl.appendChild(test);

    const runs = el("div", "block runs");
    runs.appendChild(outputBlock("base", "Base: " + short(r.base), r.base_result, false));
    runs.appendChild(outputBlock("head", "Head: " + short(r.head), r.head_result, (r.head_result || {}).returncode === 0));
    receiptEl.appendChild(runs);
    if (r.base_failure_type) {
      receiptEl.appendChild(el("p", "hint", "Base failure type: " + r.base_failure_type + (r.base_failure_is_expected ? " (accepted as the issue's failure)" : " (not accepted)")));
    }

    const actions = el("div", "actions");
    const flash = el("span", "flash", "", { role: "status" });
    const permalink = m.permalink || (m.repo && m.number ? "/r/" + m.repo + "/" + m.number : null);
    if (permalink) actions.appendChild(button("Copy permalink", () => copy(location.origin + permalink, flash, "Link copied")));
    actions.appendChild(button("Copy JSON", () => copy(JSON.stringify(envelope, null, 2), flash, "JSON copied")));
    actions.appendChild(button("Download JSON", () => download(envelope)));
    if (r.pull_request_url) {
      const live = button("Run live", () => submit(r.pull_request_url, true));
      live.id = "run-live";
      if (!config.live) { live.disabled = true; live.title = config.live_reason || "Live runs are off"; }
      actions.appendChild(live);
    }
    actions.appendChild(flash);
    receiptEl.appendChild(actions);
  }

  function button(label, onclick) {
    const b = el("button", "btn ghost small", label, { type: "button" });
    b.addEventListener("click", onclick);
    return b;
  }
  async function copy(text, flash, message) {
    try { await navigator.clipboard.writeText(text); flash.textContent = message; }
    catch (_) { flash.textContent = "Copy failed"; }
    setTimeout(() => { flash.textContent = ""; }, 2000);
  }
  function download(envelope) {
    const r = envelope.receipt;
    const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: "application/json" });
    const a = el("a", null, "", { href: URL.createObjectURL(blob), download: "latch-receipt-" + short(r.head) + ".json" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---- stepper ----
  function buildStepper() {
    clear(stepperEl);
    for (const [key, label] of STEPS) {
      const li = el("li", null, label, { "data-step": key, "data-state": "pending" });
      stepperEl.appendChild(li);
    }
  }
  function markStep(name, state) {
    const keys = STEPS.map((s) => s[0]);
    const idx = keys.indexOf(name);
    if (idx < 0) return;
    [...stepperEl.children].forEach((li, i) => {
      if (i < idx && li.dataset.state !== "failed") li.dataset.state = "done";
      if (i === idx) li.dataset.state = state;
    });
  }
  function finishSteps() { [...stepperEl.children].forEach((li) => { li.dataset.state = "done"; }); }

  // ---- ui state ----
  function setBusy(on) {
    busy = on;
    runBtn.disabled = on;
    exampleBtn.disabled = on;
    runBtn.textContent = on ? "Working…" : "Prove it";
  }
  function showNotice(text) { noticeEl.hidden = !text; noticeEl.textContent = text || ""; }
  function showError(err) {
    clear(errorEl);
    if (!err) { errorEl.hidden = true; return; }
    errorEl.append(el("h2", null, "Nothing was proven"), el("p", null, err.message || "Something went wrong."));
    if (err.code) errorEl.appendChild(el("p", "code", err.code + (err.retry_after ? " · retry in " + err.retry_after + " s" : "")));
    errorEl.hidden = false;
  }
  function fieldError(text) {
    urlError.hidden = !text; urlError.textContent = text || "";
    input.setAttribute("aria-invalid", text ? "true" : "false");
  }
  function applyConfig() {
    liveNote.hidden = config.live;
    liveNote.textContent = config.live ? "" : (config.live_reason || "Live runs are off. Cached receipts still work.");
    const live = $("run-live");
    if (live) { live.disabled = !config.live; live.title = config.live ? "" : (config.live_reason || ""); }
  }
  function endRun() { closeStreams(); setBusy(false); receiptEl.hidden = false; }
  function closeStreams() {
    if (source) { source.close(); source = null; }
    if (poll) { clearInterval(poll); poll = null; }
  }
  function onResult(data) {
    finishSteps();
    progress.hidden = true;
    showError(null);
    showNotice(null);
    renderReceipt({ receipt: data.receipt, meta: data.meta });
    if (data.meta && data.meta.permalink) history.replaceState(null, "", data.meta.permalink);
    endRun();
    receiptEl.focus({ preventScroll: false });
  }
  function onError(err) {
    const failed = stepperEl.querySelector('[data-state="active"]');
    if (failed) failed.dataset.state = "failed";
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
    buildStepper();
    progress.hidden = false;
    receiptEl.hidden = true; // the old receipt returns (replaced) when the run ends
    progress.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    detailEl.textContent = "Waiting for the worker…";
    let finished = false;
    const done = () => { finished = true; };
    const listen = (name, fn) => source.addEventListener(name, (e) => { try { fn(JSON.parse(e.data)); } catch (_) {} });
    source = new EventSource("/api/proof/" + jobId + "/events");
    listen("queued", (d) => { detailEl.textContent = d.position ? "Queued. " + d.position + " run(s) ahead." : "Starting…"; });
    listen("queue", (d) => { detailEl.textContent = d.position ? "Queued. " + d.position + " run(s) ahead." : "Starting…"; });
    listen("step", (d) => { markStep(d.step, "active"); detailEl.textContent = (STEPS.find((s) => s[0] === d.step) || [0, ""])[1] + "…"; });
    listen("detail", (d) => { detailEl.textContent = d.message; });
    listen("result", (d) => { done(); onResult(d); });
    listen("error", (d) => { done(); onError(d); });
    source.onerror = () => {
      if (finished) return;
      // EventSource retries by itself; also poll so we never hang on a dropped stream.
      if (!poll) poll = setInterval(async () => {
        try {
          const j = await (await fetch("/api/proof/" + jobId)).json();
          if (j.status === "done") { done(); onResult(j); }
          else if (j.status === "error" || j.error) { done(); onError(j.error || { message: "The run failed." }); }
          else if (j.step) markStep(j.step, "active");
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
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pull_request_url: url.trim(), live: !!live }),
      });
      const data = await res.json().catch(() => ({ error: { message: "The server returned an unreadable response." } }));
      if (!res.ok) { onError(data.error || { message: "Request failed (" + res.status + ")." }); return; }
      if (data.cached) {
        progress.hidden = true;
        renderReceipt({ receipt: data.receipt, meta: data.meta }, { cached: true });
        showNotice(data.note || (data.meta.source === "recorded" ? "Instant: this is the recorded receipt. Press Run live to reproduce it." : "Instant: this pull request was already proven here. Press Run live to run it again."));
        if (data.permalink) history.replaceState(null, "", data.permalink);
        endRun();
        return;
      }
      watch(data.job_id);
    } catch (_) {
      onError({ message: "Could not reach the server. Check your connection and try again.", code: "network" });
    }
  }

  // ---- wire up ----
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(input.value, false); });
  exampleBtn.addEventListener("click", () => {
    input.value = CLICK_URL;
    fieldError(null); showError(null);
    if (boot.example) {
      progress.hidden = true;
      renderReceipt(boot.example);
      showNotice("Instant: the recorded Click receipt. Press Run live to reproduce it.");
      history.replaceState(null, "", "/r/pallets/click/3299");
      receiptEl.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    }
  });

  applyConfig();
  if (boot.initial) {
    renderReceipt(boot.initial);
    const u = boot.initial.receipt.pull_request_url;
    if (u) input.value = u;
  } else if (boot.example) {
    renderReceipt(boot.example);
    input.value = "";
    if (boot.notice) showNotice(boot.notice);
    else showNotice("This is a recorded receipt for Click PR #3299. Paste any pull request above to prove your own.");
  }
  if (boot.notice && boot.initial) showNotice(boot.notice);
})();
