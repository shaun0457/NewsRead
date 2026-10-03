const fs = require("fs");
const path = require("path");
const { performance } = require("perf_hooks");
const { execFile } = require("child_process");
const started = performance.now();

function mark(app, stage) {
  const line = `${new Date().toISOString()} startup ${stage} +${Math.round(performance.now() - started)}ms\n`;
  // Diagnostic logging must never prevent the window from opening.
  fs.appendFile(path.join(app.getPath("userData"), "startup.log"), line, () => {});
}

function loginShellPath(platform = process.platform, shell = process.env.SHELL || "/bin/zsh", run = execFile) {
  if (platform === "win32") return Promise.resolve("");
  return new Promise(resolve => {
    run(shell, ["-ilc", 'printf "__PATH__%s__PATH__" "$PATH"'],
      { encoding: "utf8", timeout: 5000, maxBuffer: 65536, windowsHide: true }, (error, out) => {
        const match = !error && String(out).match(/__PATH__(.*)__PATH__/);
        resolve(match ? match[1] : "");
      });
  });
}

function loadingUrl(zh) {
  const title = zh ? "正在打开 EasyRead" : "Opening EasyRead";
  const hint = zh ? "正在准备文献库，请稍候…" : "Preparing your library. Please wait…";
  const html = `<!doctype html><html lang="${zh ? "zh-CN" : "en"}"><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>EasyRead</title><style>
:root{color-scheme:light dark}body{margin:0;height:100vh;display:grid;place-content:center;text-align:center;background:#f5f3ed;color:#273e3e;font:16px system-ui,sans-serif}
h1{font-size:24px;font-weight:600}p{color:#657373}.loader{width:30px;height:30px;border:3px solid #b8cccb;border-top-color:#326b71;border-radius:50%;margin:0 auto;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}@media(prefers-color-scheme:dark){body{background:#1e2527;color:#e0e6e3}p{color:#adbab9}}@media(prefers-reduced-motion:reduce){.loader{animation:none}}
</style><main role="status" aria-live="polite"><div class="loader" aria-hidden="true"></div><h1>${title}</h1><p>${hint}</p></main></html>`;
  return "data:text/html;charset=utf-8," + encodeURIComponent(html);
}

module.exports = { mark, loginShellPath, loadingUrl };
