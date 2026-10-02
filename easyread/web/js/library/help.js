/* 帮助：快捷键、怎么用、关于。按 ? 或点顶栏问号打开。 */
(function (PR) {
  "use strict";
  const dlg = PR.$("#textDlg");
  const K = (keys, what) => "<tr><td>" + keys.split(" ").map((k) => "<kbd>" + k + "</kbd>").join(" ") + "</td><td>" + what + "</td></tr>";

  PR.openHelp = function () {
    dlg.querySelector(".dialog").innerHTML =
      '<div class="help-head">' + PR.logo("hero sm") + "<div><h2>EasyRead</h2><div class=\"hint\">" + PR.t("版本 {v} · 本地运行，论文和笔记只存在你的电脑上", { v: PR.esc(PR.lib.version || "") }) + "</div></div></div>" +
      '<div class="help-update"><button class="btn sm line" data-help="check">' + PR.t("检查更新") + '</button><span class="hint" id="helpUpdateMsg">' + updateLine() + "</span>" +
      '<label class="check"><input type="checkbox" data-help="auto"' + (!PR.update || PR.update.enabled !== false ? " checked" : "") + ">" + PR.t("自动检查新版本（一天一次，只问 GitHub）") + "</label></div>" +
      '<div class="help-cols"><div><h4>' + PR.t("文献库") + '</h4><table class="keys">' +
      K("/", PR.t("搜索")) + K("J K", PR.t("上下移动")) + K("Enter", PR.t("打开阅读")) + K("S", PR.t("星标")) + K("Ctrl+V", PR.t("粘贴链接直接导入")) + K("?", PR.t("这个帮助")) +
      "</table><h4>" + PR.t("导入") + "</h4><p class=\"hint\">" + PR.t("拖 PDF 进窗口；或填 arXiv 编号、DOI、论文标题、论文网页（arXiv、OpenReview、ACL、NeurIPS、bioRxiv、PMC、期刊页面）或 PDF 直链。找不到公开 PDF 的，下载后拖进来。长论文可以只译正文。") + "</p>" +
      "<h4>" + PR.t("翻译引擎") + "</h4><p class=\"hint\">" + PR.t("本机装了 Claude Code 或 Codex 就能直接用，不用 Key；也可以用 DeepSeek、智谱、通义、Gemini 等 API，或本机 Ollama。在设置里换。") + "</p></div>" +
      '<div><h4>' + PR.t("阅读页") + '</h4><table class="keys">' +
      K("J K", PR.t("下一段 / 上一段")) + K("N Q", PR.t("给当前段写笔记 / 提问")) + K("A", PR.t("问 AI（带当前段）")) + K("E", PR.t("改译文")) + K("R", PR.t("让模型重译这段")) +
      K("B", PR.t("译文 / 对照原文")) + K("O", PR.t("原文页面板")) + K("M", PR.t("笔记面板")) + K("T", PR.t("目录")) + K("= - 0", PR.t("字号大 / 小 / 默认")) + K("1 2 3 4", PR.t("选中文字后四色划线")) +
      "</table></div></div>" +
      '<div class="actions"><button class="btn" data-close>' + PR.t("关闭") + "</button></div>";
    dlg.classList.add("open");
  };
  function updateLine() {
    const u = PR.update;
    if (!u) return "";
    if (u.newer) return PR.t("有新版本 {v}", { v: '<a href="#" data-help="open">' + PR.esc(u.latest) + "</a>" });
    return u.latest ? PR.t("已经是最新版") : "";
  }
  dlg.addEventListener("click", async (e) => {
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
  dlg.addEventListener("change", (e) => {
    if (e.target.dataset.help === "auto") PR.setAutoUpdate(e.target.checked).catch((err) => PR.toast(PR.t("保存失败：") + PR.esc(err.message)));
  });
  PR.$("#helpBtn").onclick = PR.openHelp;
  document.addEventListener("keydown", (e) => {
    if (e.key !== "?" || e.target.closest("input, textarea, select, [contenteditable]") || PR.$(".dialog-backdrop.open")) return;
    e.preventDefault();
    PR.openHelp();
  });
})(window.PR);
