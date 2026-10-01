"""启动本地服务：只监听 127.0.0.1，记下地址给命令行复用；start.cmd / start.sh 启动时页面都关了就退出。"""
from __future__ import annotations

import os
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from . import __version__, config, detect
from .log import log, setup as setup_log
from .presence import Presence
from .server import App, Handler
from .store import now_iso, read_json, write_json_atomic


class _Server(ThreadingHTTPServer):
    # Windows 上 SO_REUSEADDR 会让两个进程同时占住 8765，浏览器随机连到其中一个（比如旧版本）
    allow_reuse_address = os.name != "nt"


def serve(port: int | None = None, open_browser: bool = False, path: str = "/", exit_on_close: bool = False):
    """exit_on_close：start.cmd / start.sh 启动时为真，页面都关了、后台任务也做完了就退出。"""
    setup_log(config.LOG_PATH)
    cfg = config.load()
    app = App(cfg)
    Handler.app = app
    detect.warm(cfg)
    port = cfg["port"] if port is None else port
    try:
        httpd = _Server(("127.0.0.1", port), Handler)
    except OSError:
        httpd = _Server(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    app.presence = Presence(app.jobs.busy, httpd.shutdown, exit_on_close)
    if not config.temp_library():
        write_json_atomic(config.SERVER_INFO, {"url": url, "pid": os.getpid(), "started": now_iso()})
    log.info("EasyRead %s 已启动：%s  文献库：%s", __version__, url, app.lib.root)
    print(f"EasyRead 已启动：{url}  文献库：{app.lib.root}", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url + path)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if not config.temp_library() and (read_json(config.SERVER_INFO, {}) or {}).get("pid") == os.getpid():
            config.SERVER_INFO.unlink(missing_ok=True)  # 下次 easyread 命令不会去连一个已经关掉的服务
