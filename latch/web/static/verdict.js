/* The receipt verdict, shared by the receipt, the gallery and /eval.
   Schema: latch/verdict.py (pinned). `verdict` is exactly one of six codes the harness decides, in this precedence order:
   INVALID_TEST, FLAKY, NO_REGRESSION_FOUND, FIX_FAILS_TEST, MUTATION_SURVIVED, VALIDATED. Only VALIDATED is a pass.
   `proven` stays a boolean and equals VALIDATED. A receipt without `verdict` (older receipts) falls back to `proven`.
   Anything unrecognised fails closed. The one-line meanings are fixed copy. */
(() => {
  "use strict";
  const VERDICTS = {
    INVALID_TEST: { label: "Invalid test", pass: false, meaning: "The test is empty, never checks the changed code, or crashed instead of asserting." },
    FLAKY: { label: "Flaky", pass: false, meaning: "The test gave different results on reruns, so it can't be trusted." },
    NO_REGRESSION_FOUND: { label: "No regression found", pass: false, meaning: "The test already passes on the old code, so it can't show the bug." },
    FIX_FAILS_TEST: { label: "Fix fails the test", pass: false, meaning: "The test is good, but this change still fails it. The bug isn't fixed." },
    MUTATION_SURVIVED: { label: "Mutation survived", pass: false, meaning: "The test still passes when the fix is broken on purpose, so it isn't really checking the fix." },
    VALIDATED: { label: "Validated", pass: true, meaning: "The test fails on the old code, passes on the fix, and catches the fix being undone." },
  };
  const CODES = Object.keys(VERDICTS); // precedence order

  // The harness writes its reasons as lower-case clauses. Show them as sentences.
  function sentence(text) {
    const t = String(text).replace(/\s+/g, " ").trim();
    return t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : ".");
  }
  // -> { code, known, label, pass, meaning, reason, legacy }
  function info(receipt, meta) {
    const r = receipt || {}, m = meta || {};
    const raw = r.verdict;
    const reason = typeof r.verdict_reason === "string" && r.verdict_reason.trim() ? sentence(r.verdict_reason) : null;
    if (typeof raw === "string" && VERDICTS[raw]) {
      const v = VERDICTS[raw];
      // `proven` must agree. A receipt that says VALIDATED but not proven is never shown as a pass.
      const consistent = (r.proven === true) === v.pass;
      if (!consistent) {
        return { code: raw, known: true, label: v.label, pass: false, meaning: "This receipt contradicts itself: the verdict and the proven flag disagree, so it is not treated as a pass.", reason, legacy: false };
      }
      return { code: raw, known: true, label: v.label, pass: v.pass, meaning: v.meaning, reason, legacy: false };
    }
    if (raw != null && raw !== "") {
      return { code: String(raw).slice(0, 40), known: false, label: "Unrecognised verdict", pass: false, meaning: "This receipt carries a verdict this page does not know, so it is not treated as a pass.", reason, legacy: false };
    }
    const proven = r.proven === true;
    return {
      code: null, known: false, label: proven ? "Proven" : "Not proven", pass: proven, legacy: true, reason: null,
      meaning: proven
        ? "The test written from the issue fails on the base commit and passes on the pull request head."
        : (m.why_not_proven || r.why_not_proven || "The test did not show the issue failing on base and passing on head."),
    };
  }

  // Gallery items and eval cases carry the code on its own.
  function fromCode(code, proven) {
    if (typeof code === "string" && VERDICTS[code]) return { code, label: VERDICTS[code].label, pass: VERDICTS[code].pass };
    return { code: null, label: proven ? "Proven" : "Not proven", pass: !!proven };
  }

  // Count cases per verdict code, from the cases themselves. `none` counts cases with no recognised verdict.
  function breakdown(cases) {
    const counts = {};
    CODES.forEach((c) => { counts[c] = 0; });
    let none = 0;
    (Array.isArray(cases) ? cases : []).forEach((c) => {
      if (c && typeof c.verdict === "string" && VERDICTS[c.verdict]) counts[c.verdict] += 1; else none += 1;
    });
    return { counts, none, total: CODES.reduce((n, c) => n + counts[c], 0) + none };
  }

  // Survivor-driven strengthening (mutation.strengthened, schema: latch/strengthen.py). After a real MUTATION_SURVIVED the
  // test writer gets ONE more try; the stronger test goes through the whole gate again. Outcomes: adopted (it cleared the
  // gate), still_surviving (it ran the mutation check and failed again), kept_original (it never got that far, so the
  // original test and its verdict stand). Anything else is "unknown" and says only that the verdict above stands.
  // Input is either the receipt record or {live:true, ...} built from step events. Returns {state, text} or null.
  const num = (x) => typeof x === "number" && Number.isFinite(x);
  const pct = (x) => (num(x) ? Math.round(x * 100) + "%" : null);
  const frac = (k, t) => (num(k) && num(t) ? k + "/" + t : null);
  function strengthened(raw, opts) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    const why = typeof raw.reason === "string" && raw.reason.trim() ? raw.reason.trim().replace(/[.\s]+$/, "") : null;
    if (raw.attempted === false) {
      return { state: "not_attempted", text: "Latch did not write a stronger test" + (why ? ": " + why : "") + "." };
    }
    const n = Array.isArray(raw.survivors_before) ? raw.survivors_before.length : num(raw.survivors_before) ? raw.survivors_before : null;
    const rate = pct(raw.kill_rate_before);
    const first = "First test let " + (n == null ? "some" : n) + (n === 1 ? " mutant" : " mutants") + " survive" + (rate ? " (kill rate " + rate + ")" : "");
    const after = frac(raw.killed_after, raw.total_after);
    const afterRate = pct(raw.kill_rate_after);
    const kills = after ? after + (afterRate ? " (" + afterRate + ")" : "") : afterRate;
    let outcome = typeof raw.outcome === "string" ? raw.outcome : null;
    if (outcome === "adopted" && opts && opts.cleared === false) outcome = "still_surviving";  // the receipt's own mutation result wins
    if (!outcome && raw.live === true) return { state: "pending", text: first + "; Latch is writing a stronger test." };
    if (outcome === "adopted") {
      return { state: "adopted", text: first + "; Latch wrote a stronger test, which now kills " + (kills || "enough mutants to clear the bar") + "." };
    }
    if (outcome === "still_surviving") {
      const left = num(raw.total_after) && num(raw.killed_after) ? raw.total_after - raw.killed_after : null;
      return { state: "still_surviving", text: first + "; Latch wrote a stronger test, but it still let " + (left == null ? "too many" : left) +
        (left === 1 ? " mutant" : " mutants") + " survive" + (afterRate ? " (kill rate " + afterRate + ")" : "") + ", so the Mutation survived verdict stands." };
    }
    if (outcome === "kept_original") {
      return { state: "kept_original", text: first + "; Latch tried a stronger test, but it did not clear the gate" + (why ? " (" + why + ")" : "") +
        ". The original test and its Mutation survived verdict stand." };
    }
    return { state: "unknown", text: first + "; the result of the stronger test is not recorded, so the verdict stands as written." };
  }

  window.LatchVerdict = { VERDICTS, CODES, info, fromCode, breakdown, strengthened };
})();
