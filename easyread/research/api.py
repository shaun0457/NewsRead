from __future__ import annotations

import json
import sqlite3
from urllib.parse import parse_qs, unquote, urlparse

from .. import chat_models, config, prefs
from ..i18n import tr
from . import comparison, index, matrix, proposals, scheduler, tasks, wiki, workflows
from .store import index_folders, normalize_folders, set_vault, settings, state_dir, vault_path

PREFIX = "/api/research/v1"


def _start_index(app, rebuild: bool = False):
    def run(cancel_event, report):
        lexical = index.index_vault(rebuild=rebuild, library=app.lib, semantic=False,
                                    cancel_event=cancel_event, progress=report)
        if cancel_event.is_set():
            return lexical
        semantic = index.index_vault(library=app.lib, semantic=True,
                                     cancel_event=cancel_event, progress=report)
        return {**semantic, "lexical_phase": lexical}
    return tasks.submit("index", run)


def get(app, request_path: str):
    parsed = urlparse(request_path)
    path = unquote(parsed.path)
    if not path.startswith(PREFIX):
        return None
    endpoint = path[len(PREFIX):] or "/status"
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    if endpoint == "/status":
        vault = vault_path()
        chunks = files = embedded = 0
        db_path = state_dir() / "index.sqlite3"
        if db_path.exists():
            try:
                with sqlite3.connect(db_path) as db:
                    chunks = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
                    files = db.execute("SELECT count(*) FROM files WHERE path NOT LIKE 'easyread/%'").fetchone()[0]
                    embedded = db.execute("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
            except sqlite3.Error:
                pass
        cfg = config.load()
        models = [{"id": item.get("id"), "name": item.get("name"), "engine": item.get("engine")}
                  for item in chat_models.models(cfg)]
        return {"vault": str(vault) if vault else "", "configured": bool(vault), "model": settings().get("model") or (cfg.get("chat") or {}).get("default", ""),
                "folders": index_folders(), "models": models, "files": files, "papers": len(app.lib.all()), "chunks": chunks, "embedded": embedded,
                "index_db": str(db_path), "notes": proposals.list_notes(), "tasks": tasks.list_tasks(),
                "pending_comparison": proposals.latest_pending_comparison(),
                "pending_matrix": proposals.latest_pending_matrix(), "pending_topic": proposals.latest_pending_topic(),
                "wiki_schedule": scheduler.status()}
    if endpoint == "/search":
        return index.search(query.get("q", ""), limit=int(query.get("limit", "10")),
                            kind=query.get("kind", ""), library=app.lib)
    if endpoint == "/notes":
        return {"notes": proposals.list_notes()}
    if endpoint == "/wiki/links":
        return wiki.graph()
    if endpoint == "/index":
        return _start_index(app, rebuild=query.get("rebuild") == "1")
    if endpoint.startswith("/tasks/"):
        task = tasks.get(endpoint.rsplit("/", 1)[1])
        if task is None:
            raise ValueError(tr("找不到這個研究工作。"))
        return task
    if endpoint.startswith("/proposals/"):
        return proposals.get(endpoint.rsplit("/", 1)[1])
    raise ValueError(tr("找不到這個 Research API 路徑。"))


def post(app, endpoint: str, body: dict):
    if endpoint == "/setup":
        path = set_vault(str(body.get("vault") or "").strip(), body.get("folders"))
        return {"vault": str(path), "configured": True, "notes": proposals.list_notes()}
    if endpoint == "/settings":
        patch = {}
        if "model" in body:
            model_id = str(body["model"] or "")
            if model_id:
                chat_models.find(config.load(), model_id)
            patch["model"] = model_id
        if "folders" in body:
            patch["folders"] = normalize_folders(body["folders"])
        if patch:
            prefs.save({"research": patch})
        return {"model": settings().get("model", "")}
    if endpoint == "/index":
        return _start_index(app, rebuild=bool(body.get("rebuild")))
    if endpoint.startswith("/tasks/") and endpoint.endswith("/cancel"):
        task = tasks.cancel(endpoint.split("/")[-2])
        if task is None:
            raise ValueError(tr("找不到這個研究工作。"))
        return task
    if endpoint == "/ask":
        result = workflows.answer(str(body.get("query") or ""), str(body.get("kind") or "comparison"), app.lib,
                                  str(body.get("paper_id") or ""), str(body.get("block") or ""),
                                  str(body.get("model") or settings().get("model") or ""), int(body.get("limit") or 10))
        return result
    if endpoint == "/comparison":
        return comparison.start(app.lib, body.get("paper_ids"), body.get("dimensions"),
                                str(body.get("focus") or ""), str(body.get("model") or ""))
    if endpoint == "/matrix":
        return matrix.start(app.lib, str(body.get("paper_id") or ""), str(body.get("topic_path") or ""),
                            str(body.get("model") or settings().get("model") or ""))
    if endpoint == "/topics":
        return proposals.create_topic(str(body.get("title") or ""))
    if endpoint == "/wiki/lint":
        return wiki.start_lint(app.lib, bool(body.get("semantic")), str(body.get("model") or ""))
    if endpoint == "/wiki/schedule":
        return scheduler.configure(bool(body.get("enabled")), str(body.get("frequency") or "weekly"),
                                   str(body.get("time") or "09:00"))
    if endpoint == "/proposals":
        result = proposals.create(str(body.get("title") or ""), str(body.get("kind") or "question"),
                                  str(body.get("task") or body.get("query") or ""), app.lib,
                                  str(body.get("model") or settings().get("model") or ""),
                                  str(body.get("paper_id") or ""), str(body.get("block") or ""),
                                  str(body.get("target") or ""), int(body.get("limit") or 10))
        return result
    if endpoint.startswith("/proposals/") and endpoint.endswith("/review"):
        identity = endpoint.split("/")[-2]
        return proposals.decide(identity, str(body.get("decision") or "") == "accept")
    raise ValueError(tr("找不到這個 Research API 路徑。"))
