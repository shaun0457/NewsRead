/* 回收站：侧栏最下面的“回收站”（有东西时才出现），点开列出删掉的论文，可以恢复、彻底删除、清空。 */
(function (PR) {
  "use strict";
  const L = PR.lib;
  const dlg = () => PR.$("#trashDlg");
  let items = [];

  async function open() {
    items = (await PR.api("/api/trash")).items;
    render();
    dlg().classList.add("open");
  }

  function render() {
    const rows = items.map((t) => '<div class="trash-row"><div class="trash-t"><b>' + PR.esc(t.title_zh || t.title_en || t.id) + "</b>" +
      "<small>" + PR.esc([t.title_zh && t.title_en ? t.title_en : "", PR.t("删除于 {t}", { t: PR.shortTime(t.deleted) })].filter(Boolean).join(" · ")) + "</small></div>" +
      '<button class="btn sm" data-tr="restore" data-name="' + PR.esc(t.name) + '">' + PR.t("恢复") + "</button>" +
      '<button class="btn sm danger" data-tr="purge" data-name="' + PR.esc(t.name) + '">' + PR.t("彻底删除") + "</button></div>").join("");
    dlg().querySelector(".dialog").innerHTML = "<h2>" + PR.t("回收站") + "</h2>" +
      (items.length ? '<div class="trash-list">' + rows + "</div>" : '<p class="hint">' + PR.t("回收站是空的。") + "</p>") +
      '<div class="actions">' + (items.length ? '<button class="btn danger" data-tr="empty">' + PR.t("清空回收站") + "</button>" : "") +
      '<span class="grow"></span><button class="btn" data-tr="close">' + PR.t("关闭") + "</button></div>";
  }

  async function act(action, name, at) {
    if (action === "purge" && !(await PR.confirm({ title: PR.t("彻底删除这篇？"), body: PR.t("论文、译文、笔记都会删掉，不能恢复。"), ok: PR.t("彻底删除"), danger: true, at }))) return;
    if (action === "empty" && !(await PR.confirm({ title: PR.t("清空回收站？"), body: PR.t("{n} 篇论文会被彻底删除，不能恢复。", { n: items.length }), ok: PR.t("清空"), danger: true, at }))) return;
    try {
      await PR.api("/api/trash", { method: "POST", body: { action, name } });
    } catch (e) { return PR.toast(PR.esc(e.message)); }
    items = action === "empty" ? [] : items.filter((t) => t.name !== name);
    render();
    await L.load();
    if (action === "restore") PR.toast(PR.t("已恢复"));
  }
  PR.restoreTrash = (name) => act("restore", name);

  dlg().addEventListener("click", (e) => {
    if (e.target === dlg()) return dlg().classList.remove("open");
    const b = e.target.closest("[data-tr]");
    if (!b) return;
    if (b.dataset.tr === "close") return dlg().classList.remove("open");
    act(b.dataset.tr, b.dataset.name, b);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && dlg().classList.contains("open")) dlg().classList.remove("open"); });
  PR.$("#side").addEventListener("click", (e) => { if (e.target.closest("[data-trash]")) open(); });
})(window.PR);
