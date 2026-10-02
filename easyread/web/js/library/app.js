/* 文献库：列表、筛选、排序、键盘操作、状态轮询。 */
(function (PR) {
  "use strict";
  const L = (PR.lib = { items: [], view: "all", tag: null, q: "", sort: PR.ls.get("easyread-sort", "opened"), selected: null, engine: "claude", picked: new Set(), picking: false });
  const prefs = PR.ls.get("easyread-prefs", {});
  PR.applyTheme(prefs.theme);


  PR.$("#importBtn").innerHTML = PR.icon("plus", "sm") + "<span>" + PR.t("导入论文") + "</span>";
  PR.$("#settingsBtn").innerHTML = PR.icon("gear");
  PR.$(".search .si").outerHTML = PR.icon("search", "sm");
  PR.$("#sort").value = L.sort;

  L.byId = (id) => L.items.find((i) => i.id === id);
  L.openReader = (id) => { location.href = "/read/" + id; };
  L.patch = async function (id, fields) {
    const it = L.byId(id);
    if (it) { Object.assign(it, fields.meta_override ? {} : fields); L.render(); }  // 先改界面，再存盘
    try { await PR.api("/api/p/" + id + "/item", { method: "POST", body: fields }); }
    catch (e) { PR.toast(PR.t("保存失败：{msg}", { msg: PR.esc(e.message) })); }
    await L.load();
  };

  L.load = async function () { apply(await PR.api("/api/library")); };
  function apply(d) {
    L.lastData = d;  // 切换界面语言前存一份，刷新后先拿它画列表，不闪空白（lang-toggle.js）
    PR.token = d.token;
    L.engine = d.engine;
    L.engineLabel = d.engine_label;
    L.firstRun = d.first_run;
    L.version = d.version;
    L.trashCount = d.trash || 0;
    if (PR.libraryLocationNotice) PR.libraryLocationNotice(d);
    engineChip();
    L.items = d.items;
    L.render();
    schedule();
  }

  let pollT;
  function schedule() {
    clearTimeout(pollT);
    const busy = L.items.some((i) => i.job && ["queued", "running"].includes(i.job.state));
    pollT = setTimeout(() => L.load().catch(() => schedule()), busy ? 2500 : 15000);
  }

  function filtered() {
    const view = L.VIEWS.find((v) => v[0] === L.view) || L.VIEWS[0];
    const q = L.q.trim().toLowerCase();
    let list = L.items.filter(view[3]);
    if (L.tag) list = list.filter((i) => i.tags.includes(L.tag));
    if (q) list = list.filter((i) => [i.title_zh, i.title_en, i.authors, i.venue, i.arxiv, i.abstract, (i.tags || []).join(" "), i.year]
      .join(" ").toLowerCase().includes(q));
    const key = { opened: (i) => i.last_opened || i.added, added: (i) => i.added, year: (i) => String(i.year || ""), title: (i) => PR.titles(i).main };
    const k = key[L.sort] || key.opened;
    list.sort((a, b) => (L.sort === "title" ? String(k(a)).localeCompare(String(k(b)), "zh") : String(k(b)).localeCompare(String(k(a)))));
    return list;
  }
  L.filtered = filtered;

  function statusPill(i) {
    const m = { unread: PR.t("未读"), reading: PR.t("在读"), done: PR.t("已读") };
    return '<span class="pill ' + (i.status || "unread") + '">' + (m[i.status] || m.unread) + "</span>";
  }
  L.jobLine = function (i) {
    const j = i.job;
    if (j && j.state === "confirm") return '<span class="stat">' + PR.t("等你确认") + "</span>";
    if (j && ["queued", "running"].includes(j.state)) {
      const pct = j.total ? " " + PR.t("{done}/{total} 页", { done: j.done, total: j.total }) : "";
      return '<span class="stat job"><span class="spin"></span>' + PR.esc(j.state === "queued" ? PR.t("排队中") : (j.message || PR.t("处理中"))) + pct + "</span>";
    }
    if (j && j.state === "error") return '<span class="stat err">' + PR.t("翻译出错") + "</span>";
    if (j && j.state === "partial") return '<span class="stat err">' + PR.t("{n} 页没译成功", { n: Object.keys(j.failed || {}).length }) + "</span>";
    const tr = i.done_pages - (i.en_pages || 0);
    if (i.en_pages && !tr) return '<span class="stat">' + PR.t("英文原文") + "</span>";
    if (i.pages && tr < i.pages) return '<span class="stat">' + PR.t("已译 {done}/{total} 页", { done: tr, total: i.pages }) + "</span>";
    return "";
  };

  function rowHtml(i) {
    const tt = PR.titles(i), title = tt.main;
    const sub = tt.sub ? '<div class="t2" lang="' + tt.subLang + '">' + PR.esc(tt.sub) + "</div>" : "";
    const bits = [i.authors && PR.esc(i.authors.split(",").slice(0, 3).join(",") + (i.authors.split(",").length > 3 ? PR.t(" 等") : "")), i.year, i.venue || i.arxiv].filter(Boolean);
    const tags = (i.tags || []).map((t) => '<span class="chip cat">' + PR.icon("folder", "sm") + PR.esc(t) + "</span>").join("");
    const thumb = i.thumb ? '<div class="thumb" style="background-image:url(' + i.thumb + ')"></div>' : '<div class="thumb blank">' + PR.icon("pdf") + "</div>";
    const notes = i.notes + i.highlights ? '<span class="stat">' + PR.icon("note", "sm") + (i.notes + i.highlights) + (i.open_questions ? " · " + PR.t("{n} 问待答", { n: i.open_questions }) : "") + "</span>" : "";
    const prog = i.progress ? '<div class="meter" title="' + PR.t("阅读进度 {p}%", { p: Math.round(i.progress * 100) }) + '"><i style="width:' + Math.round(i.progress * 100) + '%"></i></div>' : "";
    const picked = L.picked.has(i.id);
    return '<div class="row' + (L.selected === i.id ? " on" : "") + (picked ? " picked" : "") + '" data-id="' + i.id + '" role="option" draggable="true"' + (L.picking ? ' aria-selected="' + picked + '"' : "") + ">" +
      '<span class="pick" data-pick title="' + PR.t("勾选（批量操作）") + '">' + PR.icon("check", "sm") + "</span>" + thumb +
      '<div><div class="t1">' + (i.starred ? '<span class="star">' + PR.icon("star") + "</span>" : "") + "<span>" + PR.esc(title) + "</span></div>" + sub +
      '<div class="t3">' + bits.map((b) => "<span>" + PR.esc(String(b)) + "</span>").join("<span>·</span>") + tags + "</div></div>" +
      '<div class="side-info">' + statusPill(i) + prog + L.jobLine(i) + notes + "</div></div>";
  }

  L.render = function () {
    PR.renderSide();
    const list = filtered();
    const view = L.VIEWS.find((v) => v[0] === L.view) || L.VIEWS[0];
    PR.$("#viewTitle").textContent = L.tag ? L.tag : L.view === "all" ? PR.t("全部论文") : view[1];
    PR.$("#count").textContent = PR.t("{n} 篇", { n: list.length });
    PR.renderBatch && PR.renderBatch(list);
    PR.$("#list").innerHTML = list.length ? list.map(rowHtml).join("") : emptyHtml();
    if (L.selected && !L.byId(L.selected)) L.select(null);
    else PR.renderDetail && PR.renderDetail();
  };
  function emptyHtml() {
    if (L.items.length) return '<div class="empty-state"><div class="big">' + PR.t("没有符合条件的论文") + "</div>" + PR.t("换个关键词或筛选试试。") + "</div>";
    const ok = L.engineReady;
    return '<div class="welcome">' + PR.logo("hero") + "<h2>" + PR.t("把英文论文，读成舒服的中文") + "</h2>" +
      '<p class="sub">' + PR.t("导入 PDF，后台逐页翻译；公式、表格照原文排好，随时对照原文，边读边划线、记笔记、提问。") + "</p>" +
      '<ol class="steps">' +
      '<li class="' + (ok ? "done" : "") + '"><b>' + PR.t("选一个翻译引擎") + "</b><span>" + (ok === undefined ? '<span class="spin"></span> ' + PR.t("正在检测本机…") : ok ? PR.t("已就绪：{name}", { name: PR.esc(L.engineLabel) }) : PR.t("当前引擎还不能用，{hint}", { hint: L.engineHint || PR.t("去设置里选一个") })) + '</span><button class="btn sm ' + (ok ? "line" : "accent") + '" onclick="PR.openSettings()">' + (ok ? PR.t("换一个") : PR.t("去设置")) + "</button></li>" +
      "<li><b>" + PR.t("导入论文") + "</b><span>" + PR.t("拖进 PDF、粘贴 arXiv 链接，或者直接在这个页面按 Ctrl+V") + "</span>" +
      '<button class="btn sm accent" onclick="PR.openImport()">' + PR.icon("plus", "sm") + PR.t("导入") + "</button></li>" +
      '<li><b>' + PR.t("开始读") + "</b><span>" + PR.t("点段落出操作条，选中文字能划线、写笔记、提问；按 <kbd>?</kbd> 看快捷键") + "</span></li></ol>" +
      '<p class="try">' + PR.t("没有现成的论文？试试") + ' <button class="linkish" onclick="PR.importRef(&quot;1706.03762&quot;)">Attention Is All You Need</button></p></div>';
  }

  /* 顶栏上的引擎状态：一眼看出现在用什么翻译、能不能用 */
  async function engineChip() {
    const chip = PR.$("#engineChip");
    chip.innerHTML = '<span class="dot"></span><span>' + PR.esc(L.engineLabel || "") + "</span>";
    if (L.engineReady === undefined && !engineChip.pending) {
      engineChip.pending = true;
      const r = await PR.api("/api/engines").catch(() => null);
      engineChip.pending = false;
      L.engineReady = r ? r.ready : true;
      const f = r && r.found && r.found[L.engine];
      L.engineHint = f && !f.found ? PR.t("本机没找到 {name}", { name: L.engineLabel }) : L.engine === "openai" ? PR.t("API 还没填 Key") : "";
      L.render();
    }
    chip.classList.toggle("bad", L.engineReady === false);
    chip.title = L.engineReady === false ? PR.t("翻译引擎还不能用：{hint}（点这里设置）", { hint: L.engineHint || "" }) : PR.t("翻译引擎（点这里设置）");
  }
  PR.$("#engineChip").onclick = () => PR.openSettings();

  L.select = function (id) {
    L.selected = id;
    PR.$(".lib").classList.toggle("has-detail", !!id);
    PR.$$(".row").forEach((r) => r.classList.toggle("on", r.dataset.id === id));
    PR.renderDetail && PR.renderDetail();
  };

  /* ---------- 事件 ---------- */
  PR.$("#list").addEventListener("click", (e) => {
    const r = e.target.closest(".row");
    if (r) L.select(r.dataset.id);
  });
  /* 点列表空白处、侧栏、标题栏空白：收起右侧详情 */
  document.addEventListener("click", (e) => {
    if (!L.selected || e.target.closest(".row, #detail, .dialog-backdrop, .menu, #toast, .topbar button, .topbar input, select")) return;
    if (e.target.closest(".main, .side, .topbar")) L.select(null);
  });
  PR.$("#list").addEventListener("dblclick", (e) => { const r = e.target.closest(".row"); if (r) L.openReader(r.dataset.id); });
  PR.$("#list").addEventListener("contextmenu", (e) => {
    const r = e.target.closest(".row");
    if (!r) return;
    e.preventDefault();
    L.select(r.dataset.id);
    PR.rowMenu && PR.rowMenu(r.dataset.id, { x: e.clientX, y: e.clientY });
  });
  PR.$("#q").addEventListener("input", PR.debounce((e) => { L.q = e.target.value; L.render(); }, 120));
  PR.$("#sort").addEventListener("change", (e) => { L.sort = e.target.value; PR.ls.set("easyread-sort", L.sort); L.render(); });

  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select, [contenteditable]")) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (PR.$(".dialog-backdrop.open")) return;
    const rows = PR.$$(".row");
    const idx = rows.findIndex((r) => r.dataset.id === L.selected);
    if (e.key === "/" || (e.key === "k" && (e.ctrlKey || e.metaKey))) { e.preventDefault(); PR.$("#q").focus(); }
    else if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); const r = rows[Math.min(rows.length - 1, idx + 1)]; if (r) { L.select(r.dataset.id); r.scrollIntoView({ block: "nearest" }); } }
    else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); const r = rows[Math.max(0, idx - 1)]; if (r) { L.select(r.dataset.id); r.scrollIntoView({ block: "nearest" }); } }
    else if (e.key === "Enter" && L.selected) L.openReader(L.selected);
    else if (e.key === "Escape") L.select(null);
    else if (e.key === "s" && L.selected) { const it = L.byId(L.selected); L.patch(it.id, { starred: !it.starred }); }
  });

  PR.onSettingsSaved = () => L.load();
  // 从阅读页按“返回”回来时浏览器可能直接用缓存的旧页面：重新取一次，在读状态、进度马上更新
  window.addEventListener("pageshow", (e) => { if (e.persisted) L.load().catch(() => {}); });
  // 等侧栏、详情这些脚本都加载完再取数据：数据先到、脚本还没到时会出错
  document.addEventListener("DOMContentLoaded", () => {
    PR.loadPrefs().then((p) => { if (p.reader && p.reader.theme) PR.applyTheme(p.reader.theme); PR.useServerUi(p); L.useServerSide(p); });
    try {
      const snap = JSON.parse(sessionStorage.getItem("easyread-lib-snap") || "null");
      sessionStorage.removeItem("easyread-lib-snap");
      if (snap && Date.now() - snap.t < 15000) apply(snap.d);
    } catch (e) { /* 没有就等下面取 */ }
    L.load().catch((e) => { PR.$("#list").innerHTML = '<div class="empty-state"><div class="big">' + PR.t("连不上本地服务") + "</div>" + PR.esc(e.message) + "</div>"; });
  });
})(window.PR);
