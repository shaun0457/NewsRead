"""后台任务的批量接口：一键停止翻译。单篇的取消仍走 /api/p/<id>/cancel。"""
from __future__ import annotations

from .i18n import tr


def post(app, path: str, body: dict):
    if path == "/api/jobs/stop":  # ids 不给就是全部
        ids = body.get("ids")
        if ids is not None and not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
            raise ValueError(tr("ids 必须是字符串数组"))
        return {"stopped": app.jobs.stop_model_work(ids)}
    return None


POST = {"/api/jobs/stop"}
