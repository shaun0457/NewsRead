"""术语统一：一批译完并进 paper.json 前，它新报的术语如果和术语表里已有的译法不同，就把这批译文里的说法换成已有的。

分段并行时几段同时开译，各段第一批看不到别段的术语表，同一个词可能各译各的；
术语表按“先并进去的为准”，后并进来的那批在这里改成同一个说法，读起来全文一致。
只换这批自己报出来的冲突术语，只在这批的译文字段里换，不动原文。
"""
from __future__ import annotations


def _key(en) -> str:
    return " ".join(str(en or "").lower().split())


def conflicts(glossary: list[dict], new: list[dict]) -> list[tuple[str, str, str]]:
    """[(英文, 这批的译法, 已有译法)]。太短的译法不换，免得误伤别的词：一个字的不换；
    是已有译法一部分的（“标准误”和“标准误差”），三个字以上才换。"""
    have = {_key(g.get("en")): str(g.get("zh") or "").strip() for g in glossary or [] if isinstance(g, dict)}
    out = []
    for g in new or []:
        if not isinstance(g, dict):
            continue
        old, mine = have.get(_key(g.get("en"))), str(g.get("zh") or "").strip()
        if old and mine and old != mine and len(mine) >= (3 if mine in old else 2):
            out.append((str(g.get("en")), mine, old))
    return out


def _swap(text: str, pairs: list[tuple[str, str]]) -> str:
    mark = "\x00"
    for mine, old in pairs:
        if mine in old:  # “标准误”→“标准误差”：先把已经是“标准误差”的护住，免得换成“标准误差差”
            text = text.replace(old, mark).replace(mine, old).replace(mark, old)
        else:
            text = text.replace(mine, old)
    return text


def _apply(value, pairs):
    if isinstance(value, str):
        return _swap(value, pairs)
    if isinstance(value, list):
        return [_apply(v, pairs) for v in value]
    return value


_FIELDS = ("zh", "caption_zh", "image_zh")


def unify(glossary: list[dict], data: dict) -> list[tuple[str, str, str]]:
    """就地改 data（模型的一批输出：blocks 或 fill 的 zh 字典），返回换了哪些。"""
    found = conflicts(glossary, data.get("glossary") or [])
    if not found:
        return []
    pairs = [(mine, old) for _, mine, old in found]
    for b in data.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        for f in _FIELDS:
            if isinstance(b.get(f), str):
                b[f] = _swap(b[f], pairs)
        for it in b.get("items") or []:
            if isinstance(it, dict) and isinstance(it.get("zh"), str):
                it["zh"] = _swap(it["zh"], pairs)
        if b.get("type") == "table" and isinstance(b.get("head"), list):
            b["head"] = _apply(b["head"], pairs)
    if isinstance(data.get("zh"), dict):  # 只读原文后补译文：{键: 译文}，表头是二维数组
        data["zh"] = {k: _apply(v, pairs) for k, v in data["zh"].items()}
    # 术语表里只留已有的那条，这批的冲突条目丢掉（merge 本来也会丢，这里显式一点）
    bad = {_key(en) for en, _, _ in found}
    data["glossary"] = [g for g in data.get("glossary") or [] if not (isinstance(g, dict) and _key(g.get("en")) in bad)]
    return found
