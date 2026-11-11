/* 設定頁的「背景執行」區（ticket 66）：版本，和 Windows 安裝版的開機自動啟動。
   開關走桌面版的 IPC（Electron 的登入項目，開機時帶 --hidden、直接縮在系統匣）。
   瀏覽器開的原始碼版沒有這個開關，改說明 `easyread autostart on`（easyread/autostart.py）。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  const T = () => ({
    autostart: PR.t("開機自動啟動"),
    trayHint: PR.t("開機後縮在系統匣，繼續抓資料、跑排程；從系統匣點 NewsRead 打開。"),
    desktopHint: PR.t("這個版本不能在這裡設定開機啟動；Windows 安裝版才有這個開關。"),
    sourceHint: PR.t("原始碼版請在 NewsRead 資料夾執行 easyread autostart on。"),
    installer: PR.t("Windows 安裝版"), desktop: PR.t("桌面版"), browser: PR.t("原始碼版"),
    failed: PR.t("沒有改成功，請再試一次。"),
  });
  const esc = (s) => PR.esc(s);

  /* 純函式（測試直接呼叫）。info = { version, kind: installer | desktop | browser, login: {supported, enabled} | null } */
  function html(info, busy, tx) {
    tx = tx || T();
    const kind = { installer: tx.installer, desktop: tx.desktop }[info.kind] || tx.browser;
    const auto = info.login && info.login.supported
      ? `<label class="switch-row"><input type="checkbox" class="switch" role="switch" id="f-autostart"` +
        `${info.login.enabled ? " checked" : ""}${busy ? " disabled" : ""}>` +
        `<span><b>${esc(tx.autostart)}</b><small>${esc(tx.trayHint)}</small></span></label>`
      : `<p class="hint">${esc(info.kind === "desktop" ? tx.desktopHint : tx.sourceHint)}</p>`;
    const name = info.version ? `NewsRead ${info.version} · ${kind}` : kind;
    return auto + `<div class="row"><span data-no-i18n>${esc(name)}</span></div>`;
  }

  /* 讀版本和開關狀態。拿不到就照沒有處理：版本空白、開關不顯示 */
  async function read(api, bridge) {
    let version = "";
    try {
      const v = await api("/api/version");
      if (v && typeof v.version === "string") version = v.version;
    } catch (_) { /* 版本讀不到不擋畫面 */ }
    if (!bridge || typeof bridge.loginItem !== "function") return { version, kind: "browser", login: null };
    let login = null;
    try { login = await bridge.loginItem(); } catch (_) { /* 主程序沒回應：當作不能設 */ }
    const ok = login && typeof login.supported === "boolean" && typeof login.enabled === "boolean";
    return { version, kind: ok && login.supported ? "installer" : "desktop", login: ok ? login : null };
  }

  /* 改開關：成功回主程序確認過的新狀態；失敗回 null，畫面維持原本的狀態 */
  async function toggle(bridge, on) {
    try {
      const login = await bridge.setLoginItem(Boolean(on));
      return login && typeof login.enabled === "boolean" ? login : null;
    } catch (_) {
      return null;
    }
  }

  PR.settingsRun = { html, read, toggle };

  let state = null, busy = false;

  function render(focus) {
    const view = PR.$("#run-view");
    if (!view || !state) return;
    view.innerHTML = html(state, busy);
    if (focus) { const el = PR.$(focus, view); if (el) el.focus(); }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const view = PR.$("#run-view");
    if (!view) return;
    view.addEventListener("change", async (ev) => {
      if (ev.target.id !== "f-autostart" || busy || !state) return;
      const before = state.login, on = ev.target.checked;
      busy = true;
      state.login = Object.assign({}, before, { enabled: on });  // 等回應時先照使用者點的畫，不閃回去
      render();
      const login = await toggle(window.easyreadDesktop, on);
      busy = false;
      state.login = login || before;  // 失敗就回到原本的狀態
      if (!login) PR.toast(esc(T().failed));
      render("#f-autostart");
    });
    read(PR.api, window.easyreadDesktop).then((info) => { state = info; render(); });
  });
})(window.PR);
