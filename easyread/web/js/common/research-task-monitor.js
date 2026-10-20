/* Cross-page monitor for local research analyses. */
(function (PR) {
  "use strict";
  const PATH_API = "/api/research/v2/reading-path/tasks";
  const state = { scope: "", path: null, comparison: null, tasks: [], timer: 0, busy: false, dialogTask: null, dialogOpen: false, returnFocus: null };
  const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);
  const active = (task) => task && ["queued", "running", "cancelling"].includes(task.state);
  const esc = (value) => PR.esc(String(value || ""));
  const key = () => "paperread:research-task-acks:" + (state.scope || "unknown");
  function acknowledgedIds() {
    try { const data = JSON.parse(localStorage.getItem(key()) || "[]"); return new Set(Array.isArray(data) ? data : []); }
    catch (_) { return new Set(); }
  }
  function rememberAck(id) {
    if (!id) return;
    const ids = acknowledgedIds(); ids.add(id);
    try { localStorage.setItem(key(), JSON.stringify([...ids].slice(-100))); } catch (_) { /* notification still works for this page */ }
  }
  function taskType(task) { return task?.kind === "comparison" ? "comparison" : "path"; }
  function label(task) { return taskType(task) === "path" ? PR.t("閱讀路徑分析") : PR.t("跨論文比較"); }
  function resultUrl(task, retry = false) {
    if (taskType(task) === "path") return "/research?mode=path" + (retry ? "&retry_task=" + encodeURIComponent(task.id) : "");
    return "/research?mode=comparisons";
  }
  function taskList() { return [state.path, state.comparison].filter(Boolean); }
  function ack(task) {
    if (!task?.id || task.acknowledged) return;
    task.acknowledged = true; rememberAck(task.id);
    const url = taskType(task) === "path" ? PATH_API + "/" + encodeURIComponent(task.id) + "/ack"
      : "/api/research/v1/tasks/" + encodeURIComponent(task.id) + "/ack";
    PR.api(url, { method: "POST", body: {} }).catch(() => {});
  }
  function closeDialog() {
    const modal = PR.$("#pr-research-task-modal");
    if (modal) modal.hidden = true;
    state.dialogOpen = false;
    if (state.returnFocus?.isConnected) state.returnFocus.focus();
    state.returnFocus = null;
  }
  function cancel(task) {
    const url = taskType(task) === "path" ? PATH_API + "/" + encodeURIComponent(task.id) + "/cancel"
      : "/api/research/v1/tasks/" + encodeURIComponent(task.id) + "/cancel";
    task.state = "cancelling"; task.message = PR.t("正在取消分析…"); render();
    PR.api(url, { method: "POST", body: {} }).then((result) => {
      const updated = result.task || result;
      if (taskType(updated) === "path") state.path = updated; else state.comparison = updated;
      render();
    }).catch((error) => PR.toast(esc(PR.t(error.message))));
  }
  function renderDialog() {
    const modal = PR.$("#pr-research-task-modal");
    const task = taskList().find((item) => item.id === state.dialogTask) || state.dialogTask;
    if (!modal || !task) return;
    const wasVisible = !modal.hidden;
    const focusedAction = wasVisible ? ["continue", "cancel", "view", "retry"].find((name) =>
      document.activeElement?.hasAttribute("data-task-" + name)) : "";
    const isPath = taskType(task) === "path", running = active(task);
    let title = running ? (isPath ? PR.t("正在分析閱讀路徑") : PR.t("正在整理跨論文比較…"))
      : task.state === "completed" ? (isPath ? PR.t("閱讀路徑已完成") : PR.t("跨論文比較已完成"))
      : task.state === "cancelled" ? PR.t("分析已取消")
      : task.state === "interrupted" ? PR.t("分析已中斷") : PR.t("分析未完成");
    let detail = task.state === "completed" && task.result?.warning
      ? task.result.warning
      : task.message || (running ? PR.t("你可以關閉此視窗，繼續使用 PaperRead；完成後會通知你。") : "");
    const signature = [task.id, task.state, task.phase, title, detail].join("\n");
    if (!modal.hidden && modal.dataset.signature === signature) return;
    const controls = running
      ? '<button class="btn line" type="button" data-task-continue>' + PR.t("繼續使用") + '</button>' + (task.state === "cancelling" ? '' : '<button class="btn danger" type="button" data-task-cancel>' + PR.t("取消分析") + '</button>')
      : task.state === "completed"
        ? '<button class="btn accent" type="button" data-task-view>' + PR.t("查看結果") + '</button>'
        : (task.state === "failed" || task.state === "interrupted")
          ? '<button class="btn accent" type="button" data-task-retry>' + PR.t("返回重試") + '</button>'
          : '<button class="btn line" type="button" data-task-continue>' + PR.t("關閉") + '</button>';
    modal.innerHTML = '<div class="pr-task-dialog" role="dialog" aria-modal="true" aria-labelledby="pr-task-title"><div class="pr-task-head"><span class="pr-task-indicator' + (running ? ' is-running' : '') + '"></span><h2 id="pr-task-title">' + esc(title) + '</h2><button type="button" class="pr-task-close" data-task-continue aria-label="' + esc(PR.t("關閉")) + '">×</button></div><p class="pr-task-kind">' + esc(label(task)) + '</p><p class="pr-task-message" role="status">' + esc(detail) + '</p>' + (running && isPath ? '<p class="pr-task-help">' + PR.t("你可以關閉此視窗，繼續使用 PaperRead；完成後會通知你。") + '</p>' : '') + '<div class="pr-task-actions">' + controls + '</div></div>';
    modal.dataset.signature = signature;
    modal.hidden = false;
    state.dialogOpen = true;
    if (terminal.has(task.state)) ack(task);
    const closeButtons = modal.querySelectorAll("[data-task-continue]");
    closeButtons.forEach((button) => { button.onclick = closeDialog; });
    const cancelButton = modal.querySelector("[data-task-cancel]");
    if (cancelButton) cancelButton.onclick = () => cancel(task);
    const viewButton = modal.querySelector("[data-task-view]");
    if (viewButton) viewButton.onclick = () => { ack(task); closeDialog(); location.href = resultUrl(task); };
    const retryButton = modal.querySelector("[data-task-retry]");
    if (retryButton) retryButton.onclick = () => { ack(task); closeDialog(); location.href = resultUrl(task, true); };
    const focusTarget = (focusedAction && modal.querySelector("[data-task-" + focusedAction + "]"))
      || modal.querySelector("[data-task-view], [data-task-retry], [data-task-continue]") || modal;
    if (!wasVisible || focusedAction) focusTarget.focus?.();
  }
  function show(task) {
    if (!task) return;
    if (!state.dialogOpen) state.returnFocus = document.activeElement;
    state.dialogTask = task.id;
    renderDialog();
  }
  function render() {
    let widget = PR.$("#pr-research-task-entry");
    if (!widget) { widget = PR.el("div", { id: "pr-research-task-entry", class: "pr-task-entry" }); document.body.appendChild(widget); }
    const tasks = taskList();
    const working = tasks.filter(active);
    const unread = tasks.find((task) => terminal.has(task.state) && !task.acknowledged && !acknowledgedIds().has(task.id));
    const current = working[0] || unread;
    widget.hidden = !current;
    if (current) {
      widget.innerHTML = '<button type="button" class="pr-task-entry-button" aria-label="' + esc(label(current)) + '"><span class="pr-task-entry-dot' + (working.length ? ' is-running' : '') + '"></span><span>' + esc(working.length ? PR.t("{name}進行中", { name: label(current) }) : PR.t("研究分析已完成")) + '</span><span class="pr-task-entry-chevron">›</span></button>';
      widget.firstElementChild.onclick = () => show(current);
    }
    if (state.dialogOpen) renderDialog();
  }
  function notifyTerminal(task) {
    if (!terminal.has(task.state) || task.state === "cancelled" || task.acknowledged || acknowledgedIds().has(task.id)) return;
    if (state.dialogOpen && state.dialogTask === task.id) { renderDialog(); return; }
    const completed = task.state === "completed";
    const title = completed ? (taskType(task) === "path" ? PR.t("閱讀路徑已完成") : PR.t("跨論文比較已完成")) :
      task.state === "interrupted" ? PR.t("分析已中斷") : PR.t("分析未完成");
    const actionLabel = completed ? PR.t("查看結果") : PR.t("返回重試");
    PR.toast(esc(title) + (task.message ? " · " + esc(task.message) : ""), {
      label: actionLabel,
      fn: () => { ack(task); location.href = resultUrl(task, !completed); }
    }, 9000);
    ack(task);
  }
  function applyPath(task) {
    if (!task) return;
    const previous = state.path?.state;
    state.path = task;
    if (terminal.has(task.state) && previous && !terminal.has(previous)) notifyTerminal(task);
    else if (terminal.has(task.state) && !task.acknowledged && !acknowledgedIds().has(task.id)) notifyTerminal(task);
  }
  function applyComparison(tasks) {
    const task = (tasks || []).filter((item) => item.kind === "comparison")
      .sort((a, b) => Number(b.created || 0) - Number(a.created || 0))[0] || null;
    if (!task) return;
    const previous = state.comparison?.state;
    state.comparison = task;
    if (terminal.has(task.state) && previous && !terminal.has(previous)) notifyTerminal(task);
    else if (terminal.has(task.state) && !task.acknowledged && !acknowledgedIds().has(task.id)) notifyTerminal(task);
  }
  async function poll() {
    if (state.busy || !PR.token) return schedule();
    state.busy = true;
    try {
      const [monitor, pathState] = await Promise.all([
        PR.api("/api/research/v1/monitor"),
        PR.api(PATH_API + "/current")
      ]);
      state.scope = monitor.scope_id || state.scope;
      const pathTask = pathState.task;
      if (pathTask) {
        if (acknowledgedIds().has(pathTask.id)) pathTask.acknowledged = true;
        applyPath(pathTask);
      }
      applyComparison(monitor.tasks);
      render();
      PR.emit("research-task-update", { path: state.path, comparison: state.comparison });
    } catch (_) { /* keep the last known state while the local service reconnects */ }
    finally { state.busy = false; schedule(); }
  }
  function schedule() {
    clearTimeout(state.timer);
    if (taskList().some(active)) state.timer = setTimeout(poll, 2000);
  }
  async function init() {
    if (location.protocol !== "http:") return;
    if (!PR.$("#pr-research-task-modal")) {
      const modal = PR.el("div", { id: "pr-research-task-modal", class: "pr-task-modal", hidden: true, tabindex: "-1" });
      document.body.appendChild(modal);
    }
    try {
      const library = await PR.api("/api/library");
      PR.token = library.token;
      await poll();
    } catch (_) { /* page app shows its own connection error */ }
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && taskList().some(active)) poll(); });
  document.addEventListener("keydown", (event) => {
    if (!state.dialogOpen) return;
    if (event.key === "Escape") { event.preventDefault(); closeDialog(); return; }
    if (event.key !== "Tab") return;
    const modal = PR.$("#pr-research-task-modal");
    const controls = Array.from(modal?.querySelectorAll('button:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])') || []);
    if (!controls.length) { event.preventDefault(); modal?.focus(); return; }
    const first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && (document.activeElement === first || !modal.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !modal.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  });
  document.addEventListener("click", (event) => {
    if (event.target.id === "pr-research-task-modal") closeDialog();
  });
  PR.researchTaskMonitor = {
    track(task, open = false) {
      if (!task) return;
      if (task.kind === "reading-path") state.path = task;
      else if (task.kind === "comparison") state.comparison = task;
      if (open) show(task);
      render(); schedule();
    },
    show,
    poll
  };
  init();
})(window.PR);
