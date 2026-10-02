/* 当前列表或分类的引用导出；勾选只属于本次对话框，不改变文献列表。 */
(function (PR) {
  "use strict";
  const L = PR.lib, dlg = PR.$("#citeExportDlg");
  const styles = [["gb", "GB/T 7714"], ["apa", "APA"], ["bibtex", "BibTeX"]];
  let items = [], selected = new Set(), style = "gb", title = "", previousFocus = null, scope = "view", viewItems = [], viewTitle = "";
  const $ = (selector) => PR.$(selector, dlg);
  const close = () => { dlg.classList.remove("open"); if (previousFocus && previousFocus.isConnected) previousFocus.focus(); };

  function preview() {
    const chosen = items.filter((i, index) => selected.has(index));
    $("textarea").value = PR.citeBatch(chosen, style);
    $("[data-copy]").disabled = $("[data-save]").disabled = !chosen.length;
  }

  function renderRows() {
    $(".cite-items").innerHTML = items.map((i, index) => {
      const missing = PR.citeMissing(i, style);
      return '<div class="cite-row"><label><input type="checkbox" data-item="' + index + '"' + (selected.has(index) ? " checked" : "") + '><span>' + PR.esc(i.title_en || i.title_zh || PR.t("（未命名）")) + "</span></label>" +
        (missing.length ? '<span class="hint">' + PR.esc(PR.t("缺{fields}", { fields: missing.join(PR.t("、")) })) + '</span><button class="linkish" data-edit="' + index + '">' + PR.t("去补") + "</button>" : "") + "</div>";
    }).join("") || '<p class="hint">' + PR.t("没有符合条件的论文") + "</p>";
    preview();
  }

  /* 范围：打开时的列表 / 全部论文 / 某个分类，在对话框里直接切换 */
  function scopes() {
    const out = [["view", viewTitle]];
    if (viewTitle !== PR.t("全部论文")) out.push(["all", PR.t("全部论文")]);
    L.cats().filter((c) => c !== viewTitle).forEach((c) => out.push(["c:" + c, c]));
    return out;
  }
  function useScope(key) {
    scope = key;
    const all = L.items.filter((i) => !i.deleted);
    items = key === "view" ? viewItems.slice() : key === "all" ? all : all.filter((i) => (i.tags || []).includes(key.slice(2)));
    title = (scopes().find(([k]) => k === key) || [, viewTitle])[1];
    selected = new Set(items.map((i, index) => index));
    const h = $("#citeExportTitle");
    if (h) h.textContent = PR.t("导出引用 · {title}（{n} 篇）", { title, n: items.length });
  }

  PR.openCiteExport = function (papers, fromTitle) {
    viewItems = papers.slice(); viewTitle = fromTitle;
    items = viewItems.slice(); selected = new Set(items.map((i, index) => index)); title = viewTitle; scope = "view";
    const saved = PR.ls.get("easyread-cite-style", "gb");
    style = styles.some(([key]) => key === saved) ? saved : "gb";
    previousFocus = document.activeElement;
    $(".dialog").innerHTML = '<h2 id="citeExportTitle">' + PR.esc(PR.t("导出引用 · {title}（{n} 篇）", { title, n: items.length })) + '</h2><div class="seg">' +
      styles.map(([key, name]) => '<button data-style="' + key + '" class="' + (key === style ? "on" : "") + '" aria-pressed="' + (key === style) + '">' + name + "</button>").join("") + '</div>' +
      '<label class="cite-scope"><span>' + PR.t("范围") + '</span><select class="input" data-scope>' + scopes().map(([k, name]) => '<option value="' + PR.esc(k) + '"' + (k === scope ? " selected" : "") + ">" + PR.esc(name) + "</option>").join("") + "</select></label>" +
      '<div class="cite-items"></div>' +
      '<label class="field"><span>' + PR.t("预览") + '</span><textarea class="input cite-preview" rows="9" readonly spellcheck="false"></textarea></label>' +
      '<div class="actions"><button class="btn accent" data-copy>' + PR.t("复制") + '</button><button class="btn line" data-save>' + PR.t("保存为文件") + '</button><button class="btn" data-close>' + PR.t("关闭") + '</button></div><p class="hint cite-note">' +
      PR.t("引用由论文信息按格式规则生成，不经过 AI。提交前请核对作者、年份和出处。") + "</p>";
    renderRows(); dlg.classList.add("open"); $("[data-style='" + style + "']").focus();
  };

  function saveFile() {
    const date = new Date(), pad = (n) => String(n).padStart(2, "0");
    const day = date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
    const name = String(title || "references").replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").slice(0, 80).replace(/[. ]+$/, "") || "references";
    const url = URL.createObjectURL(new Blob([$("textarea").value], { type: "text/plain;charset=utf-8" }));
    const link = PR.el("a", { href: url, download: name + "-" + day + (style === "bibtex" ? ".bib" : ".txt") });
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  dlg.addEventListener("change", (e) => {
    if ((e.target.dataset || {}).scope !== undefined) { useScope(e.target.value); renderRows(); return; }
    if (e.target.dataset.item === undefined) return;
    const index = Number(e.target.dataset.item);
    if (e.target.checked) selected.add(index); else selected.delete(index);
    preview();
  });
  dlg.addEventListener("click", async (e) => {
    if (e.target === dlg || e.target.closest("[data-close]")) return close();
    const format = e.target.closest("[data-style]"), edit = e.target.closest("[data-edit]");
    if (format) {
      style = format.dataset.style; PR.ls.set("easyread-cite-style", style);
      PR.$$("[data-style]", dlg).forEach((b) => { b.classList.toggle("on", b === format); b.setAttribute("aria-pressed", String(b === format)); });
      renderRows();
    }
    if (edit) { close(); L.select(items[Number(edit.dataset.edit)].id); }
    if (e.target.closest("[data-save]") && selected.size) saveFile();
    if (e.target.closest("[data-copy]") && selected.size) {
      try { await navigator.clipboard.writeText($("textarea").value); PR.toast(PR.t("已复制引用")); }
      catch (error) { $("textarea").focus(); $("textarea").select(); PR.toast(PR.t("复制失败，请手动选中")); }
    }
  });
  dlg.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    if (e.key !== "Tab") return;
    const buttons = PR.$$("button:not(:disabled), input, textarea", dlg), first = buttons[0], last = buttons[buttons.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  const button = PR.$("#citeExportBtn");
  button.innerHTML = PR.icon("copy", "sm") + PR.t("导出引用");
  button.onclick = () => PR.openCiteExport(L.filtered(), PR.$("#viewTitle").textContent);
})(window.PR);
