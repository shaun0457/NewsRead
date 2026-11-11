/* Mockup 控制：狀態切換（data-show="state1 state2"）、主題、桌機 / 窄視窗。只給 mockup 用。 */
(function () {
  "use strict";
  const body = document.body;
  const KIND = { blind: "盲判", concept: "盲判", retro: "事後補判 · 不算分" };
  function apply() {
    const st = body.dataset.state || "normal";
    document.querySelectorAll("[data-show]").forEach(el => {
      el.hidden = !el.dataset.show.split(/\s+/).includes(st);
    });
    // 只同步切換鈕（mock-bar 和頁面上 role="group" 的模式切換），不碰「直接看 AI」這類一次性按鈕
    document.querySelectorAll('.mock-bar [data-set-state], [role="group"] [data-set-state]').forEach(b => b.setAttribute("aria-pressed", String(b.dataset.setState === st)));
    document.querySelectorAll(".mock-bar [data-set-frame]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.setFrame === (body.dataset.frame || "desktop"))));
    const theme = document.documentElement.dataset.theme || "auto";
    document.querySelectorAll(".mock-bar [data-set-theme]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.setTheme === theme)));
  }
  function stop(e, el) { if (el.closest("a[href]")) e.preventDefault(); }
  document.addEventListener("click", e => {
    const s = e.target.closest("[data-set-state]");
    if (s) {
      stop(e, s);
      if (s.hasAttribute("data-skip")) {  // 不判斷直接看 AI：「你」那欄要寫還沒判斷，不能沿用盲判的範例
        const pick = document.getElementById("pick-thesis");
        if (pick) pick.textContent = "還沒判斷";
        const kind = document.querySelector("[data-picked-kind]");
        if (kind) kind.textContent = "已寫揭露紀錄 · 之後再判斷不算盲判";
        body.dataset.disclosed = "1";
      }
      body.dataset.state = s.dataset.setState; apply(); return;
    }
    const f = e.target.closest("[data-set-frame]");
    if (f) { stop(e, f); body.dataset.frame = f.dataset.setFrame; apply(); return; }
    const t = e.target.closest("[data-set-theme]");
    if (t) { stop(e, t); if (t.dataset.setTheme === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t.dataset.setTheme; apply(); return; }
    const q = e.target.closest(".qj button");
    if (q) {
      const group = q.closest(".qj");
      group.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", "false"));
      q.setAttribute("aria-pressed", "true");
      const from = body.dataset.state || "normal";
      const out = group.dataset.pickedTarget && document.getElementById(group.dataset.pickedTarget);
      if (out) {
        out.innerHTML = q.innerHTML;  // 連同加強 / 削弱的顏色一起帶過去
        const kind = out.parentElement.querySelector("[data-picked-kind]");
        const label = body.dataset.disclosed ? "非盲判（已看過 AI）" : KIND[from];
        if (kind && label) kind.textContent = label + " · 已寫進帳本";
      }
      const go = group.dataset.reveal;
      if (go) { body.dataset.state = go; apply(); }
    }
  });
  document.querySelectorAll(".qj button:not([aria-pressed])").forEach(b => b.setAttribute("aria-pressed", "false"));
  apply();
})();
