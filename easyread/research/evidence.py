"""Canonical source text used to hash and quote parsed PaperRead blocks."""
from __future__ import annotations

from .store import sha256_text


def block_text(block: dict) -> str:
    content = [str(block.get(key) or "").strip() for key in ("en", "caption_en", "tex")]
    if not any(content):
        content = [str(block.get(key) or "").strip() for key in ("zh", "caption_zh")]
    if block.get("type") == "list":
        content.extend(str(item.get("en") or item.get("zh") or "").strip() for item in block.get("items", []))
    if block.get("type") == "table":
        content.extend(" | ".join(map(str, row)) for row in (block.get("head") or []) + (block.get("rows") or []))
    return "\n".join(value for value in content if value).strip()


def block_text_hash(block: dict) -> str:
    return sha256_text(block_text(block))
