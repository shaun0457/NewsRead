// 主窗口的大小和位置：第一次打开最大化；之后记住上次关窗时的样子（大小、位置、是否最大化），
// 存在 userData 下的 window-state.json。上次所在的显示器拔掉了，就回到当前屏幕居中。
const { app, screen } = require("electron");
const fs = require("fs");
const path = require("path");

const file = () => path.join(app.getPath("userData"), "window-state.json");

function load() {
  try {
    const s = JSON.parse(fs.readFileSync(file(), "utf8"));
    const b = s.bounds;
    if (!b || !(b.width > 0 && b.height > 0)) return { maximized: true };
    // 窗口至少有一部分落在某块屏幕上才用记下的位置
    const area = screen.getDisplayMatching(b).workArea;
    const visible = b.x < area.x + area.width && b.x + b.width > area.x && b.y < area.y + area.height && b.y + b.height > area.y;
    return { bounds: visible ? b : { width: b.width, height: b.height }, maximized: !!s.maximized };
  } catch (_) {
    return { maximized: true };  // 第一次打开
  }
}

// 返回给 BrowserWindow 的尺寸选项；窗口建好后调用 track(win)
function options() {
  const s = load();
  const area = screen.getPrimaryDisplay().workAreaSize;
  return {
    opts: s.bounds ? s.bounds : { width: Math.min(1440, area.width), height: Math.min(960, area.height) },
    maximized: s.maximized,
  };
}

function track(win) {
  const save = () => {
    if (win.isDestroyed() || win.isMinimized() || win.isFullScreen()) return;
    try {
      // 最大化时记最大化之前的大小，取消最大化后能回到原来那样
      fs.writeFileSync(file(), JSON.stringify({ bounds: win.getNormalBounds(), maximized: win.isMaximized() }));
    } catch (_) {
      // 写不进去就算了，下次按默认打开
    }
  };
  win.on("close", save);
}

module.exports = { options, track };
