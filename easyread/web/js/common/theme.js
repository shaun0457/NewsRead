/* 顶栏的深色 / 浅色切换按钮（文献库页、阅读页都有）。点一下在浅色和深色之间切；
   “跟随系统”在设置 → 界面主题里选。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  const SUN = "M10 13.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM10 2v1.6M10 16.4V18M2 10h1.6M16.4 10H18M4.3 4.3l1.2 1.2M14.5 14.5l1.2 1.2M15.7 4.3l-1.2 1.2M5.5 14.5l-1.2 1.2";
  const MOON = "M16.5 12.3A7 7 0 0 1 7.7 3.5a7 7 0 1 0 8.8 8.8z";
  const svg = (d) => '<svg class="i" viewBox="0 0 20 20" aria-hidden="true"><path d="' + d + '"/></svg>';
  const dark = () => document.documentElement.dataset.theme === "dark";

  function paint(btn) {
    btn.innerHTML = svg(dark() ? SUN : MOON);
    btn.title = dark() ? "换成浅色" : "换成深色";
  }

  PR.toggleTheme = function () {
    const next = dark() ? "light" : "dark";
    if (PR.setPref && PR.prefs) PR.setPref("theme", next);  // 阅读页：和 Aa 面板里的主题是同一个设置
    else {
      const p = PR.ls.get("easyread-prefs", {});
      p.theme = next;
      PR.ls.set("easyread-prefs", p);
      PR.applyTheme(next);
      if (PR.savePrefs) PR.savePrefs("reader", { theme: next });
    }
    PR.$$(".theme-btn").forEach(paint);
  };

  /* 放在顶栏的帮助 / 阅读设置按钮前面 */
  document.addEventListener("DOMContentLoaded", () => {
    const before = document.querySelector("#helpBtn, #bar [data-act='settings']");
    if (!before) return;
    const btn = document.createElement("button");
    btn.className = "btn icon theme-btn";
    btn.onclick = PR.toggleTheme;
    before.parentNode.insertBefore(btn, before);
    paint(btn);
    // 跟随系统时，系统切换深浅色、或在设置里改了主题，图标跟着变
    new MutationObserver(() => paint(btn)).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  });
})(window.PR);
