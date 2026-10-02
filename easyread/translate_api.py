"""整篇翻译入口：继续确认中的任务、重试失败页、给已整理的原文补译文。"""
from __future__ import annotations

from . import paperdata


def enqueue(jobs, ws, body: dict) -> dict:
    last = ws.load("job") or {}
    pending = last.get("state") == "confirm"
    pages = paperdata.parse_pages(body["pages"]) if body.get("pages") else None
    scope = body.get("scope") or (last.get("scope") if pending else None)
    read = bool(last.get("read")) if pending else bool(body.get("read"))
    model = (last.get("model") or "") if pending else str(body.get("model") or "")
    target = (last.get("target") or "") if pending else ""
    if body.get("failed"):
        pages = sorted(int(k) for k in (last.get("failed") or {})) or None
        read, model, target = bool(last.get("read")), last.get("model") or "", last.get("target") or ""
    elif body.get("en"):
        # “给英文原文补译文”仍是全文操作，只有用户亲自指定 pages 才豁免页数确认。
        read = False
        if not pages:
            scope = "all"
    jobs.enqueue(ws, pages=pages, translate_after=True, scope=scope, read=read, model=model,
                 confirmed=body.get("confirmed") is True, target=target)
    return {"ok": True}
