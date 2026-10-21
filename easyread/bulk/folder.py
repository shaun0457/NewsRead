"""导入整个文件夹：递归找出里面的 PDF，文件夹层级就是分类层级。

选的是 D:/论文，里面有 CV/YOLO/a.pdf，这篇就放进“论文/CV/YOLO”；直接放在 D:/论文 下的放进“论文”。
隐藏文件夹（. 开头）和快捷方式指向的文件夹不进去。"""
from __future__ import annotations

import os
from pathlib import Path

from ..i18n import tr
from ..zotero.reader import Entry, Snapshot

MAX_FILES = 5000


def read(path: str) -> Snapshot:
    root = Path(path).expanduser()
    if not root.is_dir():
        raise ValueError(tr("找不到这个文件夹：{path}", path=str(root)))
    root = root.resolve()
    top = root.name or str(root).rstrip("\\/:")  # 选的是盘符根目录时没有名字
    entries: list[Entry] = []
    cats: list[str] = []
    for d, dirs, files in os.walk(root):  # 默认不跟进快捷方式 / 软链接指向的文件夹
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        rel = Path(d).relative_to(root).parts
        cat = "/".join(p.replace("/", "／") for p in (top, *rel))
        pdfs = sorted(f for f in files if f.lower().endswith(".pdf") and not f.startswith("."))
        if pdfs and cat not in cats:
            # 祖先也记下，空着的中间层也按文件夹顺序出现
            for k in range(1, len(rel) + 2):
                anc = "/".join(cat.split("/")[:k])
                if anc not in cats:
                    cats.append(anc)
        for f in pdfs:
            if len(entries) >= MAX_FILES:
                raise ValueError(tr("这个文件夹里的 PDF 超过 {n} 个，请分几次导入，每次选一个子文件夹", n=MAX_FILES))
            entries.append(Entry(key=str(Path(d, f).relative_to(root)), meta={}, cats=[cat], pdf=Path(d) / f))
    return Snapshot(entries=entries, collections=cats)
