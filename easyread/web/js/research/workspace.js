/* PaperRead: research discovery, candidates, and reading paths. */
(function (PR) {
  "use strict";
  const API = "/api/research/v2";
  const S = { items: [], saved: [], candidates: [], summaries: [], statuses: [], categories: [], tab: "board", mode: "topic",
    results: [], authors: [], selectedAuthor: null, resultKind: "works", resultAuthor: "", relationRequest: null, hasMore: false, error: "", errorAction: "", checked: new Set(), page: 1, filters: { category: "", status: "", interested: false, pdf: "" }, sort: "manual",
    venueQuery: "", venueOptions: [], venueSelected: [], venueWarning: "", venueBusy: false, resultFilters: null, exploreSort: "relevance_score:desc", yearFrom: "", yearTo: "", onlyOA: false, searchReason: "", filterExpanded: false };
  const esc = PR.esc;
  const $ = (sel, root) => PR.$(sel, root || document);
  const $$ = (sel, root) => PR.$$(sel, root || document);
  const byId = (id) => S.items.find((x) => x.id === id);
  const normalizeItems = (items) => (items || []).map((item) => {
    const interested = Boolean(item.starred ?? item.interested);
    return { ...item, starred: interested, interested, status: item.status === "paused" ? "unread" : item.status };
  });
  const statusLabel = (id) => (S.statuses.find((s) => s.id === id) || S.statuses[0] || { label: "待閱讀" }).label; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
  const workId = (work) => {
    const m = String(work.openalex_id || work.id || "").match(/W\d+/);
    return m ? m[0] : "";
  };
  const normalizedTitle = (w) => String(w?.title || "").normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const paperKey = (w) => w.doi ? "doi:" + String(w.doi).replace(/^https?:\/\/(dx\.)?doi\.org\//i, "").toLowerCase() : w.arxiv ? "arxiv:" + String(w.arxiv).replace(/v\d+$/i, "").toLowerCase() : workId(w) ? "openalex:" + workId(w) : "title:" + normalizedTitle(w);
  const samePaper = (a, b) => Boolean(a && b && paperKey(a) === paperKey(b));
  const candidateFor = (work) => S.candidates.find((c) => samePaper(c.paper, work));
  const savedFor = (work) => S.saved.find((item) => samePaper(item.metadata || {}, work));
  const dateText = (v) => v ? new Date(v + "T00:00:00").toLocaleDateString(PR.lang === "en" ? "en-US" : "zh-TW", { month: "numeric", day: "numeric" }) : "";
  const dayIso = (d) => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, "0"), String(d.getDate()).padStart(2, "0")].join("-");
  const escAttr = (v) => esc(v).replace(/'/g, "&#39;");
  const btn = (label, action, cls = "line", attrs = "") => '<button class="btn sm ' + cls + '" data-action="' + action + '" ' + attrs + '>' + label + "</button>";
  function uniqueQueryTerms(lines) {
    const seen = new Set(), output = [];
    for (const token of lines.join(" ").split(/\s+/).filter(Boolean)) {
      const key = token.normalize("NFKC").toLocaleLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
      if (!key || seen.has(key)) continue;
      seen.add(key); output.push(token);
    }
    return output.join(" ");
  }

  async function init() {
    try {
      const lib = await PR.api("/api/library");
      PR.token = lib.token;
      const data = await PR.api(API);
      Object.assign(S, { items: normalizeItems(data.items), saved: data.saved || [], candidates: data.candidates || [], summaries: data.summaries || [], statuses: (data.statuses || []).filter((x) => x.id !== "paused"), categories: data.categories || [] });
      paint();
      if (S.query) await search();
      poll();
    } catch (e) {
      const alerts = $("#rw-alerts");
      if (alerts) alerts.innerHTML = '<div class="rw-error" role="alert">' + PR.t("無法載入研究工作區：{message}", { message: PR.t(e.message) }) + ' <a class="linkish" href="/research">' + PR.t("重試") + '</a></div>';
      const board = $("[data-view='board']");
      if (board) board.innerHTML = '<div class="rw-empty">' + PR.t("研究工作區暫時無法載入。") + '</div>';
    }
  }
  function poll() {
    clearTimeout(S.poll);
    S.poll = setTimeout(async () => {
      try {
        const lib = await PR.api("/api/library");
        const data = await PR.api(API);
        S.items = normalizeItems(lib.items || data.items); S.saved = data.saved || []; S.candidates = data.candidates || S.candidates; S.summaries = data.summaries || S.summaries;
        S.statuses = (data.statuses || S.statuses).filter((x) => x.id !== "paused");
        if (document.activeElement?.closest(".rw-view") && document.activeElement.matches("input,select,textarea")) S.pendingRender = true;
        else renderActive();
      } catch (_) { /* keep last known view while the local service reconnects */ }
      poll();
    }, 7000);
  }
  function paint() {
    $$(".rw-tabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === S.tab));
    $$(".rw-view").forEach((v) => { v.hidden = v.dataset.view !== S.tab; });
    renderActive();
    $("[data-count='active']").textContent = allTasks().filter((i) => i.status !== "done").length || "";
    $("[data-count='candidates']").textContent = S.candidates.length || "";
    $("[data-count='summaries']").textContent = S.summaries.length || "";
  }
  function renderActive() {
    ({ explore: renderExplore, candidates: renderCandidates, summaries: renderSummaries, board: renderBoard, path: renderPath }[S.tab] || renderExplore)();
    $("[data-count='active']").textContent = allTasks().filter((i) => i.status !== "done").length || "";
    $("[data-count='candidates']").textContent = S.candidates.length || "";
    $("[data-count='summaries']").textContent = S.summaries.length || "";
  }
  function switchTab(tab) {
    S.tab = tab;
    $$(".rw-tabs [data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    $$(".rw-view").forEach((v) => { v.hidden = v.dataset.view !== tab; });
    renderActive();
  }
  function renderExplore() {
    const host = $("[data-view='explore']");
    const modeButtons = [["topic", "主題探索"], ["conference", "會議／期刊"]] // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
      .map(([id, label]) => '<button data-mode="' + id + '" class="' + (S.mode === id ? "on" : "") + '">' + label + "</button>").join("");
    let extra = "";
    if (S.mode === "conference") extra = '<span class="rw-source">可輸入一個或多個來源，例如 ICCV、ECCV、CVPR。</span>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    let html = '<div class="rw-panel"><form class="rw-toolbar" id="rw-search"><div class="rw-mode">' + modeButtons + '</div>' +
      '<input class="rw-search" id="rw-query" placeholder="' + (S.mode === "conference" ? "研究主題或關鍵字（可留空）" : "輸入研究概念或問題") + '" value="' + escAttr(S.query || "") + '">' + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      '<input id="rw-year-from" type="number" min="1800" max="2100" aria-label="起始年份" placeholder="起始年" value="' + escAttr(S.yearFrom || "") + '" style="width:94px"><input id="rw-year-to" type="number" min="1800" max="2100" aria-label="結束年份" placeholder="結束年" value="' + escAttr(S.yearTo || "") + '" style="width:94px"><label class="rw-check"><input type="checkbox" id="rw-oa"' + (S.onlyOA ? " checked" : "") + '>有公開 PDF</label><select id="rw-sort"><option value="relevance_score:desc"' + (S.exploreSort === "relevance_score:desc" ? " selected" : "") + '>相關性</option><option value="publication_date:desc"' + (S.exploreSort === "publication_date:desc" ? " selected" : "") + '>最新</option><option value="cited_by_count:desc"' + (S.exploreSort === "cited_by_count:desc" ? " selected" : "") + '>引用數</option></select>' + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      (S.mode === "topic" ? '<button class="btn line" type="button" data-action="ai-query">AI 擴展搜尋詞</button>' : '') + '<button class="btn accent" type="submit">搜尋</button></form>' + renderSourceFilter() + (S.mode === "conference" ? extra + '<div class="rw-source">' + PR.t("OpenAlex 書目資料可用於篩選出版來源；需核對正式出版狀態時，卡片會保留可查證的來源與 DOI 資訊。") + '</div>' : '<div class="rw-source">' + PR.t("主題搜尋以 OpenAlex 公開書目資料為基礎；引用關係的涵蓋範圍依資料來源而異。") + '</div>') + '</div>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    if (S.error) html += '<div class="rw-error">' + esc(S.error) + ' <button class="linkish" data-action="' + escAttr(S.errorAction || "retry-search") + '">重試</button></div>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    if (S.stale) html += '<div class="rw-stale"><span>' + PR.t("目前顯示上次成功取得的結果。") + '</span> ' + esc(S.staleError || "") + "</div>"; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    if (S.warning) html += '<div class="rw-stale">' + esc(S.warning) + "</div>"; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    if (S.loadingSearch) html += '<div class="rw-results" aria-live="polite">' + Array.from({ length: 6 }, () => '<article class="rw-card rw-paper rw-skeleton"><i></i><i></i><i></i></article>').join("") + '</div><p class="rw-source">正在查詢論文來源…</p>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    if (S.results.length) html += '<div class="rw-toolbar"><span class="rw-source">' + PR.t("合併後 {n} 篇", { n: S.resultCount == null ? S.results.length : S.resultCount }) + ' · ' + esc(S.checkedAt || "") + '</span><span class="grow"></span>' + Object.entries(S.providerStatus || {}).map(([name, status]) => '<span class="rw-provider ' + escAttr(status) + '">' + esc(name) + ': ' + PR.t(status === "loading" ? "查詢中" : status === "failed" ? "未連線" : "完成") + '</span>').join("") + '</div><div class="rw-results">' + S.results.map(workCard).join("") + "</div>" + (S.hasMore && S.page < 100 ? '<div class="rw-toolbar" style="justify-content:center;margin-top:16px">' + btn("載入更多論文", "next-page") + "</div>" : ""); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    else if (!S.error && !S.loadingSearch) html += '<div class="rw-empty">' + (S.searchReason === "not-found" ? "找不到此 DOI 或論文識別資料；請確認輸入內容，或改用標題關鍵字搜尋。" : "輸入研究概念開始探索論文。") + "</div>"; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    host.innerHTML = html;
  }
  function renderSourceFilter() {
    const selected = new Set(S.venueSelected.map((s) => s.id));
    const types = { conference: "會議", journal: "期刊", "book series": "書籍系列", repository: "典藏庫", "ebook platform": "電子書平台" }; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    const choices = S.venueOptions.map((s) => '<label class="rw-source-option"><input type="checkbox" data-source-choice="' + escAttr(s.id) + '"' + (selected.has(s.id) ? " checked" : "") + '><span>' + esc(s.name) + '<small>' + esc((s.matched_queries || []).join(" / ")) + ' · ' + esc(PR.t(types[s.type] || s.type || "來源類型未提供")) + ' · ' + esc(PR.t("OpenAlex 收錄 {n} 篇", { n: s.works_count == null ? PR.t("未提供") : s.works_count.toLocaleString() })) + '</small></span></label>').join(""); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    return '<div class="rw-source-filter"><label for="rw-venue-query">出版來源</label><input id="rw-venue-query" value="' + escAttr(S.venueQuery) + '" placeholder="ICCV、ECCV、CVPR"><button type="button" class="btn sm line" data-action="search-sources"' + (S.venueBusy ? " disabled" : "") + '>' + PR.t(S.venueBusy ? "正在查找…" : "加入出版來源") + '</button><span class="rw-source">' + PR.t("已選 {n} 個來源", { n: S.venueSelected.length }) + '</span>' + (S.venueSelected.length ? btn("清除選取", "clear-source", "line") : "") + '</div>' + (choices ? '<div class="rw-source-options">' + choices + '</div>' : "") + (S.venueWarning ? '<div class="rw-stale">' + esc(S.venueWarning) + '</div>' : ""); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
  }
  function alreadyInLibrary(w) {
    const doi = String(w.doi || "").replace(/^https?:\/\/(dx\.)?doi\.org\//i, "").toLowerCase();
    const arxiv = String(w.arxiv || "").replace(/v\d+$/i, "").toLowerCase();
    const openalex = String(w.openalex_id || w.id || "").replace(/\/$/, "").toLowerCase();
    return S.items.find((i) => doi && String(i.doi || "").replace(/^https?:\/\/(dx\.)?doi\.org\//i, "").toLowerCase() === doi || arxiv && String(i.arxiv || "").replace(/v\d+$/i, "").toLowerCase() === arxiv || openalex && String(i.openalex_id || "").replace(/\/$/, "").toLowerCase() === openalex);
  }
  function workCard(w) {
    const key = paperKey(w), inCandidate = Boolean(candidateFor(w));
    const citations = w.cited_by_count == null ? PR.t("引用數未提供") : PR.t("引用 {n}", { n: Number(w.cited_by_count).toLocaleString() }); // i18n-ok: Research 工作區依產品規格固定使用繁體中文。
    const metadata = [w.authors, w.year, w.venue, citations].filter(Boolean).map(esc).join(" · ");
    return '<article class="rw-card rw-paper"><h3>' + esc(w.title) + '</h3><div class="meta">' + metadata + '</div><div>' + (w.pdf_url ? '<span class="rw-chip oa">有公開 PDF</span>' : w.is_oa ? '<span class="rw-chip">可公開取用，PDF 未確認</span>' : '<span class="rw-chip">公開 PDF 未確認</span>') + (w.publication_type ? '<span class="rw-chip">書目類型：' + esc(w.publication_type) + '</span>' : "") + (inCandidate ? '<span class="rw-chip">候選論文</span>' : "") + '</div><p class="abstract">' + esc(w.abstract || "來源未提供摘要。") + '</p>' + (w.recommendation_reason ? '<div class="rw-source"><span>' + PR.t("推薦依據：") + '</span> ' + esc(w.recommendation_reason) + '</div>' : "") + '<div class="rw-source"><span>' + PR.t("資料來源：") + '</span> ' + esc((w.sources || [w.source || "OpenAlex"]).join("、")) + ' · ' + esc(S.checkedAt || "") + '</div><div class="actions">' + btn(inCandidate ? "移出候選" : "加入候選", "candidate", inCandidate ? "line" : "accent", 'data-key="' + escAttr(key) + '"') + (w.url ? '<a class="btn sm line" target="_blank" rel="noopener" href="' + escAttr(w.url) + '">論文來源</a>' : "") + "</div></article>"; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
  }
  function renderCandidates() {
    const host = $("[data-view='candidates']"), records = S.candidates || [];
    host.innerHTML = '<div class="rw-section-head"><div><h2>候選論文</h2><p>加入候選後會在背景自動整理摘要；加入閱讀看板仍由你決定。</p></div><button class="btn line" data-tab="path">規劃閱讀路徑</button></div>' + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      (records.length ? '<div class="rw-results">' + records.map((record) => {
        const w = record.paper || {}, paper = alreadyInLibrary(w), id = paper?.id || "";
        const summaryControl = record.summary_markdown
          ? btn("查看摘要", "view-summary", "accent", 'data-key="' + escAttr(record.paper_key) + '"') + btn("重新整理摘要", "candidate-summary", "line", 'data-key="' + escAttr(record.paper_key) + '" data-force-summary="1"') + btn("匯出摘要", "download-summary", "line", 'data-key="' + escAttr(record.paper_key) + '"') /* i18n-dom: shared DOM translator localizes rendered UI text. */
          : record.summary_status === "failed"
            ? '<span class="rw-state">' + PR.t("摘要整理失敗：{message}", { message: PR.t(record.summary_error || "請重試。") }) + '</span>' + btn("重試整理摘要", "retry-summary", "line", 'data-key="' + escAttr(record.paper_key) + '"') /* i18n-dom: shared DOM translator localizes rendered UI text. */
          : ["queued", "running"].includes(record.summary_status)
            ? '<span class="rw-state" role="status"><i class="spin"></i> ' + (record.summary_status === "running" ? "AI 正在整理摘要…" : "已加入背景摘要佇列…") + '</span>' /* i18n-dom: shared DOM translator localizes rendered UI text. */
            : btn("整理摘要", "retry-summary", "line", 'data-key="' + escAttr(record.paper_key) + '"'); /* i18n-dom: shared DOM translator localizes rendered UI text. */
        return '<article class="rw-card rw-paper"><h3>' + esc(w.title || "未命名論文") + '</h3><div class="meta">' + esc([w.authors, w.year, w.venue].filter(Boolean).join(" · ")) + '</div><p class="abstract">' + esc(w.abstract || "來源未提供摘要。") + '</p>' + (record.summary_markdown ? '<span class="rw-chip">已整理摘要</span>' : '') + '<div class="actions">' + summaryControl + (id ? '<a class="btn sm line" href="/read/' + escAttr(id) + '">開啟閱讀</a>' : btn("加入閱讀看板", "queue", "line", 'data-key="' + escAttr(record.paper_key) + '"')) + btn("移出候選", "remove-candidate", "line", 'data-key="' + escAttr(record.paper_key) + '"') + '</div></article>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
      }).join("") + '</div>' : '<div class="rw-empty">候選清單目前是空的。先到研究探索搜尋，再按「加入候選」。</div>'); /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  function renderSummaries() {
    const host = $("[data-view='summaries']"), records = S.summaries || [];
    host.innerHTML = '<div class="rw-section-head"><div><h2>已整理摘要</h2><p>整理結果會獨立保存；論文移出候選清單後，摘要仍會保留。</p></div></div>' + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      (records.length ? '<div class="rw-results">' + records.map((record) => '<article class="rw-card rw-paper"><h3>' + esc(record.paper.title || "未命名論文") + '</h3><div class="meta">' + esc([record.paper.authors, record.paper.year, record.paper.venue].filter(Boolean).join(" · ")) + '</div><span class="rw-chip">已整理摘要</span><div class="rw-source"><span>' + PR.t("整理模型：") + '</span>' + esc(record.summary_model || "未提供") + (record.updated ? ' · ' + esc(record.updated) : '') + '</div><div class="actions">' + btn("查看摘要", "view-summary", "accent", 'data-key="' + escAttr(record.paper_key) + '"') + btn("匯出摘要", "download-summary", "line", 'data-key="' + escAttr(record.paper_key) + '"') + btn("移到回收站", "trash-summary", "line", 'data-key="' + escAttr(record.paper_key) + '"') + '</div></article>').join("") + '</div>' : '<div class="rw-empty">目前還沒有摘要。加入候選論文後會在背景自動整理摘要。</div>'); /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  function renderPath() {
    const host = $("[data-view='path']");
    const start = new URLSearchParams(location.search);
    const topic = S.pathTopic || (start.get("mode") === "paper" ? "" : start.get("q") || "");
    const goal = S.pathGoal || "建立主題脈絡並找出延伸方向"; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    const startTitle = start.get("start_title") || start.get("title") || "";
    host.innerHTML = '<section class="rw-panel"><h2>規劃論文閱讀路徑</h2><p class="rw-source">以研究主題或目前論文為起點，AI 只會排序已取得的論文，並說明每篇的閱讀用途。</p><div class="rw-form-grid"><label class="rw-field"><span>研究主題</span><input id="rw-path-topic" value="' + escAttr(topic) + '" placeholder="例如：Long Video Understanding"></label><label class="rw-field"><span>研究目標</span><input id="rw-path-goal" value="' + escAttr(goal) + '" placeholder="建立先備知識、理解方法或探索方向"></label>' + (startTitle ? '<div class="rw-field wide"><span>起點論文</span><strong>' + esc(startTitle) + '</strong></div>' : '') + '</div><button class="btn accent" data-action="generate-path"' + (S.pathLoading ? ' disabled' : '') + '>' + (S.pathLoading ? '<i class="spin"></i> AI 正在整理閱讀順序…' : '產生閱讀路徑') + '</button></section>' + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      (S.pathError ? '<div class="rw-error">' + esc(S.pathError) + ' ' + btn("重試", "generate-path") + '</div>' : '') + (S.pathResults?.length ? '<div class="rw-path-list">' + S.pathResults.map((step, index) => '<article class="rw-card rw-path-card"><span class="rw-path-index">' + (index + 1) + '</span><div><span class="rw-chip">' + esc(step.role) + '</span><h3>' + esc(step.paper.title) + '</h3><p class="meta">' + esc([step.paper.year, step.paper.venue, step.paper.authors].filter(Boolean).join(" · ")) + '</p><p>' + esc(step.reason || "未提供推薦理由。") + '</p><p class="rw-source">' + PR.t("根據已搜尋的論文資料排序；來源：{source}", { source: esc(step.paper.source || "OpenAlex") }) + '</p><div class="actions">' + btn("加入候選", "candidate", "line", 'data-key="' + escAttr(paperKey(step.paper)) + '" data-paper-index="' + index + '"') + (alreadyInLibrary(step.paper) ? '<a class="btn sm line" href="/read/' + escAttr(alreadyInLibrary(step.paper).id) + '">開啟閱讀</a>' : "") + '</div></div></article>').join("") + '</div>' : ""); /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  function savedTask(s) { return { id: "saved:" + s.paper_key, saved_key: s.paper_key, paper_ref: s.paper_key, title: s.metadata.title, authors: s.metadata.authors, year: s.metadata.year, status: s.status, tags: s.categories || (s.category ? [s.category] : []), interested: s.interested, pdf_state: s.pdf_state, pdf_error: s.pdf_error, progress: 0, manual_order: s.manual_order || 0, saved: true, metadata: s.metadata }; }
  const taskRef = (item) => "paper:" + (item.saved_key || item.paper_ref || item.id);
  function allTasks() { return [...S.items, ...S.saved.filter((x) => x.pdf_state !== "imported").map(savedTask)]; }
  function renderBoard() {
    const host = $("[data-view='board']"), all = allTasks();
    const category = S.filters.category, status = S.filters.status;
    let list = all.filter((i) => (!category || (i.tags || []).includes(category)) && (!status || i.status === status) && (!S.filters.interested || i.interested) && (!S.filters.pdf || (S.filters.pdf === "missing" ? i.saved || !(i.pages > 0) : i.pages > 0)));
    if (S.sort === "recent") list.sort((a,b) => String(b.last_opened || b.added || "").localeCompare(String(a.last_opened || a.added || "")));
    else list.sort((a,b) => Number(a.manual_order || 0)-Number(b.manual_order || 0));
    S.boardVisible = list;
    const columns = S.statuses.map((s) => '<section class="rw-column" data-column="' + escAttr(s.id) + '" style="--col:' + escAttr(s.color) + '"><div class="rw-column-head"><i class="dot"></i>' + esc(s.label) + '<span class="n">' + list.filter((x) => (x.status || "unread") === s.id).length + '</span><button class="linkish" data-action="add-column" title="新增狀態">＋</button></div>' + list.filter((x) => (x.status || "unread") === s.id).map(taskCard).join("") + '</section>').join(""); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    const activeFilter = Boolean(category || status || S.filters.interested || S.filters.pdf);
    const activeLabels = [category && category, status && PR.t(statusLabel(status)), S.filters.pdf && PR.t(S.filters.pdf === "missing" ? "待補 PDF" : "已有 PDF"), S.filters.interested && PR.t("感興趣")].filter(Boolean); /* i18n-dom: shared DOM translator localizes rendered UI text. */
    host.innerHTML = '<div class="rw-board-tools"><details class="rw-filter-details"' + (S.filterExpanded ? " open" : "") + '><summary><span class="rw-filter-title">篩選條件</span>' + (activeLabels.length ? '<span class="rw-filter-count">' + activeLabels.length + ' 項已套用</span><span class="rw-filter-active">' + activeLabels.map(esc).join(" · ") + '</span>' : '<span class="rw-filter-active">依分類、狀態、PDF 或感興趣篩選</span>') + '<span class="rw-filter-chevron" aria-hidden="true">⌄</span></summary><div class="rw-filter-content"><label class="rw-filter-field"><span>分類</span><select data-filter="category" aria-label="依分類篩選"><option value="">所有分類</option>' + S.categories.map((c) => '<option value="' + escAttr(c) + '"' + (category === c ? " selected" : "") + '>' + esc(c) + '</option>').join("") + '</select></label><label class="rw-filter-field"><span>閱讀狀態</span><select data-filter="status" aria-label="依閱讀狀態篩選"><option value="">所有狀態</option>' + S.statuses.map((s) => '<option value="' + escAttr(s.id) + '"' + (status === s.id ? " selected" : "") + '>' + esc(s.label) + '</option>').join("") + '</select></label><label class="rw-filter-field"><span>PDF</span><select data-filter="pdf" aria-label="依 PDF 狀態篩選"><option value="">PDF 狀態不限</option><option value="missing"' + (S.filters.pdf === "missing" ? " selected" : "") + '>待補 PDF</option><option value="ready"' + (S.filters.pdf === "ready" ? " selected" : "") + '>已有 PDF</option></select></label><button type="button" class="rw-filter-chip' + (S.filters.interested ? ' on' : '') + '" data-action="toggle-interested-filter" aria-pressed="' + S.filters.interested + '"><span aria-hidden="true">★</span> ' + PR.t("感興趣") + '</button><label class="rw-filter-field rw-sort-field"><span>排序</span><select data-sort><option value="manual">手動優先序</option><option value="recent"' + (S.sort === "recent" ? " selected" : "") + '>最近閱讀</option></select></label>' + (activeFilter ? btn("清除篩選", "clear-filters", "line") : "") + '</div></details>' + btn("管理狀態", "manage-status", "line") + '</div><div class="rw-board">' + (columns || "") + '</div>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    host.querySelector(".rw-filter-details").addEventListener("toggle", (event) => { S.filterExpanded = event.currentTarget.open; });
    if (!list.length) host.innerHTML += '<div class="rw-empty">看板目前沒有符合條件的論文。' + btn("從論文探索加入", "go-explore") + '</div>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
  }
  function taskCard(i) {
    const percent = Math.round(Math.max(0, Math.min(1, Number(i.progress || 0))) * 100);
    const categories = (i.tags || []).join("、"); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    const title = i.saved ? i.title : (i.title_zh || i.title_en || "未命名論文"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
    const accessibleLabel = PR.t("論文：{title}。閱讀狀態：{status}。可拖曳移動；也可按 Alt 加左右方向鍵變更狀態。", { title, status: PR.t(statusLabel(i.status || "unread")) });
    return '<article class="rw-task" draggable="true" tabindex="0" aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight" aria-label="' + escAttr(accessibleLabel) + '" data-task="' + escAttr(i.id) + '" data-saved="' + (i.saved ? "1" : "0") + '"><h3>' + (i.saved ? esc(i.title) : '<a href="/read/' + escAttr(i.id) + '">' + esc(title) + '</a>') + '</h3><div class="muted">' + esc(i.authors || "作者未提供") + (i.year ? " · " + esc(i.year) : "") + '</div>' + (categories ? '<div class="muted"><span>' + PR.t("分類：") + '</span> ' + esc(categories) + '</div>' : "") + (i.saved ? '<div class="muted">' + (i.pdf_state === "failed" ? "待補 PDF" : i.pdf_state === "running" ? "正在下載 PDF" : "等待 PDF") + '</div>' : '<div class="rw-progress" title="' + escAttr(PR.t("閱讀進度 {n}%", { n: percent })) + '"><i style="width:' + percent + '%"></i></div><div class="muted">' + PR.t("閱讀進度 {n}%", { n: percent }) + '</div>') + '<div class="task-line">' + (i.saved ? '<button class="linkish" data-action="attach-pdf" data-key="' + escAttr(i.saved_key) + '">附加 PDF</button>' : '') + (i.saved && i.pdf_state === "failed" ? '<button class="linkish" data-action="retry-pdf" data-key="' + escAttr(i.saved_key) + '">重試 PDF</button>' : '') + '<button class="linkish interest-star' + (i.interested ? ' is-interested' : '') + '" aria-label="' + escAttr(PR.t(i.interested ? "取消感興趣" : "標記感興趣")) + '" title="' + escAttr(PR.t(i.interested ? "取消感興趣" : "標記感興趣")) + '" data-action="interested" data-task-id="' + escAttr(i.id) + '"' + (i.saved ? ' data-saved-key="' + escAttr(i.saved_key) + '"' : "") + '>' + (i.interested ? "★" : "☆") + '</button></div></article>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
  }
  function rememberExploreInputs() {
    const fields = { "rw-query": "query", "rw-venue-query": "venueQuery", "rw-year-from": "yearFrom", "rw-year-to": "yearTo", "rw-sort": "exploreSort" };
    for (const [id, key] of Object.entries(fields)) if ($("#" + id)) S[key] = $("#" + id).value;
    if ($("#rw-oa")) S.onlyOA = $("#rw-oa").checked;
  }
  async function searchSources() {
    if (S.venueBusy) return;
    rememberExploreInputs();
    const query = $("#rw-venue-query")?.value?.trim() || "";
    S.venueQuery = query;
    S.errorAction = "retry-source";
    if (!query) { S.error = "請輸入期刊或會議名稱。"; return renderExplore(); } // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    S.venueBusy = true; renderExplore();
    try {
      const r = await PR.api(API + "/search?kind=sources&q=" + encodeURIComponent(query));
      S.venueOptions = r.results || []; S.venueWarning = r.warning || "";
      const selected = new Map(S.venueSelected.filter((s) => S.venueOptions.some((candidate) => candidate.id === s.id)).map((s) => [s.id, s]));
      S.venueOptions.filter((s) => s.suggested).forEach((s) => selected.set(s.id, s));
      S.venueSelected = Array.from(selected.values());
      if (r.stale) S.venueWarning = [S.venueWarning, r.error, "目前顯示上次成功取得的來源清單。"].filter(Boolean).join(" "); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
      S.error = S.venueOptions.length ? "" : "找不到相符的出版來源。"; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
      S.errorAction = "retry-search";
    } catch (e) { S.error = e.message; if (S.venueOptions.length) S.venueWarning = "出版來源查詢未完成，保留先前結果。"; } // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    finally { S.venueBusy = false; rememberExploreInputs(); }
    renderExplore();
  }
  async function search() {
    rememberExploreInputs();
    const requestId = S.searchRequestId = (S.searchRequestId || 0) + 1;
    const previous = { results: S.results, authors: S.authors, resultCount: S.resultCount, authorCount: S.authorCount,
      checkedAt: S.checkedAt, lastQuery: S.lastQuery, resultKind: S.resultKind, resultAuthor: S.resultAuthor,
      relationRequest: S.relationRequest, relation: S.relation, stale: S.stale, staleError: S.staleError, warning: S.warning, page: S.page, authorPage: S.authorPage, searchReason: S.searchReason, resultFilters: S.resultFilters, hasMore: S.hasMore };
    S.error = ""; S.errorAction = ""; S.stale = false; S.warning = ""; S.searchReason = ""; S.relation = false; S.relationRequest = null; S.results = []; S.authors = []; S.page = 1; S.loadingSearch = true;
    const query = String(S.query || "").trim();
    renderExplore();
    try {
        S.resultKind = "works"; S.resultAuthor = "";
        if (!query && S.venueSelected.length && S.exploreSort === "relevance_score:desc") S.exploreSort = "publication_date:desc";
        const realSourceIds = S.venueSelected.map((source) => String(source.id || "").match(/S\d+$/)?.[0]).filter(Boolean);
        const hasManualVenue = S.mode === "conference" && S.venueSelected.some((source) => String(source.id || "").startsWith("venue:"));
        const venueTerms = Array.from(new Set(S.venueSelected.flatMap((source) => source.matched_queries?.length ? source.matched_queries : [source.name]).filter(Boolean)));
        const p = new URLSearchParams({ kind: "works", q: query, page: "1", sort: S.exploreSort, year_from: S.yearFrom, year_to: S.yearTo, open_access: S.onlyOA ? "1" : "0" });
        if (realSourceIds.length) p.set("source_ids", realSourceIds.join("|"));
        S.resultFilters = Object.fromEntries(p); S.lastQuery = query;
        const providers = [];
        if (S.mode !== "conference" || !S.venueSelected.length || realSourceIds.length) providers.push({ name: "OpenAlex", url: API + "/search?" + p });
        if (S.mode === "conference" && S.venueSelected.length) {
          const venueParams = { q: query, venues: venueTerms.join("|"), year_from: S.yearFrom, year_to: S.yearTo, page: "1" };
          providers.push({ name: "DBLP", url: API + "/search?" + new URLSearchParams({ kind: "dblp", ...venueParams }) });
          providers.push({ name: "Crossref", url: API + "/search?" + new URLSearchParams({ kind: "crossref", ...venueParams }) });
        }
        if (!providers.length) throw new Error("請先輸入研究主題，或選擇至少一個出版來源。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
        S.providerStatus = Object.fromEntries(providers.map((provider) => [provider.name, "loading"]));
        S.providerErrors = [];
        const settled = await Promise.all(providers.map(async (provider) => {
          try {
            const result = await PR.api(provider.url);
            if (requestId !== S.searchRequestId) return { ok: false };
            S.providerStatus[provider.name] = "done";
            mergeResults(result.results || [], provider.name);
            S.resultCount = S.results.length;
            S.checkedAt = result.checked_at || S.checkedAt;
            if (result.warning) S.providerErrors.push(provider.name + "：" + result.warning); /* i18n-dom: shared DOM translator localizes rendered UI text. */
            renderExplore();
            return { ok: true, result };
          } catch (error) {
            if (requestId !== S.searchRequestId) return { ok: false };
            S.providerStatus[provider.name] = "failed";
            S.providerErrors.push(provider.name + "：" + error.message); /* i18n-dom: shared DOM translator localizes rendered UI text. */
            renderExplore();
            return { ok: false, error };
          }
        }));
        if (requestId !== S.searchRequestId) return;
        if (!settled.some((x) => x.ok)) throw new Error(S.providerErrors.join("；") || "所有論文來源目前都無法連線。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
        S.resultCount = S.results.length;
        S.hasMore = settled.some((x) => x.result?.has_more);
        S.page = 1;
        if (S.providerErrors.length) S.warning = "部分來源未能回應，已先顯示成功取得的結果：" + S.providerErrors.join("；"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
    } catch (e) {
      if (requestId !== S.searchRequestId) return;
      S.error = e.message;
      S.results = previous.results; S.authors = previous.authors; S.resultCount = previous.resultCount; S.authorCount = previous.authorCount;
      S.checkedAt = previous.checkedAt; S.lastQuery = previous.lastQuery; S.resultKind = previous.resultKind; S.resultAuthor = previous.resultAuthor;
      S.relationRequest = previous.relationRequest; S.relation = previous.relation; S.warning = previous.warning; S.page = previous.page; S.authorPage = previous.authorPage; S.searchReason = previous.searchReason;
      S.resultFilters = previous.resultFilters;
      S.hasMore = previous.hasMore;
      if (S.results.length || S.authors.length) {
        S.stale = true;
        S.staleError = "本次搜尋未完成，保留先前結果" + (previous.lastQuery && previous.lastQuery !== query ? "（先前查詢：「" + previous.lastQuery + "」）" : "") + "。"; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
      } else { S.stale = previous.stale; S.staleError = previous.staleError; }
    }
    if (requestId === S.searchRequestId) { S.loadingSearch = false; renderExplore(); }
  }
  function mergeResults(incoming, provider) {
    const identity = (work) => {
      const doi = String(work.doi || "").replace(/^https?:\/\/(dx\.)?doi\.org\//i, "").toLowerCase();
      const arxiv = String(work.arxiv || "").replace(/v\d+$/i, "").toLowerCase();
      const id = workId(work);
      const title = String(work.title || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
      return doi ? "doi:" + doi : arxiv ? "arxiv:" + arxiv : id ? "openalex:" + id : "title:" + title;
    };
    const byId = new Map(S.results.map((work, index) => [identity(work), index]));
    for (const raw of incoming) {
      const work = { ...raw, source: raw.source || provider };
      const key = identity(work), index = byId.get(key);
      if (index == null) { byId.set(key, S.results.length); S.results.push({ ...work, sources: [provider] }); }
      else {
        const old = S.results[index];
        S.results[index] = { ...old, ...Object.fromEntries(Object.entries(work).filter(([, value]) => value != null && value !== "")),
          venue: old.venue || work.venue, abstract: old.abstract || work.abstract, pdf_url: old.pdf_url || work.pdf_url,
          sources: Array.from(new Set([...(old.sources || []), provider])) };
      }
    }
  }
  function setResults(r) { S.results = r.results || []; S.resultCount = r.count; S.hasMore = r.has_more ?? ((r.page || 1) * 20 < r.count); S.checkedAt = r.checked_at; S.stale = Boolean(r.stale); S.staleError = r.error || ""; S.warning = r.warning || ""; S.searchReason = r.reason || ""; S.relation = Boolean(r.relation); }
  async function relations(button) {
    if (S.relationBusy) return;
    S.relationBusy = true;
    const original = button.textContent;
    button.disabled = true; button.innerHTML = '<i class="spin"></i> 正在查詢…'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    const id = button.dataset.work, relation = button.dataset.relation;
    try { const r = await PR.api(API + "/work/" + id + "?relation=" + relation); S.relationRequest = { id, relation }; S.page = 1; setResults(r); S.error = ""; renderExplore(); }
    catch (e) { S.error = e.message; if (S.results.length) { S.stale = true; S.staleError = "本次論文關聯查詢未完成，保留先前結果。"; } renderExplore(); } // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    finally { S.relationBusy = false; if (button.isConnected) { button.disabled = false; button.textContent = original; } }
  }
  async function loadMore(button) {
    if (S.pageBusy) return;
    const requestId = S.searchRequestId, page = Number(S.page || 1) + 1;
    S.pageBusy = true; button.disabled = true; button.innerHTML = '<i class="spin"></i> 正在載入…'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    try {
      let providers;
      if (S.relationRequest) {
        providers = [{ name: "OpenAlex", url: API + "/work/" + S.relationRequest.id + "?relation=" + S.relationRequest.relation + "&page=" + page }];
      } else {
        const oa = new URLSearchParams(S.resultFilters || { kind: "works", q: S.lastQuery || "", sort: S.exploreSort }); oa.set("page", String(page));
        providers = [];
        if (S.mode !== "conference" || !S.venueSelected.length || S.venueSelected.some((source) => /S\d+$/.test(source.id || ""))) providers.push({ name: "OpenAlex", url: API + "/search?" + oa });
        if (S.mode === "conference" && S.venueSelected.length) {
          const venueParams = { q: S.lastQuery || "", venues: S.venueSelected.flatMap((x) => x.matched_queries?.length ? x.matched_queries : [x.name]).join("|"), year_from: S.yearFrom, year_to: S.yearTo, page: String(page) };
          providers.push({ name: "DBLP", url: API + "/search?" + new URLSearchParams({ kind: "dblp", ...venueParams }) });
          providers.push({ name: "Crossref", url: API + "/search?" + new URLSearchParams({ kind: "crossref", ...venueParams }) });
        }
      }
      const settled = await Promise.allSettled(providers.map((source) => PR.api(source.url)));
      if (requestId !== S.searchRequestId) return;
      let success = 0, more = false; const errors = [];
      settled.forEach((result, index) => {
        const source = providers[index];
        if (result.status === "fulfilled") { success++; mergeResults(result.value.results || [], source.name); more ||= Boolean(result.value.has_more); }
        else errors.push(PR.t("{source}：{message}", { source: source.name, message: PR.t(result.reason.message) }));
      });
      if (!success) throw new Error(errors.join("；") || "目前無法載入更多論文。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
      S.page = page; S.hasMore = more;
      S.warning = errors.length ? PR.t("部分來源的下一頁未能載入，已保留成功取得的結果：{errors}", { errors: errors.join("; ") }) : "";
      S.resultCount = S.results.length; renderExplore();
    } catch (error) { PR.toast(PR.t(error.message)); }
    finally { S.pageBusy = false; if (button.isConnected) { button.disabled = false; button.textContent = "載入更多論文"; } } /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  function openModal(title, bodyHtml, onSave, saveLabel = "儲存", options = {}) { // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    const modal = $("#rw-modal");
    modal.innerHTML = '<div class="rw-dialog' + (options.headerClose ? ' has-header-close' : '') + '" role="dialog" aria-modal="true"><div class="rw-dialog-head"><h2>' + esc(title) + '</h2>' + (options.headerClose ? '<button type="button" class="rw-dialog-close" data-modal-close aria-label="關閉" title="關閉">×</button>' : '') + '</div><div class="rw-dialog-body">' + bodyHtml + '</div><div class="rw-dialog-foot">' + (saveLabel === "關閉" ? '<button class="btn line" data-modal-close>關閉</button>' : '<button class="btn line" data-modal-close>關閉</button><button class="btn accent" data-modal-save>' + esc(saveLabel) + '</button>') + '</div></div>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    modal.hidden = false;
    $("[data-modal-close]", modal).onclick = () => { modal.hidden = true; };
    $("[data-modal-save]", modal).onclick = async () => { try { await onSave(modal); modal.hidden = true; } catch (e) { PR.toast(esc(e.message)); } };
    modal.onclick = (e) => { if (options.dismissOnBackdrop !== false && e.target === modal) modal.hidden = true; };
  }
  function queueModal(work) {
    const cats = S.categories.map((c) => '<option value="' + escAttr(c) + '">' + esc(c) + '</option>').join("");
    if (!work) return PR.toast("找不到論文資料，請重新搜尋。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
    const body = '<div class="rw-form-grid"><div class="rw-field wide"><label>分類（可複選）</label><select id="q-categories" multiple size="' + Math.min(5, Math.max(2, S.categories.length)) + '">' + cats + '</select><small>加入閱讀看板會開始尋找公開 PDF；這與候選清單分開管理。</small></div><div class="rw-field wide"><label class="rw-check"><input id="q-interested" type="checkbox">標記為感興趣</label></div></div>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    openModal("加入閱讀看板", body, async (modal) => { /* i18n-dom: shared DOM translator localizes rendered UI text. */
      const category = Array.from($("#q-categories", modal).selectedOptions).map((o) => o.value);
      await PR.api(API + "/save-paper", { method: "POST", body: { paper: work, categories: category, interested: $("#q-interested", modal).checked } });
      PR.toast("已加入待閱讀看板並開始尋找可用 PDF；不會自動整理摘要。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
      const data = await PR.api(API); S.saved = data.saved || S.saved; S.items = data.items || S.items; renderExplore();
    }, "加入並尋找 PDF"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  async function patchTask(task, fields) {
    await saveTaskFields(task, fields);
    const data = await PR.api(API); S.items = normalizeItems(data.items || S.items); S.saved = data.saved || S.saved; renderActive();
  }
  function saveTaskFields(task, fields) {
    return PR.api(API + "/item", { method: "POST", body: task.saved ? { saved_key: task.saved_key || task.id.slice(6), ...fields } : { id: task.id, ...fields } });
  }
  function attachPdf(key) {
    const input = document.createElement("input"); input.type = "file"; input.accept = "application/pdf,.pdf"; input.hidden = true;
    document.body.appendChild(input);
    input.onchange = async () => {
      const file = input.files && input.files[0]; input.remove(); if (!file) return;
      try {
        PR.toast("正在加入 PDF 並連結閱讀計畫…", null, 30000); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
        const qs = new URLSearchParams({ paper_key: key, name: file.name });
        const result = await PR.api(API + "/attach-pdf?" + qs, { method: "POST", body: file });
        const data = await PR.api(API); S.items = data.items || []; S.saved = data.saved || []; PR.toast(result.queued ? "PDF 已加入文獻庫，正在準備原頁與文字。" : "PDF 已加入文獻庫，閱讀計畫已保留。", null, 6000); renderActive(); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
      } catch (e) { PR.toast(PR.t("附加 PDF 失敗：{message}", { message: PR.t(e.message) })); }
    };
    input.click();
  }
  function statusManager() {
    let values = S.statuses.map((x) => ({ ...x }));
    const draw = () => '<p class="rw-source">拖曳左側把手調整順序。內建狀態可改名稱與顏色；刪除自訂狀態時，該欄論文會移至指定狀態。</p><div class="rw-list">' + values.map((s) => '<div class="rw-follow rw-status-row" data-status-row="' + escAttr(s.id) + '"><span class="rw-status-grip" draggable="true" data-status-drag="' + escAttr(s.id) + '" title="拖曳調整順序" aria-label="拖曳調整狀態順序">⠿</span><span class="rw-chip" style="border-color:' + escAttr(s.color) + '">●</span><input data-status-label="' + escAttr(s.id) + '" value="' + escAttr(s.label) + '" maxlength="32"><input type="color" data-status-color="' + escAttr(s.id) + '" value="' + (/^#[0-9a-f]{6}$/i.test(s.color) ? s.color : "#8b8b8b") + '">' + (!s.builtin ? '<select data-status-move="' + escAttr(s.id) + '">' + values.filter((x) => x.id !== s.id).map((x) => '<option value="' + escAttr(x.id) + '">刪除後移至 ' + esc(x.label) + '</option>').join("") + '</select><button class="btn sm" data-status-remove="' + escAttr(s.id) + '">刪除</button>' : '<span class="rw-source">內建</span>') + '</div>').join("") + '</div><button class="btn sm line" data-status-add>＋ 新增自訂狀態</button>'; // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    const moves = {};
    let draggedId = null;
    const modal = $("#rw-modal");
    const captureDraft = () => {
      values = values.map((s) => ({
        ...s,
        label: $('[data-status-label="' + CSS.escape(s.id) + '"]', modal)?.value ?? s.label,
        color: $('[data-status-color="' + CSS.escape(s.id) + '"]', modal)?.value ?? s.color,
      }));
    };
    openModal("管理閱讀狀態", draw(), async (dialog) => { // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
      captureDraft();
      values = values.map((s, position) => ({ ...s, label: s.label.trim(), position }));
      const r = await PR.api(API + "/statuses", { method: "POST", body: { statuses: values, moves } }); S.statuses = r.statuses; paint();
    });
    modal.onclick = (e) => {
      if (e.target === modal) { modal.hidden = true; return; }
      const remove = e.target.closest("[data-status-remove]"), add = e.target.closest("[data-status-add]");
      if (add) { captureDraft(); values.push({ id: "custom-" + Math.random().toString(36).slice(2, 10), label: "新狀態", color: "#8b8b8b", builtin: false }); $(".rw-dialog-body", modal).innerHTML = draw(); return; } // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
      if (remove) {
        const id = remove.dataset.statusRemove, move = $('[data-status-move="' + CSS.escape(id) + '"]', modal)?.value;
        captureDraft(); moves[id] = move; values = values.filter((x) => x.id !== id); $(".rw-dialog-body", modal).innerHTML = draw();
      }
    };
    modal.ondragstart = (e) => {
      const handle = e.target.closest("[data-status-drag]");
      if (!handle) return;
      draggedId = handle.dataset.statusDrag;
      e.dataTransfer.setData("text/plain", draggedId);
      e.dataTransfer.effectAllowed = "move";
      handle.closest("[data-status-row]")?.classList.add("dragging");
    };
    modal.ondragend = () => { draggedId = null; $$(".rw-status-row", modal).forEach((row) => row.classList.remove("dragging", "drop-target")); };
    modal.ondragover = (e) => {
      const row = e.target.closest("[data-status-row]");
      if (!row || !draggedId) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      $$(".rw-status-row.drop-target", modal).forEach((item) => item !== row && item.classList.remove("drop-target"));
      row.classList.add("drop-target");
    };
    modal.ondragleave = (e) => {
      const row = e.target.closest("[data-status-row]");
      if (row && !row.contains(e.relatedTarget)) row.classList.remove("drop-target");
    };
    modal.ondrop = (e) => {
      const target = e.target.closest("[data-status-row]");
      const sourceId = draggedId || e.dataTransfer.getData("text/plain");
      if (!target || !sourceId || target.dataset.statusRow === sourceId) return;
      e.preventDefault();
      captureDraft();
      const sourceIndex = values.findIndex((s) => s.id === sourceId);
      if (sourceIndex < 0 || !values.some((s) => s.id === target.dataset.statusRow)) return;
      const before = e.clientY < target.getBoundingClientRect().top + target.offsetHeight / 2;
      const [source] = values.splice(sourceIndex, 1);
      let insertAt = values.findIndex((s) => s.id === target.dataset.statusRow);
      if (!before) insertAt += 1;
      values.splice(insertAt, 0, source);
      $(".rw-dialog-body", modal).innerHTML = draw();
      draggedId = null;
    };
  }
  async function aiSummary() {
    const record = S.candidates.find((c) => c.paper_key === S.summaryKey);
    const chosen = record ? [record.paper] : [];
    if (!chosen.length) return PR.toast("請先從候選清單選擇一篇論文。"); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    const button = $("[data-action='candidate-summary'][data-key='" + CSS.escape(S.summaryKey) + "']");
    if (S.summaryBusy) return;
    if (record.summary_markdown && !S.forceSummary) return showSummary(record);
    S.forceSummary = false;
    S.summaryBusy = true;
    if (button) { button.disabled = true; button.textContent = "正在整理摘要…"; } /* i18n-dom: shared DOM translator localizes rendered UI text. */
    try {
      const r = await PR.api(API + "/ai-summary", { method: "POST", body: { papers: chosen } });
      S.summaryText = r.text || "";
      await PR.api(API + "/candidate", { method: "POST", body: { action: "save-summary", paper: chosen[0], summary_markdown: S.summaryText, model: r.model || "" } });
      const current = await PR.api(API); S.candidates = current.candidates || S.candidates; S.summaries = current.summaries || S.summaries;
      return showSummary(S.candidates.find((c) => c.paper_key === S.summaryKey) || { ...record, summary_markdown: S.summaryText, summary_model: r.model });
    } catch (e) { PR.toast(PR.t("摘要整理未完成：{message}", { message: PR.t(e.message) })); }
    finally { S.summaryBusy = false; if (button) { button.disabled = false; button.textContent = "整理摘要"; } } /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  function showSummary(record) {
    const content = '<div class="rw-source">根據候選論文的來源摘要整理' + (record.summary_model ? ' · ' + esc(record.summary_model) : '') + (record.updated || record.summary_updated ? ' · ' + esc(record.updated || record.summary_updated) : '') + '</div><article class="markdown rw-summary">' + PR.mdBlocks(record.summary_markdown || "") + '</article><div class="rw-dialog-foot"><button class="btn line" data-download-summary>匯出摘要</button></div>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    S.summaryText = record.summary_markdown || "";
    openModal("論文摘要整理", content, async () => {}, "關閉"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
    $("[data-download-summary]").onclick = () => exportMarkdown(record.paper.title + "-summary.md", S.summaryText);
  }
  async function exportMarkdown(filename, text) {
    const safeName = filename.replace(/[\\/:*?"<>|]/g, "_");
    if (window.showSaveFilePicker) {
      try {
        const handle = await window.showSaveFilePicker({ suggestedName: safeName, types: [{ description: "Markdown", accept: { "text/markdown": [".md"] } }] });
        const stream = await handle.createWritable(); await stream.write(text); await stream.close();
        PR.toast("摘要已匯出。"); return; /* i18n-dom: shared DOM translator localizes rendered UI text. */
      } catch (error) { if (error.name === "AbortError") return; throw error; }
    }
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = safeName; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function aiQuery() {
    const query = $("#rw-query")?.value?.trim() || "";
    if (!query) return PR.toast("請先輸入研究主題。"); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    const button = $("[data-action='ai-query']"); if (button?.disabled) return;
    if (button) { button.disabled = true; button.innerHTML = '<i class="spin"></i> 正在整理搜尋詞…'; } /* i18n-dom: shared DOM translator localizes rendered UI text. */
    try {
      const r = await PR.api(API + "/ai-query", { method: "POST", body: { query } });
      openModal("AI 建議的英文搜尋詞", '<p class="rw-source">可選取草稿中的文字，再按「AI 改寫」取得建議。</p><div class="rw-field"><label>搜尋詞草稿（每行一組）</label><textarea id="rw-ai-query" rows="7">' + esc((r.suggestions || []).join("\n")) + '</textarea></div><button type="button" class="btn line" data-action="rewrite-selected">AI 改寫選取文字</button><div id="rw-rewrite-results"></div>', async (modal) => { /* i18n-dom: shared DOM translator localizes rendered UI text. */
        const edited = $("#rw-ai-query", modal).value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
        const unique = uniqueQueryTerms(edited);
        if (!unique) throw new Error("請保留至少一組搜尋詞。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
        S.mode = "topic"; S.query = unique; S.results = []; renderExplore(); await search();
      }, "使用搜尋詞", { dismissOnBackdrop: false, headerClose: true }); /* i18n-dom: shared DOM translator localizes rendered UI text. */
    } catch (e) { PR.toast(PR.t("AI 搜尋詞整理未完成：{message}", { message: PR.t(e.message) })); }
    finally { if (button?.isConnected) { button.disabled = false; button.textContent = "AI 擴展搜尋詞"; } } /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  async function rewriteSelected() {
    const modal = $("#rw-modal"), draft = $("#rw-ai-query", modal);
    const start = draft?.selectionStart ?? 0, end = draft?.selectionEnd ?? 0;
    const selected = draft?.value.slice(start, end).trim() || "";
    if (!selected) return PR.toast("請先在搜尋詞草稿中選取要改寫的文字。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
    const button = $("[data-action='rewrite-selected']", modal); if (button.disabled) return;
    button.disabled = true; button.textContent = "AI 正在改寫…"; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    $("#rw-rewrite-results", modal).innerHTML = '<div class="rw-source" role="status">正在依選取文字產生建議…</div>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    try {
      const result = await PR.api(API + "/ai-rewrite", { method: "POST", body: { selected_text: selected, context: draft.value } });
      S.rewriteRange = { start, end };
      $("#rw-rewrite-results", modal).innerHTML = '<div class="rw-list">' + result.suggestions.map((value, index) => '<div class="rw-rewrite-option"><span>' + esc(value) + '</span><button class="btn sm line" data-rewrite-accept="' + index + '">套用</button></div>').join("") + '</div>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
      S.rewriteSuggestions = result.suggestions;
    } catch (e) { $("#rw-rewrite-results", modal).innerHTML = '<div class="rw-error">' + esc(PR.t("{message} 請確認模型設定後重試。", { message: PR.t(e.message) })) + '</div>'; }
    finally { button.disabled = false; button.textContent = "AI 改寫選取文字"; } /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  async function generatePath() {
    if (S.pathLoading) return;
    const topicField = $("#rw-path-topic"), goalField = $("#rw-path-goal");
    S.pathTopic = topicField?.value.trim() || ""; S.pathGoal = goalField?.value.trim() || "";
    const params = new URLSearchParams(location.search);
    const startPaper = { title: params.get("start_title") || params.get("title") || "", doi: params.get("start_doi") || "", openalex_id: params.get("start_openalex") || "" };
    if (!S.pathTopic && !startPaper.title) { S.pathError = "請輸入研究主題，或從閱讀器以目前論文作為起點。"; renderPath(); return; } /* i18n-dom: shared DOM translator localizes rendered UI text. */
    S.pathLoading = true; S.pathError = ""; renderPath();
    try {
      const papers = [...S.candidates.map((c) => c.paper), ...S.results];
      const result = await PR.api(API + "/reading-path", { method: "POST", body: { topic: S.pathTopic, goal: S.pathGoal, start_paper: startPaper, papers } });
      S.pathResults = result.results || [];
      if (!S.pathResults.length) S.pathError = "目前來源資料不足以建立有依據的閱讀路徑。請先搜尋主題或加入候選論文，再重試。"; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    } catch (e) { S.pathError = e.message; }
    finally { S.pathLoading = false; renderPath(); }
  }
  document.addEventListener("click", async (e) => {
    const tab = e.target.closest("[data-tab]"); if (tab) return switchTab(tab.dataset.tab);
    const mode = e.target.closest("[data-mode]"); if (mode) { rememberExploreInputs(); S.mode = mode.dataset.mode; S.error = ""; S.stale = false; S.warning = ""; S.results = []; S.authors = []; return renderExplore(); }
    const rewrite = e.target.closest("[data-rewrite-accept]"); if (rewrite) {
      const value = S.rewriteSuggestions?.[Number(rewrite.dataset.rewriteAccept)];
      if (typeof value === "string" && value.trim()) {
        S.mode = "topic"; S.query = value; S.results = []; S.error = ""; S.stale = false;
        $("#rw-modal").hidden = true; renderExplore(); await search();
      }
      return;
    }
    const b = e.target.closest("[data-action]"); if (!b) return;
    try {
      switch (b.dataset.action) {
        case "manage-status": return statusManager();
        case "add-column": return statusManager();
        case "go-explore": return switchTab("explore");
        case "clear-filters": S.filters = { category: "", status: "", interested: false, pdf: "" }; return renderBoard();
        case "toggle-interested-filter": S.filters.interested = !S.filters.interested; return renderBoard();
        case "retry-search": return search();
        case "retry-source": return searchSources();
        case "search-sources": return searchSources();
        case "clear-source": rememberExploreInputs(); S.venueSelected = []; return renderExplore();
        case "queue": { const key = b.dataset.key; const work = S.results.find((w) => paperKey(w) === key) || S.candidates.find((c) => c.paper_key === key)?.paper; return queueModal(work); }
        case "candidate": {
          const key = b.dataset.key;
          let work = S.results.find((w) => paperKey(w) === key);
          const pathIndex = Number(b.dataset.paperIndex); if (!work && Number.isInteger(pathIndex)) work = S.pathResults?.[pathIndex]?.paper;
          const record = S.candidates.find((c) => c.paper_key === key) || candidateFor(work);
          work ||= record?.paper;
          if (!work) throw new Error("找不到這篇論文資料，請重新搜尋後操作。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
          if (b.disabled) return;
          b.disabled = true; b.textContent = record ? "正在移出…" : "正在加入…"; /* i18n-dom: shared DOM translator localizes rendered UI text. */
          try {
            await PR.api(API + "/candidate", { method: "POST", body: { action: record ? "remove" : "add", paper: work } });
            S.candidates = (await PR.api(API)).candidates || [];
          } catch (error) { b.disabled = false; b.textContent = record ? "移出候選" : "加入候選"; throw error; } /* i18n-dom: shared DOM translator localizes rendered UI text. */
          PR.toast(record ? "已從候選清單移除。" : "已加入候選清單，摘要會在背景自動整理。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
          return renderActive();
        }
        case "remove-candidate": {
          const record = S.candidates.find((c) => c.paper_key === b.dataset.key); if (!record) return;
          await PR.api(API + "/candidate", { method: "POST", body: { action: "remove", paper: record.paper } });
          S.candidates = (await PR.api(API)).candidates || []; return renderCandidates();
        }
        case "candidate-summary": S.summaryKey = b.dataset.key; S.forceSummary = b.dataset.forceSummary === "1"; return aiSummary();
        case "retry-summary": {
          const record = S.candidates.find((c) => c.paper_key === b.dataset.key); if (!record) return;
          b.disabled = true; b.innerHTML = '<i class="spin"></i> 已重新排入…'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
          await PR.api(API + "/candidate", { method: "POST", body: { action: "retry-summary", paper: record.paper } });
          S.candidates = (await PR.api(API)).candidates || S.candidates; return renderCandidates();
        }
        case "view-summary": { const record = S.summaries.find((x) => x.paper_key === b.dataset.key) || S.candidates.find((c) => c.paper_key === b.dataset.key); if (record?.summary_markdown) showSummary(record); return; }
        case "download-summary": { const record = S.summaries.find((x) => x.paper_key === b.dataset.key) || S.candidates.find((c) => c.paper_key === b.dataset.key); if (record?.summary_markdown) await exportMarkdown(record.paper.title + "-summary.md", record.summary_markdown); return; }
        case "trash-summary": {
          const record = S.summaries.find((x) => x.paper_key === b.dataset.key); if (!record) return;
          if (!(await PR.confirm({ title: "將摘要移到回收站？", body: "摘要會從「已整理摘要」移除，可在文獻庫的回收站還原。論文與閱讀資料不會受到影響。", ok: "移到回收站", danger: true, at: b }))) return; /* i18n-dom: shared DOM translator localizes rendered UI text. */
          b.disabled = true;
          try { await PR.api("/api/trash", { method: "POST", body: { action: "move-summary", type: "summary", name: record.paper_key } }); }
          catch (error) { b.disabled = false; throw error; }
          S.summaries = S.summaries.filter((x) => x.paper_key !== record.paper_key);
          renderSummaries(); PR.toast("摘要已移到回收站。"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
          try { const updated = await PR.api(API); S.candidates = updated.candidates || S.candidates; }
          catch (_) { /* The completed move remains reflected in the current view. */ }
          return;
        }
        case "generate-path": return generatePath();
        case "rewrite-selected": return rewriteSelected();
        case "publication-check": {
          b.disabled = true; b.textContent = "正在核對 DOI…"; /* i18n-dom: shared DOM translator localizes rendered UI text. */
          try {
            const record = await PR.api(API + "/publication-check?doi=" + encodeURIComponent(b.dataset.doi));
            const body = '<dl class="rw-publication-data"><dt>Crossref 登錄標題</dt><dd>' + esc(record.title || "未提供") + '</dd><dt>出版來源</dt><dd>' + esc(record.container_title || "未提供") + '</dd><dt>資料類型</dt><dd>' + esc(record.type || "未提供") + '</dd><dt>出版年份</dt><dd>' + esc(record.year || "未提供") + '</dd><dt>DOI</dt><dd>' + esc(record.doi) + '</dd></dl><p class="rw-source">Crossref 書目紀錄可協助核對 DOI、刊名與資料類型；仍需依會議官方紀錄確認正式發表狀態。</p>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
            openModal("DOI／出版資料核對", body, async () => {}, "關閉"); /* i18n-dom: shared DOM translator localizes rendered UI text. */
          } catch (error) { PR.toast(PR.t("Crossref 核對失敗：{message}", { message: PR.t(error.message) })); }
          finally { b.disabled = false; b.textContent = "核對 DOI 出版資料"; } /* i18n-dom: shared DOM translator localizes rendered UI text. */
          return;
        }
        case "relation": return relations(b);
        case "skip": await PR.api(API + "/skip", { method: "POST", body: { paper_key: b.dataset.key } }); S.results = S.results.filter((w) => paperKey(w) !== b.dataset.key); return renderExplore();
        case "retry-pdf": await PR.api(API + "/retry-pdf", { method: "POST", body: { paper_key: b.dataset.key } }); PR.toast("已重新排入 PDF 下載。"); return init(); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
        case "attach-pdf": return attachPdf(b.dataset.key);
        case "interested": { const task = allTasks().find((x) => x.id === b.dataset.taskId); if (task) { const interested = !task.interested; return patchTask(task, { interested, starred: interested }); } break; }
        case "ai-summary": return aiSummary();
        case "ai-query": return aiQuery();
        case "next-page": {
          return loadMore(b);
        }
      }
    } catch (err) { PR.toast(esc(err.message)); }
  });
  document.addEventListener("submit", (e) => { if (e.target.id === "rw-search") { e.preventDefault(); search(); } });
  document.addEventListener("input", (e) => {
    const fields = { "rw-query": "query", "rw-venue-query": "venueQuery", "rw-year-from": "yearFrom", "rw-year-to": "yearTo", "rw-sort": "exploreSort" };
    const key = fields[e.target.id];
    if (key) S[key] = e.target.value;
    if (e.target.id === "rw-oa") S.onlyOA = e.target.checked;
  });
  document.addEventListener("focusout", (e) => { if (S.pendingRender && e.target.closest(".rw-view") && !$(".rw-modal:not([hidden])")) { S.pendingRender = false; renderActive(); } });
  document.addEventListener("change", async (e) => {
    const c = e.target;
    if (["rw-query", "rw-venue-query", "rw-year-from", "rw-year-to", "rw-sort"].includes(c.id)) rememberExploreInputs();
    if (c.id === "rw-oa") S.onlyOA = c.checked;
    if (c.matches("[data-select-work]")) { c.checked ? S.checked.add(c.dataset.selectWork) : S.checked.delete(c.dataset.selectWork); return; }
    if (c.matches("[data-source-choice]")) {
      const id = c.dataset.sourceChoice, source = S.venueOptions.find((s) => s.id === id);
      rememberExploreInputs();
      S.venueSelected = S.venueSelected.filter((s) => s.id !== id);
      if (c.checked && source) S.venueSelected.push(source);
      return renderExplore();
    }
    if (c.matches("[data-filter]")) { const k = c.dataset.filter; S.filters[k] = c.type === "checkbox" ? c.checked : c.value; renderBoard(); return; }
    if (c.matches("[data-sort]")) { S.sort = c.value; renderBoard(); return; }
  });
  document.addEventListener("keydown", async (e) => {
    if (!e.altKey || !["ArrowLeft", "ArrowRight"].includes(e.key) || e.target.closest("a,button,input,select,textarea")) return;
    const card = e.target.closest(".rw-task[data-task]"); if (!card) return;
    const columns = Array.from(document.querySelectorAll(".rw-column")), current = card.closest(".rw-column");
    const index = columns.indexOf(current), next = columns[index + (e.key === "ArrowRight" ? 1 : -1)];
    if (!next) return;
    const task = allTasks().find((item) => item.id === card.dataset.task); if (!task) return;
    e.preventDefault();
    const destination = next.dataset.column;
    const order = allTasks().filter((item) => (item.status || "unread") === destination).length * 100 + 100;
    try { await patchTask(task, { status: destination, manual_order: order }); PR.toast(PR.t("閱讀狀態已移至「{status}」。", { status: PR.t(statusLabel(destination)) })); }
    catch (error) { PR.toast(PR.t(error.message)); }
  });
  let dragged = null;
  document.addEventListener("dragstart", (e) => { const task = e.target.closest("[data-task]"); if (!task) return; dragged = task.dataset.task; e.dataTransfer.setData("text/plain", dragged); e.dataTransfer.effectAllowed = "move"; });
  document.addEventListener("dragover", (e) => { const col = e.target.closest("[data-column]"); if (!col || !dragged) return; e.preventDefault(); col.classList.add("drop-target"); });
  document.addEventListener("dragleave", (e) => { const col = e.target.closest("[data-column]"); if (col && !col.contains(e.relatedTarget)) col.classList.remove("drop-target"); });
  document.addEventListener("drop", async (e) => {
    const col = e.target.closest("[data-column]"); if (!col || !dragged) return; e.preventDefault(); col.classList.remove("drop-target");
    const task = allTasks().find((x) => x.id === dragged); const targetCard = e.target.closest("[data-task]"); if (!task) return;
    const destination = col.dataset.column; let rollback = [{ item: task, status: task.status || "unread", manual_order: task.manual_order || 0 }];
    try {
      if (targetCard && targetCard.dataset.task !== dragged) {
        const group = allTasks().filter((x) => (x.status || "unread") === destination && x.id !== dragged).sort((a, b) => Number(a.manual_order || 0) - Number(b.manual_order || 0));
        rollback = [task, ...group].map((item) => ({ item, status: item.status || "unread", manual_order: item.manual_order || 0 }));
        const at = group.findIndex((x) => x.id === targetCard.dataset.task);
        group.splice(at < 0 ? group.length : at, 0, task);
        await Promise.all(group.map((x, index) => saveTaskFields(x, { status: destination, manual_order: (index + 1) * 100 })));
        const data = await PR.api(API); S.items = data.items || S.items; S.saved = data.saved || S.saved; renderBoard();
      } else {
        const group = allTasks().filter((x) => (x.status || "unread") === destination && x.id !== dragged).sort((a, b) => Number(a.manual_order || 0) - Number(b.manual_order || 0));
        rollback = [task, ...group].map((item) => ({ item, status: item.status || "unread", manual_order: item.manual_order || 0 }));
        await saveTaskFields(task, { status: destination, manual_order: (group.length + 1) * 100 });
        const data = await PR.api(API); S.items = data.items || S.items; S.saved = data.saved || S.saved; renderBoard();
      }
    } catch (err) {
      const restored = await Promise.allSettled(rollback.map((x) => saveTaskFields(x.item, { status: x.status, manual_order: x.manual_order })));
      try { const data = await PR.api(API); S.items = data.items || S.items; S.saved = data.saved || S.saved; renderBoard(); } catch (_) { /* retain the last rendered board while the service reconnects */ }
      const fullyRestored = restored.every((x) => x.status === "fulfilled");
      PR.toast(fullyRestored ? "拖曳未能儲存，已還原原排序。" : "拖曳未能儲存；連線恢復後請確認排序。" ); // i18n-ok: 研究工作區依產品規格固定使用繁體中文。
    }
    dragged = null;
  });
  const searchParams = new URLSearchParams(location.search);
  if (searchParams.get("mode") === "conference") S.mode = "conference";
  if (searchParams.get("mode") === "path") S.tab = "path";
  if (searchParams.get("mode") === "candidates") S.tab = "candidates";
  if (searchParams.has("q") && !["path", "candidates"].includes(searchParams.get("mode"))) S.tab = "explore";
  if (searchParams.get("q")) S.query = searchParams.get("q");
  init();
})(window.PR);
