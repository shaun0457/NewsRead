/* Select library papers, review one comparison, then save it to Obsidian. */
(function (PR) {
  "use strict";
  const endpoint = "/api/research/v1";
  const defaults = [PR.t("研究問題"), PR.t("核心方法"), PR.t("資料集"), PR.t("評估指標"), PR.t("限制")];
  const state = { status: null, papers: [], selected: new Set(), dimensions: new Set(defaults),
    filter: "", focus: "", custom: "", vault: "", showSettings: false, model: "", task: null,
    proposal: null, matrixTask: null, matrixProposal: null, topicProposal: null, matrixPaper: "", topicPath: "",
    topicTitle: "", wiki: null, wikiPage: "", lintTask: null, semanticLint: false, scheduleDraft: null,
    busy: false, error: "", poll: "", matrixPoll: "", lintPoll: "" };
  const panel = () => PR.$("#researchpanel");
  const active = () => state.task && ["queued", "running", "cancelling"].includes(state.task.state);
  const matrixActive = () => state.matrixTask && ["queued", "running", "cancelling"].includes(state.matrixTask.state);
  const esc = (value) => PR.esc(String(value == null ? "" : value));
  const obsidianUri = (path) => {
    const vault = String(state.status?.vault || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();
    return vault && path ? "obsidian://open?vault=" + encodeURIComponent(vault) + "&file=" + encodeURIComponent(path.replace(/\.md$/i, "")) : "";
  };

  PR.researchOpen = () => PR.side === "research";
  PR.toggleResearch = async function (force) {
    const open = force != null ? force : PR.side !== "research";
    PR.openSide(open ? "research" : null);
    if (open) await load(); else state.poll = "";
  };

  function taskMarkup() {
    if (!state.task) return "";
    const task = state.task;
    const progress = task.total ? " · " + task.done + "/" + task.total : "";
    const message = task.state === "failed" ? PR.t("比較失敗：{message}", { message: task.message }) :
      task.state === "cancelled" ? PR.t("比較已取消") :
      task.state === "completed" ? PR.t("比較報告已完成，請先審閱。") :
      task.message || PR.t("正在準備比較…");
    return '<div class="rs-task" role="status"><span>' + esc(message + progress) + '</span>' +
      (active() ? '<button class="linkish" data-r="cancel">' + PR.t("取消") + '</button>' : "") +
      (task.total ? '<progress max="' + task.total + '" value="' + task.done + '"></progress>' : "") + '</div>';
  }

  function paperMarkup(item) {
    const ready = item.parsed_blocks > 0;
    return '<label class="rs-paper"><input type="checkbox" data-paper="' + esc(item.id) + '"' + (state.selected.has(item.id) ? " checked" : "") + (ready ? "" : " disabled") +
      '><span><b>' + esc(item.title_en || item.title_zh || item.id) + '</b><small>' + esc([item.year, item.authors].filter(Boolean).join(" · ")) +
      (ready ? "" : " · " + PR.t("原文尚未整理")) + '</small></span></label>';
  }

  function reportMarkup() {
    const p = state.proposal;
    if (!p) return "";
    return '<section class="rs-section rs-report"><h3>' + PR.t("比較報告草稿") + '</h3>' +
      '<p class="hint">' + PR.t("請檢查比較條件及研究問題。參考論文集中列在末尾；接受前不會寫入 Obsidian。") + '</p>' +
      '<div class="rs-report-body">' + PR.mdBlocks(p.content || "", { cite: false, xref: false }) + '</div><div class="rs-actions">' +
      (p.status === "pending" ? '<button class="btn sm" data-r="accept">' + PR.t("確認並存入 Obsidian") + '</button><button class="btn sm" data-r="reject">' + PR.t("捨棄草稿") + '</button>' :
        '<span class="hint">' + esc(p.status === "accepted" ? PR.t("已存入 Obsidian") : p.status === "conflict" ? PR.t("Obsidian 中的檔案已變更，請重新產生比較。") : PR.t("已捨棄草稿")) + '</span>') +
      (p.status === "accepted" ? '<button class="btn sm" data-r="open-note">' + PR.t("在 Obsidian 開啟") + '</button>' : "") + '</div></section>';
  }

  function matrixTaskMarkup() {
    const task = state.matrixTask;
    if (!task) return "";
    const message = task.state === "failed" ? PR.t("矩陣整理失敗：{message}", { message: task.message }) :
      task.state === "cancelled" ? PR.t("矩陣整理已取消") :
      task.state === "completed" ? PR.t("矩陣列已完成，請檢查差異與來源。") : task.message || PR.t("正在整理矩陣資料…");
    return '<div class="rs-task" role="status"><span>' + esc(message) + '</span>' +
      (["queued", "running", "cancelling"].includes(task.state) ? '<button class="linkish" data-r="matrix-cancel">' + PR.t("取消") + '</button>' : "") +
      (task.total ? '<progress max="' + task.total + '" value="' + task.done + '"></progress>' : "") + '</div>';
  }

  function stagedMarkup(proposal, prefix, heading) {
    if (!proposal) return "";
    const status = proposal.status === "pending" ?
      '<div class="rs-actions"><button class="btn sm" data-r="' + prefix + '-accept">' + PR.t("確認並存入 Obsidian") +
      '</button><button class="btn sm" data-r="' + prefix + '-reject">' + PR.t("捨棄草稿") + '</button></div>' :
      '<span class="hint">' + esc(proposal.status === "accepted" ? PR.t("已存入 Obsidian") : proposal.status === "conflict" ?
        PR.t("Obsidian 中的檔案已變更，請重新產生提案。") : PR.t("已捨棄草稿")) + '</span>';
    return '<section class="rs-section"><h3>' + heading + '</h3><p class="hint">' + PR.t("以下是實際寫入前的差異；請確認論文證據及主題內容。") +
      '</p><pre class="rs-diff">' + esc(proposal.diff || "") + '</pre>' + status +
      (proposal.status === "accepted" ? '<button class="btn sm" data-r="' + prefix + '-open">' + PR.t("在 Obsidian 開啟") + '</button>' : "") + '</section>';
  }

  function wikiMarkup() {
    const wiki = state.wiki;
    const pages = wiki?.pages || [];
    const selected = pages.find((page) => page.path === state.wikiPage) || pages[0];
    const noteByPath = new Map(pages.map((page) => [page.path, page]));
    const pageOptions = pages.map((page) => '<option value="' + esc(page.path) + '"' + (selected?.path === page.path ? ' selected' : '') + '>' +
      esc(page.title + ' · ' + page.path) + '</option>').join('');
    const linkList = (paths) => paths?.length ? '<ul>' + paths.map((path) => {
      const item = noteByPath.get(path);
      return '<li><a target="_blank" rel="noopener" href="' + esc(obsidianUri(path)) + '">' + esc(item?.title || path) + '</a></li>';
    }).join('') + '</ul>' : '<p class="hint">' + PR.t("尚無連結") + '</p>';
    const report = state.lintTask?.result;
    const issues = report?.issues || {};
    const issueLabels = { broken_links: PR.t("失效連結"), ambiguous_links: PR.t("歧義連結"), orphan_pages: PR.t("孤立頁"),
      pages_without_backlinks: PR.t("沒有反向連結"), stale_sources: PR.t("失效來源"), due_review: PR.t("待回顧"), invalid_review_dates: PR.t("無效回顧日期"),
      possible_missing_concepts: PR.t("可能缺少的概念") };
    const issueMarkup = report ? '<div class="rs-lint-counts">' + Object.entries(issueLabels).map(([key, label]) =>
      '<span>' + esc(label) + '<b>' + Number(issues[key] || 0) + '</b></span>').join('') + '</div>' +
      '<p class="hint">' + esc(report.report_path || '') + '</p>' +
      (report.broken?.length ? '<details><summary>' + PR.t("失效連結") + ' · ' + issues.broken_links + '</summary><ul>' +
        report.broken.map((item) => '<li>' + esc(item.from + ' → [[' + item.target + ']]') + '</li>').join('') + '</ul></details>' : '') +
      (report.ambiguous?.length ? '<details><summary>' + PR.t("歧義連結") + ' · ' + issues.ambiguous_links + '</summary><ul>' +
        report.ambiguous.map((item) => '<li>' + esc(item.from + ' → [[' + item.target + ']]：' + item.matches.join('、')) + '</li>').join('') + '</ul></details>' : '') + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      (report.orphans?.length ? '<details><summary>' + PR.t("孤立頁") + ' · ' + issues.orphan_pages + '</summary><ul>' +
        report.orphans.map((path) => '<li>' + esc(path) + '</li>').join('') + '</ul></details>' : '') +
      (report.unreferenced?.length ? '<details><summary>' + PR.t("沒有反向連結") + ' · ' + issues.pages_without_backlinks + '</summary><ul>' +
        report.unreferenced.map((path) => '<li>' + esc(path) + '</li>').join('') + '</ul></details>' : '') +
      (report.broken_sources?.length ? '<details><summary>' + PR.t("失效來源") + ' · ' + issues.stale_sources + '</summary><ul>' +
        report.broken_sources.map((item) => '<li>' + esc(item.path + ' · ' + item.reason) + '</li>').join('') + '</ul></details>' : '') +
      (report.due_review?.length ? '<details><summary>' + PR.t("待回顧") + ' · ' + issues.due_review + '</summary><ul>' +
        report.due_review.map((item) => '<li>' + esc(item.path + ' · ' + item.date) + '</li>').join('') + '</ul></details>' : '') +
      (report.concept_candidates?.length ? '<details><summary>' + PR.t("可能缺少的概念") + ' · ' + issues.possible_missing_concepts + '</summary><ul>' +
        report.concept_candidates.map((item) => '<li><b>' + esc(item.term) + '</b> · ' + esc(item.pages.join('、')) + '</li>').join('') + '</ul></details>' : '') + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      semanticMarkup(report.semantic_review) : '';
    const schedule = state.scheduleDraft || state.status?.wiki_schedule || { enabled: false, frequency: 'weekly', time: '09:00' };
    const lintActive = state.lintTask && ['queued', 'running', 'cancelling'].includes(state.lintTask.state);
    const lintMessage = state.lintTask ? (state.lintTask.state === 'failed' ? PR.t("Wiki Lint 失敗：{message}", { message: state.lintTask.message }) :
      state.lintTask.state === 'completed' ? PR.t("Wiki Lint 報告已完成。") : state.lintTask.message) : '';
    return '<section class="rs-section"><h3>' + PR.t("5. Wiki 連結與健康檢查") + '</h3>' +
      '<p class="hint">' + PR.t("反向連結由 Wiki 連結即時計算，不會重複寫入筆記。Lint 只提供檢查與候選建議，不會修改 Vault。") + '</p>' +
      (wiki ? (selected ? '<label class="rs-label">' + PR.t("選擇筆記") + '<select class="input" data-r="wiki-page">' + pageOptions + '</select></label>' +
        '<div class="rs-wiki-links"><div><b>' + PR.t("連出連結") + '</b>' + linkList(selected.outlinks) + '</div><div><b>' + PR.t("反向連結") + '</b>' + linkList(selected.backlinks) + '</div></div>' : '<p class="hint">' + PR.t("Vault 中目前沒有索引到 Markdown 筆記。") + '</p>') : '') +
      '<button class="btn sm" data-r="wiki-refresh"' + (!state.status?.configured || state.busy ? ' disabled' : '') + '>' + PR.t("重新整理 Wiki 連結") + '</button>' +
      '<hr><b>' + PR.t("Wiki Lint（只讀檢查）") + '</b>' +
      '<label class="rs-check"><input type="checkbox" data-r="semantic-lint"' + (state.semanticLint ? ' checked' : '') + '>' + PR.t("加上 AI 語意審閱：候選矛盾、可能過期內容與缺少概念") + '</label>' +
      '<button class="btn sm" data-r="lint-start"' + (!state.status?.configured || lintActive || state.busy ? ' disabled' : '') + '>' + PR.t("執行 Wiki Lint") + '</button>' +
      (lintMessage ? '<p class="hint" role="status">' + esc(lintMessage) + '</p>' : '') + issueMarkup +
      (schedule.available ? '<details class="rs-schedule"><summary>' + PR.t("定期執行") + '</summary>' +
        '<label class="rs-check"><input type="checkbox" data-r="schedule-enabled"' + (schedule.enabled ? ' checked' : '') + '>' + PR.t("啟用定期 Lint") + '</label>' +
        '<label class="rs-label">' + PR.t("頻率") + '<select class="input" data-r="schedule-frequency"><option value="weekly"' + (schedule.frequency === 'weekly' ? ' selected' : '') + '>' + PR.t("每週（週日）") + '</option><option value="monthly"' + (schedule.frequency === 'monthly' ? ' selected' : '') + '>' + PR.t("每月 1 日") + '</option></select></label>' +
        '<label class="rs-label">' + PR.t("執行時間") + '<input class="input" type="time" data-r="schedule-time" value="' + esc(schedule.time || '09:00') + '"></label>' +
        '<button class="btn sm" data-r="schedule-save"' + (state.busy ? ' disabled' : '') + '>' + PR.t("儲存排程") + '</button>' +
        '<p class="hint">' + PR.t("排程以目前登入的 Windows 帳戶執行，只做本機結構檢查；休眠錯過時，重新登入並喚醒電腦後會補跑。") + '</p></details>' : '') +
      '</section>';
  }

  function semanticMarkup(review) {
    if (!review) return '';
    const findings = review.candidates || [];
    return '<div class="rs-semantic"><b>' + esc(review.status === 'not-run' ? PR.t("未執行 AI 語意審閱") :
      review.status === 'failed' ? PR.t("AI 語意審閱未完成") : PR.t("AI 候選，請人工核對")) + '</b>' +
      (review.note ? '<p class="hint">' + esc(review.note) + '</p>' : '') +
      (review.status === 'partial' ? '<p class="hint">' + esc(PR.t("僅檢查部分筆記，未涵蓋 {n} 份筆記。", { n: review.omitted_pages?.length || 0 })) + '</p>' : '') +
      (review.error ? '<p class="hint">' + esc(review.error) + '</p>' : '') +
      (findings.length ? '<ul>' + findings.map((item) => '<li><b>' + esc(item.type) + '</b> ' + esc(item.summary) +
        (item.suggestion ? '<p>' + PR.t("建議：") + esc(item.suggestion) + '</p>' : '') +
        (item.evidence || []).map((ref) => '<blockquote>' + esc(ref.path + '：「' + ref.quote + '」') + '</blockquote>').join('') + '</li>').join('') + '</ul>' : '') + /* i18n-dom: shared DOM translator localizes rendered UI text. */
      '</div>';
  }

  function render() {
    const el = panel();
    if (!el) return;
    const previousScrollTop = el.querySelector(".rs-scroll")?.scrollTop || 0;
    const configured = !!state.status?.configured;
    const matches = state.papers.filter((item) => (item.title_en + " " + item.title_zh + " " + item.authors + " " + item.id)
      .toLocaleLowerCase().includes(state.filter.toLocaleLowerCase()));
    const count = state.selected.size;
    const canStart = configured && count >= 2 && count <= 5 && state.dimensions.size > 0 && !active() && !state.busy;
    const chosenModel = (state.status?.models || []).find((m) => m.id === (state.model || state.status.model));
    const modelOptions = (state.status?.models || []).map((m) => '<option value="' + esc(m.id) + '"' +
      ((state.model || state.status.model) === m.id ? " selected" : "") + '>' + esc(m.name || m.id) + '</option>').join("");
    const parsed = state.papers.filter((item) => item.parsed_blocks > 0);
    const topicNotes = (state.status?.notes || []).filter((note) => note.kind === "topic");
    const matrixPaper = state.matrixPaper || (parsed.some((item) => item.id === PR.pid) ? PR.pid : parsed[0]?.id || "");
    const paperOptions = parsed.map((item) => '<option value="' + esc(item.id) + '"' + (matrixPaper === item.id ? " selected" : "") + '>' +
      esc(item.title_en || item.title_zh || item.id) + '</option>').join("");
    const topicOptions = topicNotes.map((note) => '<option value="' + esc(note.path) + '"' + ((state.topicPath || topicNotes[0]?.path) === note.path ? " selected" : "") + '>' +
      esc(note.title) + '</option>').join("");
    el.innerHTML = '<div class="rs-head"><b>' + PR.t("比較論文") + '</b><span class="grow"></span><button class="btn icon" data-r="close" title="' + PR.t("關閉") + '">×</button></div>' +
      '<div class="rs-scroll"><p class="rs-lede">' + PR.t("選取文獻庫中的論文，產生跨論文比較與候選研究問題。單篇筆記請使用原有的筆記匯出。") + '</p>' +
      (!configured ? '<section class="rs-section"><h3>' + PR.t("先連結 Obsidian Vault") + '</h3><input class="input" data-r="vault" placeholder="C:\\Users\\name\\Documents\\Research" value="' + esc(state.vault) + '"><button class="btn sm" data-r="setup">' + PR.t("連結 Vault") + '</button></section>' :
        '<details class="rs-section rs-settings"' + (state.showSettings ? " open" : "") + '><summary>' + PR.t("儲存位置與模型") + '</summary><label>' + PR.t("Obsidian Vault") + '<input class="input" data-r="vault" value="' + esc(state.vault || state.status.vault) + '"></label><button class="btn sm" data-r="setup">' + PR.t("更新 Vault") + '</button><label>' + PR.t("研究模型") + '<select class="input" data-r="model">' + modelOptions + '</select></label></details>') +
      '<section class="rs-section"><h3>' + PR.t("1. 選擇 2 至 5 篇論文") + ' <small>' + count + '/5</small></h3>' +
      '<input class="input" data-r="filter" placeholder="' + PR.t("搜尋文獻庫中的標題或作者") + '" value="' + esc(state.filter) + '">' +
      '<div class="rs-paper-list">' + (matches.length ? matches.map(paperMarkup).join("") : '<p class="hint">' + PR.t("沒有符合條件的論文。") + '</p>') + '</div></section>' +
      '<section class="rs-section"><h3>' + PR.t("2. 設定比較焦點") + '</h3><label class="rs-label">' + PR.t("比較焦點（選填）") +
      '<input class="input" data-r="focus" placeholder="' + PR.t("例如：長影片理解的記憶壓縮方法") + '" value="' + esc(state.focus) + '"></label>' +
      '<p class="hint">' + PR.t("比較維度可自由增減：") + '</p><div class="rs-dimensions">' +
      [...new Set([...defaults, ...state.dimensions])].map((value) => '<label><input type="checkbox" data-dimension="' + esc(value) + '"' +
        (state.dimensions.has(value) ? " checked" : "") + '>' + esc(value) + '</label>').join("") + '</div>' +
      '<div class="rs-add"><input class="input" data-r="custom" placeholder="' + PR.t("新增自訂維度") + '" value="' + esc(state.custom) + '"><button class="btn sm" data-r="add-dimension">' + PR.t("新增") + '</button></div></section>' +
      '<section class="rs-section"><h3>' + PR.t("3. 產生並審閱報告") + '</h3><p class="hint">' + PR.t("會讀取所選論文的已解析原文及個人批註；較長的論文需要較久時間，可查看進度或取消。") + '</p>' +
      (chosenModel ? '<p class="hint">' + esc(PR.t("目前模型：{model}", { model: chosenModel.name || chosenModel.id })) + '</p>' : "") +
      '<button class="btn sm" data-r="compare"' + (canStart ? "" : " disabled") + '>' + PR.t("產生比較報告") + '</button>' + taskMarkup() + '</section>' +
      reportMarkup() +
      '<section class="rs-section"><h3>' + PR.t("4. 主題研究矩陣") + '</h3><p class="hint">' +
      PR.t("選一篇已整理的論文，加入 Topic 筆記矩陣。原文定位會附在各欄；個人判斷保留空白。") + '</p>' +
      (topicNotes.length ? '<label class="rs-label">' + PR.t("主題筆記") + '<select class="input" data-r="topic-path">' + topicOptions + '</select></label>' :
        '<p class="hint">' + PR.t("目前沒有 Topic 筆記，先建立空白主題筆記。") + '</p>') +
      (parsed.length ? '<label class="rs-label">' + PR.t("論文") + '<select class="input" data-r="matrix-paper">' + paperOptions + '</select></label>' :
        '<p class="hint">' + PR.t("文獻庫中沒有已整理完成的論文。") + '</p>') +
      (state.topicProposal?.status === 'pending' ? '<p class="hint">' + PR.t("請先審閱或捨棄目前的新 Topic 提案。") + '</p>' : '') +
      (topicNotes.length ? '<details class="rs-create-topic"><summary>' + PR.t("建立另一個主題") + '</summary>' : '') +
      '<div class="rs-add"><input class="input" data-r="topic-title" placeholder="' + PR.t("例如：3D 點雲分割") + '" value="' + esc(state.topicTitle) + '"><button class="btn sm" data-r="topic-create"' + (configured && state.topicTitle.trim() && state.topicProposal?.status !== 'pending' ? '' : ' disabled') + '>' + PR.t("建立空白主題") + '</button></div>' +
      (topicNotes.length ? '</details>' : '') +
      (state.matrixProposal?.status === 'pending' ? '<p class="hint">' + PR.t("請先審閱或捨棄目前的矩陣提案。") + '</p>' : '') +
      (topicNotes.length && parsed.length ? '<button class="btn sm" data-r="matrix-start"' + (!configured || active() || matrixActive() || !matrixPaper || state.matrixProposal?.status === 'pending' ? ' disabled' : '') + '>' + PR.t("產生矩陣列草稿") + '</button>' : '') +
      matrixTaskMarkup() + '</section>' + stagedMarkup(state.matrixProposal, "matrix", PR.t("主題矩陣差異")) +
      stagedMarkup(state.topicProposal, "topic", PR.t("新主題筆記差異")) +
      wikiMarkup() +
      (state.error ? '<p class="rs-error">' + esc(state.error) + '</p>' : "") + '</div>';
    const scrollContainer = el.querySelector(".rs-scroll");
    if (scrollContainer) scrollContainer.scrollTop = previousScrollTop;
  }

  async function load() {
    state.busy = true; render();
    try {
      const [status, library] = await Promise.all([PR.api(endpoint + "/status"), PR.api("/api/library")]);
      state.status = status;
      state.papers = library.items || [];
      state.vault = state.vault || status.vault || "";
      if (!state.scheduleDraft && status.wiki_schedule) state.scheduleDraft = { ...status.wiki_schedule };
      state.proposal = status.pending_comparison || state.proposal;
      state.matrixProposal = status.pending_matrix || state.matrixProposal;
      state.topicProposal = status.pending_topic || state.topicProposal;
      if (!state.matrixPaper && state.papers.some((item) => item.id === PR.pid && item.parsed_blocks > 0)) state.matrixPaper = PR.pid;
      if (!state.selected.size && state.papers.some((item) => item.id === PR.pid && item.parsed_blocks > 0)) state.selected.add(PR.pid);
      const recent = (status.tasks || []).find((item) => item.kind === "comparison");
      if (recent) {
        state.task = recent;
        if (recent.state === "completed" && recent.result?.proposal?.id) {
          state.proposal = await PR.api(endpoint + "/proposals/" + recent.result.proposal.id);
        }
        if (["queued", "running", "cancelling"].includes(recent.state)) watch(recent.id);
      }
      const recentMatrix = (status.tasks || []).find((item) => item.kind === "matrix");
      if (recentMatrix) {
        state.matrixTask = recentMatrix;
        if (recentMatrix.state === "completed" && recentMatrix.result?.proposal?.id)
          state.matrixProposal = await PR.api(endpoint + "/proposals/" + recentMatrix.result.proposal.id);
        if (["queued", "running", "cancelling"].includes(recentMatrix.state)) watchMatrix(recentMatrix.id);
      }
      const recentLint = (status.tasks || []).find((item) => item.kind === "wiki-lint");
      if (recentLint) {
        state.lintTask = recentLint;
        if (["queued", "running", "cancelling"].includes(recentLint.state)) watchLint(recentLint.id);
      }
      if (status.configured) {
        try {
          state.wiki = await PR.api(endpoint + "/wiki/links");
          if (!state.wikiPage) state.wikiPage = state.topicPath || state.wiki.pages?.[0]?.path || "";
          if (!state.topicPath) state.topicPath = state.wiki.pages?.find((page) => page.kind === "topic")?.path || "";
        } catch (error) { state.error = error.message || String(error); }
      }
    } catch (error) { state.error = error.message || String(error); }
    finally { state.busy = false; render(); }
  }

  async function watch(identity) {
    if (state.poll === identity) return;
    state.poll = identity;
    while (state.poll === identity && PR.researchOpen()) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      try { state.task = await PR.api(endpoint + "/tasks/" + identity); }
      catch (error) { state.error = error.message || String(error); break; }
      if (state.task.state === "completed") state.proposal = state.task.result?.proposal || null;
      render();
      if (!["queued", "running", "cancelling"].includes(state.task.state)) break;
    }
    if (state.poll === identity) state.poll = "";
  }

  async function watchMatrix(identity) {
    const key = "matrix:" + identity;
    if (state.matrixPoll === key) return;
    state.matrixPoll = key;
    while (state.matrixPoll === key && PR.researchOpen()) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      try { state.matrixTask = await PR.api(endpoint + "/tasks/" + identity); }
      catch (error) { state.error = error.message || String(error); break; }
      if (state.matrixTask.state === "completed" && state.matrixTask.result?.proposal?.id)
        state.matrixProposal = await PR.api(endpoint + "/proposals/" + state.matrixTask.result.proposal.id);
      render();
      if (!["queued", "running", "cancelling"].includes(state.matrixTask.state)) break;
    }
    if (state.matrixPoll === key) state.matrixPoll = "";
  }

  async function watchLint(identity) {
    if (state.lintPoll === identity) return;
    state.lintPoll = identity;
    while (state.lintPoll === identity && PR.researchOpen()) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      try { state.lintTask = await PR.api(endpoint + "/tasks/" + identity); }
      catch (error) { state.error = error.message || String(error); break; }
      render();
      if (!["queued", "running", "cancelling"].includes(state.lintTask.state)) break;
    }
    if (state.lintPoll === identity) state.lintPoll = "";
  }

  async function run(fn) {
    if (state.busy) return;
    state.busy = true; state.error = ""; render();
    try { await fn(); } catch (error) { state.error = error.message || String(error); }
    finally { state.busy = false; render(); }
  }

  panel().addEventListener("click", async (event) => {
    const button = event.target.closest("[data-r]");
    if (!button) return;
    const action = button.dataset.r;
    if (action === "close") return PR.toggleResearch(false);
    if (action === "setup") return run(async () => {
      await PR.api(endpoint + "/setup", { method: "POST", body: { vault: state.vault } });
      state.status = await PR.api(endpoint + "/status");
      state.wiki = await PR.api(endpoint + "/wiki/links");
      state.topicPath = state.wiki.pages?.find((page) => page.kind === "topic")?.path || "";
    });
    if (action === "add-dimension") {
      const value = state.custom.trim().slice(0, 60);
      if (value && state.dimensions.size < 12) state.dimensions.add(value);
      state.custom = ""; render(); return;
    }
    if (action === "compare") return run(async () => {
      state.proposal = null;
      state.task = await PR.api(endpoint + "/comparison", { method: "POST", body: {
        paper_ids: [...state.selected], dimensions: [...state.dimensions], focus: state.focus,
        model: state.model || state.status?.model || "" } });
      watch(state.task.id);
    });
    if (action === "matrix-start") return run(async () => {
      state.matrixProposal = null;
      state.matrixTask = await PR.api(endpoint + "/matrix", { method: "POST", body: {
        paper_id: state.matrixPaper || PR.$('[data-r="matrix-paper"]', panel())?.value || "",
        topic_path: state.topicPath || PR.$('[data-r="topic-path"]', panel())?.value || "",
        model: state.model || state.status?.model || "" } });
      watchMatrix(state.matrixTask.id);
    });
    if (action === "matrix-cancel") return run(async () => {
      state.matrixTask = await PR.api(endpoint + "/tasks/" + state.matrixTask.id + "/cancel", { method: "POST", body: {} });
    });
    if (action === "topic-create") return run(async () => {
      state.topicProposal = await PR.api(endpoint + "/topics", { method: "POST", body: { title: state.topicTitle } });
    });
    if (action === "wiki-refresh") return run(async () => {
      state.wiki = await PR.api(endpoint + "/wiki/links");
      state.wikiPage = state.topicPath || state.wiki.pages?.[0]?.path || "";
    });
    if (action === "lint-start") return run(async () => {
      state.lintTask = await PR.api(endpoint + "/wiki/lint", { method: "POST", body: {
        semantic: state.semanticLint, model: state.model || state.status?.model || "" } });
      watchLint(state.lintTask.id);
    });
    if (action === "schedule-save") return run(async () => {
      const draft = state.scheduleDraft || state.status?.wiki_schedule || {};
      state.scheduleDraft = await PR.api(endpoint + "/wiki/schedule", { method: "POST", body: {
        enabled: !!draft.enabled, frequency: draft.frequency || "weekly", time: draft.time || "09:00" } });
      state.status.wiki_schedule = state.scheduleDraft;
    });
    if (action === "cancel") return run(async () => {
      state.task = await PR.api(endpoint + "/tasks/" + state.task.id + "/cancel", { method: "POST", body: {} });
    });
    if (action === "accept" || action === "reject") return run(async () => {
      state.proposal = await PR.api(endpoint + "/proposals/" + state.proposal.id + "/review", {
        method: "POST", body: { decision: action } });
    });
    if (["matrix-accept", "matrix-reject", "topic-accept", "topic-reject"].includes(action)) return run(async () => {
      const isTopic = action.startsWith("topic-");
      const proposal = isTopic ? state.topicProposal : state.matrixProposal;
      const decided = await PR.api(endpoint + "/proposals/" + proposal.id + "/review", {
        method: "POST", body: { decision: action.endsWith("accept") ? "accept" : "reject" } });
      if (isTopic) {
        state.topicProposal = decided;
        if (decided.status === "accepted") {
          state.topicPath = decided.path || decided.target;
          state.status = await PR.api(endpoint + "/status");
          state.wiki = await PR.api(endpoint + "/wiki/links");
        }
      } else {
        state.matrixProposal = decided;
        if (decided.status === "accepted") state.wiki = await PR.api(endpoint + "/wiki/links");
      }
    });
    if (action === "open-note") {
      const uri = obsidianUri(state.proposal?.path || state.proposal?.target || "");
      if (uri) window.open(uri, "_blank", "noopener");
    }
    if (action === "matrix-open" || action === "topic-open") {
      const proposal = action === "matrix-open" ? state.matrixProposal : state.topicProposal;
      const uri = obsidianUri(proposal?.path || proposal?.target || "");
      if (uri) window.open(uri, "_blank", "noopener");
    }
  });
  panel().addEventListener("change", (event) => {
    if (event.target.matches("[data-paper]")) {
      const id = event.target.dataset.paper;
      if (event.target.checked && state.selected.size >= 5) {
        state.error = PR.t("最多選擇 5 篇論文。");
        render();
        return;
      }
      if (event.target.checked) state.selected.add(id); else state.selected.delete(id);
      state.error = "";
      render();
    }
    if (event.target.matches("[data-dimension]")) {
      const value = event.target.dataset.dimension;
      if (event.target.checked) state.dimensions.add(value); else state.dimensions.delete(value);
      render();
    }
    if (event.target.matches("[data-r=model]")) {
      state.model = event.target.value;
      render();
    }
    if (event.target.matches('[data-r="matrix-paper"]')) state.matrixPaper = event.target.value;
    if (event.target.matches('[data-r="topic-path"]')) state.topicPath = event.target.value;
    if (event.target.matches('[data-r="wiki-page"]')) state.wikiPage = event.target.value;
    if (event.target.matches('[data-r="semantic-lint"]')) state.semanticLint = event.target.checked;
    if (event.target.matches('[data-r="schedule-enabled"]')) {
      state.scheduleDraft = { ...(state.scheduleDraft || state.status?.wiki_schedule || {}), enabled: event.target.checked };
      render();
    }
    if (event.target.matches('[data-r="schedule-frequency"]')) {
      state.scheduleDraft = { ...(state.scheduleDraft || state.status?.wiki_schedule || {}), frequency: event.target.value };
    }
    if (event.target.matches('[data-r="schedule-time"]')) {
      state.scheduleDraft = { ...(state.scheduleDraft || state.status?.wiki_schedule || {}), time: event.target.value };
    }
  });
  panel().addEventListener("input", (event) => {
    const key = event.target.dataset.r;
    if (["filter", "focus", "custom", "vault"].includes(key)) state[key] = event.target.value;
    if (key === "topic-title") {
      state.topicTitle = event.target.value;
      const button = PR.$('[data-r="topic-create"]', panel());
      if (button) button.disabled = !state.status?.configured || !state.topicTitle.trim() || state.topicProposal?.status === 'pending';
    }
    if (key === "filter") {
      const pos = event.target.selectionStart;
      render();
      const next = PR.$('[data-r="filter"]', panel());
      next?.focus(); next?.setSelectionRange(pos, pos);
    }
  });
  panel().addEventListener("toggle", (event) => {
    if (event.target.matches(".rs-settings")) state.showSettings = event.target.open;
  }, true);
  panel().addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches('[data-r="custom"]')) {
      event.preventDefault(); PR.$('[data-r="add-dimension"]', panel()).click();
    }
  });
})(window.PR);
