"""分段并行：把要译的页切成几段连续的页，各段同时开译，段内一批接一批按顺序译。

段内和逐批串行一样：后一批能看到前一批并进去的术语表、章节和上一段结尾。
段与段的交界只有 段数-1 处，切口尽量挑在“上一页句子写完了、下一页从新段落或标题开始”的地方；
交界处跨页的那一段由前一段的最后一批补完整（它本来就看下一页开头），后一段第一批跳过页首那半段。
"""
from __future__ import annotations

import math
import re
from pathlib import Path

AUTO_MAX = 8      # “自动”最多同时几段
LANE_BATCHES = 2  # “自动”时每段大约几批：段数 = 总批数 / 2 向上取整（每批 2 页时每段 4 页，30 页 → 8 段）

_NOISE = re.compile(r"^\s*(\d{1,4}|[ivxl]{1,5}|(?i:page \d+.*|arxiv:.*))\s*$")  # i18n-ok 页码、arXiv 水印这类
_HEADING = re.compile(r"^\s*((\d+(\.\d+)*\.?|[A-Z]\.?)\s+[A-Z][a-z]|\[\d+\]\s|(?i:appendix|references|abstract|acknowledg)\b)")  # i18n-ok 章节标题、新的参考文献条目


def workers(setting, n_batches: int) -> int:
    """最多同时几段。setting 是设置里的“同时几段”：0 或空是自动，按篇幅每段大约 2 批，最多 8 段。"""
    try:
        cap = int(setting or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap > 0:
        return min(8, cap)
    return max(1, min(AUTO_MAX, math.ceil(n_batches / LANE_BATCHES)))


_WORD = re.compile(r"[A-Za-z]{2,}")
_CAPTION = re.compile(r"^\s*(Table|Figure|Fig\.|Algorithm)\s*\d", re.I)  # i18n-ok
_FOOTNOTE = re.compile(r"^\s*([¹²³⁴⁵⁶⁷⁸⁹*†‡]|\d{1,2}\s*(https?|www\.)|\d{1,2}[A-Z][a-z])|https?://")


def _body(line: str) -> bool:
    return len(_WORD.findall(line)) >= 4 and not _FOOTNOTE.search(line)


def _lines(root: Path, n: int) -> list[str]:
    p = root / "extract" / f"page-{n:03d}.txt"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [s.strip() for s in text.splitlines() if s.strip() and not _NOISE.match(s)]


def seam_cost(root: Path, prev: int, nxt: int) -> float:
    """在 prev 页和 nxt 页之间切开的代价：0 干净（新章节开头），1 句子写完了，2 看不出来，3 明显断在句子中间。"""
    if nxt != prev + 1:
        return 0.0  # 中间隔着没要译的页，本来就接不上
    # 只看正文行：脚注、网址、表格里的数字、图表题注都不算（脚注末尾的句号骗不了人，页首先排的表格也不算开头）
    tail = [s for s in _lines(root, prev) if _body(s)]
    head = [s for s in _lines(root, nxt) if (_HEADING.match(s) and len(s) < 80) or (_body(s) and not _CAPTION.match(s))]
    if not tail or not head:
        return 2.0
    first, last = head[0], tail[-1]
    if first[:1].islower() or last.endswith(("-", ",")):
        return 3.0
    if _HEADING.match(first) and len(first) < 80:
        return 0.0
    return 1.0 if last.endswith((".", "?", "!", ":")) else 2.0


def plan(pages: list[int], size: int, k: int, root: Path) -> list[list[int]]:
    """把 pages 切成至多 k 段。先定最慢一段要译几批（总批数 / k 向上取整），每段不超过这么多批；
    在这个限制下挑交界代价最小的切法：每多一个交界加 0.5，再加交界本身的代价，再按批数加一点（奇数页的段多一次调用）。
    这样 7 批开 4 段（2,2,2,1），5 批开 3 段（2,2,1）就够，交界越少越好；有余量时切口挪到干净的地方。"""
    n = len(pages)
    if k <= 1 or n <= 1:
        return [list(pages)] if pages else []
    k = min(k, n)
    cap = math.ceil(math.ceil(n / size) / k) * size
    inf = float("inf")
    # best[j][i]：前 i 页切成 j 段的最小代价
    best = [[inf] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    seam = [0.0] + [0.5 + seam_cost(root, pages[i - 1], pages[i]) for i in range(1, n)]
    for j in range(1, k + 1):
        for i in range(1, n + 1):
            for s in range(max(0, i - cap), i):
                if best[j - 1][s] == inf:
                    continue
                c = best[j - 1][s] + seam[s] + 0.3 * math.ceil((i - s) / size)
                if c < best[j][i]:
                    best[j][i], back[j][i] = c, s
    j = min((j for j in range(1, k + 1) if best[j][n] < inf), key=lambda j: (best[j][n], j))
    out, i = [], n
    while j:
        s = back[j][i]
        out.append(pages[s:i])
        i, j = s, j - 1
    return out[::-1]
