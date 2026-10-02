"""译文语言：论文翻成哪种语言。默认中文；设置里可以改，每篇论文第一次翻译时记下当时的语言。

数据格式不变：译文仍然存在 zh / caption_zh / title_zh 这些字段里，字段名只是历史叫法。
"""
from __future__ import annotations

# 代码 → (界面上显示的名字, 提示词里怎么称呼, 英文名)
TARGETS = {
    "zh": ("中文", "中文", "Chinese"),  # i18n-ok 语言名
    "ja": ("日本語", "日语（日本語）", "Japanese"),  # i18n-ok
    "ko": ("한국어", "韩语（한국어）", "Korean"),  # i18n-ok
    "es": ("Español", "西班牙语（Español）", "Spanish"),  # i18n-ok
    "fr": ("Français", "法语（Français）", "French"),  # i18n-ok
    "de": ("Deutsch", "德语（Deutsch）", "German"),  # i18n-ok
}
DEFAULT = "zh"


def valid(code: str | None) -> str:
    return code if code in TARGETS else DEFAULT


def of_paper(meta: dict | None, cfg: dict | None = None) -> str:
    """这篇论文的译文语言：翻过的用当时记下的，没翻过的用设置里的。"""
    meta = meta or {}
    if meta.get("target") in TARGETS:
        return meta["target"]
    if meta.get("title_zh"):  # 1.3 以前译的论文没记语言，都是中文
        return DEFAULT
    if cfg is None:
        from . import config
        cfg = config.load()
    return valid(cfg.get("target"))


def prompt_name(code: str) -> str:
    return TARGETS[valid(code)][1]


def listing() -> list[dict]:
    return [{"id": k, "name": v[0]} for k, v in TARGETS.items()]


def reply_lang(meta: dict | None) -> str:
    """问 AI、整理笔记用什么语言回答：论文翻过就用译文语言，没翻过跟界面语言。提示词里的称呼。"""
    meta = meta or {}
    if meta.get("target") in TARGETS:
        return prompt_name(meta["target"])
    if meta.get("title_zh"):  # 1.3 以前译的论文没记语言，都是中文
        return "中文"  # i18n-ok 提示词
    from . import i18n
    return "中文" if i18n.lang() == "zh" else "英文（English）"  # i18n-ok 提示词
