/* The receipt verdict, shared by the receipt, the gallery and /eval.
   Draft contract: `verdict` is exactly one of five codes the harness decides. `proven` stays a boolean and equals VALIDATED.
   A receipt without `verdict` (older receipts) falls back to `proven`. Anything unrecognised fails closed. */
(() => {
  "use strict";
  const VERDICTS = {
    VALIDATED: { label: "Validated", pass: true, meaning: "The test written from the issue fails on the base commit, passes on the head, and survived the mutation check." },
    NO_REGRESSION_FOUND: { label: "No regression found", pass: false, meaning: "The checks ran and found no regression, but they did not show the issue failing and then passing, so nothing is validated." },
    INVALID_TEST: { label: "Invalid test", pass: false, meaning: "The generated test is not valid evidence, so it cannot say anything about the patch." },
    MUTATION_SURVIVED: { label: "Mutation survived", pass: false, meaning: "The test passes, but changed versions of the fix still passed it, so the test is too weak to trust." },
    FLAKY: { label: "Flaky", pass: false, meaning: "Repeated runs of the test disagreed with each other, so the result cannot be trusted." },
  };
  const CODES = Object.keys(VERDICTS);

  // -> { code, known, label, pass, meaning, reason, legacy }
  function info(receipt, meta) {
    const r = receipt || {}, m = meta || {};
    const raw = r.verdict;
    const reason = typeof r.verdict_reason === "string" && r.verdict_reason.trim() ? r.verdict_reason.trim() : null;
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

  window.LatchVerdict = { VERDICTS, CODES, info, fromCode };
})();
