/* 导出引用：选范围（列表 / 全部 / 分类）、选顺序（作者 / 年份 / 自己拖），勾选只属于本次对话框，不改变文献列表。 */
(function (PR) {
  "use strict";
  const L = PR.lib, dlg = PR.$("#citeExportDlg");
  const styles = [["gb", "GB/T 7714"], ["apa", "APA"], ["bibtex", "BibTeX"]];
  // 学位论文多用顺序编码制：按正文里第一次引用的先后编号，所以要能自己排
  const ORDERS = [["author", PR.t("按作者")], ["year", PR.t("按年份")], ["custom", PR.t("自己排（拖动）")]];
  let items = [], selected = new Set(), style = "gb", order = "author", title = "", previousFocus = null, scope = "view", viewItems = [], viewTitle = "", dragging = -1;
  const $ = (selector) => PR.$(selector, dlg);
  const close = () => { dlg.classList.remove("open"); if (previousFocus && previousFocus.isConnected) previousFocus.focus(); };
  const keyOf = (i, index) => i.id || "#" + index;

  function sortItems() {
    if (order === "author") items = PR.citeSort(items, style === "bibtex" ? "apa" : style);
    if (order === "year") items = items.slice().sort((a, b) => String(a.year || "9999").localeCompare(String(b.year || "9999")) || PR.citeSort([a, b], "apa").indexOf(a) * 2 - 1);
  }

  function preview() {
    const chosen = items.filter((i, index) => selected.has(keyOf(i, index)));
    $("textarea").value = PR.citeBatch(chosen, style, "keep");
    $("[data-copy]").disabled = $("[data-save]").disabled = !chosen.length;
  }

  function renderRows() {
    $(".cite-items").innerHTML = items.map((i, index) => {
      const missing = PR.citeMissing(i, style);
      return '<div class="cite-row" draggable="true" data-row="' + index + '"><span class="cite-grip" title="' + PR.t("拖动调整顺序") + '">⋮⋮</span>' +
        '<label><input type="checkbox" data-item="' + index + '"' + (selected.has(keyOf(i, index)) ? " checked" : "") + '><span>' + PR.esc(i.title_en || i.title_zh || PR.t("（未命名）")) + "</span></label>" +
        (missing.length ? '<span class="hint">' + PR.esc(PR.t("缺{fields}", { fields: missing.join(PR.t("、")) })) + '</span><button class="linkish" data-edit="' + index + '">' + PR.t("去补") + "</button>" : "") + "</div>";
    }).join("") || '<p class="hint">' + PR.t("没有符合条件的论文") + "</p>";
    preview();
  }

  /* 范围：打开时的列表 / 全部论文 / 某个分类 */
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
    selected = new Set(items.map(keyOf));
    sortItems();
    const h = $("#citeExportTitle");
    if (h) h.textContent = PR.t("导出引用 · {title}（{n} 篇）", { title, n: items.length });
  }

  const select = (attr, list, cur) => '<select class="input" ' + attr + ">" + list.map(([k, name]) => '<option value="' + PR.esc(k) + '"' + (k === cur ? " selected" : "") + ">" + PR.esc(name) + "</option>").join("") + "</select>";

  PR.openCiteExport = function (papers, fromTitle) {
    viewItems = papers.slice(); viewTitle = fromTitle; scope = "view";
    const saved = PR.ls.get("easyread-cite-style", "gb");
    style = styles.some(([key]) => key === saved) ? saved : "gb";
    const savedOrder = PR.ls.get("easyread-cite-order", "author");
    order = ORDERS.some(([key]) => key === savedOrder) ? savedOrder : "author";
    useScope("view");
    previousFocus = document.activeElement;
    const sc = scopes();
    $(".dialog").innerHTML = '<h2 id="citeExportTitle">' + PR.esc(PR.t("导出引用 · {title}（{n} 篇）", { title, n: items.length })) + "</h2>" +
      '<div class="cite-bar"><div class="seg">' + styles.map(([key, name]) => '<button data-style="' + key + '" class="' + (key === style ? "on" : "") + '" aria-pressed="' + (key === style) + '">' + name + "</button>").join("") + "</div>" +
      (sc.length > 1 ? '<label class="cite-pick"><span>' + PR.t("范围") + "</span>" + select("data-scope", sc, scope) + "</label>" : "") +
      '<label class="cite-pick"><span>' + PR.t("顺序") + "</span>" + select("data-order", ORDERS, order) + "</label></div>" +
      (sc.length > 1 ? "" : '<p class="hint cite-tip">' + PR.t("在侧栏建分类后，这里可以只导出某个分类。") + "</p>") +
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

  function setOrder(next) {
    order = next; PR.ls.set("easyread-cite-order", order);
    const sel = $("[data-order]");
    if (sel && sel.value !== order) sel.value = order;
  }

  /* 拖一行到另一行的位置：顺序自动切到“自己排” */
  PR.citeMove = function (from, to) {
    if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return;
    const [moved] = items.splice(from, 1);
    items.splice(to, 0, moved);
    setOrder("custom"); renderRows();
  };
  dlg.addEventListener("dragstart", (e) => { const row = e.target.closest && e.target.closest("[data-row]"); if (row) { dragging = Number(row.dataset.row); row.classList.add("dragging"); } });
  dlg.addEventListener("dragover", (e) => { if (dragging >= 0 && e.target.closest && e.target.closest("[data-row]")) e.preventDefault(); });
  dlg.addEventListener("drop", (e) => {
    const row = e.target.closest && e.target.closest("[data-row]");
    if (dragging < 0 || !row) return;
    e.preventDefault(); PR.citeMove(dragging, Number(row.dataset.row)); dragging = -1;
  });
  dlg.addEventListener("dragend", () => { dragging = -1; PR.$$(".cite-row.dragging", dlg).forEach((r) => r.classList.remove("dragging")); });

  dlg.addEventListener("change", (e) => {
    const data = e.target.dataset || {};
    if (data.scope !== undefined) { useScope(e.target.value); renderRows(); return; }
    if (data.order !== undefined) { setOrder(e.target.value); sortItems(); renderRows(); return; }
    if (data.item === undefined) return;
    const index = Number(data.item), key = keyOf(items[index], index);
    if (e.target.checked) selected.add(key); else selected.delete(key);
    preview();
  });
  dlg.addEventListener("click", async (e) => {
    if (e.target === dlg || e.target.closest("[data-close]")) return close();
    const format = e.target.closest("[data-style]"), edit = e.target.closest("[data-edit]");
    if (format) {
      style = format.dataset.style; PR.ls.set("easyread-cite-style", style);
      PR.$$("[data-style]", dlg).forEach((b) => { b.classList.toggle("on", b === format); b.setAttribute("aria-pressed", String(b === format)); });
      sortItems(); renderRows();
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
    const buttons = PR.$$("button:not(:disabled), input, textarea, select", dlg), first = buttons[0], last = buttons[buttons.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  const button = PR.$("#citeExportBtn");
  button.innerHTML = PR.icon("copy", "sm") + PR.t("导出引用");
  button.onclick = () => PR.openCiteExport(L.filtered(), PR.$("#viewTitle").textContent);
})(window.PR);
