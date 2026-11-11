/* 閱讀器的心智圖側欄（ticket 03 起只剩心智圖；閱讀路徑、深度剖析、閱讀狀態隨研究工作區移除）。 */
(function (PR) {
  "use strict";
  const S = PR.state, API = "/api/reader";
  PR.researchOpen = () => PR.side === "research";
  PR.toggleResearch = function (force) {
    const open = force == null ? PR.side !== "research" : Boolean(force);
    PR.openSide(open ? "research" : null);
    if (open) render();
  };

  function paperTitle() { return S.paper?.meta?.title_zh || S.paper?.meta?.title_en || PR.t("這篇論文"); }
  const titleHtml = (value, fallback = "") => PR.titleHtml ? PR.titleHtml(value || fallback) : PR.esc(value || fallback);
  function mindmapEmpty() {
    return '<div class="rp-map-empty"><svg viewBox="0 0 180 104" role="img" aria-label="研究心智圖示意圖" xmlns="http://www.w3.org/2000/svg"><path d="M90 50 42 24M90 50 139 24M90 50 42 80M90 50 139 80" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><rect x="67" y="36" width="46" height="28" rx="10" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2"/><rect x="18" y="12" width="48" height="23" rx="8" fill="var(--surface)" stroke="currentColor"/><rect x="115" y="12" width="48" height="23" rx="8" fill="var(--surface)" stroke="currentColor"/><rect x="18" y="69" width="48" height="23" rx="8" fill="var(--surface)" stroke="currentColor"/><rect x="115" y="69" width="48" height="23" rx="8" fill="var(--surface)" stroke="currentColor"/><circle cx="90" cy="50" r="4" fill="var(--accent)"/></svg><p>' + PR.t("尚未產生心智圖") + '</p><span>' + PR.t("產生後會在這裡呈現論文的研究脈絡。") + '</span></div>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
  }
  function parseMindmap(source) {
    const root = document.createElement("ul"); root.className = "rp-tree";
    const stack = [{ depth: -1, list: root }];
    for (const line of String(source || "").split(/\r?\n/)) {
      if (!line.trim() || /^\s*mindmap\s*$/i.test(line)) continue;
      const spaces = (line.match(/^\s*/) || [""])[0].replace(/\t/g, "  ").length;
      let label = line.trim();
      // Mermaid mindmap labels may have an explicit node id followed by a
      // shape delimiter. Plain labels (including Chinese text) must stay intact.
      label = label.replace(/^[\w-]+(?=\(\(|\[|\{|\()/, "");
      label = label.replace(/^root\(\((.*)\)\)$/i, "$1").replace(/^\(\((.*)\)\)$/, "$1").replace(/^\((.*)\)$/, "$1").replace(/^\[(.*)\]$/, "$1").replace(/^\{(.*)\}$/, "$1").trim();
      if (!label) continue;
      while (stack.length > 1 && stack.at(-1).depth >= spaces) stack.pop();
      const item = document.createElement("li"), node = document.createElement("span");
      node.className = stack.length === 1 ? "rp-node root" : "rp-node";
      node.innerHTML = titleHtml(label.slice(0, 180));
      item.append(node); stack.at(-1).list.append(item);
      const children = document.createElement("ul"); item.append(children); stack.push({ depth: spaces, list: children });
    }
    return root;
  }
  let activeMindmapCtrl = null;
  let lastGeneratedMindmap = null;

  function displayMindmap(box, data) {
    const view = box.querySelector("#rp-mindmap"); if (!view) return;
    const expandBtn = box.querySelector("#rp-map-expand");
    const title = paperTitle();
    if (activeMindmapCtrl) {
      activeMindmapCtrl.destroy();
      activeMindmapCtrl = null;
    }
    if (PR.mindmap && PR.mindmap.renderPanel) {
      activeMindmapCtrl = PR.mindmap.renderPanel(view, data, {
        title,
        onRegenerate: () => renderMindmap(box, true),
      });
    } else {
      view.replaceChildren(parseMindmap(data.mermaid));
    }
    const note = document.createElement("small"); note.className = "rp-map-meta"; note.textContent = PR.t("依目前論文文字產生 · {model}", { model: data.model || PR.t("快取結果") }); view.append(note);
    if (expandBtn) expandBtn.style.display = "";
  }

  async function renderMindmap(box, force = false) {
    const view = box.querySelector("#rp-mindmap"); if (!view) return;
    const button = box.querySelector("#rp-map-generate");
    const expandBtn = box.querySelector("#rp-map-expand");
    const defaultLabel = PR.t("產生／更新心智圖");
    const id = encodeURIComponent(PR.pid);

    if (force) {
      if (button) {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        button.textContent = PR.t("正在重新產生…");
      }
      if (activeMindmapCtrl) {
        activeMindmapCtrl.destroy();
        activeMindmapCtrl = null;
      }
      view.replaceChildren(); view.setAttribute("aria-live", "polite");
      view.innerHTML = '<div class="rp-map-loading"><i class="spinner"></i><span>' + PR.t("正在依據論文內文產生心智圖…") + '</span></div>';
      if (expandBtn) expandBtn.style.display = "none";
      try {
        const res = await PR.api(API + "/paper/" + id + "/mindmap/tasks", { method: "POST", body: { force: true } });
        PR.researchTaskMonitor?.track(res.task, true);
        if (res.task && res.task.state === "completed" && res.task.result) {
          lastGeneratedMindmap = res.task.result;
          displayMindmap(box, res.task.result);
          if (button) { button.disabled = false; button.removeAttribute("aria-busy"); button.textContent = defaultLabel; }
        }
      } catch (error) {
        if (button) { button.disabled = false; button.removeAttribute("aria-busy"); button.textContent = defaultLabel; }
        view.innerHTML = '<div class="rp-map-error"><span>' + PR.esc(error.message) + '</span><button class="btn sm line" data-rp-map-retry>' + PR.t("重試") + '</button></div>';
      }
      return;
    }

    if (activeMindmapCtrl) {
      activeMindmapCtrl.destroy();
      activeMindmapCtrl = null;
    }
    view.replaceChildren(); view.setAttribute("aria-live", "polite");
    view.innerHTML = '<div class="rp-map-loading"><i class="spinner"></i><span>' + PR.t("正在根據論文內文整理研究心智圖…") + '</span></div>';
    if (expandBtn) expandBtn.style.display = "none";
    try {
      const result = await PR.api(API + "/paper/" + id + "/mindmap");
      const liveTask = result?.task;
      if (liveTask && ["queued", "running", "cancelling"].includes(liveTask.state)) {
        if (button) {
          button.disabled = true;
          button.setAttribute("aria-busy", "true");
          button.textContent = PR.t("正在重新產生…");
        }
        view.innerHTML = '<div class="rp-map-loading"><i class="spinner"></i><span>' + PR.esc(liveTask.message || PR.t("正在依據論文內文產生心智圖…")) + '</span></div>';
        PR.researchTaskMonitor?.track(liveTask, false);
        return;
      }
      if (button) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.textContent = defaultLabel;
      }
      if (!result?.mermaid) { view.innerHTML = mindmapEmpty(); return; }
      lastGeneratedMindmap = result;
      displayMindmap(box, result);
    } catch (error) {
      if (button) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.textContent = defaultLabel;
      }
      view.innerHTML = '<div class="rp-map-error"><span>' + PR.esc(error.message) + '</span><button class="btn sm line" data-rp-map-retry>' + PR.t("重試") + '</button></div>';
    }
  }
  async function render() {
    const box = PR.$("#researchpanel");
    const title = paperTitle();
    box.innerHTML = '<div class="research-v2-head"><b>' + PR.t("心智圖") + '</b><button data-rp-close aria-label="關閉">×</button></div><div class="research-v2-body"><div class="rp-current">' + titleHtml(title) + '</div><section class="rp-section"><div class="rp-section-titleline"><h3>' + PR.t("論文心智圖") + '</h3><button type="button" class="btn sm line rp-btn-expand" id="rp-map-expand" style="display:none">' + PR.t("詳細檢視") + '</button></div><p class="hint">' + PR.t("根據目前論文整理研究問題、方法、發現、貢獻與限制。") + '</p><div id="rp-mindmap" class="rp-mindmap"></div><button class="btn accent" id="rp-map-generate">' + PR.t("產生／更新心智圖") + '</button></section></div>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    renderMindmap(box);
    box.querySelector("#rp-map-generate").onclick = () => renderMindmap(box, true);
    const expandBtn = box.querySelector("#rp-map-expand");
    if (expandBtn) {
      expandBtn.onclick = () => {
        if (!lastGeneratedMindmap || !PR.mindmap) return;
        const mindData = PR.mindmap.parseToData(lastGeneratedMindmap.mermaid, paperTitle());
        PR.mindmap.openModal(mindData, {
          title: paperTitle(),
          onRegenerate: () => renderMindmap(box, true),
        });
      };
    }
    box.onclick = (event) => {
      if (event.target.closest("[data-rp-map-retry]")) renderMindmap(box, true);
    };
  }
  document.addEventListener("click", (event) => { if (event.target.closest("[data-rp-close]")) PR.toggleResearch(false); });

  if (typeof PR.on === "function") {
    PR.on("research-task-update", (status) => {
      const task = status?.mindmap;
      if (!task) return;
      if (task.paper_id && task.paper_id !== PR.pid) return;
      const box = PR.$("#researchpanel");
      if (!box || !PR.researchOpen()) return;
      const view = box.querySelector("#rp-mindmap");
      const button = box.querySelector("#rp-map-generate");
      const expandBtn = box.querySelector("#rp-map-expand");
      const defaultLabel = PR.t("產生／更新心智圖");
      if (task.state === "completed") {
        renderMindmap(box, false);
      } else if (task.state === "failed" || task.state === "interrupted") {
        if (button) { button.disabled = false; button.removeAttribute("aria-busy"); button.textContent = defaultLabel; }
        if (view) view.innerHTML = '<div class="rp-map-error"><span>' + PR.esc(task.message || PR.t("分析未完成")) + '</span><button class="btn sm line" data-rp-map-retry>' + PR.t("重試") + '</button></div>';
      } else if (task.state === "cancelled") {
        if (button) { button.disabled = false; button.removeAttribute("aria-busy"); button.textContent = defaultLabel; }
        renderMindmap(box, false);
      } else if (["queued", "running", "cancelling"].includes(task.state)) {
        if (button) { button.disabled = true; button.setAttribute("aria-busy", "true"); button.textContent = PR.t("正在重新產生…"); }
        if (expandBtn) expandBtn.style.display = "none";
        if (view && !view.querySelector(".rp-map-loading")) {
          view.replaceChildren();
          view.innerHTML = '<div class="rp-map-loading"><i class="spinner"></i><span>' + PR.esc(task.message || PR.t("正在依據論文內文產生心智圖…")) + '</span></div>';
        }
      }
    });

    PR.on("open-research-mindmap", () => {
      PR.toggleResearch(true);
      const box = PR.$("#researchpanel");
      if (box) {
        const view = box.querySelector("#rp-mindmap");
        if (view) view.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });

    PR.on("retry-research-mindmap", () => {
      PR.toggleResearch(true);
      const box = PR.$("#researchpanel");
      if (box) renderMindmap(box, true);
    });
  }

  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("open") === "mindmap") {
      setTimeout(() => PR.toggleResearch(true), 300);
    }
  } catch (_) {}

})(window.PR);
