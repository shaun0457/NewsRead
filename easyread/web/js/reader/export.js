/* 导出笔记：勾选要哪些（我的笔记、划线、我的问题、AI 的回答和解释、论文笔记、问 AI 的对话），导出 Markdown。 */
(function (PR) {
  "use strict";
  const S = PR.state;
  const KINDS = [
    ["paper", PR.t("论文笔记（整篇的感悟）")], ["note", PR.t("我的笔记")], ["highlight", PR.t("我的划线")], ["question", PR.t("我的问题")],
    ["ai", PR.t("AI 的回答和解释（页边）")], ["chat", PR.t("问 AI 的对话记录")], ["quote", PR.t("每条附上原文引用")], ["mindmap", PR.t("論文心智圖")],
  ];
  const ORDERABLE = ["paper", "note", "highlight", "question", "ai", "chat", "mindmap"];
  const DEFAULT_ORDER = [...ORDERABLE];

  function counts() {
    const notes = PR.myNotes();
    return {
      paper: (S.reader.paper_note || {}).body ? 1 : 0,
      note: notes.filter((n) => n.kind === "note" || (n.kind !== "question" && n.kind !== "highlight")).length,
      highlight: notes.filter((n) => n.kind === "highlight").length,
      question: notes.filter((n) => n.kind === "question").length,
      ai: (S.discussion.entries || []).length,
    };
  }

  PR.openExport = function () {
    const c = counts();
    const saved = PR.ls.get("easyread-export", { paper: true, note: true, highlight: true, question: true, ai: true, chat: false, quote: true, mindmap: false });
    const storedOrder = PR.ls.get("easyread-export-order", DEFAULT_ORDER);
    const savedOrder = Array.isArray(storedOrder) ? storedOrder : DEFAULT_ORDER;
    const order = [...savedOrder.filter((key) => ORDERABLE.includes(key)), ...DEFAULT_ORDER.filter((key) => !savedOrder.includes(key))];
    const labels = Object.fromEntries(KINDS.map(([key, label]) => [key, label]));
    const dlg = PR.$("#readerDlg");
    const rows = order.map((key) => '<div class="exp-row" draggable="true" data-exp-row="' + key + '"><span class="exp-grip" aria-hidden="true" title="拖曳調整順序">⠿</span><label><input type="checkbox" data-exp="' + key + '"' + (saved[key] ? " checked" : "") + ">" + labels[key] + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      (c[key] != null ? '<span class="n">' + PR.t("{n} 条", { n: c[key] }) + "</span>" : "") + '</label></div>').join("");
    const quote = KINDS.find(([key]) => key === "quote");
    dlg.querySelector(".dialog").innerHTML = "<h2>" + PR.t("匯出筆記") + "</h2><p class=\"hint exp-hint\">拖曳各項目可調整匯出順序。</p><div class=\"exp-opts\">" + rows + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      '<div class="exp-row exp-quote"><span class="exp-grip exp-grip-muted" aria-hidden="true">·</span><label><input type="checkbox" data-exp="quote"' + (saved.quote ? " checked" : "") + ">" + quote[1] + '</label></div></div><p class="hint">順序只會調整匯出的 Markdown，不會改動閱讀器中的筆記。</p>' + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      '<div class="actions"><button class="btn" data-exp-close>' + PR.t("取消") + '</button><button class="btn primary" data-exp-go>' + PR.t("匯出筆記") + '</button></div>';
    dlg.querySelector(".exp-opts").addEventListener("dragstart", (event) => {
      const row = event.target.closest("[data-exp-row]");
      if (!row) return;
      event.dataTransfer.setData("text/plain", row.dataset.expRow);
      event.dataTransfer.effectAllowed = "move";
      row.classList.add("dragging");
    });
    dlg.querySelector(".exp-opts").addEventListener("dragend", (event) => event.target.closest("[data-exp-row]")?.classList.remove("dragging"));
    dlg.querySelector(".exp-opts").addEventListener("dragover", (event) => {
      const row = event.target.closest("[data-exp-row]");
      if (!row) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });
    dlg.querySelector(".exp-opts").addEventListener("drop", (event) => {
      const target = event.target.closest("[data-exp-row]");
      const key = event.dataTransfer.getData("text/plain");
      const source = dlg.querySelector('[data-exp-row="' + CSS.escape(key) + '"]');
      if (!target || !source || target === source) return;
      event.preventDefault();
      const before = event.clientY < target.getBoundingClientRect().top + target.offsetHeight / 2;
      target.parentNode.insertBefore(source, before ? target : target.nextSibling);
      saveOrder(dlg);
    });
    dlg.classList.add("open");
  };

  function saveOrder(dlg) {
    PR.ls.set("easyread-export-order", PR.$$("[data-exp-row]", dlg).map((row) => row.dataset.expRow));
  }

  PR.$("#readerDlg").addEventListener("click", async (e) => {
    const dlg = PR.$("#readerDlg");
    if (e.target.closest("[data-exp-close]")) return dlg.classList.remove("open");
    const exportButton = e.target.closest("[data-exp-go]");
    if (!exportButton) return;
    if (exportButton.disabled) return;
    exportButton.disabled = true; exportButton.innerHTML = '<i class="spin"></i> 正在準備匯出…'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    const pick = {};
    PR.$$("[data-exp]", dlg).forEach((i) => (pick[i.dataset.exp] = i.checked));
    PR.ls.set("easyread-export", pick);
    const order = PR.$$("[data-exp-row]", dlg).map((row) => row.dataset.expRow);
    PR.ls.set("easyread-export-order", order);
    let chat = [];
    if (pick.chat) {
      let data = S.chat || {};
      if (PR.store.mode === "server") {
        try { data = await PR.api("/api/p/" + PR.pid + "/chat"); }
        catch (err) { PR.toast(PR.t("读不到对话记录：{msg}", { msg: PR.esc(err.message) })); exportButton.disabled = false; exportButton.textContent = "匯出筆記"; return; } /* i18n-dom: shared DOM translator localizes rendered UI text. */
      }
      chat = data.threads ? data.threads.flatMap((t) => t.messages || []) : data.messages || [];
    }
    let mindmap = "";
    if (pick.mindmap) {
      try {
        const id = encodeURIComponent(PR.pid), endpoint = "/api/research/v2/paper/" + id + "/mindmap";
        let result = await PR.api(endpoint);
        if (!result.mermaid) result = await PR.api(endpoint, { method: "POST", body: {} });
        if (!result.mermaid) throw new Error(PR.t("沒有取得心智圖內容。"));
        mindmap = result.mermaid;
      } catch (err) { PR.toast(PR.t("心智圖準備失敗：{message}", { message: PR.esc(err.message) })); exportButton.disabled = false; exportButton.textContent = PR.t("匯出筆記"); return; }
    }
    const text = PR.notesMarkdown(pick, chat, { order, chat, mindmap });
    const stem = ((S.paper.meta || {}).short_zh || (S.paper.meta || {}).title_zh || PR.t("论文")).replace(/[\\/:*?"<>|]/g, "");
    const filename = stem + PR.t("-笔记.md");
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({ suggestedName: filename, types: [{ description: "Markdown", accept: { "text/markdown": [".md"] } }] });
        const stream = await handle.createWritable(); await stream.write(text); await stream.close();
      } catch (err) { if (err.name !== "AbortError") PR.toast(PR.t("匯出失敗：{message}", { message: PR.esc(err.message) })); exportButton.disabled = false; exportButton.textContent = PR.t("匯出筆記"); return; }
    } else {
      const a = PR.el("a", { href: URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" })), download: filename });
      document.body.appendChild(a); a.click(); a.remove();
    }
    dlg.classList.remove("open");
  });
})(window.PR);
