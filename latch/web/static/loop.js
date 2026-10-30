(() => {
  "use strict";
  // Secondary "Fix loop" view: replays a recorded run (or streams a live one) as a timeline.
  // Every string from events is untrusted model/pytest output: textContent only.
  const $ = (id) => document.getElementById(id);
  const tabProof = $("tab-proof"), tabLoop = $("tab-loop");
  const panelProof = $("panel-proof"), panelLoop = $("panel-loop");
  const timeline = $("loop-timeline"), gate = $("loop-gate"), tag = $("loop-tag"), note = $("loop-note");
  const replayBtn = $("loop-replay"), allBtn = $("loop-all"), liveBtn = $("loop-live"), errorEl = $("loop-error");
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  let boot = {};
  try { boot = JSON.parse($("boot").textContent); } catch (_) { /* tabs still work */ }
  let config = boot.config || {};
  let recorded = null, loaded = false, token = 0, source = null, poll = null, running = false;

  function el(tag, cls, text, attrs) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    if (attrs) for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function clock(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleTimeString(undefined, { hour12: false });
  }
  function modelName(m) { return String(m || "").replace(/^nvidia\//, ""); }
  function setGate(state, text) { gate.dataset.state = state; gate.textContent = text; }

  // ---- tabs ----
  function select(which) {
    const loop = which === "loop";
    tabProof.setAttribute("aria-selected", String(!loop));
    tabLoop.setAttribute("aria-selected", String(loop));
    tabProof.tabIndex = loop ? -1 : 0;
    tabLoop.tabIndex = loop ? 0 : -1;
    panelProof.hidden = loop;
    panelLoop.hidden = !loop;
    if (loop) {
      if (location.hash !== "#fix-loop") history.replaceState(null, "", location.pathname + location.search + "#fix-loop");
      if (!loaded) loadRecorded();
      refreshConfig();
    } else if (location.hash === "#fix-loop") {
      history.replaceState(null, "", location.pathname + location.search);
    }
  }
  tabProof.addEventListener("click", () => select("proof"));
  tabLoop.addEventListener("click", () => select("loop"));
  [tabProof, tabLoop].forEach((t) => t.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const next = t === tabProof ? tabLoop : tabProof;
      next.focus(); next.click(); e.preventDefault();
    }
  }));

  // Submitting a PR URL always brings the proof receipt back to the front.
  $("form").addEventListener("submit", () => select("proof"));
  $("example").addEventListener("click", () => select("proof"));

  // ---- event rendering ----
  function diffBlock(text) {
    const pre = el("pre", "diff", null, { tabindex: "0" });
    String(text || "").split("\n").forEach((line, i, all) => {
      const cls = line.startsWith("@@") ? "hunk" : line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : "";
      pre.appendChild(el("span", cls, line + (i < all.length - 1 ? "\n" : "")));
    });
    return pre;
  }
  function fold(summary, content, isDiff) {
    const d = el("details");
    d.appendChild(el("summary", null, summary));
    d.appendChild(isDiff ? diffBlock(content) : el("pre", null, String(content || "(empty)"), { tabindex: "0" }));
    return d;
  }
  function chip(label, ok) { return el("span", "chip " + (ok ? "ok" : "bad"), label); }
  function card(ev, tone, title, build) {
    const li = el("li", "tl-item"); li.dataset.tone = tone;
    const c = el("div", "tl-card");
    const head = el("div", "tl-head");
    head.append(el("h3", "tl-title", title), el("span", "tl-time", clock(ev.ts)));
    c.appendChild(head);
    // The harness verdict, when the loop recorded one on this event. Only VALIDATED reads as a pass.
    const code = [ev.verdict_code, ev.verdict].find((x) => typeof x === "string" && window.LatchVerdict && window.LatchVerdict.VERDICTS[x]);
    if (code) {
      const v = window.LatchVerdict.VERDICTS[code];
      const line = el("p", "tl-verdict");
      line.append(el("span", "pill " + (v.pass ? "pass" : "fail"), v.label, { "data-verdict": code }), el("span", "tl-text", v.meaning));
      c.appendChild(line);
    }
    if (build) build(c);
    if (ev.truncated) c.appendChild(el("p", "tl-meta", "Long text was clipped to 20 KB (head and tail kept)."));
    li.appendChild(c);
    return li;
  }
  function meta(c, ...parts) {
    const text = parts.filter(Boolean).join(" · ");
    if (text) c.appendChild(el("p", "tl-meta", text));
  }

  function renderEvent(ev) {
    switch (ev.type) {
      case "started":
        return card(ev, "info", "Run started", (c) => {
          meta(c, ev.repo, "base " + String(ev.base || "").slice(0, 10), "head " + String(ev.head || "").slice(0, 10), "up to " + ev.max_iterations + " iterations");
          if (ev.case_note) c.appendChild(el("p", "tl-text", String(ev.case_note)));
          c.appendChild(fold("Issue text", ev.issue));
        });
      case "proof_test":
        return card(ev, "info", "Proof test written and frozen", (c) => {
          meta(c, ev.name, "written by " + modelName(ev.generated_by), ev.completion_id && "completion " + ev.completion_id);
          c.appendChild(el("p", "tl-text", "Written from the issue alone. The agent can never edit it."));
          c.appendChild(fold("Show the test", ev.test));
        });
      case "gate_shut":
        return card(ev, "shut", "Gate shut", (c) => {
          c.appendChild(el("p", "tl-text", ev.reason || "The proof test fails on the agent's fix."));
          const chips = el("div", "chips");
          chips.append(
            chip(ev.base_red ? "proof test red on base" : "proof test NOT red on base", !!ev.base_red),
            chip(ev.head_suite_green ? "repo suite green on head" : "repo suite red on head", !!ev.head_suite_green),
            chip(ev.head_proof_green ? "proof test green on head" : "proof test red on head", !!ev.head_proof_green),
          );
          c.appendChild(chips);
          c.appendChild(fold("pytest output", ev.pytest_output));
        });
      case "proof_test_attempt":
        if (ev.valid !== false) return null;
        return card(ev, "retry", "Proof test attempt " + (ev.attempt || "") + " rejected", (c) => {
          meta(c, ev.completion_id && "completion " + ev.completion_id);
          c.appendChild(el("p", "tl-text", (ev.rejection ? String(ev.rejection) : "The generated test was rejected") + ". " + (ev.attempt === 1 ? "Asking the model once more." : "No test was run.")));
        });
      case "model_retry":
        return card(ev, "retry", "Model call retried", (c) => {
          const why = ev.error ? String(ev.error).split(":")[0] : ev.status ? "HTTP " + ev.status : "network error";
          const wait = typeof ev.delay === "number" && ev.will_retry ? "waiting " + (Math.round(ev.delay * 10) / 10) + " s" : "";
          meta(c, "attempt " + ev.attempt + " of " + ev.attempts, why, wait);
          c.appendChild(el("p", "tl-text", ev.will_retry === false ? "The model request failed and was not retried." : "A transient model error. Trying again automatically."));
        });
      case "gate_check":
        return card(ev, "info", "Gate check: head already passes", null);
      case "triage": {
        const ok = ev.verdict === "reproduced";
        return card(ev, ok ? "info" : "shut", "Triage: " + String(ev.verdict || "").replace("_", " "), (c) => {
          meta(c, modelName(ev.model), ev.completion_id && "completion " + ev.completion_id);
          if (ev.reason) c.appendChild(el("p", "tl-text", ev.reason));
        });
      }
      case "iteration_started":
        return card(ev, "work", "Iteration " + ev.iteration + " begins", (c) => meta(c, "agent " + modelName(ev.model)));
      case "model_response":
        return card(ev, "work", "Patch proposed", (c) => {
          meta(c, modelName(ev.model), ev.completion_id && "completion " + ev.completion_id);
          c.appendChild(fold("Raw model reply", ev.model_text));
        });
      case "patch_applied":
        return card(ev, "work", "Patch applied", (c) => {
          meta(c, (ev.changed_files || []).join(", "));
          c.appendChild(fold("Diff", ev.diff, true));
          c.querySelector("details").open = true;
        });
      case "iteration_result": {
        const open = ev.verdict === "gate_open";
        return card(ev, open ? "open" : "shut", "Rerun, iteration " + ev.iteration + ": " + (open ? "gate open" : String(ev.verdict || "gate shut").replace("_", " ")), (c) => {
          const chips = el("div", "chips");
          if (typeof ev.proof_returncode === "number") chips.appendChild(chip("proof test " + (ev.proof_returncode === 0 ? "green" : "red"), ev.proof_returncode === 0));
          if (typeof ev.suite_returncode === "number") chips.appendChild(chip("repo suite " + (ev.suite_returncode === 0 ? "green" : "red"), ev.suite_returncode === 0));
          if (chips.children.length) c.appendChild(chips);
          if (ev.detail) c.appendChild(el("p", "tl-text", ev.detail));
          c.appendChild(fold("pytest output", ev.pytest_output));
        });
      }
      case "gate_open":
        return card(ev, "open", "Gate open", (c) => {
          c.appendChild(el("p", "tl-text", ev.reason || "The proof test is green and the repository suite is green."));
        });
      case "gave_up":
        return card(ev, "shut", "Gave up", (c) => {
          c.appendChild(el("p", "tl-text", ev.reason || "The loop stopped without opening the gate."));
        });
      case "error":
        return card(ev, "shut", "Error", (c) => c.appendChild(el("p", "tl-text", ev.reason || "The run failed.")));
      default:
        return null;
    }
  }

  function gateFor(ev) {
    switch (ev.type) {
      case "started": case "proof_test": return ["working", "Gate: checking"];
      case "gate_shut": return ["shut", "Gate: shut"];
      case "iteration_started": case "model_response": case "patch_applied": return ["working", "Gate: shut, agent patching"];
      case "iteration_result": return ev.verdict === "gate_open" ? ["open", "Gate: open"] : ["shut", "Gate: shut"];
      case "gate_open": return ["open", "Gate: open"];
      case "gate_check": return ["info", "Gate: checking"];
      case "model_retry": return ["working", ev.will_retry === false ? "Model error" : "Gate: retrying model call"];
      case "proof_test_attempt": return ["working", "Gate: rewriting proof test"];
      case "gave_up": case "error": return ["shut", ev.type === "error" ? "Error" : "Gave up"];
      default: return null;
    }
  }
  function add(ev, scroll) {
    const li = renderEvent(ev);
    if (li) {
      timeline.appendChild(li);
      if (scroll && !reduced()) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    const g = gateFor(ev);
    if (g) setGate(g[0] === "info" ? "working" : g[0], g[1]);
  }
  function stop() {
    token++;
    if (source) { source.close(); source = null; }
    if (poll) { clearInterval(poll); poll = null; }
    running = false;
    replayBtn.disabled = allBtn.disabled = false;
    liveBtn.disabled = !(config.loop && config.loop.live);
  }
  function reset() { stop(); clear(timeline); errorEl.hidden = true; setGate("idle", "Gate: waiting"); }

  // ---- recorded replay ----
  async function loadRecorded() {
    note.textContent = "Loading the recorded run…";
    try {
      const res = await fetch("/api/loop/example");
      if (!res.ok) throw new Error("none");
      recorded = (await res.json()).events;
      loaded = true;
      const started = recorded.find((ev) => ev.type === "started");
      note.textContent = started && started.case_note
        ? String(started.case_note)
        : "A real run on a constructed demo (a room-booking module), not an upstream issue. The agent's fix passes its own tests but still merges back-to-back bookings.";
      showAll();
    } catch (_) {
      note.textContent = "No recorded fix loop run is installed on this server.";
      replayBtn.disabled = allBtn.disabled = true;
    }
  }
  function showAll() {
    if (!recorded) return;
    reset(); tag.textContent = "Recorded run";
    recorded.forEach((ev) => add(ev, false));
  }
  function replay() {
    if (!recorded) return;
    if (reduced()) return showAll();
    reset(); tag.textContent = "Recorded run";
    const my = token; let i = 0;
    running = true; replayBtn.disabled = true;
    const step = () => {
      if (my !== token) return;
      if (i >= recorded.length) { stop(); return; }
      const ev = recorded[i++];
      add(ev, true);
      setTimeout(step, ev.type === "model_response" || ev.type === "iteration_started" ? 450 : 850);
    };
    step();
  }
  replayBtn.addEventListener("click", replay);
  allBtn.addEventListener("click", showAll);

  // ---- live run ----
  function fail(err) {
    stop();
    errorEl.hidden = false;
    clear(errorEl);
    errorEl.append(el("h2", null, "The live fix loop did not finish"), el("p", null, (err && err.message) || "Something went wrong."));
    if (err && err.code) errorEl.appendChild(el("p", "code", err.code));
    setGate("shut", "Error");
    refreshConfig();
  }
  async function runLive() {
    if (running) return;
    reset(); tag.textContent = "Live run"; errorEl.hidden = true;
    running = true; replayBtn.disabled = allBtn.disabled = liveBtn.disabled = true;
    note.textContent = "Starting a live run. This calls the model and takes about 30 to 60 seconds.";
    let data;
    try {
      const res = await fetch("/api/loop", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      data = await res.json().catch(() => ({}));
      if (!res.ok) return fail(data.error || { message: "Request failed (" + res.status + ")." });
    } catch (_) { return fail({ message: "Could not reach the server.", code: "network" }); }
    const my = ++token; let seen = 0, finished = false;
    const onEvent = (ev) => { if (my === token) { seen++; add(ev, true); } };
    setGate("working", "Gate: queued");
    source = new EventSource("/api/loop/" + data.job_id + "/events");
    const listen = (name, fn) => source.addEventListener(name, (e) => { try { fn(JSON.parse(e.data)); } catch (_) {} });
    listen("queued", (d) => setGate("working", d.position ? "Queued: " + d.position + " ahead" : "Starting"));
    listen("queue", (d) => setGate("working", d.position ? "Queued: " + d.position + " ahead" : "Starting"));
    listen("loop", onEvent);
    listen("done", () => { finished = true; note.textContent = "Live run finished."; stop(); refreshConfig(); });
    listen("error", (d) => { finished = true; fail(d); });
    source.onerror = () => {
      if (finished || poll || my !== token) return;
      poll = setInterval(async () => {
        try {
          const j = await (await fetch("/api/loop/" + data.job_id)).json();
          (j.events || []).slice(seen).forEach(onEvent);
          if (j.status === "done") { finished = true; stop(); }
          else if (j.status === "error") { finished = true; fail(j.error); }
        } catch (_) { /* keep polling */ }
      }, 2500);
    };
  }
  liveBtn.addEventListener("click", runLive);

  async function refreshConfig() {
    try { config = await (await fetch("/api/config")).json(); } catch (_) { /* keep */ }
    const live = !!(config.loop && config.loop.live);
    liveBtn.hidden = !(config.loop && config.loop.available);
    liveBtn.disabled = !live || running;
    liveBtn.title = live ? "" : (config.live_reason || "Live runs are off.");
  }

  liveBtn.hidden = !(config.loop && config.loop.available);
  liveBtn.disabled = !(config.loop && config.loop.live);
  if (location.hash === "#fix-loop") select("loop");
})();
