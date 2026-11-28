"""Traditional translation normalization and reversible migration of legacy Chinese papers."""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

from .i18n import _tw_converter
from .store import dir_lock, text_hash, write_json_atomic


def convert(text):
    return _tw_converter().convert(text) if isinstance(text, str) else text


SIMPLIFIED_SAMPLE = 5000  # 〔預設〕判斷簡繁時看前幾個字


@lru_cache(maxsize=2)
def _only_chars(name: str) -> frozenset:
    """OpenCC 的單字對照表（STCharacters / TSCharacters）裡只屬於一邊的字：對照的候選字不含它自己。
    「里 → 裏 里」「后 → 後 后」這種簡繁都用的字不算。沒裝 OpenCC 或讀不到表是空的。"""
    try:
        import opencc
    except ImportError:
        return frozenset()
    path = Path(opencc.__file__).parent / "dictionary" / f"{name}.txt"
    out = set()
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                key, _, cands = line.rstrip("\n").partition("\t")
                if len(key) == 1 and cands and key not in cands.split():
                    out.add(key)
    except OSError:
        return frozenset()
    return frozenset(out)


def looks_simplified(texts: list[str]) -> bool:
    """這段中文是不是簡體：前 SIMPLIFIED_SAMPLE 個字裡，只有簡體用的字比只有繁體用的字多才算。
    簡繁都用的字（里、后、游、台…）不算。沒裝 OpenCC 回 False（不轉）。"""
    simp_only, trad_only = _only_chars("STCharacters"), _only_chars("TSCharacters")
    if not (simp_only and trad_only):
        return False
    sample = "".join(texts)[:SIMPLIFIED_SAMPLE]
    simp = sum(1 for ch in sample if ch in simp_only)
    trad = sum(1 for ch in sample if ch in trad_only)
    return simp > trad


_KEEP = "\ue000"  # 私用區的字：轉換時暫代原文本來就有的「臺」（i18n-ok）


def to_taiwan(text: str) -> str:
    """簡體轉台灣繁體（s2twp：字和用詞，例如软件 → 軟體）。OpenCC 把「台」一律轉成「臺」，
    台灣新聞和公司名稱（台積電、台北）多用「台」，所以轉回來；原文本來就寫「臺」的（國立臺灣大學）照舊。"""
    if not isinstance(text, str):
        return text
    return _tw_converter().convert(text.replace("臺", _KEEP)).replace("臺", "台").replace(_KEEP, "臺")  # i18n-ok 字，不是畫面文字


def normalize(data: dict) -> None:
    """Convert authored translation fields only; never touch English, TeX, IDs or source hashes."""
    def walk(value):
        if isinstance(value, dict):
            original = value.get("zh")
            for key, child in list(value.items()):
                if key in ("zh", "caption_zh", "title_zh", "short_zh") and isinstance(child, str):
                    value[key] = convert(child)
                elif key == "zh" and isinstance(child, dict):
                    value[key] = {k: convert(v) if isinstance(v, str) else v for k, v in child.items()}
                else:
                    walk(child)
            if isinstance(original, str) and original != value.get("zh"):
                # Phrase conversion may change UTF-16 sentence offsets. Recompute
                # each existing boundary from the original prefix.
                for pair in value.get("sents", []):
                    prefix = original.encode("utf-16-le")[:pair[1] * 2].decode("utf-16-le")
                    pair[1] = len(convert(prefix).encode("utf-16-le")) // 2
            if value.get("type") == "table":
                for field in ("head", "rows"):
                    value[field] = [[convert(cell) for cell in row] for row in value.get(field, [])]
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(data)


def _translations(paper: dict) -> dict:
    result = {}
    for block in paper.get("blocks", []):
        bid = block.get("id", "")
        result[bid] = block.get("zh") or block.get("en") or ""
        result[bid + "#caption"] = block.get("caption_zh") or block.get("caption_en") or ""
        for i, item in enumerate(block.get("items", [])):
            result[f"{bid}#{i}"] = item.get("zh") or item.get("en") or ""
    return result


def migrate(ws) -> bool:
    """Preserve both originals before converting translator text and quote anchors.

    Handwritten note bodies and user translation edits remain byte-for-byte text.
    Existing stale edit bases remain stale; current bases follow the conversion.
    """
    with dir_lock(ws.root):
        paper = ws.load("paper") or {}
        meta = paper.get("meta") or {}
        if meta.get("target") not in (None, "zh") or meta.get("paperread_traditional_v"):
            return False
        if not any(b.get("zh") or b.get("caption_zh") for b in paper.get("blocks", [])):
            return False
        reader = ws.load("reader")
        originals = _translations(paper)
        history = ws.root / "history" / "before-paperread-zh-TW"
        history.mkdir(parents=True, exist_ok=True)
        for name in ("paper", "reader"):
            source = ws.root / f"{name}.json"
            backup = history / source.name
            if source.exists() and not backup.exists():
                backup.write_bytes(source.read_bytes())
        normalize(paper)
        paper.setdefault("meta", {}).update(target="zh-TW", paperread_traditional_v=1)
        converted = _translations(paper)
        for key, edit in reader.get("edits", {}).items():
            if edit.get("base") == text_hash(originals.get(key, "")):
                edit["base"] = text_hash(converted.get(key, ""))
        for note in reader.get("notes", {}).values():
            if note.get("quote") and note.get("side") != "en" and not reader.get("edits", {}).get(note.get("key") or note.get("anchor"), {}).get("zh"):
                note["quote"] = convert(note["quote"])
        write_json_atomic(ws.paper_path, paper)
        write_json_atomic(ws.reader_path, reader)
        return True
