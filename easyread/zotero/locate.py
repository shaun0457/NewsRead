"""找 Zotero 的数据目录（放 zotero.sqlite 和 storage/ 的地方）。

默认在 ~/Zotero；用户在 Zotero 设置里改过的话，写在 Zotero 配置目录的 prefs.js 里（extensions.zotero.dataDir）。
“链接到文件”的附件可能存成相对路径 attachments:xxx，相对的是 prefs.js 里的 extensions.zotero.baseAttachmentPath。"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ..i18n import tr

DB = "zotero.sqlite"


def _profile_roots() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / "Zotero" / "Zotero" / "Profiles"] if appdata else []
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "Zotero" / "Profiles"]
    return [home / ".zotero" / "zotero"]


def _pref(text: str, name: str) -> str:
    m = re.search(r'user_pref\("' + re.escape(name) + r'",\s*"((?:[^"\\]|\\.)*)"\);', text)
    return re.sub(r"\\(.)", lambda e: e.group(1), m.group(1)) if m else ""  # prefs.js 只转义反斜杠和引号


def _prefs() -> list[dict]:
    """每个 Zotero 配置里写的 dataDir 和 baseAttachmentPath。"""
    out = []
    for root in _profile_roots():
        for prefs in root.glob("*/prefs.js") if root.is_dir() else []:
            try:
                text = prefs.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out.append({"data_dir": _pref(text, "extensions.zotero.dataDir"),
                        "base": _pref(text, "extensions.zotero.baseAttachmentPath")})
    return out


def candidates() -> list[dict]:
    """可能的数据目录：[{path, base}]，有 zotero.sqlite 的才算；base 是相对附件的根目录（不知道就空）。"""
    found: dict[str, dict] = {}
    prefs = _prefs()
    base = next((p["base"] for p in prefs if p["base"]), "")
    for d in [p["data_dir"] for p in prefs if p["data_dir"]] + [str(Path.home() / "Zotero")]:
        path = Path(d)
        if (path / DB).is_file() and str(path) not in found:
            found[str(path)] = {"path": str(path), "base": base}
    return list(found.values())


def resolve(path: str) -> Path:
    """用户给的路径：可以是数据目录，也可以直接是 zotero.sqlite 文件。"""
    p = Path(path).expanduser()
    if p.is_file() and p.name.endswith(".sqlite"):
        p = p.parent
    if not (p / DB).is_file():
        raise ValueError(tr("这个文件夹里没有 Zotero 的数据库（{db}）：{path}", db=DB, path=str(p)))
    return p
