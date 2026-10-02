/* 迁移 / 切换 / 合并文献库前的确认窗：居中、带遮罩，“从哪 → 到哪”分两行写清楚，注意事项单列。
   PR.migrateDialog({title, from, to, meta, notes, ok}) → Promise<boolean>
   Enter 确定，Esc 或点遮罩取消。 */
(function (PR) {
  "use strict";

  function row(label, path) {
    return '<div class="mg-row"><span class="mg-tag">' + PR.esc(label) + '</span><span class="mg-path">' + PR.esc(path) + "</span></div>";
  }

  PR.migrateDialog = function (o) {
    return new Promise((done) => {
      const wrap = PR.el("div", { class: "mg-backdrop" },
        '<div class="mg" role="dialog" aria-modal="true">' +
          '<div class="mg-title">' + PR.esc(o.title) + "</div>" +
          '<div class="mg-route">' + row(PR.t("从"), o.from) + '<div class="mg-arrow">↓</div>' + row(PR.t("到"), o.to) + "</div>" +
          (o.meta ? '<div class="mg-meta">' + PR.esc(o.meta) + "</div>" : "") +
          '<ul class="mg-notes">' + o.notes.map((n) => "<li>" + PR.esc(n) + "</li>").join("") + "</ul>" +
          '<div class="mg-acts"><button class="btn" data-mg="no">' + PR.t("取消") + '</button>' +
          '<button class="btn accent" data-mg="ok">' + PR.esc(o.ok) + "</button></div>" +
        "</div>");
      const finish = (v) => {
        document.removeEventListener("keydown", onKey, true);
        wrap.classList.remove("open");
        setTimeout(() => wrap.remove(), 160);
        done(v);
      };
      const onKey = (e) => {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
        else if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); e.stopPropagation(); finish(true); }
      };
      wrap.addEventListener("click", (e) => {
        if (e.target === wrap) return finish(false);
        const b = e.target.closest("[data-mg]");
        if (b) finish(b.dataset.mg === "ok");
      });
      document.addEventListener("keydown", onKey, true);
      document.body.appendChild(wrap);
      requestAnimationFrame(() => wrap.classList.add("open"));
      wrap.querySelector('[data-mg="ok"]').focus();
    });
  };
})(window.PR);
