"""术语统一：一批译完并进 paper.json 前，它新报的术语如果和术语表里已有的译法不同，就把这批译文里的说法换成已有的。

分段并行时几段同时开译，各段第一批看不到别段的术语表，同一个词可能各译各的；
术语表按“先并进去的为准”，后并进来的那批在这里改成同一个说法，读起来全文一致。
只换这批自己报出来的冲突术语，只在原文确实出现这个英文术语的块里换，不动原文和 $公式$。
"""
from __future__ import annotations

import re

_MATH = re.compile(r"(\$[^$]*\$)")
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _key(en) -> str:
    return " ".join(str(en or "").lower().split())


def conflicts(glossary: list[dict], new: list[dict]) -> list[tuple[str, str, str]]:
    """[(英文, 这批的译法, 已有译法)]。太短的译法不换，免得误伤别的词：一个字的不换；
    是已有译法一部分的（“标准误”和“标准误差”），三个字以上才换；带括号注释的不换。"""
    have = {_key(g.get("en")): str(g.get("zh") or "").strip() for g in glossary or [] if isinstance(g, dict)}
    out = []
    for g in new or []:
        if not isinstance(g, dict):
            continue
        old, mine = have.get(_key(g.get("en"))), str(g.get("zh") or "").strip()
        if any(c in s for s in (old or "", mine) for c in "（()）"):
            continue  # “Unlikelihood（非似然训练）”这种带注释的写法拿来替换正文会到处重复注释，不换
        if old and mine and old != mine and len(mine) >= (3 if mine in old else 2):
            out.append((str(g.get("en")), mine, old))
    return out


def _swap_plain(text: str, mine: str, old: str, keep: list[str]) -> str:
    """keep：包含 mine 的其他已知译法（“协方差”里的“方差”、“标准误差”里的“标准误”），先护住再换。"""
    marks = {}
    for i, k in enumerate(sorted(keep, key=len, reverse=True)):
        if k in text:
            m = f"\x00{i}\x01"
            marks[m] = k
            text = text.replace(k, m)
    if _CJK.search(mine):
        text = text.replace(mine, old)
    else:  # 拉丁字母的译法只换整词，不换词的一部分
        text = re.sub(r"(?<!\w)" + re.escape(mine) + r"(?!\w)", lambda _: old, text)
    for m, k in marks.items():
        text = text.replace(m, k)
    return text


def _swap(text: str, swaps) -> str:
    parts = _MATH.split(text)  # 奇数位是 $公式$，不碰
    for i in range(0, len(parts), 2):
        for mine, old, keep in swaps:
            parts[i] = _swap_plain(parts[i], mine, old, keep)
    return "".join(parts)


def _apply(value, swaps):
    if isinstance(value, str):
        return _swap(value, swaps)
    if isinstance(value, list):
        return [_apply(v, swaps) for v in value]
    return value


def _mentions(en_text: str, en: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(en) + r"(s|es)?(?!\w)", en_text or "", re.I))


def _block_en(b: dict) -> str:
    items = " ".join(str(it.get("en") or "") for it in b.get("items") or [] if isinstance(it, dict))
    return " ".join([*(str(b.get(k) or "") for k in ("en", "caption_en", "image_en")), items, str(b.get("head") or ""), str(b.get("rows") or "")])


def unify(glossary: list[dict], data: dict, en_of: dict | None = None) -> list[tuple[str, str, str]]:
    """就地改 data（模型的一批输出：blocks，或只读原文补译时的 zh 字典），返回换了哪些。
    en_of：补译时 {键: 英文}，用来判断这个键的原文里有没有这个术语。"""
    found = conflicts(glossary, data.get("glossary") or [])
    if not found:
        return []
    known = {str(g.get("zh") or "") for g in list(glossary or []) + list(data.get("glossary") or []) if isinstance(g, dict)}

    def swaps_for(en_text: str):
        # 已有译法包含 mine 时（“标准误差”含“标准误”）old 本身也要护住，免得换成“标准误差差”
        return [(mine, old, [k for k in known | {old} if mine in k and k != mine])
                for en, mine, old in found if _mentions(en_text, en)]

    for b in data.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        swaps = swaps_for(_block_en(b))
        if not swaps:
            continue
        for f in ("zh", "caption_zh", "image_zh"):
            if isinstance(b.get(f), str):
                b[f] = _swap(b[f], swaps)
        for it in b.get("items") or []:
            if isinstance(it, dict) and isinstance(it.get("zh"), str):
                it["zh"] = _swap(it["zh"], swaps)
        if b.get("type") == "table":
            for f in ("head", "rows"):
                if isinstance(b.get(f), list):
                    b[f] = _apply(b[f], swaps)
    if isinstance(data.get("zh"), dict):
        for k, v in data["zh"].items():
            swaps = swaps_for(str((en_of or {}).get(k) or ""))
            if swaps:
                data["zh"][k] = _apply(v, swaps)
    # 术语表里只留已有的那条，这批的冲突条目丢掉（merge 本来也会丢，这里显式一点）
    bad = {_key(en) for en, _, _ in found}
    data["glossary"] = [g for g in data.get("glossary") or [] if not (isinstance(g, dict) and _key(g.get("en")) in bad)]
    return found
