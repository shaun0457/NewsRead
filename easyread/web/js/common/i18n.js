/* 界面语言。代码里只写中文：PR.t("已导入 {n} 篇", { n })；中文原文就是键，英文在 web/i18n/en.json。
   后端返回页面时按系统语言（或设置里选的）写好 <html lang>，英文时把词典塞进 #pr-i18n。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  let dict = {}, zhTw = {};
  try { dict = JSON.parse((document.getElementById("pr-i18n") || {}).textContent || "{}"); } catch (e) { dict = {}; }
  try { zhTw = JSON.parse((document.getElementById("pr-zh-tw") || {}).textContent || "{}"); } catch (e) { zhTw = {}; }
  PR.lang = document.documentElement.lang === "en" ? "en" : document.documentElement.lang.toLowerCase() === "zh-cn" ? "zh" : "zh-TW";
  PR.langChoice = document.documentElement.dataset.langChoice || "zh-TW";
  PR.target = document.documentElement.dataset.target || "zh-TW";  // 译文语言（论文翻成什么），名字表在 util.js

  const fill = (s, vars) => vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : s;
  PR.t = (zh, vars) => fill(PR.lang === "en" ? dict[zh] || zh : PR.lang === "zh-TW" ? zhTw[zh] || zh : zh, vars);

  /* 写死在 HTML 里的中文：按原文整句对照替换，HTML 不用改 */
  const CJK = /[一-鿿]/;
  const ATTRS = ["placeholder", "title", "aria-label", "alt"];
  const USER_CONTENT = "[data-no-i18n], #paper .blk, #paper .paper-head h1, #paper .paper-head .kicker, #paper .paper-head .title-en, #paper .paper-head .byline, #paper .demo-credit, .rw-paper h3, .rw-paper .meta, .rw-paper .abstract, .rw-path-card h3, .rw-path-card .meta, .rw-path-card > div > p:not(.rw-source), .rp-node, .markdown-body";
  const isUserContent = (el) => el && el.closest && el.closest(USER_CONTENT);
  PR.translateDom = function (root) {
    if (PR.lang !== "en" && PR.lang !== "zh-TW") return;
    root = root || document.body;
    if (root.nodeType === Node.TEXT_NODE) {
      if (isUserContent(root.parentElement)) return;
      const raw = root.nodeValue, key = raw.trim();
      if (key && CJK.test(key)) {
        const translated = PR.lang === "en" ? dict[key] : zhTw[key];
        if (translated && translated !== key) root.nodeValue = raw.replace(key, translated);
      }
      return;
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (isUserContent(n.parentElement)) continue;
      const raw = n.nodeValue, key = raw.trim();
      if (key && CJK.test(key)) {
        const translated = PR.lang === "en" ? dict[key] : zhTw[key];
        if (translated && translated !== key) n.nodeValue = raw.replace(key, translated);
      }
    }
    const elements = root.nodeType === Node.ELEMENT_NODE ? [root, ...root.querySelectorAll("*")] : root.querySelectorAll("*");
    elements.forEach((el) => { if (isUserContent(el)) return; ATTRS.forEach((a) => {
      const v = el.getAttribute(a);
      if (v && CJK.test(v)) {
        const translated = PR.lang === "en" ? dict[v.trim()] : zhTw[v.trim()];
        // zh-TW entries often intentionally map a Traditional Chinese label to itself.
        // Setting the same attribute still emits a MutationObserver record and would
        // make the DOM translator observe itself forever.
        if (translated && translated !== v) el.setAttribute(a, translated);
      }
    }); });
  };
  if (PR.lang === "en" || PR.lang === "zh-TW") {
    const translatedTitle = PR.lang === "en" ? dict[document.title] : zhTw[document.title];
    if (translatedTitle) document.title = translatedTitle;
    const watchDom = () => {
      PR.translateDom(document.body);
      if (!window.MutationObserver) return;
      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          if (mutation.type === "attributes") PR.translateDom(mutation.target);
          else mutation.addedNodes.forEach((node) => PR.translateDom(node));
        }
      });
      observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ATTRS });
    };
    if (document.body) watchDom();
    else document.addEventListener("DOMContentLoaded", watchDom, { once: true });
  }
})(window.PR);
