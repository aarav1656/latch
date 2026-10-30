(() => {
  "use strict";
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    const label = btn.textContent;
    btn.addEventListener("click", async () => {
      const src = document.getElementById(btn.getAttribute("data-copy"));
      try { await navigator.clipboard.writeText(src.textContent); btn.textContent = "Copied"; } catch (_) { btn.textContent = "Copy failed"; }
      setTimeout(() => { btn.textContent = label; }, 2000);
    });
  });
})();
