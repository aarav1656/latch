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

  window.LatchVerdict = { VERDICTS, CODES, info, fromCode, breakdown };
})();
