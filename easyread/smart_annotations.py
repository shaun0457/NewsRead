"""AI 智慧標註：產生可驗證的待確認候選，接受後才寫入既有 notes。"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import defaultdict

from .i18n import tr
from .prompts import _block_text
from .store import Workspace, now_iso, text_hash


ANNOTATION_TYPES = {"highlight", "underline"}
COLORS = {"yellow", "green", "blue", "red", "pink"}
SEMANTIC_COLORS = {
    "yellow": "核心概念、研究動機、主要主張、研究發現",  # i18n-ok: semantic map
    "green": "方法、模型架構、技術創新、實作細節",  # i18n-ok: semantic map
    "blue": "實驗數據、量化結果、比較證據、觀察",  # i18n-ok: semantic map
    "red": "研究限制、失敗案例、假設條件、待研究問題",  # i18n-ok: semantic map
}
MAX_CANDIDATES = 120
CHUNK_CHARS = 10000


def _section_label(block: dict, current: dict | None) -> str:
    if current:
        return " ".join(filter(None, [str(current.get("num") or "").strip(), current.get("zh") or current.get("en") or ""]))
    return tr("論文開頭")


def _sources(paper: dict) -> list[dict]:
    out = []
    current = None
    for block in paper.get("blocks", []) or []:
        if block.get("type") in ("heading", "references"):
            current = block
        text = _block_text(block).strip()
        if not text or block.get("type") in ("note",):
            continue
        out.append({
            "anchor": str(block.get("id") or ""), "key": str(block.get("id") or ""),
            "page": block.get("page"), "section": _section_label(block, current),
            "zh": str(block.get("zh") or text), "en": str(block.get("en") or ""),
            "sents": block.get("sents") if block.get("type") == "para" else None,
            "text": text,
        })
    return [x for x in out if x["anchor"]]


def _selected_sources(paper: dict, scope: str, section_id: str) -> list[dict]:
    sources = _sources(paper)
    if scope != "section" or not section_id:
        return sources
    selected = []
    active = False
    section_label = ""
    for item in sources:
        if item["anchor"] == section_id:
            active = True
            section_label = item["section"]
        elif active and item["section"] != section_label:
            break
        if active:
            selected.append(item)
    return selected or [x for x in sources if x["anchor"] == section_id]


def _chunks(sources: list[dict]) -> list[list[dict]]:
    chunks, current, size = [], [], 0
    for source in sources:
        estimate = len(source["zh"]) + len(source["en"]) + 180
        if current and size + estimate > CHUNK_CHARS:
            chunks.append(current)
            current, size = [], 0
        current.append(source)
        size += estimate
    if current:
        chunks.append(current)
    return chunks


def _prompt(title: str, mode: str, purpose: str, chunk: list[dict]) -> str:
    mode_text = {
        "auto": "找出最值得整體標記的句子，候選數量保持精簡。",  # i18n-ok: model prompt
        "suggest": "列出可逐筆審閱的候選句子，寧可少而精，不要替每段文字上色。",  # i18n-ok: model prompt
        "purpose": "只挑選與研究目的直接相關、具有研究價值的句子。",  # i18n-ok: model prompt
    }.get(mode, "列出少量高價值候選句子。")  # i18n-ok: model prompt
    records = []
    for source in chunk:
        records.append(
            f"[anchor={source['anchor']} key={source['key']} page={source.get('page') or ''} section={source['section']}]\n"
            f"ZH: {source['zh']}\nEN: {source['en']}"
        )
    return (
        "你是 PaperRead 的論文閱讀標註助手。只能根據提供的文字工作，不可補造論文內容、數據或引用。\n"  # i18n-ok: model prompt
        f"論文：{title}\n研究目的：{purpose or '未指定，依論文研究價值判斷'}\n{mode_text}\n\n"  # i18n-ok: model prompt
        "顏色規則：" + "；".join(f"{color}={meaning}" for color, meaning in SEMANTIC_COLORS.items()) + "。\n"  # i18n-ok: model prompt
        "highlight 用於完整有意義的內容；underline 用於句子中的關鍵主張、方法或證據。\n"  # i18n-ok: model prompt
        "請只輸出 JSON，不要 Markdown 或說明文字，格式："  # i18n-ok: model prompt
        '{"annotations":[{"anchor":"來源中的 anchor","key":"來源中的 key","quote_en":"完全照抄 EN 的連續文字",'  # i18n-ok: model prompt
        '"quote_zh":"完全照抄 ZH 的連續文字","type":"highlight 或 underline","color":"yellow/green/blue/red","note":"繁體中文一至三句，不要重複原文或附英文引用",'  # i18n-ok: model prompt
        '"reason":"為何值得標註","confidence":0.0,"side":"zh"}]}\n'  # i18n-ok: model prompt
        "quote_en 必須逐字從 EN 原文複製，quote_zh 必須逐字從 ZH 譯文複製；兩者都不要翻譯、改寫或自行補標點。正式標註會套用在 ZH 譯文；ZH 缺少時才退回 EN。note 只寫繁體中文解釋與研究價值，不要附加原文引用。anchor、key 只可使用來源標籤。最多輸出 12 筆。\n\n"  # i18n-ok: model prompt
        + "\n\n".join(records)
    )


def _norm(text: str) -> str:
    # ‖ is an internal sentence-alignment marker and is not rendered as text.
    return re.sub(r"\s+", " ", str(text or "").replace("‖", "").replace("\u200b", "")).strip()


def _normalized_match(text: str, quote: str) -> tuple[int, str] | None:
    """Match whitespace/alignment-marker differences while retaining real offsets."""
    chars, positions = [], []
    previous_space = False
    for index, char in enumerate(str(text or "")):
        if char in ("‖", "\u200b"):
            continue
        if char.isspace():
            if previous_space:
                continue
            chars.append(" ")
            positions.append(index)
            previous_space = True
            continue
        chars.append(char)
        positions.append(index)
        previous_space = False
    target = _norm(quote)
    normalized = "".join(chars)
    start = normalized.find(target)
    if start < 0 or not target:
        return None
    end_index = start + len(target) - 1
    begin = positions[start]
    end = positions[end_index] + 1
    return begin, str(text or "")[begin:end]


def _u16_positions(text: str) -> list[int]:
    """Map UTF-16 offsets (the paper.json/JS convention) to Python offsets."""
    positions = [0]
    for index, char in enumerate(str(text or "")):
        positions.append(positions[-1] + (2 if ord(char) > 0xFFFF else 1))
    return positions


def _aligned_zh_location(source: dict, en_location: dict) -> dict | None:
    """Map an English match to its aligned Chinese sentence(s), when available."""
    en, zh, sents = str(source.get("en") or ""), str(source.get("zh") or ""), source.get("sents")
    if not en or not zh or not isinstance(sents, list) or len(sents) < 2:
        return None
    if not isinstance(sents[-1], list) or len(sents[-1]) != 2:
        return None
    en_pos, zh_pos = _u16_positions(en), _u16_positions(zh)
    if sents[-1] != [en_pos[-1], zh_pos[-1]]:
        return None
    en_start = en_pos[min(max(int(en_location.get("index") or 0), 0), len(en))]
    en_end_py = min(len(en), int(en_location.get("index") or 0) + len(str(en_location.get("quote") or "")))
    en_end = en_pos[en_end_py]
    rows = [row for row in sents if isinstance(row, list) and len(row) == 2]
    start_row = next((i for i, row in enumerate(rows) if row[0] > en_start), None)
    end_row = next((i for i, row in enumerate(rows) if row[0] >= en_end), None)
    if start_row is None or end_row is None:
        return None
    zh_start_u16 = 0 if start_row == 0 else rows[start_row - 1][1]
    zh_end_u16 = rows[end_row][1]
    if not (0 <= zh_start_u16 < zh_end_u16 <= zh_pos[-1]):
        return None
    start = next((i for i, value in enumerate(zh_pos) if value >= zh_start_u16), None)
    end = next((i for i, value in enumerate(zh_pos) if value >= zh_end_u16), None)
    if start is None or end is None or end <= start:
        return None
    quote = zh[start:end].strip()
    if not quote:
        return None
    leading = len(zh[start:end]) - len(zh[start:end].lstrip())
    return {"source": source, "side": "zh", "quote": quote, "index": start + leading}


def _locate(quote: str, suggested_anchor: str, sources: list[dict], preferred_side: str = "") -> dict | None:
    quote = str(quote or "").strip()
    if not quote:
        return None
    preferred = [x for x in sources if x["anchor"] == suggested_anchor]
    candidates = preferred + [x for x in sources if x not in preferred]
    exact = []
    normalized = []
    sides = [preferred_side] if preferred_side in ("zh", "en") else []
    sides += [side for side in ("en", "zh") if side not in sides]
    for source in candidates:
        for side in sides:
            text = source.get(side) or ""
            if quote in text:
                exact.append((source, side, text.index(quote), quote))
            else:
                match = _normalized_match(text, quote)
                if match:
                    normalized.append((source, side, match[0], match[1], _norm(quote)))
    matches = exact or normalized
    if not matches:
        return None
    unique = {(m[0]["anchor"], m[1], _norm(m[3] if len(m) > 3 else m[3])) for m in matches}
    if len(unique) != 1:
        # A duplicate phrase is unsafe unless the model pointed at the exact source block.
        preferred_matches = [m for m in matches if m[0]["anchor"] == suggested_anchor]
        if len(preferred_matches) != 1:
            return None
        matches = preferred_matches
    source, side, index = matches[0][:3]
    actual = matches[0][3]
    text = source[side]
    if actual == text and index:
        actual = text[index:index + len(str(quote))]
    return {"source": source, "side": side, "quote": actual, "index": index}


def _stable_id(paper_id: str, item: dict) -> str:
    raw = "|".join(str(item.get(k) or "") for k in ("anchor", "key", "quote", "type", "color"))
    return "ai-" + hashlib.sha256((paper_id + "|" + raw).encode("utf-8")).hexdigest()[:20]


def _candidate(paper_id: str, raw: dict, sources: list[dict], model: str, purpose: str, created: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    typ = str(raw.get("type") or raw.get("annotation_type") or "highlight").lower()
    if typ not in ANNOTATION_TYPES:
        return None
    color = str(raw.get("color") or "yellow").lower()
    # Existing reader notes call the red semantic color "pink"; keep that
    # canonical value so old CSS and manual annotations continue to render.
    if color == "red":
        color = "pink"
    if color not in COLORS:
        return None
    requested_side = str(raw.get("side") or "").lower()
    raw_quote = str(raw.get("quote") or "").strip()
    quote_en = str(raw.get("quote_en") or (raw_quote if requested_side != "zh" else "") or "").strip()
    quote_zh = str(raw.get("quote_zh") or (raw_quote if requested_side == "zh" or (raw_quote and not raw.get("quote_en") and not raw.get("quote_zh") and not requested_side) else "") or "").strip()
    if not quote_en and not quote_zh:
        return None
    suggested_anchor = str(raw.get("anchor") or "")
    located_en = _locate(quote_en, suggested_anchor, sources, "en") if quote_en else None
    source = located_en["source"] if located_en else next((x for x in sources if x["anchor"] == suggested_anchor), None)
    if not source:
        source = {"anchor": suggested_anchor, "key": str(raw.get("key") or ""), "page": None, "section": "", "zh": "", "en": "", "sents": None}
    located_zh = _locate(quote_zh, source["anchor"], [source], "zh") if quote_zh else None
    if located_zh is None and located_en and source.get("zh"):
        located_zh = _aligned_zh_location(source, located_en)
    located = located_zh or (located_en if not source.get("zh") or not quote_zh else None)
    actual_quote = located["quote"] if located else (quote_zh or quote_en)
    confidence = raw.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    annotation_side = located["side"] if located else ("zh" if source.get("zh") else "en")
    annotation = {
        "annotation_id": _stable_id(paper_id, {"anchor": source["anchor"], "key": source["key"], "quote": actual_quote, "type": typ, "color": color}),
        "paper_id": paper_id, "quote": actual_quote, "type": typ, "style": "underline" if typ == "underline" else "marker",
        "color": color, "note": str(raw.get("note") or "").strip()[:1200], "reason": str(raw.get("reason") or "").strip()[:1200],
        "purpose": purpose[:500], "page": source.get("page"), "anchor": source["anchor"], "key": source["key"],
        "prefix": (source.get(annotation_side) or source.get("zh") or source.get("en") or "")[:32], "suffix": "", "confidence": confidence,
        "section": source.get("section") or "", "status": "pending", "locatable": bool(located),
        "side": annotation_side,
        "source_quote_en": located_en["quote"] if located_en else quote_en,
        "source_quote_zh": actual_quote if annotation_side == "zh" else quote_zh,
        "source_en_hash": text_hash(source.get("en") or ""),
        "source_zh_hash": text_hash(source.get("zh") or ""),
        "source_text_hash": text_hash(source.get(annotation_side) or ""),
        "model": model, "created_at": created, "updated_at": created,
    }
    if located:
        text = located["source"].get(located["side"]) or ""
        i = located["index"]
        annotation["prefix"] = text[max(0, i - 32):i]
        annotation["suffix"] = text[i + len(actual_quote):i + len(actual_quote) + 32]
    return annotation


def _dedupe(candidates: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for item in candidates:
        key = (item.get("anchor"), item.get("key"), _norm(item.get("quote")), item.get("type"))
        if key in seen:
            continue
        seen.add(key)
        if any(x.get("anchor") == item.get("anchor") and (_norm(x.get("quote")) in _norm(item.get("quote")) or _norm(item.get("quote")) in _norm(x.get("quote"))) for x in out):
            continue
        out.append(item)
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def generate(ws: Workspace, *, scope="all", section_id="", mode="auto", purpose="", model_id="", cancel=None) -> dict:
    from . import chat_models, config, engines, usage
    paper = ws.load("paper") or {}
    sources = _selected_sources(paper, scope, section_id)
    if not sources:
        raise ValueError(tr("這篇論文目前沒有可供分析的文字。"))
    cfg, selected = chat_models.engine_cfg(config.load(), model_id or None)
    cfg = engines.for_translation(cfg)
    model_name = chat_models.label(selected)
    meter = usage.Meter(cfg.get("engine") or "")
    title = (paper.get("meta") or {}).get("title_zh") or (paper.get("meta") or {}).get("title_en") or tr("未命名論文")
    # 先把舊版本候選重新對照目前 blocks；重新翻譯後再按智慧標註時，
    # 使用者會看到哪些項目仍有效、哪些必須重新分析，而不是沿用舊譯文位置。
    refresh_after_translation(ws)
    generated = []
    existing = (ws.load("reader") or {}).get("ai_annotations") or {}
    saved = 0
    for chunk in _chunks(sources):
        if cancel is not None and cancel.is_set():
            raise engines.Cancelled()
        raw = engines.parse_json(engines.run(cfg, _prompt(title, mode, purpose, chunk), ws.root, [], cancel, meter))
        rows = raw.get("annotations", []) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        chunk_items = _dedupe([item for row in rows if (item := _candidate(ws.id, row, sources, model_name, purpose, now_iso()))])
        ops = []
        for item in chunk_items:
            if any(x["annotation_id"] == item["annotation_id"] for x in generated):
                continue
            generated.append(item)
            old = existing.get(item["annotation_id"])
            if old and old.get("status") in ("accepted", "rejected"):
                continue
            if old:
                item["status"] = old.get("status", "pending")
                item["created_at"] = old.get("created_at", item["created_at"])
            ops.append({"op": "ai_annotation", "annotation": item, "at": item["updated_at"]})
        if ops:
            ws.apply_reader_ops(ops, client="smart-annotations")
            saved += len(ops)
            existing = (ws.load("reader") or {}).get("ai_annotations") or {}
    return {"count": saved, "total": len(generated), "usage": meter.snapshot(), "model": model_name}


def _valid_patch(annotation: dict, patch: dict, sources: list[dict] | None = None) -> dict:
    out = dict(annotation)
    if "quote" in patch and sources is not None:
        quote = str(patch.get("quote") or "").strip()
        located = _locate(quote, str(annotation.get("anchor") or ""), sources, str(annotation.get("side") or ""))
        out["quote"] = quote
        out["locatable"] = bool(located)
        if located:
            source = located["source"]
            out.update({"quote": located["quote"], "anchor": source["anchor"], "key": source["key"],
                        "page": source.get("page"), "section": source.get("section") or "", "side": located["side"]})
            text = source.get(located["side"]) or ""
            i = located["index"]
            out["prefix"] = text[max(0, i - 32):i]
            out["suffix"] = text[i + len(located["quote"]):i + len(located["quote"]) + 32]
            out["source_en_hash"] = text_hash(source.get("en") or "")
            out["source_zh_hash"] = text_hash(source.get("zh") or "")
            out["source_text_hash"] = text_hash(text)
            out["source_quote_zh"] = located["quote"] if located["side"] == "zh" else out.get("source_quote_zh", "")
    for key in ("note", "reason", "purpose"):
        if key in patch:
            out[key] = str(patch[key] or "")[:1200]
    if patch.get("color") in COLORS:
        out["color"] = "pink" if patch["color"] == "red" else patch["color"]
    if patch.get("type") in ANNOTATION_TYPES:
        out["type"] = patch["type"]
        out["style"] = "underline" if patch["type"] == "underline" else "marker"
    out["updated_at"] = now_iso()
    return out


def _formal_note(annotation: dict, existing: dict) -> dict:
    nid = "ai-note-" + annotation["annotation_id"].removeprefix("ai-")
    return {
        "id": nid, "anchor": annotation.get("anchor"), "key": annotation.get("key"), "quote": annotation.get("quote"),
        "prefix": annotation.get("prefix", ""), "suffix": annotation.get("suffix", ""), "side": annotation.get("side"),
        "kind": "highlight", "color": annotation.get("color", "yellow"), "style": annotation.get("style", "marker"),
        "body": annotation.get("note", ""), "created": existing.get("created", now_iso()), "updated": now_iso(),
        "ai_generated": True, "ai_annotation_id": annotation["annotation_id"],
    }


def _source_for_annotation(annotation: dict, sources: list[dict]) -> dict | None:
    """Find the current block, even when a retranslation regenerated its block id."""
    anchor = str(annotation.get("anchor") or "")
    exact = next((source for source in sources if source["anchor"] == anchor), None)
    old_en_hash = str(annotation.get("source_en_hash") or "")
    old_zh_hash = str(annotation.get("source_zh_hash") or "")
    if exact and (not old_en_hash or text_hash(exact.get("en") or "") == old_en_hash or
                  not old_zh_hash or text_hash(exact.get("zh") or "") == old_zh_hash):
        return exact
    en_hash = old_en_hash
    if en_hash:
        matches = [source for source in sources if text_hash(source.get("en") or "") == en_hash]
        if len(matches) == 1:
            return matches[0]
    zh_hash = old_zh_hash
    if zh_hash:
        matches = [source for source in sources if text_hash(source.get("zh") or "") == zh_hash]
        if len(matches) == 1:
            return matches[0]
    return None


def _refresh_annotation(annotation: dict, sources: list[dict]) -> dict:
    """Rebase an AI suggestion against the latest paper blocks after translation."""
    out = dict(annotation)
    source = _source_for_annotation(annotation, sources)
    if not source:
        out.update({"locatable": False, "source_stale": True, "stale_reason": "source_missing"})
        return out
    side = str(annotation.get("side") or "")
    source_quote_en = str(annotation.get("source_quote_en") or (annotation.get("quote") if side == "en" else ""))
    source_quote_zh = str(annotation.get("source_quote_zh") or (annotation.get("quote") if side == "zh" else ""))
    located_en = _locate(source_quote_en, source["anchor"], [source], "en") if source_quote_en else None
    located_zh = _locate(source_quote_zh, source["anchor"], [source], "zh") if source_quote_zh else None
    if located_zh is None and located_en and source.get("zh"):
        located_zh = _aligned_zh_location(source, located_en)
    located = located_zh or (located_en if not source.get("zh") else None)
    out.update({
        "anchor": source["anchor"], "key": source["key"], "page": source.get("page"),
        "section": source.get("section") or "", "source_en_hash": text_hash(source.get("en") or ""),
        "source_zh_hash": text_hash(source.get("zh") or ""),
    })
    if located:
        text = located["source"].get(located["side"]) or ""
        i = located["index"]
        out.update({
            "quote": located["quote"], "side": located["side"], "locatable": True,
            "source_quote_en": located_en["quote"] if located_en else source_quote_en,
            "source_quote_zh": located["quote"] if located["side"] == "zh" else source_quote_zh,
            "source_text_hash": text_hash(text), "source_stale": False, "stale_reason": "",
            "prefix": text[max(0, i - 32):i], "suffix": text[i + len(located["quote"]):i + len(located["quote"]) + 32],
        })
        return out
    current_hash = text_hash(source.get("zh" if source.get("zh") else side) or "") if side in ("zh", "en") else ""
    old_hash = str(annotation.get("source_text_hash") or "")
    reason = "translation_changed" if source.get("zh") and old_hash and current_hash != old_hash else "source_changed"
    out.update({"locatable": False, "source_stale": True, "stale_reason": reason})
    return out


def refresh_after_translation(ws: Workspace, block_ids: set[str] | None = None) -> dict:
    """Revalidate AI suggestions and accepted notes after paper text is replaced.

    English quotes survive a retranslation because the English source is stable. A
    quote that was made against the old Chinese translation is kept for review but
    marked stale instead of silently being attached to a wrong sentence.
    """
    reader = ws.load("reader") or {}
    annotations = reader.get("ai_annotations") or {}
    if not annotations:
        return {"updated": 0, "rev": reader.get("rev", 0)}
    sources = _sources(ws.load("paper") or {})
    scope = set(block_ids or ())
    ops = []
    for aid, annotation in annotations.items():
        if scope and annotation.get("anchor") not in scope and not _source_for_annotation(annotation, sources):
            continue
        updated = _refresh_annotation(annotation, sources)
        changed = any(updated.get(key) != annotation.get(key) for key in (
            "anchor", "key", "page", "section", "quote", "side", "prefix", "suffix", "locatable",
            "source_quote_en", "source_quote_zh", "source_en_hash", "source_zh_hash", "source_text_hash", "source_stale", "stale_reason"))
        if not changed:
            continue
        updated["updated_at"] = now_iso()
        ops.append({"op": "ai_annotation", "annotation": updated, "at": updated["updated_at"]})
        for note in (reader.get("notes") or {}).values():
            if note.get("ai_annotation_id") != aid or note.get("deleted"):
                continue
            note_updated = dict(note, anchor=updated.get("anchor"), key=updated.get("key"), quote=updated.get("quote"),
                                prefix=updated.get("prefix", ""), suffix=updated.get("suffix", ""), side=updated.get("side"),
                                stale=not updated.get("locatable"), updated=updated["updated_at"])
            ops.append({"op": "note", "note": note_updated, "at": updated["updated_at"]})
    if not ops:
        return {"updated": 0, "rev": reader.get("rev", 0)}
    result = ws.apply_reader_ops(ops, client="smart-annotation-source-refresh")
    return {"updated": len(ops), **result}


def apply_action(ws: Workspace, body: dict) -> dict:
    action = str(body.get("action") or "")
    reader = ws.load("reader") or {}
    annotations = reader.get("ai_annotations") or {}
    sources = _sources(ws.load("paper") or {})
    ids = [str(body.get("id"))] if body.get("id") else list(annotations)
    if action == "accept_all":
        ids = [k for k, v in annotations.items() if v.get("status") in ("pending", "edited") and v.get("locatable")]
    if action not in ("accept", "reject", "edit", "accept_all"):
        raise ValueError(tr("智慧標註操作不正確。"))
    ops = []
    for aid in ids:
        annotation = annotations.get(aid)
        if not annotation:
            continue
        if action == "reject":
            updated = dict(annotation, status="rejected", updated_at=now_iso())
            ops.append({"op": "ai_annotation", "annotation": updated, "at": updated["updated_at"]})
        elif action == "edit":
            updated = _valid_patch(annotation, body.get("patch") or {}, sources)
            updated["status"] = "edited"
            ops.append({"op": "ai_annotation", "annotation": updated, "at": updated["updated_at"]})
        elif action in ("accept", "accept_all"):
            if not annotation.get("locatable"):
                raise ValueError(tr("這筆標註尚未確認文字位置，請先修改原文。"))
            updated = dict(annotation, status="accepted", updated_at=now_iso())
            ops.append({"op": "ai_annotation", "annotation": updated, "at": updated["updated_at"]})
            notes = reader.get("notes") or {}
            if not any(n.get("ai_annotation_id") == aid and not n.get("deleted") for n in notes.values()):
                ops.append({"op": "note", "note": _formal_note(updated, {}) , "at": updated["updated_at"]})
    if ops:
        result = ws.apply_reader_ops(ops, client="smart-annotation-review")
    else:
        result = {"applied": [], "rev": reader.get("rev", 0)}
    return {"ok": True, "action": action, "count": len(ops), **result}


def sections(ws: Workspace) -> list[dict]:
    paper = ws.load("paper") or {}
    return [{"id": b.get("id"), "label": _section_label(b, b), "page": b.get("page")} for b in paper.get("blocks", []) if b.get("type") in ("heading", "references")]
