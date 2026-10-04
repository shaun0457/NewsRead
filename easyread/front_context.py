"""分段并行时，每段第一批的“前文参考”：论文开头、章节目录、上一页全文。只给模型理解用，不翻译。

段内后面的批能看到前一批的译文和上一段结尾；每段第一批开译时前文还没译出来，
只能给原文：页首如果是半句话，上一页那整句是理解它的关键；前面定义过的缩写、符号也在前文里。
全部来自 PDF 抽取的文字，不多调一次模型，大约多两三千 token。
"""
from __future__ import annotations

import re
from pathlib import Path

from .segments import _HEADING, _lines

HEAD_CHARS = 1800   # 论文开头：标题、作者、摘要
PREV_CHARS = 5000   # 上一页全文太长时只留后面这些（离本批最近的部分）
OUTLINE_MAX = 60    # 章节目录最多几条
_REFS = re.compile(r"^\s*(\d+\.?\s*)?(references|bibliography)\s*$", re.I)  # i18n-ok
_ENTRY = re.compile(r"[A-Z]\.\s*(,|and\b)|\bet al\.|\(\d{4}\)|\d{4}\.")  # 参考文献条目、正文句子里像作者、年份的写法


def _page(root: Path, n: int) -> str:
    return "\n".join(_lines(root, n))


def outline(root: Path, upto: int) -> list[str]:
    """第 1 页到 upto 页里像章节标题的行，带页码。到参考文献为止（后面的编号条目不是标题）；
    太多时留离本批最近的那些。"""
    out: list[str] = []
    for n in range(1, upto + 1):
        for s in _lines(root, n):
            if len(s) < 80 and _REFS.match(s):
                return out[-OUTLINE_MAX:]
            if len(s) < 80 and _HEADING.match(s) and not s.startswith("[") and not _ENTRY.search(s):
                out.append(f"{s}（第 {n} 页）")
    return out[-OUTLINE_MAX:]


def build(root: Path, first_page: int) -> str:
    """first_page 这批之前的原文参考。first_page 是 1 时没有前文，返回空。"""
    if first_page <= 1:
        return ""
    parts = ["===== 前文参考（原文，只用来理解本批：缩写、符号、指代、页首半句话的完整意思；不要翻译、不要输出）====="]
    head = _page(root, 1)[:HEAD_CHARS]
    if head and first_page > 2:  # 上一页就是第 1 页时，下面已经整页给了
        parts.append("【论文开头】\n" + head)
    toc = outline(root, first_page - 1)
    if toc:
        parts.append("【前面的章节】\n" + "\n".join(toc))
    prev = _page(root, first_page - 1)
    if prev:
        parts.append(f"【第 {first_page - 1} 页全文】\n" + (prev if len(prev) <= PREV_CHARS else "……" + prev[-PREV_CHARS:]))
    parts.append("===== 前文参考到此 =====")
    return "\n".join(parts)
