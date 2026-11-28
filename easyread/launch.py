"""启动本地服务：只监听 127.0.0.1，记下地址给命令行复用。

同一個資料目錄只跑一個服務（instance.py 的檔案鎖）；關掉頁面後照樣常駐（ticket 07），
只有明確指定 --exit-on-close 時才在頁面都關了之後退出。停止時排程和背景執行緒在 STOP_TIMEOUT 內收工。
"""
from __future__ import annotations

import os
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer

from . import __version__, ai_engines, config, detect, instance, triage
from .i18n import tr
from .log import log, setup as setup_log
from .presence import Presence
from .scheduler import Scheduler
from . import tasks as research_tasks
from .server import App, Handler, allowed_hosts, host_name
from .store import now_iso, read_json, write_json_atomic

STOP_TIMEOUT = 5.0  # 停止時最多等排程工作幾秒；卡住的工作是 daemon 執行緒，不會擋住程序結束
SCHEDULE_NAME = "schedule.json"
TRANSLATE_CATCHUP_INTERVAL = 300.0  # 〔預設〕每 5 分鐘看一次等額度的翻譯能不能補翻


class _Server(ThreadingHTTPServer):
    # Windows 上 SO_REUSEADDR 会让两个进程同时占住 8765，浏览器随机连到其中一个（比如旧版本）
    allow_reuse_address = os.name != "nt"


def _server_info() -> dict:
    try:
        info = read_json(config.SERVER_INFO, {})
    except (OSError, ValueError, RecursionError):
        return {}
    return info if isinstance(info, dict) else {}


def running_url() -> str:
    """已經在跑的服務記下的位址；讀不到或格式不對就是空字串。"""
    return instance.server_url(_server_info())


def serve(port: int | None = None, open_browser: bool = False, path: str = "/", exit_on_close: bool = False,
          host: str | None = None):
    """exit_on_close：页面都关了、后台任务也做完了就退出（預設常駐）。已經有一個在跑時丟 instance.AlreadyRunning。"""
    setup_log(config.LOG_PATH)
    started = time.monotonic()
    cfg = config.load()
    log.info("startup config-ready +%.0fms", (time.monotonic() - started) * 1000)
    lock = None
    if not config.temp_library():  # 暫用文獻庫（測試、多庫）不佔資料目錄的鎖，也不寫 .server.json
        lock = instance.InstanceLock(config.HOME / instance.LOCK_NAME)
        if not lock.acquire():
            log.info("已经有一个 NewsRead 在跑，不再启动第二个")
            raise instance.AlreadyRunning(running_url())
    try:
        _serve(cfg, started, port, open_browser, path, exit_on_close, host)
    finally:
        if lock:
            lock.release()


def _serve(cfg: dict, started: float, port, open_browser: bool, path: str, exit_on_close: bool, host):
    app = App(cfg)
    log.info("startup library-jobs-ready +%.0fms", (time.monotonic() - started) * 1000)
    Handler.app = app
    detect.warm(cfg)
    port = cfg["port"] if port is None else port
    bind_host = host or os.environ.get("PAPERREAD_HOST") or "127.0.0.1"
    try:
        httpd = _Server((bind_host, port), Handler)
    except OSError:
        httpd = _Server((bind_host, 0), Handler)
    try:
        configured_public_host = os.environ.get("PAPERREAD_PUBLIC_HOST", "").strip()
        public_host = host_name(configured_public_host) if configured_public_host else ""
        if configured_public_host and not public_host:
            raise ValueError(tr("PAPERREAD_PUBLIC_HOST 必須包含有效的主機名稱"))
        if not public_host:
            public_host = "127.0.0.1" if bind_host in ("0.0.0.0", "::") else bind_host
        url = f"http://{public_host}:{httpd.server_address[1]}"
        Handler.allowed_hosts = allowed_hosts(bind_host, public_host, os.environ.get("PAPERREAD_ALLOWED_HOSTS"))
        log.info("startup http-bound +%.0fms", (time.monotonic() - started) * 1000)
        app.shutdown = httpd.shutdown
        app.location.marker.start()
        app.presence = Presence(lambda: app.jobs.busy() or research_tasks.busy(), httpd.shutdown, exit_on_close)
        app.scheduler = Scheduler(None if config.temp_library() else config.HOME / SCHEDULE_NAME)
        app.scheduler.add("triage", triage.INTERVAL, lambda: triage.run_pending(app))  # AI 分類（ticket 14）
        app.jobs.translate_gate = lambda cfg: ai_engines.for_app(app).translation_gate(cfg)  # 匯入後自動翻譯的額度保護
        app.scheduler.add("translate_catchup", TRANSLATE_CATCHUP_INTERVAL, lambda: app.jobs.resume_waiting())  # 額度解除後補翻
        app.scheduler.start()
        if not config.temp_library():
            write_json_atomic(config.SERVER_INFO, {"url": url, "pid": os.getpid(), "started": now_iso()})
        log.info("NewsRead %s 已啟動：%s  文獻庫：%s", __version__, url, app.lib.root)
        print(f"NewsRead 已啟動：{url}  文獻庫：{app.lib.root}", flush=True)  # i18n-ok Electron and smoke_backend match this line
        if open_browser:
            threading.Timer(0.4, lambda: webbrowser.open(url + path)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    finally:
        _stop(app, httpd)


def _stop(app: App, httpd: _Server) -> None:
    """服務停下之後：排程、presence 監看、文獻庫標記的背景執行緒都在時限內結束。"""
    if app.scheduler and not app.scheduler.stop(STOP_TIMEOUT):
        log.warning("排程工作沒有在 %.1f 秒內結束，直接退出", STOP_TIMEOUT)
    if app.presence:
        app.presence.close()
    app.location.marker.close()
    httpd.server_close()
    if not config.temp_library() and _server_info().get("pid") == os.getpid():
        config.SERVER_INFO.unlink(missing_ok=True)  # 下次 easyread 命令不会去连一个已经关掉的服务
