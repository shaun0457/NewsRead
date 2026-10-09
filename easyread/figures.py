"""圖塊處理：保留圖片在譯文中的版面佔位，讓讀者回到原 PDF 查看。

PaperRead 不偵測、翻譯或裁切圖內文字，也不把圖片截圖嵌入譯文。舊版
資料中的裁切工具仍保留供相容性使用，但新的整理流程會清除模型提供的
裁切框與圖片文字欄位。
"""
from __future__ import annotations

import hashlib
import json
import math
import threading

from . import pdfwork
from .log import log

_running: set[str] = set()


def figure_box(value) -> list[float] | None:
    """归一化 [x0, y0, x1, y1]；不是有限数、反了或太小都算无效。"""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        coords = [float(x) for x in value]
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(x) for x in coords):
        return None
    box = [round(max(0.0, min(1.0, x)), 4) for x in coords]
    if box[2] - box[0] < .02 or box[3] - box[1] < .02:
        return None
    return box


def _crop_path(root, page: int, box: list[float]) -> str:
    source = (root / "source.pdf").stat()
    identity = json.dumps([page, box, source.st_size, source.st_mtime_ns])
    name = f"crop-{page}-{hashlib.sha256(identity.encode()).hexdigest()[:20]}"
    return f"figures/{name}.webp"


def crop(root, page: int, box: list[float]) -> str:
    """按页码、框和 PDF 身份命名截图，已有同名文件就直接用。返回相对路径。"""
    rel = _crop_path(root, page, box)
    if not (root / rel).is_file():
        pdfwork.crop(root, page, box, rel.rsplit("/", 1)[1][:-5])
    return rel


def normalize_figure(block: dict) -> None:
    """只保留圖注與版面佔位，不保存圖內文字或裁切框。"""
    block.pop("box", None)
    block["src"] = ""
    for key in ("image_en", "image_zh", "image_text_en", "image_text_zh"):
        block.pop(key, None)


def prepare_figures(root, blocks: list[dict], total_pages: int) -> None:
    """清理模型產生的圖片裁切資訊，保留原文圖片的版面佔位。"""
    for block in blocks:
        if block.get("type") != "figure":
            continue
        block["src"] = ""
        block.pop("box", None)
        for key in ("image_en", "image_zh", "image_text_en", "image_text_zh"):
            block.pop(key, None)


def _pending(ws):
    """圖片只保留原文版面佔位，不建立背景截圖工作。"""
    return []


def missing(ws) -> list[tuple[str, int, list[float]]]:
    """需要补截或更新自动截图的图块：[(块 id, 页码, 框)]。"""
    return [(b["id"], page, box) for b, page, box in _pending(ws)]


def fill(ws) -> int:
    """补截或更新自动截图；写回时保留截图期间发生的编辑和重译。"""
    done = {}
    for block, page, box in _pending(ws):
        try:
            done[block["id"]] = (block, crop(ws.root, page, box))
        except Exception:  # noqa: BLE001
            log.exception("截图失败 %s %s", ws.root, block["id"])
    if done:
        def apply(paper):
            count = 0
            for b in paper.get("blocks", []):
                previous, src = done.get(b.get("id"), (None, None))
                if b == previous:
                    b["src"] = src
                    count += 1
            return count
        return ws.update("paper", apply)
    return 0


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
