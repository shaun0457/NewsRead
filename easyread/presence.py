"""关掉页面后自动退出（只在 start.cmd / start.sh 启动时开）。

每个文献库页、阅读页都连着一条 WebSocket（见 wsock.py）。最后一个页面关掉后，
等一会儿（刷新、在文献库和阅读页之间跳转时，新页面几秒内就会连上来）还是没有页面，
并且没有翻译、回答问题之类的后台任务在跑，就退出服务。后台任务没做完时先不退，做完再退。

命令行 `easyread serve`（agent 用的）和桌面版不开这个，服务一直跑。
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .log import log

GRACE = 15        # 最后一个页面断开后再等多久
FIRST_WAIT = 120  # 启动后一直没有页面连上来（浏览器没打开之类），等多久


class Presence:
    def __init__(self, busy: Callable[[], bool], stop: Callable[[], None], enabled: bool,
                 grace: float = GRACE, first_wait: float = FIRST_WAIT, tick: float = 1.0):
        self.busy, self.stop, self.enabled = busy, stop, enabled
        self.grace, self.first_wait, self.tick = grace, first_wait, tick
        self.pages = 0
        self.seen = False  # 有没有页面连上来过
        self.lock = threading.Lock()
        self.idle_since: float | None = time.monotonic()
        if enabled:
            threading.Thread(target=self._watch, daemon=True).start()

    def enter(self) -> None:
        with self.lock:
            self.pages += 1
            self.seen = True

    def leave(self) -> None:
        with self.lock:
            self.pages = max(0, self.pages - 1)

    def keep(self) -> None:
        """有人用 `easyread serve` 要一个常驻的服务、却复用了这个会自动退出的：从此不再自动退出。"""
        if self.enabled:
            log.info("改为常驻，不再在页面关掉后自动退出")
        self.enabled = False

    def should_stop(self, now: float) -> bool:
        with self.lock:
            idle = self.pages == 0
            wait = self.grace if self.seen else self.first_wait
        if not idle or self.busy():
            self.idle_since = None
            return False
        if self.idle_since is None:
            self.idle_since = now
        return now - self.idle_since >= wait

    def _watch(self) -> None:
        while self.enabled:
            time.sleep(self.tick)
            if self.enabled and self.should_stop(time.monotonic()):
                log.info("页面都关了，后台没有任务在跑，退出服务")
                self.stop()
                return
