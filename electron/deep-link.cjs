// easyread://open?sha256=…&block=… 打开指定论文和段落（给 Zotero 插件等外部工具用，约定见 docs/api.md）。
// 桌面版只做转发：交给后端的 /open，由后端按指纹找论文。
const { URL } = require("url");

const SCHEME = "easyread";

// 只放行 open 和已知参数，别的链接一律忽略，不把任意内容带进后端地址
function openPath(link) {
  let url;
  try { url = new URL(link); } catch { return null; }
  if (url.protocol !== `${SCHEME}:` || (url.hostname || url.pathname.replace(/^\/+/, "")) !== "open") return null;
  const query = new URLSearchParams();
  for (const key of ["sha256", "id", "block"]) {
    const value = url.searchParams.get(key);
    if (value && /^[A-Za-z0-9_-]{1,64}$/.test(value)) query.set(key, value);
  }
  return query.has("sha256") || query.has("id") ? `/open?${query}` : null;
}

// Windows / Linux 把链接放在命令行参数里（首次启动和 second-instance 都是）
function fromArgv(argv) {
  const link = (argv || []).find(arg => typeof arg === "string" && arg.toLowerCase().startsWith(`${SCHEME}:`));
  return link ? openPath(link) : null;
}

function register(app, proc) {
  if (!app.setAsDefaultProtocolClient) return;
  // 开发时（electron .）要把入口脚本一起登记，否则系统会启动一个空的 Electron
  if (proc.defaultApp && proc.argv && proc.argv.length >= 2) {
    app.setAsDefaultProtocolClient(SCHEME, proc.execPath, [require("path").resolve(proc.argv[1])]);
  } else {
    app.setAsDefaultProtocolClient(SCHEME);
  }
}

module.exports = { SCHEME, openPath, fromArgv, register };
