/* 界面语言。代码里只写中文：PR.t("已导入 {n} 篇", { n })；中文原文就是键，英文在 web/i18n/en.json。
   后端返回页面时按系统语言（或设置里选的）写好 <html lang>，英文时把词典塞进 #pr-i18n。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  let dict = {};
  try { dict = JSON.parse((document.getElementById("pr-i18n") || {}).textContent || "{}"); } catch (e) { dict = {}; }
  PR.lang = document.documentElement.lang === "en" ? "en" : "zh";
  PR.langChoice = document.documentElement.dataset.langChoice || "auto";  // 设置里选的：auto 跟随系统
  /* 译文语言（论文翻成什么）。名字用各自的文字写，和界面语言无关 */
  PR.TARGETS = [["zh", "中文"], ["ja", "日本語"], ["ko", "한국어"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"]];  // i18n-ok
  PR.target = document.documentElement.dataset.target || "zh";
  PR.targetName = (code) => (PR.TARGETS.find(([k]) => k === code) || PR.TARGETS[0])[1];

  const fill = (s, vars) => vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : s;
  PR.t = (zh, vars) => fill(PR.lang === "en" ? dict[zh] || zh : zh, vars);

  /* 写死在 HTML 里的中文：按原文整句对照替换，HTML 不用改 */
  const CJK = /[一-鿿]/;
  const ATTRS = ["placeholder", "title", "aria-label", "alt"];
  PR.translateDom = function (root) {
    if (PR.lang !== "en") return;
    root = root || document.body;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const raw = n.nodeValue, key = raw.trim();
      if (key && CJK.test(key) && dict[key]) n.nodeValue = raw.replace(key, dict[key]);
    }
    root.querySelectorAll("*").forEach((el) => ATTRS.forEach((a) => {
      const v = el.getAttribute(a);
      if (v && CJK.test(v) && dict[v.trim()]) el.setAttribute(a, dict[v.trim()]);
    }));
  };
  if (PR.lang === "en") {
    if (dict[document.title]) document.title = dict[document.title];
    if (document.body) PR.translateDom(document.body);
    else document.addEventListener("DOMContentLoaded", () => PR.translateDom(document.body));
  }
})(window.PR);
