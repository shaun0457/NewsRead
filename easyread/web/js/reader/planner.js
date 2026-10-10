/* Research context for the currently open paper. */
(function (PR) {
  "use strict";
  const S = PR.state, API = "/api/research/v2";
  PR.researchOpen = () => PR.side === "research";
  PR.toggleResearch = function (force) {
    const open = force == null ? PR.side !== "research" : Boolean(force);
    PR.openSide(open ? "research" : null);
    if (open) render();
  };

  function paperTitle() { return S.paper?.meta?.title_zh || S.paper?.meta?.title_en || PR.t("這篇論文"); }
  function openUrl(path, params) { const url = new URLSearchParams(params); return path + "?" + url.toString(); }
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
      node.textContent = label.slice(0, 180);
      item.append(node); stack.at(-1).list.append(item);
      const children = document.createElement("ul"); item.append(children); stack.push({ depth: spaces, list: children });
    }
    return root;
  }
  async function renderMindmap(box, force = false) {
    const view = box.querySelector("#rp-mindmap"); if (!view) return;
    const button = box.querySelector("#rp-map-generate");
    const defaultLabel = PR.t("產生／更新心智圖");
    if (force && button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.textContent = PR.t("正在重新產生…");
    }
    view.replaceChildren(); view.setAttribute("aria-live", "polite");
    view.innerHTML = '<div class="rp-map-loading"><i class="spinner"></i><span>' + PR.t("正在根據論文內文整理研究心智圖…") + '</span></div>';
    const id = encodeURIComponent(PR.pid);
    try {
      const result = !force ? await PR.api(API + "/paper/" + id + "/mindmap") : null;
      if (!force && !result?.mermaid) { view.innerHTML = mindmapEmpty(); return; }
      const generated = force ? await PR.api(API + "/paper/" + id + "/mindmap", { method: "POST", body: { force: true } }) : result;
      view.replaceChildren(parseMindmap(generated.mermaid));
      const note = document.createElement("small"); note.className = "rp-map-meta"; note.textContent = PR.t("依目前論文文字產生 · {model}", { model: generated.model || PR.t("快取結果") }); view.append(note);
    } catch (error) {
      view.innerHTML = '<div class="rp-map-error"><span>' + PR.esc(error.message) + '</span><button class="btn sm line" data-rp-map-retry>重試</button></div>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    } finally {
      if (force && button) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.textContent = defaultLabel;
      }
    }
  }
  async function render() {
    const box = PR.$("#researchpanel"), id = PR.pid, item = S.item || {};
    const title = paperTitle();
    const params = { mode: "topic", q: S.paper?.meta?.title_en || title, start_title: title,
      start_doi: S.paper?.meta?.doi || "", start_openalex: S.paper?.meta?.openalex_id || "" };
    const researchLink = openUrl("/research", params);
    const interested = Boolean(item.starred ?? item.interested);
    box.innerHTML = '<div class="research-v2-head"><b>' + PR.t("研究脈絡") + '</b><button data-rp-close aria-label="關閉">×</button></div><div class="research-v2-body"><div class="rp-current">' + PR.esc(title) + '</div><section class="rp-section"><h3>' + PR.t("論文心智圖") + '</h3><p class="hint">' + PR.t("根據目前論文整理研究問題、方法、發現、貢獻與限制。") + '</p><div id="rp-mindmap" class="rp-mindmap"></div><button class="btn accent" id="rp-map-generate">' + PR.t("產生／更新心智圖") + '</button></section><section class="rp-section"><h3>' + PR.t("延伸探索") + '</h3><a class="btn line" href="' + PR.esc(researchLink) + '">' + PR.t("以此論文探索相關研究") + '</a><a class="btn line" href="' + PR.esc(openUrl("/research", { ...params, mode: "path" })) + '">' + PR.t("探索研究方向與閱讀路徑") + '</a><a class="btn line" href="' + PR.esc(openUrl("/research", { ...params, mode: "candidates" })) + '">' + PR.t("前往候選清單") + '</a></section><section class="rp-section"><h3>' + PR.t("閱讀狀態") + '</h3><div class="rp-status-controls"><div id="rp-status-options" class="seg rp-status-segment" role="group" aria-label="閱讀狀態"></div><button type="button" class="btn icon line rp-interest-star' + (interested ? ' is-interested' : '') + '" id="rp-interested" aria-label="' + PR.esc(PR.t(interested ? '取消感興趣' : '標記感興趣')) + '" title="' + PR.esc(PR.t(interested ? '取消感興趣' : '標記感興趣')) + '" aria-pressed="' + interested + '">' + PR.icon("star", "sm") + '</button></div><p class="hint">' + PR.t("閱讀進度依閱讀器紀錄，和是否理解或整理論文分開。") + '</p><div id="rp-status-feedback" class="hint" role="status" aria-live="polite"></div></section></div>'; /* i18n-dom: shared DOM translator localizes rendered UI text. */
    renderMindmap(box);
    try {
      const data = await PR.api(API);
      const options = box.querySelector("#rp-status-options"), statuses = (data.statuses || []).filter((x) => x.id !== "paused");
      options.style.setProperty("--rp-status-count", String(Math.max(statuses.length, 1)));
      for (const status of statuses) { const button = document.createElement("button"); button.type = "button"; button.dataset.rpStatus = status.id; button.textContent = status.label; button.classList.toggle("on", (item.status || "unread") === status.id); button.setAttribute("aria-pressed", String((item.status || "unread") === status.id)); options.append(button); }
    } catch (error) { box.querySelector("#rp-status-options").textContent = "無法載入狀態"; } /* i18n-dom: shared DOM translator localizes rendered UI text. */
    box.querySelector("#rp-map-generate").onclick = () => renderMindmap(box, true);
    box.onclick = async (event) => {
      if (event.target.closest("[data-rp-map-retry]")) renderMindmap(box, true);
      const statusButton = event.target.closest("[data-rp-status]");
      if (statusButton) {
        const options = box.querySelector("#rp-status-options");
        if (options.dataset.busy || statusButton.classList.contains("on")) return;
        const previous = options.querySelector(".on")?.dataset.rpStatus || "unread", next = statusButton.dataset.rpStatus;
        options.dataset.busy = "1"; options.querySelectorAll("button").forEach((button) => { button.disabled = true; });
      box.querySelector("#rp-status-feedback").textContent = PR.t("正在儲存狀態…");
        try {
          await PR.api(API + "/item", { method: "POST", body: { id, status: next } });
          S.item = { ...S.item, status: next };
          options.querySelectorAll("button").forEach((button) => { const active = button.dataset.rpStatus === next; button.classList.toggle("on", active); button.setAttribute("aria-pressed", String(active)); });
          box.querySelector("#rp-status-feedback").textContent = PR.t("閱讀狀態已更新。");
        } catch (error) { box.querySelector("#rp-status-feedback").textContent = PR.t("狀態儲存失敗，請重試。"); PR.toast(PR.esc(error.message)); }
        finally { delete options.dataset.busy; options.querySelectorAll("button").forEach((button) => { button.disabled = false; }); }
        return;
      }
      const interested = event.target.closest("#rp-interested");
      if (interested) {
        const active = interested.getAttribute("aria-pressed") !== "true";
        if (interested.disabled) return;
        interested.disabled = true;
        interested.classList.add("is-saving");
        PR.api(API + "/item", { method: "POST", body: { id, interested: active, starred: active } }).then(() => {
          S.item = { ...S.item, interested: active, starred: active };
          interested.setAttribute("aria-pressed", String(active));
          interested.classList.toggle("is-interested", active);
          interested.setAttribute("aria-label", active ? "取消感興趣" : "標記感興趣"); interested.title = active ? "取消感興趣" : "標記感興趣"; /* i18n-dom: shared DOM translator localizes rendered UI text. */
          PR.toast(active ? PR.t("已標記感興趣，首頁與閱讀看板會同步更新。") : PR.t("已取消感興趣標記，首頁與閱讀看板會同步更新。"));
        }).catch((error) => {
          PR.toast(PR.esc(error.message));
        }).finally(() => { interested.disabled = false; interested.classList.remove("is-saving"); });
      }
    };
  }
  document.addEventListener("click", (event) => { if (event.target.closest("[data-rp-close]")) PR.toggleResearch(false); });
})(window.PR);
