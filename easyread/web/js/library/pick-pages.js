/* 选页翻译（#55）：文献库详情里点“选页翻译…”，列出还没译的页，点几个页码再点“翻译”。
   只列没译的页：已经译好的不会被误点重译（要整篇重来用“全部重新翻译”）。
   i.todo 是服务端给的 "3-5,9"。Esc 或点外面关掉。 */
(function (PR) {
  "use strict";
  let cur = null;

  function pages(spec) { // "3-5,9" → [3,4,5,9]
    const out = [];
    String(spec || "").split(",").forEach((part) => {
      const [a, b] = part.split("-").map(Number);
      if (a) for (let n = a; n <= (b || a); n++) out.push(n);
    });
    return out;
  }

  function close() {
    if (!cur) return;
    document.removeEventListener("keydown", cur.onKey, true);
    document.removeEventListener("mousedown", cur.onDown, true);
    cur.box.remove();
    cur = null;
  }

  PR.pickPages = function (i, at) {
    close();
    const todo = pages(i.todo), picked = new Set();
    const box = PR.el("div", { class: "popover confirm pick-pages", role: "dialog" },
      '<div class="cf-title">' + PR.t("选几页翻译") + "</div>" +
      '<div class="cf-body">' + PR.t("这里只列还没译的 {n} 页，点页码选中。", { n: todo.length }) + "</div>" +
      '<div class="pp-grid">' + todo.map((n) => '<button class="pp-page" data-pp="' + n + '">' + n + "</button>").join("") + "</div>" +
      '<div class="cf-acts"><button class="btn sm pp-all" data-pp-all>' + PR.t("全选") + '</button><span class="pp-gap"></span>' +
      '<button class="btn sm" data-pp-cancel>' + PR.t("取消") + '</button><button class="btn sm accent" data-pp-go disabled></button></div>');
    document.body.appendChild(box);
    const go = box.querySelector("[data-pp-go]"), all = box.querySelector("[data-pp-all]");
    const sync = () => {
      box.querySelectorAll("[data-pp]").forEach((b) => b.classList.toggle("on", picked.has(+b.dataset.pp)));
      go.disabled = !picked.size;
      go.textContent = picked.size ? PR.t("翻译这 {n} 页", { n: picked.size }) : PR.t("翻译");
      all.textContent = picked.size === todo.length ? PR.t("全不选") : PR.t("全选");
    };
    sync();
    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-pp]");
      if (b) { const n = +b.dataset.pp; picked.has(n) ? picked.delete(n) : picked.add(n); return sync(); }
      if (e.target.closest("[data-pp-all]")) { if (picked.size === todo.length) picked.clear(); else todo.forEach((n) => picked.add(n)); return sync(); }
      if (e.target.closest("[data-pp-cancel]")) return close();
      if (e.target.closest("[data-pp-go]") && picked.size) {
        const spec = [...picked].sort((a, b) => a - b).join(",");
        close();
        try {
          await PR.api("/api/p/" + i.id + "/translate", { method: "POST", body: { pages: spec } });
          PR.toast(PR.t("已开始翻译")); PR.lib.load();
        } catch (err) { PR.toast(PR.esc(err.message)); }
      }
    });
    const r = at && at.getBoundingClientRect ? at.getBoundingClientRect() : null;
    const w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = Math.max(8, Math.min(innerWidth - w - 8, r ? r.left : (innerWidth - w) / 2)) + "px";
    box.style.top = (r ? (r.bottom + 6 + h > innerHeight - 8 ? Math.max(8, r.top - h - 6) : r.bottom + 6) : Math.max(8, innerHeight * 0.2)) + "px";
    requestAnimationFrame(() => box.classList.add("open"));
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } };
    const onDown = (e) => { if (!box.contains(e.target)) close(); };
    cur = { box, onKey, onDown };
    document.addEventListener("keydown", onKey, true);
    setTimeout(() => document.addEventListener("mousedown", onDown, true), 0);
  };
})(window.PR);
