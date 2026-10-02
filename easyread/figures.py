"""图块补截图：模型没给裁剪框（或是旧论文）时，按原页定位里算好的图区域从 PDF 截图。

定位（layout.json）里图块的框是题注往上 / 往下撑到相邻正文为止的区域，包含图和题注本身，
和右侧原页面板里框出来的黄框是同一块。截出来的图放 figures/<块 id>.webp，写回 paper.json 的 src。
"""
from __future__ import annotations

import threading

from . import pdfwork
from .log import log

_running: set[str] = set()


def missing(ws) -> list[tuple[str, int, list[float]]]:
    """还没有截图、但定位里有框的图块：[(块 id, 页码, 框)]。"""
    layout = ws.load("layout") or {}
    out = []
    for b in (ws.load("paper") or {}).get("blocks", []):
        if b.get("type") != "figure" or b.get("src"):
            continue
        loc = layout.get(b.get("id")) or {}
        box = loc.get("box")
        if not (isinstance(box, list) and len(box) == 4 and loc.get("page")):
            continue
        x0, y0, x1, y1 = box
        if x1 - x0 < 0.05 or y1 - y0 < 0.03:  # 只匹配到一行题注、没撑开的框截出来没用
            continue
        out.append((b["id"], int(loc["page"]), [float(v) for v in box]))
    return out


def fill(ws) -> int:
    """截好所有缺的图，返回补了几张。单张失败只记日志。"""
    done = {}
    for bid, page, box in missing(ws):
        try:
            done[bid] = pdfwork.crop(ws.root, page, box, bid)
        except Exception:  # noqa: BLE001
            log.exception("截图失败 %s %s", ws.root, bid)
    if done:
        def apply(paper):
            for b in paper.get("blocks", []):
                if b.get("id") in done and not b.get("src"):
                    b["src"] = done[b["id"]]
        ws.update("paper", apply)
    return len(done)


def fill_later(ws, gate=None) -> None:
    """打开阅读页时在后台补；补完 paper.json 变了，页面轮询到就会重画。"""
    key = str(ws.root)
    if key in _running or not missing(ws):
        return
    if gate:
        gate.begin()
    _running.add(key)

    def run():
        try:
            fill(ws)
        finally:
            _running.discard(key)
            if gate:
                gate.end()
    threading.Thread(target=run, daemon=True).start()
