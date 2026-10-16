"""Carry external PDF link annotations into inline reader text, without guessing translations."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, urlsplit

from .store import write_json_atomic

_VERSION = 1
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^\s()]*)\)")
_PROTECTED = re.compile(r"```[\s\S]*?```|`[^`]*`|\$\$[\s\S]*?\$\$|\$[^$]*\$|\[[^\]\n]*\]\([^\n]*?\)")


def safe_url(value: str) -> str:
    if not isinstance(value, str) or re.search(r"[\s\x00-\x1f\x7f]", value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in ("http", "https") and parsed.hostname:
            return quote(value, safe=":/?#@!$&'*+,;=%~-._")
        if parsed.scheme.lower() == "mailto" and parsed.path:
            return quote(value, safe=":/?#@!$&'*+,;=%~-._")
    except ValueError:
        pass
    return ""


def extract(pdf: Path) -> dict[str, list[dict]]:
    from pypdf import PdfReader
    from pypdfium2 import raw
    from .pdfwork import open_pdf
    from contextlib import closing

    result = {}
    reader = PdfReader(pdf)
    with open_pdf(pdf) as doc:
        for number, source in enumerate(reader.pages):
            annotations = []
            for ref in source.get("/Annots", []):
                item = ref.get_object()
                action = item.get("/A")
                action = action.get_object() if action else {}
                uri = safe_url(action.get("/URI", ""))
                rect = item.get("/Rect")
                if item.get("/Subtype") == "/Link" and uri and rect and len(rect) == 4:
                    annotations.append((uri, [float(v) for v in rect]))
            if not annotations:
                continue
            with closing(doc[number]) as page, closing(page.get_textpage()) as tp:
                chars = []
                for i in range(tp.count_chars()):
                    code = raw.FPDFText_GetUnicode(tp, i)
                    if not code or code > 0x10ffff or 0xd800 <= code <= 0xdfff:
                        continue
                    chars.append((chr(code), tp.get_charbox(i)))
                records = []
                for uri, (left, bottom, right, top) in annotations:
                    selected = [i for i, (_, box) in enumerate(chars)
                                if left <= (box[0] + box[2]) / 2 <= right
                                and bottom <= (box[1] + box[3]) / 2 <= top]
                    if not selected:
                        continue
                    first, last = min(selected), max(selected)
                    label = "".join(chars[i][0] for i in selected).strip()
                    if not label:
                        continue
                    records.append({"url": uri, "quote": label,
                                    "prefix": "".join(c for c, _ in chars[max(0, first - 100):first]),
                                    "suffix": "".join(c for c, _ in chars[last + 1:last + 101])})
                if records:
                    result[str(number + 1)] = records
    return result


def ensure(ws) -> dict[str, list[dict]]:
    source = ws.source_pdf
    if not source or not source.is_file():
        return {}
    stat = source.stat()
    identity = [str(source.resolve()), stat.st_size, stat.st_mtime_ns, _VERSION]
    cache = ws.root / "extract" / "pdf-links.json"
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("source") == identity:
            return saved.get("pages", {})
    except (OSError, ValueError):
        pass
    try:
        pages = extract(source)
    except Exception:  # An unreadable annotation must not block reading or translation.
        from .log import log
        log.exception("Could not extract PDF links: %s", source.name)
        return {}
    cache.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(cache, {"source": identity, "pages": pages})
    return pages


def _normal(text: str) -> str:
    return re.sub(r"\s+|[*`]", "", text).casefold()


def insert(text: str, links: list[dict]) -> str:
    """Match literal source labels plus context; ambiguous repeated labels remain plain."""
    if not isinstance(text, str) or not text:
        return text
    protected = [m.span() for m in _PROTECTED.finditer(text)]
    replacements = []
    for link in links:
        url = safe_url(link.get("url", ""))
        words = link.get("quote", "").split()
        if not words or not url:
            continue
        pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
        choices = []
        for match in pattern.finditer(text):
            a, b = match.span()
            if any(a < y and b > x for x, y in protected):
                continue
            # Avoid matching "here" inside "there".
            if a and text[a - 1].isalnum() and text[a].isalnum():
                continue
            if b < len(text) and text[b - 1].isalnum() and text[b].isalnum():
                continue
            before, after = _normal(text[max(0, a - 100):a]), _normal(text[b:b + 100])
            prefix, suffix = _normal(link.get("prefix", "")), _normal(link.get("suffix", ""))
            left = next((n for n in range(min(len(before), len(prefix)), 0, -1) if before[-n:] == prefix[-n:]), 0)
            right = next((n for n in range(min(len(after), len(suffix)), 0, -1) if after[:n] == suffix[:n]), 0)
            choices.append((left + right, a, b))
        choices.sort(reverse=True)
        if not choices:
            continue
        score, a, b = choices[0]
        if (len(choices) > 1 and score <= choices[1][0]) or (score < 8 and text[a:b] != link["url"]):
            continue
        if any(a < y and b > x for x, y, _ in replacements):
            continue
        label = text[a:b].replace("[", "\\[").replace("]", "\\]")
        replacements.append((a, b, f"[{label}]({url})"))
    for a, b, value in sorted(replacements, reverse=True):
        text = text[:a] + value + text[b:]
    return text


def _offset(old: str, new: str, offset: int) -> int:
    """Retain sentence boundaries when adding invisible Markdown link syntax."""
    def units(value):
        return len(value.encode("utf-16-le")) // 2
    position = len(old.encode("utf-16-le")[:offset * 2].decode("utf-16-le", errors="ignore"))
    mapped = position
    for tag, a, b, c, d in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "insert" and a <= position:
            mapped += d - c
        elif tag != "equal" and b <= position:
            mapped += (d - c) - (b - a)
    return units(new[:mapped])


def restore_blocks(blocks: list[dict], pages: dict) -> bool:
    changed = False
    for block in blocks:
        # A block may continue onto the next page.
        number = block.get("page")
        links = list(pages.get(str(number), []))
        if isinstance(number, int):
            links += pages.get(str(number + 1), [])
        for obj in [block, *(block.get("items") or [])]:
            if not isinstance(obj, dict):
                continue
            old_en = obj.get("en", "")
            for field in ("en", "caption_en", "image_en"):
                old = obj.get(field)
                new = insert(old, links)
                if old != new:
                    obj[field] = new
                    changed = True
            if old_en != obj.get("en", "") and obj.get("sents"):
                obj["sents"] = [[_offset(old_en, obj["en"], row[0]), row[1]] for row in obj["sents"]]
    return changed


def refresh(ws) -> None:
    pages = ensure(ws)
    if pages and restore_blocks((ws.load("paper") or {}).get("blocks", []), pages):
        # Re-read under the workspace lock; preserve new translations and all reader data.
        ws.update("paper", lambda paper: restore_blocks(paper.get("blocks", []), pages))
