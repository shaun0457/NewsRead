/* 导入：对话框（选文件 / 链接）+ 把 PDF 拖进窗口任何地方 + 在页面上直接粘贴链接。 */
(function (PR) {
  "use strict";
  const L = PR.lib;
  const dlg = PR.$("#importDlg");
  const SCOPES = [["all", "全文"], ["body", "正文（到参考文献为止）"], ["range", "指定页"]];
  // 导入后做什么：翻译成中文 / 只读英文原文（模型把版面排好，不翻译）/ 只放原页图
  const AFTER = [["translate", "翻译成中文", "后台逐页翻译，正文是中文，随时对照原文"],
    ["read", "读英文原文", "不翻译：模型只把公式、表格、段落排好，正文就是英文，比翻译省用量；想看中文了随时点“翻译成中文”"],
    ["none", "先不处理", "不用模型，阅读页先放原页图片"]];

  const pref = () => {
    const p = Object.assign({ auto: true, scope: "all", from: 1, to: 10 }, PR.ls.get("easyread-import", {}));
    if (p.scope === "first") Object.assign(p, { scope: "range", from: 1, to: p.first || 10 });  // 旧的“前几页”
    if (!p.after) p.after = p.auto ? "translate" : "none";  // 旧的“导入后翻译”勾选框
    return p;
  };
  const savePref = (p) => PR.ls.set("easyread-import", Object.assign(pref(), p));

  PR.openImport = function (ref) {
    const p = pref();
    const off = L.engine === "none";
    const after = off ? "none" : p.after;
    dlg.querySelector(".dialog").innerHTML =
      "<h2>导入论文</h2>" +
      '<div class="dropzone" id="pick">' + PR.icon("upload") + '<div class="big">选择 PDF，或拖到这里</div><div class="hint">可以一次选多个；同一个文件不会重复导入</div></div>' +
      '<div class="or">或者</div>' +
      '<label class="field"><span>链接、arXiv 编号、DOI 或论文标题</span><div class="inline"><input class="input" id="arxivRef" placeholder="2411.00640 · 10.18653/v1/N19-1423 · 论文网页链接 · 论文标题">' +
      '<button class="btn accent" id="arxivGo">导入</button></div></label>' +
      '<div class="imp-opts"><span class="imp-lbl">导入后</span><div class="seg" id="afterSeg">' + AFTER.map(([k, l, tip]) => '<button data-after="' + k + '" title="' + tip + '" class="' + (after === k ? "on" : "") + '"' + (off && k !== "none" ? " disabled" : "") + ">" + l + "</button>").join("") + "</div></div>" +
      '<div class="imp-opts' + (after === "none" ? " dim" : "") + '" id="scopeRow"><span class="imp-lbl">范围</span><div class="seg" id="scopeSeg">' + SCOPES.map(([k, l]) => '<button data-scope="' + k + '" class="' + (p.scope === k ? "on" : "") + '">' + l + "</button>").join("") + "</div>" +
      '<span class="first-n"' + (p.scope === "range" ? "" : " hidden") + '>第 <input class="input" id="pgFrom" type="number" min="1" value="' + p.from + '"> 到 <input class="input" id="pgTo" type="number" min="1" value="' + p.to + '"> 页</span></div>' +
      '<div class="imp-opts' + (after === "none" ? " dim" : "") + '" id="modelRow"><span class="imp-lbl">模型</span><select class="input" id="impModel">' +
      '<option value="">' + PR.esc(L.engineLabel || "未设置") + "</option></select>" +
      '<button class="linkish" id="impEngine" title="增删模型在设置 → 模型">管理模型</button></div>' +
      '<div class="actions"><button class="btn" id="impClose">关闭</button></div>';
    dlg.classList.add("open");
    setTimeout(() => { const i = PR.$("#arxivRef"); if (ref) i.value = ref; i.focus(); }, 50);
    fillModels(p.model);
  };

  /* 模型：默认是设置里的翻译引擎，也可以直接选“问 AI”名单里配好的模型 */
  async function fillModels(want) {
    let r;
    try { r = await PR.api("/api/chat/models"); } catch (e) { return; }
    const sel = PR.$("#impModel");
    if (!sel) return;
    // 标着“翻译”的那张卡片就是空值（用设置里的翻译配置，包括“能看图”）；对不上时才留第一项翻译引擎
    if (r.translate) sel.innerHTML = "";
    sel.insertAdjacentHTML("beforeend", (r.models || []).map((m) =>
      '<option value="' + (m.id === r.translate ? "" : PR.esc(m.id)) + '"' + (m.ready ? "" : " disabled") + ">" + PR.esc(m.label + " · " + m.source) + "</option>").join(""));
    const ok = (r.models || []).some((m) => m.id === want && m.id !== r.translate && m.ready);
    sel.value = ok ? want : "";
  }
  const close = () => dlg.classList.remove("open");
  function opts() {
    const p = pref();
    const after = L.engine === "none" ? "none" : p.after;
    const from = Math.max(1, +p.from || 1), to = Math.max(1, +p.to || from);
    const scope = p.scope === "range" ? "range:" + Math.min(from, to) + "-" + Math.max(from, to) : p.scope;
    const sel = PR.$("#impModel");
    return { translate: after !== "none", read: after === "read", scope, model: after === "none" ? "" : sel ? sel.value : "" };
  }

  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.closest("#impClose")) close();
    if (e.target.closest("#pick")) PR.$("#fileInput").click();
    if (e.target.closest("#arxivGo")) importRef(PR.$("#arxivRef").value);
    if (e.target.closest("#impEngine")) { close(); PR.openSettings(); }
    const a = e.target.closest("[data-after]");
    if (a && !a.disabled) {
      savePref({ after: a.dataset.after });
      PR.$$("[data-after]", dlg).forEach((b) => b.classList.toggle("on", b === a));
      PR.$("#scopeRow").classList.toggle("dim", a.dataset.after === "none");
      PR.$("#modelRow").classList.toggle("dim", a.dataset.after === "none");
    }
    const s = e.target.closest("[data-scope]");
    if (s) {
      savePref({ scope: s.dataset.scope });
      PR.$$("[data-scope]", dlg).forEach((b) => b.classList.toggle("on", b === s));
      PR.$(".first-n", dlg).hidden = s.dataset.scope !== "range";
    }
  });
  dlg.addEventListener("change", (e) => { if (e.target.id === "impModel") savePref({ model: e.target.value }); });
  dlg.addEventListener("input", (e) => {  // 边输边存：输完直接点“导入”也用新的页码
    if (e.target.id === "pgFrom") savePref({ from: +e.target.value || 1 });
    if (e.target.id === "pgTo") savePref({ to: +e.target.value || 1 });
  });
  dlg.addEventListener("keydown", (e) => { if (e.target.id === "arxivRef" && e.key === "Enter") importRef(e.target.value); if (e.key === "Escape") close(); });
  PR.$("#importBtn").onclick = () => PR.openImport();
  PR.$("#fileInput").addEventListener("change", (e) => { importFiles(Array.from(e.target.files)); e.target.value = ""; });

  async function importFiles(files) {
    const pdfs = files.filter((f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
    if (!pdfs.length) return PR.toast("只支持 PDF 文件");
    close();
    const o = opts();
    let last = null;
    for (const [k, f] of pdfs.entries()) {
      PR.toast("正在导入 " + (k + 1) + "/" + pdfs.length + "：" + PR.esc(f.name), null, 60000);
      try {
        const r = await PR.api("/api/import?translate=" + (o.translate ? 1 : 0) + "&read=" + (o.read ? 1 : 0) + "&model=" + encodeURIComponent(o.model) + "&scope=" + encodeURIComponent(o.scope) + "&name=" + encodeURIComponent(f.name), { method: "POST", body: f });
        last = r.id;
        if (!r.new) PR.toast("《" + PR.esc(f.name) + "》" + (r.queued ? "已重新加入准备队列" : "已经在库里了"));
      } catch (e) { PR.toast("导入失败：" + PR.esc(e.message)); }
    }
    await L.load();
    if (last) { L.select(last); PR.toast("已导入 " + pdfs.length + " 篇" + (o.read ? "，后台开始整理原文" : o.translate ? "，后台开始翻译" : ""), { label: "打开", fn: () => L.openReader(last) }, 6000); }
  }

  async function importRef(ref) {
    ref = (ref || "").trim();
    if (!ref) return;
    const btn = PR.$("#arxivGo");
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin"></span> 查找中'; }
    else PR.toast('<span class="spin"></span> 正在查找并下载 ' + PR.esc(ref), null, 60000);
    const o = opts();
    try {
      const r = await PR.api("/api/import-url", { method: "POST", body: { ref, translate: o.translate, read: o.read, model: o.model, scope: o.scope } });
      close();
      await L.load();
      L.select(r.id);
      PR.toast(r.new ? "已导入" + (o.read ? "，后台开始整理原文" : o.translate ? "，后台开始翻译" : "") : r.queued ? "已重新加入准备队列" : "这篇已经在库里了", { label: "打开", fn: () => L.openReader(r.id) }, 6000);
    } catch (e) {
      PR.toast("导入失败：" + PR.esc(e.message), null, 8000);
      if (btn) { btn.disabled = false; btn.textContent = "导入"; }
    }
  }
  PR.importRef = importRef;

  /* 在文献库页面直接 Ctrl+V 一个链接或 arXiv 编号 */
  document.addEventListener("paste", (e) => {
    if (e.target.closest("input, textarea, [contenteditable]") || PR.$(".dialog-backdrop.open")) return;
    const files = Array.from(e.clipboardData.files || []);
    if (files.length) { e.preventDefault(); return importFiles(files); }
    const t = (e.clipboardData.getData("text") || "").trim();
    if (/^(https?:\/\/\S+|(arxiv:)?\d{4}\.\d{4,5}(v\d+)?|(doi:\s*)?10\.\d{4,9}\/\S+)$/i.test(t)) { e.preventDefault(); PR.openImport(t); }
  });

  /* 拖进窗口任何地方都能导入 */
  let depth = 0;
  const overlay = PR.$("#dropOverlay");
  const hasFiles = (e) => Array.from(e.dataTransfer && e.dataTransfer.types || []).includes("Files");
  window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; depth++; overlay.classList.add("on"); });
  window.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) overlay.classList.remove("on"); });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth = 0; overlay.classList.remove("on");
    importFiles(Array.from(e.dataTransfer.files));
  });
})(window.PR);
