PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Latch</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Hallmark · macrostructure: Workbench · tone: technical · anchor hue: cobalt
 * audience: engineer merging an agent pull request · use: run the gate
 * theme: Cobalt · enrichment: none
 */
:root {
  --color-paper: oklch(98.5% 0.004 250);
  --color-ink: oklch(24% 0.02 258);
  --color-body: oklch(34% 0.018 257);
  --color-muted: oklch(48% 0.02 257);
  --color-rule: oklch(88% 0.01 255);
  --color-accent: oklch(58% 0.20 256);
  --color-accent-ink: oklch(99% 0.002 250);
  --color-graphite: oklch(22% 0.016 260);
  --color-graphite-ink: oklch(94% 0.01 250);
  --color-focus: oklch(58% 0.20 256);
  --color-shut: oklch(52% 0.16 25);
  --font-display: "Space Grotesk", "Source Sans 3", sans-serif;
  --font-body: "Source Sans 3", "Space Grotesk", sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-7: 48px;
  --text-display: 2.5rem;
  --radius-control: 6px;
  --radius-card: 10px;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --dur: 150ms;
}
* { box-sizing: border-box; }
html, body { overflow-x: clip; margin: 0; }
body {
  background: var(--color-paper);
  color: var(--color-ink);
  font-family: var(--font-body);
  font-size: 1.0625rem;
  line-height: 1.5;
}
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--color-rule);
}
.mark { font-family: var(--font-display); font-weight: 600; letter-spacing: -0.03em; }
button {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 0.95rem;
  white-space: nowrap;
  color: var(--color-accent-ink);
  background: var(--color-accent);
  border: 1px solid var(--color-accent);
  border-radius: var(--radius-control);
  padding: 10px 16px;
  cursor: pointer;
  transition: transform var(--dur) var(--ease-out), opacity var(--dur) var(--ease-out);
}
button:hover { transform: translateY(-1px); }
button:focus-visible { outline: 2px solid var(--color-focus); outline-offset: 3px; }
button:active { transform: translateY(1px); }
button:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }
.stage {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.8fr);
  gap: var(--space-6);
  padding: var(--space-7) var(--space-6);
  max-width: 1120px;
}
h1 {
  font-family: var(--font-display);
  font-weight: 600;
  font-style: normal;
  font-size: var(--text-display);
  letter-spacing: -0.04em;
  line-height: 1.05;
  margin: 0 0 var(--space-3);
  overflow-wrap: anywhere;
  min-width: 0;
}
.lede { color: var(--color-body); max-width: 42rem; margin: 0 0 var(--space-5); }
.label {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-muted);
  margin: 0 0 var(--space-2);
}
pre {
  margin: 0 0 var(--space-5);
  padding: var(--space-4);
  background: var(--color-graphite);
  color: var(--color-graphite-ink);
  border-radius: var(--radius-card);
  font-family: var(--font-mono);
  font-size: 0.82rem;
  line-height: 1.55;
  overflow-x: auto;
  white-space: pre-wrap;
}
.gate {
  border: 1px solid var(--color-rule);
  border-radius: var(--radius-card);
  padding: var(--space-5);
  align-self: start;
}
#latch {
  font-family: var(--font-display);
  font-size: 2.25rem;
  font-weight: 600;
  letter-spacing: -0.04em;
  margin: var(--space-2) 0 var(--space-3);
}
#latch.shut { color: var(--color-shut); }
#latch.open { color: var(--color-accent); }
ol { margin: 0; padding-left: 1.1rem; color: var(--color-body); }
li { margin: 6px 0; }
li.done { color: var(--color-ink); font-weight: 600; }
.dim { color: var(--color-muted); }
.proof-form { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-3); margin: var(--space-5) 0; }
input { min-width: 0; padding: 11px 12px; border: 1px solid var(--color-rule); border-radius: var(--radius-control); color: var(--color-ink); font: inherit; }
input:focus-visible { outline: 2px solid var(--color-focus); outline-offset: 2px; }
.result { border-top: 1px solid var(--color-rule); margin-top: var(--space-5); padding-top: var(--space-5); }
.result[hidden] { display: none; }
.proof-meta { display: grid; gap: var(--space-2); }
.proof-meta p { margin: 0; overflow-wrap: anywhere; }
.status { font-family: var(--font-display); font-weight: 600; }
.actions { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; }
.secondary { color: var(--color-ink); background: transparent; border-color: var(--color-rule); }
@media (max-width: 800px) {
  .stage { grid-template-columns: minmax(0, 1fr); padding: var(--space-5) var(--space-4); }
  .bar { padding: var(--space-4); }
  h1 { font-size: 2rem; }
  .proof-form { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) {
  button { transition: none; }
}
</style>
</head>
<body>
<header class="bar">
  <div class="mark">Latch <span class="dim">/ issue proof</span></div>
  <a href="/api/pr-proof/latest" id="receipt-link" hidden>Latest receipt</a>
</header>
<main class="stage">
  <section>
    <p class="label">Issue to verified fix</p>
    <h1>Does this pull request fix the bug it claims to?</h1>
    <p class="lede">Latch reads the linked issue, writes a behavior test from the report, then runs it against the exact base and head commits. The lock opens only when the test fails on base and passes on the pull request.</p>
    <form id="proof-form" class="proof-form">
      <label class="dim" for="pull-url" style="grid-column:1/-1">Public GitHub pull request</label>
      <input id="pull-url" name="pull_request_url" type="url" autocomplete="url" required aria-describedby="form-help" value="https://github.com/pallets/click/pull/3299">
      <button id="prove" type="submit">Prove this fix</button>
      <span id="form-help" class="dim" style="grid-column:1/-1">The pull request must close one issue in the same repository.</span>
    </form>
    <p id="feedback" class="status" role="status" aria-live="polite">Ready for a public pull request.</p>
    <div id="result" class="result" hidden>
      <p class="label">Linked issue</p>
      <h2 id="issue-title"></h2>
      <div class="proof-meta">
        <p><strong>Pull request:</strong> <a id="pr-title" target="_blank" rel="noreferrer"></a></p>
        <p><strong>Base:</strong> <code id="base-sha"></code></p>
        <p><strong>Head:</strong> <code id="head-sha"></code></p>
        <p><strong>Base test:</strong> <span id="base-result"></span></p>
        <p><strong>Head test:</strong> <span id="head-result"></span></p>
      </div>
      <p class="label" style="margin-top:var(--space-5)">Generated behavior test</p>
      <pre id="test-source"></pre>
      <div class="actions"><a id="download" class="secondary" href="/api/pr-proof/latest">View proof receipt JSON</a></div>
    </div>
  </section>
  <aside class="gate">
    <p class="label">Proof status</p>
    <p id="latch" class="shut">Shut</p>
    <p id="reason" class="dim"></p>
    <ol id="steps">
      <li data-step="fetching">Pull request and linked issue</li>
      <li data-step="fetching-commits">Exact base and head commits</li>
      <li data-step="model">Issue-grounded test generation</li>
      <li data-step="base-test">Test fails on original code</li>
      <li data-step="head-test">Test passes on proposed fix</li>
      <li data-step="receipt">Proof receipt saved</li>
    </ol>
  </aside>
</main>
<script>
const form = document.querySelector("#proof-form"), button = document.querySelector("#prove");
const feedback = document.querySelector("#feedback"), lock = document.querySelector("#latch");
const result = document.querySelector("#result");
let activeJob = null, timer = null;
function step(name) {
  const order = ["fetching", "fetching-commits", "model", "base-test", "head-test", "receipt"], current = order.indexOf(name);
  for (const item of document.querySelectorAll("#steps li")) item.className = order.indexOf(item.dataset.step) <= current ? "done" : "dim";
}
function showReceipt(receipt) {
  if (!receipt) return;
  result.hidden = false;
  document.querySelector("#issue-title").textContent = receipt.issue_title || "Linked issue";
  const link = document.querySelector("#pr-title"); link.textContent = receipt.pull_request_title || receipt.pull_request_url; link.href = receipt.pull_request_url;
  document.querySelector("#base-sha").textContent = receipt.base;
  document.querySelector("#head-sha").textContent = receipt.head;
  document.querySelector("#base-result").textContent = receipt.base_result?.returncode === 0 ? "passed" : "failed as expected";
  document.querySelector("#head-result").textContent = receipt.head_result?.returncode === 0 ? "passed" : "failed";
  document.querySelector("#test-source").textContent = receipt.test || "No test was produced.";
  const open = receipt.proven === true;
  lock.textContent = open ? "Proven" : "Not proven"; lock.className = open ? "open" : "shut";
  feedback.textContent = open ? "The generated test failed on base and passed on head." : "The generated test did not prove this fix. Review both test outputs in the receipt.";
  document.querySelector("#receipt-link").hidden = false;
  step("receipt");
}
async function poll() {
  if (!activeJob) return;
  try {
    const response = await fetch(`/api/pr-proof/status?id=${encodeURIComponent(activeJob)}`), job = await response.json();
    if (!response.ok) throw new Error(job.error || "Could not read proof status.");
    feedback.textContent = job.phase === "failed" ? job.reason : `Working: ${job.step.replaceAll("-", " ")}`;
    step(job.step);
    if (job.phase === "running") { timer = setTimeout(poll, 700); return; }
    button.disabled = false; activeJob = null;
    if (job.phase === "failed") { lock.textContent = "Shut"; return; }
    const latest = await fetch("/api/pr-proof/latest");
    showReceipt((await latest.json()).receipt);
  } catch (error) { feedback.textContent = error.message; button.disabled = false; activeJob = null; }
}
form.addEventListener("submit", async event => {
  event.preventDefault(); clearTimeout(timer); result.hidden = true; lock.textContent = "Shut"; lock.className = "shut"; step("fetching");
  button.disabled = true; feedback.textContent = "Starting proof run…";
  try {
    const response = await fetch("/api/pr-proof", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pull_request_url: form.pull_request_url.value }) });
    const body = await response.json(); if (!response.ok) throw new Error(body.reason || "Could not start the proof run.");
    activeJob = body.id; poll();
  } catch (error) { feedback.textContent = error.message; button.disabled = false; }
});
fetch("/api/pr-proof/latest").then(response => response.json()).then(body => showReceipt(body.receipt)).catch(() => {});
</script>
</body>
</html>
"""
