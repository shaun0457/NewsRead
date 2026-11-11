"""閱讀器自己的 API（ticket 03）：Obsidian Vault 設定、匯出、心智圖。

原本這些走研究工作區的 /api/research/v1、/api/research/v2；抽出來之後研究工作區可以整個移除（ticket 04），
閱讀器不受影響。行為和舊路徑相同。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from . import mindmap, obsidian_export, tasks, vault

PREFIX = "/api/reader"
# 閱讀器的背景工作提示只顯示這兩種；閱讀路徑、深度剖析這些研究工作區的工作不列
READER_TASK_KINDS = frozenset({"mindmap", "smart-annotate"})
# /paper/<pid>/mindmap[/tasks[/<id>[/cancel|/ack]]]
_MINDMAP = re.compile(r"/paper/([^/]+)/mindmap(/tasks(?:/([^/]+)(?:/(cancel|ack))?)?)?")


def _endpoint(path: str) -> str | None:
    path = urlparse(path).path  # server 已經 unquote 過，這裡不再解一次
    if path != PREFIX and not path.startswith(PREFIX + "/"):
        return None
    return "/" + path[len(PREFIX):].strip("/")


def _vault_status() -> dict:
    root = vault.vault_path()
    return {"vault": str(root) if root else "", "configured": bool(root)}


def get(app, request_path: str) -> dict | None:
    """處理 GET；不是這個 API 的路徑回 None。"""
    endpoint = _endpoint(request_path)
    if endpoint is None:
        return None
    if endpoint == "/vault":
        return _vault_status()
    if endpoint == "/tasks":
        scope = tasks.scope_id(app.lib.root)
        return {"scope_id": scope, "tasks": [t for t in tasks.list_tasks(scope=scope) if t.get("kind") in READER_TASK_KINDS]}
    match = _MINDMAP.fullmatch(endpoint)
    if match:
        pid, in_tasks, identity, action = match.groups()
        if not in_tasks:
            return mindmap.cached(app, pid)
        if identity == "current" and not action:
            return {"task": mindmap.current_task(app.lib.root, pid)}
        if identity and not action:
            return mindmap.task(app, identity, pid)
    return None


def post(app, request_path: str, body) -> dict | None:
    """處理 POST；不是這個 API 的路徑回 None。"""
    endpoint = _endpoint(request_path)
    if endpoint is None:
        return None
    body = body if isinstance(body, dict) else {}
    if endpoint == "/vault":
        vault.set_vault(str(body.get("vault") or "").strip(), body.get("folders"))
        return _vault_status()
    if endpoint == "/export/obsidian":
        return obsidian_export.export_to_vault(body.get("documents"))
    if endpoint == "/export/zip":
        return obsidian_export.export_zip(body.get("documents"))
    match = _MINDMAP.fullmatch(endpoint)
    if match:
        pid, in_tasks, identity, action = match.groups()
        if not in_tasks:
            return mindmap.generate(app, pid, body)
        if not identity:
            return mindmap.submit(app, pid, body)
        if action == "cancel":
            return mindmap.cancel(app, identity)
        if action == "ack":
            return mindmap.acknowledge(app, identity, pid)
    return None
