"""全文译完后的术语一致性检查：同一个英文术语在译文里用了不同说法时，定一个说法，把其余的统一过来。

合并时的统一（terms.unify）只管模型自己报进术语表的冲突，而且按先并进来的为准；
这里看全文实际的译文：程序先筛出“原文有这个术语、译文里却没有术语表译法”的段落（没有就不调模型），
把这些段落连同术语表译法在全文出现了几段，一起发给模型（只看文字不看图）。
模型按全文多数用法和学界通行说法定一个译法（不一定是术语表里先登记的那个），给出只换了术语的整段新译文。
定下的译法和术语表不同时，术语表改过来，原来用术语表译法的段落由程序直接替换。
新译文必须真的用上定下的译法、只在术语附近有改动、公式和引用号一个不差，否则不采用。
块 id 不变，笔记挂得住；用户改过的译文不动；每处改动记进 job.log。
"""
from __future__ import annotations

import difflib
import json
import re

from . import engines, langs
from .i18n import tr
from .paperdata import set_block_text
from .terms import _mentions, _swap

LIMIT = 40          # 一次最多检查几段
_MATH = re.compile(r"\$[^$]*\$")
_CITE = re.compile(r"\[[\d,\s–-]+\]")
_PAREN = re.compile(r"[（(].*?[）)]")


def _fields(b: dict):
    """(键, 英文, 译文)：键同页面上的写法，和 set_block_text 一致。"""
    t = b.get("type")
    if t in ("para", "heading"):
        yield b["id"], str(b.get("en") or ""), str(b.get("zh") or "")
    elif t == "list":
        for i, it in enumerate(b.get("items") or []):
            if isinstance(it, dict):
                yield f"{b['id']}#{i}", str(it.get("en") or ""), str(it.get("zh") or "")
    elif t in ("table", "figure"):
        yield f"{b['id']}#caption", str(b.get("caption_en") or ""), str(b.get("caption_zh") or "")


def _has(zh: str, want: str) -> bool:
    return want.lower() in zh.lower()


def _rules(paper: dict) -> list[tuple[str, str]]:
    out = []
    for g in paper.get("glossary") or []:
        if not isinstance(g, dict):
            continue
        en, want = str(g.get("en") or "").strip(), _PAREN.sub("", str(g.get("zh") or "")).strip()
        if len(en) >= 3 and len(want) >= 2 and want.lower() != en.lower():
            out.append((en, want))
    return out


def _skip(key: str, edited: set[str]) -> bool:
    return key in edited or key.partition("#")[0] in edited


def suspects(paper: dict, edited: set[str], pages: set[int] | None = None) -> tuple[list[dict], dict[str, int]]:
    """（可疑的地方 [{key, page, en, zh, terms: [{en, want}]}]，{术语: 用了术语表译法的段数}）。pages：只查这次译的页。"""
    rules = _rules(paper)
    out, agree = [], {}
    for b in paper.get("blocks") or []:
        if pages is not None and b.get("page") not in pages:
            continue
        for key, en, zh in _fields(b):
            if not zh or _skip(key, edited):
                continue
            miss = []
            for t, w in rules:
                if _mentions(en, t):
                    if _has(zh, w):
                        agree[t] = agree.get(t, 0) + 1
                    else:
                        miss.append({"en": t, "want": w})
            if miss:
                out.append({"key": key, "page": b.get("page"), "en": en, "zh": zh, "terms": miss})
    return out[:LIMIT], agree


def prompt(items: list[dict], agree: dict[str, int], target_name: str) -> str:
    terms = {}
    for it in items:
        for t in it["terms"]:
            terms[t["en"]] = {"术语表译法": t["want"], "用了术语表译法的段数": agree.get(t["en"], 0)}
    rows = [{"key": it["key"], "terms": [t["en"] for t in it["terms"]], "en": it["en"], "zh": it["zh"]} for it in items]
    return (f"下面是一篇学术论文{target_name}译文里术语可能不统一的地方。terms 里是这些英文术语、术语表登记的译法，"
            "以及全文有几段用了这个译法；passages 是原文出现了这个术语、译文里却没用术语表译法的段落。\n"
            "1. 先给每个术语定一个全文统一用的译法（use）：看全文多数段落怎么译、哪个说法在这个领域最通行，"
            "不一定是术语表登记的那个。缩写（如 LLM）不算另一种译法。\n"
            "2. 再看每段：如果把术语译成了别的说法，给出只把那个说法换成 use、其余一字不改的整段新译文"
            "（公式、引用号、标点、句子都不动，‖ 符号原样保留）。如果是合理的省略、代词、缩写，或者这里的英文不是那个术语的意思，不要输出这段。\n"
            '只输出一个 JSON 对象，不要任何别的文字：{"use": {"英文术语": "定下的译法"}, "fixes": [{"key": "段的 key", "zh": "改后的整段译文"}]}\n\n'
            + json.dumps({"terms": terms, "passages": rows}, ensure_ascii=False, indent=1))


