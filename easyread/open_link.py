"""给外部工具（Zotero 插件等）的稳定入口：/api/version 和 /open。约定见 docs/api.md，改坏兼容要升 API_VERSION。"""
from __future__ import annotations

import re
from urllib.parse import quote

from . import __version__

API_VERSION = 1


def version() -> dict:
    return {"api": API_VERSION, "version": __version__}


def target(lib, query: dict[str, list[str]]) -> str:
    """/open?sha256=…&block=… 或 /open?id=…：找到论文就去阅读页（带段落锚点），找不到回文献库。"""
    first = lambda key: (query.get(key) or [""])[0].strip()  # noqa: E731
    sha, pid, block = first("sha256").lower(), first("id"), first("block")
    ws = None
    if re.fullmatch(r"[0-9a-f]{64}", sha):
        ws = lib.find_by_sha(sha)
    elif pid:
        ws = lib.ws(pid)
    if ws is None:
        return "/"
    anchor = "#" + quote(block) if re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", block) else ""
    return f"/read/{ws.root.name}{anchor}"
