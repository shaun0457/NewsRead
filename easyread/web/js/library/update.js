/* 新版本提示：打开文献库时问一次服务（服务一天最多问一次 GitHub），有新版本就在顶栏放一个“新版本 x.y.z”，
   第一次看到这个版本时再弹一条提示。点开看这次更新了什么、去哪下载；可以跳过这个版本。
   帮助里有“检查更新”和“自动检查新版本”开关。 */
(function (PR) {
  "use strict";
  const SKIP = "easyread-skip-update", SEEN = "easyread-seen-update";
  const desktop = /Electron/i.test(navigator.userAgent);
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
    return desktop ? "下载对应系统的安装包，装上就会覆盖旧版本，论文和设置都还在。"
      : "从源码运行的：下载新版 zip 解压后双击 start.cmd（macOS / Linux 运行 ./start.sh），或者在项目目录里 git pull；用 pip 装的：pip install -U easyread。论文和设置在数据目录里，不受影响。";
  }

  function show(u) {
    PR.update = u;
    const on = !!(u && u.newer && PR.ls.get(SKIP, "") !== u.latest);
    chip.hidden = !on;
    if (!on) return;
    chip.innerHTML = '<span class="dot"></span><span>新版本 ' + PR.esc(u.latest) + "</span>";
    chip.title = "EasyRead " + u.latest + " 已发布，点开看更新了什么";
    if (PR.ls.get(SEEN, "") !== u.latest) {  // 每个新版本只弹一次
      PR.ls.set(SEEN, u.latest);
      PR.toast("EasyRead " + PR.esc(u.latest) + " 发布了", { label: "看看更新了什么", fn: PR.openUpdate }, 9000);
    }
  }

  PR.openUpdate = function () {
    const u = PR.update;
    if (!u || !u.latest) return;
    const dlg = PR.$("#textDlg");
    dlg.querySelector(".dialog").innerHTML =
      '<div class="help-head">' + PR.logo("hero sm") + "<div><h2>EasyRead " + PR.esc(u.latest) + (u.newer ? " 可以更新了" : "") + '</h2><div class="hint">你现在用的是 ' + PR.esc(u.current) +
      (u.published ? " · " + PR.esc(u.published.slice(0, 10)) + " 发布" : "") + "</div></div></div>" +
      '<div class="update-notes">' + (notesHtml(u.notes) || '<p class="hint">这次没写更新说明。</p>') + "</div>" +
      (u.newer ? '<p class="hint">' + howTo() + "</p>" : "") +
      '<div class="actions">' + (u.newer ? '<button class="btn" data-up="skip">跳过这个版本</button>' : "") + '<button class="btn" data-close>关闭</button>' +
      '<a class="btn accent" href="' + PR.esc(u.url) + '" target="_blank" rel="noopener">' + (u.newer ? "去下载" : "在 GitHub 上看") + "</a></div>";
    dlg.classList.add("open");
  };

  PR.$("#textDlg").addEventListener("click", (e) => {
    if (!e.target.closest('[data-up="skip"]')) return;
    PR.ls.set(SKIP, PR.update.latest);
    PR.$("#textDlg").classList.remove("open");
    show(PR.update);
    PR.toast("不再提示 " + PR.esc(PR.update.latest) + "，有更新的版本时再告诉你");
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

  setTimeout(() => PR.checkUpdate(false).catch(() => {}), 1500);  // 等文献库先显示出来
})(window.PR);
