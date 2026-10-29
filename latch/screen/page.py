PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Latch</title>
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
@media (max-width: 800px) {
  .stage { grid-template-columns: minmax(0, 1fr); padding: var(--space-5) var(--space-4); }
  .bar { padding: var(--space-4); }
  h1 { font-size: 2rem; }
}
@media (prefers-reduced-motion: reduce) {
  button { transition: none; }
}
</style>
</head>
<body>
<header class="bar">
  <div class="mark">Latch</div>
  <button id="run" type="button">Run the gate</button>
</header>
<main class="stage">
  <section>
    <h1>Annual discount at 10 seats</h1>
    <p class="lede">The suite stays green after the boundary moves. Lightning names the test that cannot fail. Ultra writes the one that can. The harness runs it.</p>
    <p class="label">billing.py</p>
    <pre id="source">Loading the pull request.</pre>
    <p class="label">test_suite.py</p>
    <pre id="tests"></pre>
  </section>
  <aside class="gate">
    <p class="label">Padlock</p>
    <p id="latch" class="shut">Shut</p>
    <p id="reason" class="dim"></p>
    <ol id="steps">
      <li data-step="suite">Original suite</li>
      <li data-step="mutant">Same suite, changed line</li>
      <li data-step="lightning">Lightning</li>
      <li data-step="ultra">Ultra</li>
      <li data-step="kill">New test on the change</li>
      <li data-step="done">New test on the original</li>
    </ol>
  </aside>
  <section>
    <p class="label">Lightning</p>
    <pre id="lightning">Waiting.</pre>
    <p class="label">Ultra</p>
    <pre id="assertion">Waiting.</pre>
  </section>
</main>
<script>
const latch = document.querySelector("#latch");
const reason = document.querySelector("#reason");
const assertion = document.querySelector("#assertion");
const lightning = document.querySelector("#lightning");
const button = document.querySelector("#run");

function mark(state) {
  const done = {
    suite: state.weak_green === true,
    mutant: state.mutant_still_green === true,
    lightning: Boolean(state.lightning),
    ultra: Boolean(state.assertion),
    kill: state.kill_failed === true,
    done: state.restored_passed === true
  };
  for (const item of document.querySelectorAll("#steps li")) {
    item.className = done[item.dataset.step] ? "done" : "dim";
  }
}

function paint(payload) {
  const state = payload.state || {};
  const open = state.kill_failed && state.restored_passed;
  latch.textContent = open ? "Open" : "Shut";
  latch.className = open ? "open" : "shut";
  reason.textContent = state.reason || "";
  if (state.lightning) lightning.textContent = state.lightning;
  if (state.assertion) assertion.textContent = state.assertion;
  mark(state);
  const running = payload.phase === "running";
  button.disabled = running;
  button.textContent = running ? "Running" : "Run the gate";
}

async function loadFixture() {
  const response = await fetch("/api/fixture");
  if (!response.ok) {
    document.querySelector("#source").textContent = "The fixture did not load.";
    return;
  }
  const body = await response.json();
  document.querySelector("#source").textContent = body.billing || "";
  document.querySelector("#tests").textContent = body.tests || "";
}

async function poll() {
  const response = await fetch("/api/status");
  if (!response.ok) return;
  const payload = await response.json();
  paint(payload);
  if (payload.phase === "running") setTimeout(poll, 500);
}

button.addEventListener("click", async () => {
  button.disabled = true;
  button.textContent = "Running";
  const response = await fetch("/api/run", { method: "POST" });
  if (response.status === 409) {
    poll();
    return;
  }
  if (!response.ok) {
    reason.textContent = "The gate did not start.";
    button.disabled = false;
    button.textContent = "Run the gate";
    return;
  }
  poll();
});

loadFixture();
poll();
</script>
</body>
</html>
"""