def accept(old: str, new: str, uses: list[str]) -> bool:
    """新译文能不能用：确实改了、每个定下的译法都出现了、公式和引用号一个不差、改动只在术语那么大的范围里。"""
    if not isinstance(new, str) or not new.strip() or new == old or not uses:
        return False
    if any(not _has(new, u) for u in uses):
        return False
    if sorted(_MATH.findall(old)) != sorted(_MATH.findall(new)) or sorted(_CITE.findall(old)) != sorted(_CITE.findall(new)):
        return False
    if old.count("‖") != new.count("‖"):
        return False
    # 把新译文里定下的译法拿掉，剩下的应该就是旧译文删掉旧说法：旧的只少了术语那么长，新加的几乎没有
    rest = new
    for u in sorted(set(uses), key=len, reverse=True):
        rest = re.sub(re.escape(u), "", rest, flags=re.I)
    ops = difflib.SequenceMatcher(None, old, rest, autojunk=False).get_opcodes()
    removed = sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag != "equal")
    added = sum(j2 - j1 for tag, _, _, j1, j2 in ops if tag != "equal")
    return removed <= max(6, 2 * sum(len(u) for u in uses) + 4) and added <= 2


def _text_of(paper: dict, key: str) -> str | None:
    return next((zh for b in paper.get("blocks", []) for k, _, zh in _fields(b) if k == key), None)


def _retarget(ws, en: str, old: str, use: str, edited: set[str], pages: set[int], journal) -> int:
    """定下的译法和术语表的不同：术语表改过来，原来用术语表译法的段落直接替换（只换原文有这个术语的段落）。"""
    hit = []

    def apply(paper):
        # 包含旧译法的其他术语译法（“协方差”里的“方差”）先护住
        keep = [str(g.get("zh") or "") for g in paper.get("glossary") or [] if isinstance(g, dict) and old in str(g.get("zh") or "") and str(g.get("zh")) != old]
        for g in paper.get("glossary") or []:
            if isinstance(g, dict) and str(g.get("en") or "").strip().lower() == en.lower():
                g["zh"] = use
        for b in paper.get("blocks") or []:
            if b.get("page") not in pages:
                continue
            for key, en_text, zh in _fields(b):
                if zh and not _skip(key, edited) and _mentions(en_text, en) and _has(zh, old):
                    hit.append((key, _swap(zh, [(old, use, keep)])))
    ws.update("paper", apply)
    for key, zh in hit:
        set_block_text(ws, key, zh)
    if hit:
        journal(ws, tr("术语一致性：{en} 全文改用“{use}”（原来是“{old}”），{n} 段", en=en, use=use, old=old, n=len(hit)))
    return len(hit)


def check(ws, cfg: dict, pages: list[int], cancel, meter, journal, lock) -> int:
    """跑一遍检查并改好，返回改了几段。lock：翻译用的合并锁，改 paper.json 时拿着。"""
    def edited_now() -> set[str]:
        reader = ws.load("reader") or {}
        return {k for k, v in (reader.get("edits") or {}).items() if isinstance(v, dict) and v.get("zh")}

    items, agree = suspects(ws.load("paper"), edited_now(), set(pages))
    if not items:
        journal(ws, tr("术语一致性检查：没有发现不一致"))
        return 0
    paper = ws.load("paper")
    name = langs.prompt_name(langs.of_paper(paper.get("meta")))
    data = engines.parse_json(engines.run(cfg, prompt(items, agree, name), ws.root, None, cancel, meter))
    data = data if isinstance(data, dict) else {}
    asked = {t["en"]: t["want"] for it in items for t in it["terms"]}
    use = {en: str(v).strip() for en, v in (data.get("use") or {}).items() if en in asked and str(v or "").strip()}
    n = 0
    with lock:
        edited = edited_now()
        for en, u in use.items():
            if _PAREN.sub("", u).strip() == u and u != asked[en] and len(u) >= 2:
                n += _retarget(ws, en, asked[en], u, edited, set(pages), journal)
    by_key = {it["key"]: it for it in items}
    for f in data.get("fixes") or []:
        it = by_key.get(str(f.get("key"))) if isinstance(f, dict) else None
        if not it:
            continue
        uses = [use.get(t["en"], t["want"]) for t in it["terms"]]
        if not accept(it["zh"], f.get("zh"), uses):
            continue
        with lock:
            if _text_of(ws.load("paper"), it["key"]) != it["zh"] or _skip(it["key"], edited_now()):
                continue  # 检查期间这段被改过了（重译、用户改译文），不覆盖
            set_block_text(ws, it["key"], f["zh"].strip())
        n += 1
        journal(ws, tr("术语一致性：第 {page} 页 {key} 统一了 {terms}", page=it["page"], key=it["key"], terms="、".join(uses)))
    journal(ws, tr("术语一致性检查：查了 {n} 段，改了 {m} 段", n=len(items), m=n))
    return n
