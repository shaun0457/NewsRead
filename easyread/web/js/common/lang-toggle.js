/* 顶栏的中 / EN 切换按钮：中文界面显示 EN，英文界面显示“中”，点一下换成另一种并刷新。
   “跟随系统”在设置 → 阅读 → 界面语言里选。离线单文件版没有服务存设置，不显示。 */
(function (PR) {
  "use strict";
  const btn = PR.$("#langBtn");
  if (!btn) return;
  if (location.protocol === "file:") { btn.hidden = true; return; }
  btn.textContent = PR.lang === "en" ? "中" : "EN";  // i18n-ok 按钮上写的是要切换到的语言
  btn.title = PR.t("切换到英文界面");
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      await PR.api("/api/prefs", { method: "POST", body: { ui: { lang: PR.lang === "en" ? "zh" : "en" } } });
      location.reload();
    } catch (e) {
      btn.disabled = false;
      PR.toast(PR.t("保存失败：{msg}", { msg: PR.esc(e.message) }));
    }
  };
})(window.PR);
