/* 设置 → 云文献库：只管理本地位置，同步交给网盘客户端。 */
(function (PR) {
  "use strict";
  let busy = false, dismissedHost = "";
  const state = () => PR.settingsState;
  const redraw = () => { if (state().tab === "cloud") PR.settingsRender(); };
  const size = (n) => n >= 1073741824 ? (n / 1073741824).toFixed(1) + " GB" : (n / 1048576).toFixed(1) + " MB";
  const disabled = (s) => busy || (s.cloud && (s.cloud.temp || s.cloud.restart_required || s.cloud.moving));

  async function load(s) {
    if (s.cloudLoading) return;
    s.cloudLoading = true; s.cloudError = "";
    try { s.cloud = await PR.api("/api/library/location"); }
    catch (e) { s.cloudError = e.message; }
    finally { s.cloudLoading = false; redraw(); }
  }

  function button(action, label, path, off, primary) {
    return '<button class="btn sm ' + (primary ? "accent" : "line") + '" data-cloud="' + action + '"' + (path ? ' data-path="' + PR.esc(path) + '"' : "") +
      (off ? " disabled" : "") + ">" + PR.esc(label) + "</button>";
  }

  /* 一张网盘卡片：名字 + 一句状态 + 一个主按钮；目标已有论文时“合并”退成次要的文字按钮 */
  function target(s, item) {
    const name = PR.esc(item.label || PR.t("自定义文件夹"));
    const head = '<div class="cloud-card-icon">' + PR.icon(item.label ? "cloud" : "folder") + '</div><div class="cloud-card-body"><b>' + name + '</b><div class="cloud-path">' + PR.esc(item.path) + "</div>";
    if (item.incomplete) return '<div class="cloud-card warn">' + head + '<span class="cloud-state">' + PR.t("上次搬到这里没完成，原文献库没受影响") + '</span></div>' +
      button("cleanup", PR.t("清理没搬完的内容"), item.path, busy) + "</div>";
    const off = disabled(s) || !item.writable || item.path === s.cloud.path;
    const state = item.path === s.cloud.path ? PR.t("正在用") : !item.writable ? PR.t("不可写") : item.papers ? PR.t("里面已有 {n} 篇", { n: item.papers }) : PR.t("空的，可以搬过去");
    const acts = item.papers
      ? button("use", PR.t("改用这里的文献库"), item.path, off, true) + '<button class="linkish" data-cloud="merge" data-path="' + PR.esc(item.path) + '"' + (off ? " disabled" : "") + ">" + PR.t("或把本机的也合并进去") + "</button>"
      : button("copy", PR.t("搬过去"), item.path, off, true);
    return '<div class="cloud-card">' + head + '<span class="cloud-state">' + state + "</span></div>" + '<div class="cloud-card-acts">' + acts + "</div></div>";
  }

  function where(d) {  // 现在的文献库在哪个网盘里
    const norm = (p) => String(p || "").replace(/[\\/]+$/, "").replace(/\\/g, "/").toLowerCase() + "/";
    const hit = (d.candidates || []).find((c) => c.root_path && norm(d.path).startsWith(norm(c.root_path)));
    return hit ? PR.t("在 {name} 里，会自动同步", { name: hit.label }) : PR.t("在本机，不会同步");
  }

  function result(s) {
    const r = s.cloudResult;
    if (!r && !(s.cloud && s.cloud.restart_required)) return "";
    return '<div class="cloud-result" role="status"><b>' + PR.t("需要重启 EasyRead 才能生效") + '</b><p class="cloud-path">' +
      PR.esc(r ? r.message : PR.t("文献库位置已更改，请先重启再继续阅读。")) + "</p>" +
      (r ? '<p>' + PR.t("已复制 {copied} 篇，跳过 {skipped} 项", { copied: r.copied || 0, skipped: (r.skipped || []).length }) + "</p>" +
        ((r.skipped || []).length ? '<details><summary>' + PR.t("查看跳过的项目") + '</summary><ul>' +
          r.skipped.map((x) => '<li class="cloud-path">' + PR.esc(x.id + ": " + x.reason) + '</li>').join("") + '</ul></details>' : "") : "") +
      (r && r.old_path ? '<p class="hint cloud-path">' + PR.esc(PR.t("原文献库保留在：{path}", { path: r.old_path })) + "</p>" : "") +
      (window.easyreadDesktop && window.easyreadDesktop.relaunch ? button("restart", PR.t("现在重启"), "", busy)
        : '<p class="hint">' + PR.t("请关掉 EasyRead 再重新打开") + "</p>") + "</div>";
  }

  PR.settingsTabs.cloud = {
    render(s) {
      if (!s.cloud && !s.cloudLoading && !s.cloudError) load(s);
      const d = s.cloud;
      if (!d) return '<div class="cloud-settings">' + (s.cloudError ? '<p class="bad">' + PR.esc(s.cloudError) + "</p>" : "") +
        '<p class="hint">' + (s.cloudLoading ? PR.t("正在检查文献库位置…") : "") + "</p>" + button("refresh", PR.t("重试"), "", s.cloudLoading) + "</div>";
      return '<div class="cloud-settings">' +
        '<p class="set-lead">' + PR.t("把文献库放进网盘的同步文件夹，换台电脑，论文、译文、笔记都还在。") + "</p>" +
        (s.cloudError ? '<p class="bad">' + PR.esc(s.cloudError) + "</p>" : "") +
        '<div class="cloud-now"><div class="cloud-card-icon">' + PR.icon("folder") + '</div><div class="cloud-card-body"><span class="cloud-label">' + PR.t("现在的文献库") + "</span><b>" + PR.esc(where(d)) +
        '</b><div class="cloud-path">' + PR.esc(d.path) + "</div></div>" + button("reveal", PR.t("打开文件夹"), "", busy) + "</div>" +
        (d.temp ? '<p class="hint">' + PR.t("当前是临时文献库，不能更改位置。") + "</p>" : "") + result(s) +
        '<h4 class="set-h">' + PR.t("放到网盘") + "</h4>" +
        '<div class="cloud-cards">' + (d.candidates || []).map((c) => target(s, c)).join("") + (s.cloudCustom ? target(s, s.cloudCustom) : "") + "</div>" +
        (!(d.candidates || []).length && !s.cloudCustom ? '<p class="hint">' + PR.t("这台电脑上没找到 OneDrive、Dropbox 或 iCloud。") + "</p>" : "") +
        '<div class="cloud-actions">' + button("custom", PR.t("选其他文件夹…"), "", disabled(s)) + button("refresh", PR.t("重新检测"), "", busy || d.restart_required) +
        '<span class="hint">' + PR.t("坚果云、Google Drive 选它们的同步文件夹就行") + "</span></div>" +
        (busy ? '<p class="cloud-progress" role="status"><span class="spin"></span> ' + PR.t("正在处理文献库，请不要关闭 EasyRead…") + "</p>" : "") +
        '<details class="cloud-notes"><summary>' + PR.t("用之前看一眼") + "</summary><ul><li>" +
        PR.t("不要在两台电脑上同时开着 EasyRead，否则同一篇论文的改动会互相覆盖。") + "</li><li>" +
        PR.t("iCloud 和 Google Drive 的省空间模式可能让文件只留在云端。请把 EasyRead 文件夹设为始终保留在此设备上。") + "</li><li>" +
        PR.t("百度网盘、迅雷没有实时同步文件夹，不适合放文献库。") + "</li><li>" +
        PR.t("搬的时候是复制，原来的文件夹保留不删。") + "</li></ul></details></div>";
    },
    async click(e, s) {
      const b = e.target.closest("[data-cloud]");
      if (!b) return false;
      const action = b.dataset.cloud;
      if (busy || b.disabled) return true;
      try {
        if (action === "refresh") { await load(s); return true; }
        if (action === "reveal") { await PR.api("/api/library/reveal", { method: "POST", body: {} }); return true; }
        if (action === "restart") {
          if (window.easyreadDesktop && window.easyreadDesktop.relaunch) await window.easyreadDesktop.relaunch();
          else PR.toast(PR.t("请关掉 EasyRead 再重新打开"));
          return true;
        }
        if (action === "cleanup") {
          if (!(await PR.confirm({ title: PR.t("清理没搬完的内容？"), body: PR.t("只删除上次迁移复制到 {path} 的内容，那里原有的论文和你现在用的文献库都不动。", { path: b.dataset.path }), ok: PR.t("清理") }))) return true;
          busy = true; redraw();
          await PR.api("/api/library/cleanup", { method: "POST", body: { path: b.dataset.path } });
          if (s.cloudCustom && s.cloudCustom.path === b.dataset.path) s.cloudCustom = await PR.api("/api/library/inspect", { method: "POST", body: { path: b.dataset.path } });
          busy = false; await load(s);
          PR.toast(PR.t("已清理"));
          return true;
        }
        if (disabled(s)) return true;
        if (action === "custom") {
          const desktop = window.easyreadDesktop;
          const path = desktop && desktop.pickFolder ? await desktop.pickFolder() : await PR.promptText({
            title: PR.t("文献库文件夹"), body: PR.t("填写网盘同步文件夹或已有 EasyRead 文献库的完整路径。") + "\n" +
              PR.t("普通目录会使用其下的 EasyRead 子文件夹；已有文献库直接使用。"), max: 4096,
          });
          if (path) {
            busy = true; redraw();
            s.cloudCustom = await PR.api("/api/library/inspect", { method: "POST", body: { path } });
          }
          return true;
        }
        if (!["copy", "use", "merge"].includes(action)) return false;
        busy = true; redraw();
        const d = await PR.api("/api/library/location");
        s.cloud = d;
        const dest = await PR.api("/api/library/inspect", { method: "POST", body: { path: b.dataset.path } });
        const path = dest.path || b.dataset.path;
        const text = action === "use" ? PR.t("将使用 {path} 中的 {n} 篇论文，本机原来的文献库保留不动。", { path, n: dest.papers })
          : action === "merge" ? PR.t("会把本机 {n} 篇论文（{size}）合并到 {path}；重复论文和同名目录会跳过，原文献库保留不删。", { n: d.papers, size: size(d.bytes || 0), path })
          : PR.t("会把 {n} 篇论文（{size}）复制到 {path}，原来的文件夹保留不删。", { n: d.papers, size: size(d.bytes || 0), path });
        const yes = await PR.confirm({ title: PR.t("更改文献库位置"), body: text + "\n\n" +
          PR.t("请确认其他阅读窗口的笔记已保存并关闭。完成后需要重启 EasyRead。"), ok: PR.t("继续") });
        if (!yes) return true;
        s.cloudResult = await PR.api("/api/library/move", { method: "POST", body: { path, mode: action } });
        if (s.cloudResult.ok === false) throw new Error(s.cloudResult.message);
        s.cloud.restart_required = true;
        PR.libraryLocationNotice({ library_status: "restart_required" });
      } catch (err) {
        s.cloudError = err.message;
        PR.toast(err.message);
      } finally { busy = false; redraw(); }
      return true;
    },
  };

  PR.libraryLocationNotice = function (data) {
    let node = PR.$("#cloudNotice");
    const restart = data.library_status === "restart_required";
    const host = data.other_device;
    if (!restart && (!host || host === dismissedHost)) { if (node) node.remove(); return; }
    if (!node) {
      node = PR.el("div", { id: "cloudNotice", class: "cloud-notice", role: "status" });
      PR.$(".main").insertBefore(node, PR.$(".list-head"));
    }
    node.innerHTML = '<span>' + PR.esc(restart ? PR.t("文献库位置已更改，请先重启再继续阅读。") :
      PR.t("文献库可能正在另一台电脑（{host}）上打开。同时修改同一篇论文，改动会互相覆盖。", { host })) + "</span>" +
      (!restart ? '<button class="btn sm" data-cloud-dismiss>' + PR.t("关闭") + "</button>" : "");
    node.onclick = (e) => { if (!restart && e.target.closest("[data-cloud-dismiss]")) { dismissedHost = host; node.remove(); } };
  };
})(window.PR);
