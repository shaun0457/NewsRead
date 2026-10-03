/* 新版本提示：打开文献库时问一次服务（服务一天最多问一次 GitHub），有新版本就在顶栏放一个“新版本 x.y.z”，
   第一次看到这个版本时再弹一条提示。点开看这次更新了什么、去哪下载；可以跳过这个版本。
   帮助里有“检查更新”和“自动检查新版本”开关。 */
(function (PR) {
  "use strict";
  const SKIP = "easyread-skip-update", SEEN = "easyread-seen-update";
  const desktop = /Electron/i.test(navigator.userAgent);
  const bridge = window.easyreadDesktop;
  let nativeUpdate = { supported: false, phase: "idle" };
  function renderNativeUpdate() {
    const panel = document.querySelector("#nativeUpdate");
    if (!panel) return;
    panel.hidden = !nativeUpdate.supported;
    const phase = nativeUpdate.phase;
    const working = ["checking", "downloading", "installing"].includes(phase);
    const labels = { checking: "正在检查…", downloading: "正在下载更新", downloaded: "重启并更新", installing: "正在重启安装…", error: "重试更新", current: "已经是最新版" };
    panel.innerHTML = '<p class="hint">' + PR.t("在应用内下载更新，完成后点击重启安装。更新前请先完成正在进行的翻译或编辑。") + '</p>' +
      '<button class="btn accent" data-native-update' + (working ? " disabled" : "") + '>' +
      PR.t(labels[phase] || "下载更新") + (phase === "downloading" ? " " + Math.floor(nativeUpdate.percent || 0) + "%" : "") + '</button>' +
      (nativeUpdate.error ? '<p class="hint">' + PR.esc(nativeUpdate.error) + '</p>' : "");
  }
  function acceptNativeUpdate(state) { nativeUpdate = state; renderNativeUpdate(); }
  if (bridge && bridge.updateState) {
    bridge.onUpdateState(acceptNativeUpdate);
    bridge.updateState().then(acceptNativeUpdate).catch(() => {});
  }
  document.addEventListener("click", async event => {
    if (!event.target.closest("[data-native-update]")) return;
    try {
      acceptNativeUpdate(await (nativeUpdate.phase === "downloaded" ? bridge.installUpdate() : bridge.downloadUpdate()));
    } catch (error) { acceptNativeUpdate({ ...nativeUpdate, phase: "error", error: error.message }); }
  });
  PR.update = null;

  const chip = PR.el("button", { class: "engine-chip update-chip", id: "updateChip", hidden: "" });
  PR.$("#engineChip").before(chip);
  chip.onclick = () => PR.openUpdate();

  /* Release 说明是 Markdown：只认段落、“- ”列表、**粗体**、[链接](地址)、`代码`，够用了 */
  function inline(s) {
    return PR.esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/(^|[\s（(])(https?:\/\/[^\s<）)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  }
  function notesHtml(md) {
    let h = "", list = false;
    for (const raw of (md || "").split(/\r?\n/)) {
      const line = raw.trim();
      const li = line.match(/^[-*] (.*)/);
      if (li) { if (!list) { h += "<ul>"; list = true; } h += "<li>" + inline(li[1]) + "</li>"; continue; }
      if (list) { h += "</ul>"; list = false; }
      if (!line) continue;
      const head = line.match(/^#{1,4} (.*)/);
      h += head ? "<h4>" + inline(head[1]) + "</h4>" : "<p>" + inline(line) + "</p>";
    }
    return h + (list ? "</ul>" : "");
  }

  function howTo() {
    if (nativeUpdate.supported) return PR.t("可以直接在此下载并重启更新；也可以前往 GitHub 手动下载安装包。论文和设置保留。");
    return desktop ? PR.t("下载对应系统的安装包，装上就会覆盖旧版本，论文和设置都还在。")
      : PR.t("从源码运行的：下载新版 zip 解压后双击 start.cmd（macOS / Linux 运行 ./start.sh），或者在项目目录里 git pull；用 pip 装的：pip install -U easyread。论文和设置在数据目录里，不受影响。");
  }

  function show(u) {
    PR.update = u;
    const on = !!(u && u.newer && PR.ls.get(SKIP, "") !== u.latest);
    chip.hidden = !on;
    if (!on) return;
    chip.innerHTML = '<span class="dot"></span><span>' + PR.t("新版本 {v}", { v: PR.esc(u.latest) }) + "</span>";
    chip.title = PR.t("EasyRead {v} 已发布，点开看更新了什么", { v: u.latest });
    if (PR.ls.get(SEEN, "") !== u.latest) {  // 每个新版本只弹一次
      PR.ls.set(SEEN, u.latest);
      PR.toast(PR.t("EasyRead {v} 发布了", { v: PR.esc(u.latest) }), { label: PR.t("看看更新了什么"), fn: PR.openUpdate }, 9000);
    }
  }

  PR.openUpdate = function () {
    const u = PR.update;
    if (!u || !u.latest) return;
    const dlg = PR.$("#textDlg");
    dlg.querySelector(".dialog").innerHTML =
      '<div class="help-head">' + PR.logo("hero sm") + "<div><h2>EasyRead " + PR.esc(u.latest) + (u.newer ? PR.t(" 可以更新了") : "") + '</h2><div class="hint">' + PR.t("你现在用的是 {v}", { v: PR.esc(u.current) }) +
      (u.published ? PR.t(" · {date} 发布", { date: PR.esc(u.published.slice(0, 10)) }) : "") + "</div></div></div>" +
      '<div class="update-notes">' + (notesHtml(u.notes) || '<p class="hint">' + PR.t("这次没写更新说明。") + "</p>") + "</div>" +
      (u.newer ? '<p class="hint">' + howTo() + "</p>" : "") +
      (u.newer ? '<div id="nativeUpdate" hidden></div>' : "") +
      '<div class="actions">' + (u.newer ? '<button class="btn" data-up="skip">' + PR.t("跳过这个版本") + "</button>" : "") + '<button class="btn" data-close>' + PR.t("关闭") + "</button>" +
      '<a class="btn accent" href="' + PR.esc(u.url) + '" target="_blank" rel="noopener">' + (u.newer ? PR.t("去下载") : PR.t("在 GitHub 上看")) + "</a></div>";
    dlg.classList.add("open");
    renderNativeUpdate();
  };

  PR.$("#textDlg").addEventListener("click", (e) => {
    if (!e.target.closest('[data-up="skip"]')) return;
    PR.ls.set(SKIP, PR.update.latest);
    PR.$("#textDlg").classList.remove("open");
    show(PR.update);
    PR.toast(PR.t("不再提示 {v}，有更新的版本时再告诉你", { v: PR.esc(PR.update.latest) }));
  });

  /* 帮助里用：force 为真时马上问 GitHub */
  PR.checkUpdate = async function (force) {
    const u = await PR.api("/api/update" + (force ? "?force=1" : ""));
    if (force) PR.ls.set(SKIP, "");  // 手动检查：之前跳过的版本也重新提示
    show(u);
    return u;
  };
  PR.setAutoUpdate = async function (on) {
    show(await PR.api("/api/update", { method: "POST", body: { enabled: on } }));
  };

  /* 设置 → 阅读最下面：版本、检查更新、自动检查开关 */
  function updateLine() {
    const u = PR.update;
    if (!u) return "";
    if (u.newer) return PR.t("有新版本 {v}", { v: '<a href="#" data-help="open">' + PR.esc(u.latest) + "</a>" });
    return u.latest ? PR.t("已经是最新版") : "";
  }
  PR.updateSection = () => '<h4 class="set-h">' + PR.t("版本") + '</h4><div class="help-update"><span>' + PR.esc(PR.lib.version || "") + "</span>" +
    '<button class="btn sm line" data-help="check">' + PR.t("检查更新") + '</button><span class="hint" id="helpUpdateMsg">' + updateLine() + "</span>" +
    '<label class="check"><input type="checkbox" data-help="auto"' + (!PR.update || PR.update.enabled !== false ? " checked" : "") + ">" + PR.t("自动检查新版本（一天一次，只问 GitHub）") + "</label></div>";
  document.addEventListener("click", async (e) => {
    const b = e.target.closest('[data-help="check"], [data-help="open"]');
    if (!b) return;
    e.preventDefault();
    if (b.dataset.help === "open") return PR.openUpdate();
    const msg = PR.$("#helpUpdateMsg");
    b.disabled = true; msg.textContent = PR.t("正在检查…");
    try {
      const u = await PR.checkUpdate(true);
      msg.innerHTML = u.latest ? updateLine() : PR.t("没连上 GitHub，稍后再试");
    } catch (err) { msg.textContent = PR.t("检查失败：") + err.message; }
    b.disabled = false;
  });
  document.addEventListener("change", (e) => {
    if (e.target.dataset.help === "auto") PR.setAutoUpdate(e.target.checked).catch((err) => PR.toast(PR.t("保存失败：") + PR.esc(err.message)));
  });

  setTimeout(() => PR.checkUpdate(false).catch(() => {}), 1500);  // 等文献库先显示出来
})(window.PR);
