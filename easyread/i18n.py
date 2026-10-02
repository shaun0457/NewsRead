"""界面语言：中文系统显示中文，其余显示英文；设置里可以手动指定。

代码里只写中文：前端 `PR.t("中文 {n}", {n})`，后端 `tr("中文 {n}", n=…)`。
中文原文就是词条的键，英文在 web/i18n/en.json；缺了哪条英文，tests/test_i18n.py 会报出来。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import lru_cache

from .config import WEB

EN_PATH = WEB / "i18n" / "en.json"
CHOICES = ("auto", "zh", "en")


@lru_cache(maxsize=1)
def _dict_cached(mtime: float) -> dict:
    return json.loads(EN_PATH.read_text(encoding="utf-8"))


def en_dict() -> dict:
    try:
        return _dict_cached(EN_PATH.stat().st_mtime)
    except (OSError, ValueError):
        return {}


def _is_zh(tag: str | None) -> bool:
    tag = (tag or "").strip().lower().replace("_", "-")
    return tag.startswith("zh") or tag.startswith("chinese")


@lru_cache(maxsize=1)
def system_lang() -> str:
    # 桌面版由 Electron 传进来（macOS 从启动台打开时拿不到 LANG）
    tag = os.environ.get("EASYREAD_SYSTEM_LANG")
    if tag:
        return "zh" if _is_zh(tag) else "en"
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var)
        if value and value not in ("C", "POSIX", "C.UTF-8"):
            return "zh" if _is_zh(value) else "en"
    if sys.platform == "win32":
        try:
            import ctypes
            return "zh" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x04 else "en"
        except (AttributeError, OSError):
            pass
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=3).stdout
            first = next((line.strip(' ",()') for line in out.splitlines() if line.strip(' ",()')), "")
            return "zh" if _is_zh(first) else "en"
        except (OSError, subprocess.SubprocessError):
            pass
    return "zh"  # 判断不出来时保持原来的中文


def choice() -> str:
    from . import prefs
    value = (prefs.load().get("ui") or {}).get("lang")
    return value if value in CHOICES else "auto"


def lang() -> str:
    value = choice()
    return value if value in ("zh", "en") else system_lang()


def tr(text: str, **kw) -> str:
    """中文原文 → 当前语言；{name} 占位符用 kw 填。"""
    if lang() == "en":
        text = en_dict().get(text) or text
    return text.format(**kw) if kw else text


def inject(page: str, language: str | None = None) -> str:
    """返回页面时写上语言，英文时把词典也塞进去，前端同步就能用。"""
    picked = choice() if language is None else language  # 设置里的“界面语言”要显示当前选的是哪项
    language = language or lang()
    page = page.replace('<html lang="zh-CN">', f'<html lang="{"zh-CN" if language == "zh" else "en"}" data-lang-choice="{picked}">', 1)
    if language == "en":
        payload = json.dumps(en_dict(), ensure_ascii=False).replace("<", "\\u003c")
        page = page.replace("</title>", f'</title>\n<script id="pr-i18n" type="application/json">{payload}</script>', 1)
    return page
