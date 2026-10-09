"""Small in-process task registry for potentially slow local indexing work."""
from __future__ import annotations

import threading
import time
import uuid

from ..i18n import tr


_LOCK = threading.Lock()
_TASKS: dict[str, dict] = {}
_CANCEL: dict[str, threading.Event] = {}


def _public(task: dict) -> dict:
    return {key: value for key, value in task.items() if key != "_runner"}


def submit(kind: str, runner, retry_failed: bool = False) -> dict:
    with _LOCK:
        active = next((task for task in _TASKS.values()
                       if task["kind"] == kind and task["state"] in ("queued", "running", "cancelling")), None)
        if active:
            return _public(active)
        recent_failure = next((task for task in _TASKS.values()
                               if task["kind"] == kind and task["state"] in ("failed", "cancelled")
                               and time.time() - task["updated"] < 60), None)
        if recent_failure and not retry_failed:
            return _public(recent_failure)
        expired = sorted((task for task in _TASKS.values() if task["state"] not in ("queued", "running", "cancelling")),
                         key=lambda item: item["updated"], reverse=True)[100:]
        for old in expired:
            _TASKS.pop(old["id"], None)
        identity = str(uuid.uuid4())
        task = {"id": identity, "kind": kind, "state": "queued", "phase": "queued", "done": 0,
                "total": 0, "message": tr("排入背景工作…"), "created": time.time(), "updated": time.time()}
        cancel = threading.Event()
        _TASKS[identity] = task
        _CANCEL[identity] = cancel

    def report(phase: str, done: int, total: int, message: str):
        with _LOCK:
            if task["state"] in ("cancelling", "cancelled"):
                return
            task.update(phase=phase, done=max(0, int(done or 0)), total=max(0, int(total or 0)),
                        message=str(message or "")[:240], updated=time.time())

    def work():
        with _LOCK:
            task.update(state="running", phase="starting", message=tr("背景工作開始"), updated=time.time())
        try:
            result = runner(cancel, report)
            with _LOCK:
                if cancel.is_set():
                    task.update(state="cancelled", phase="cancelled", message=tr("工作已取消"))
                else:
                    task.update(state="completed", phase="completed", message=tr("工作完成"), result=result)
                task["updated"] = time.time()
        except Exception as error:  # noqa: BLE001
            with _LOCK:
                task.update(state="cancelled" if cancel.is_set() else "failed",
                            phase="cancelled" if cancel.is_set() else "failed",
                            message=tr("工作已取消") if cancel.is_set() else str(error)[:500], updated=time.time())
        finally:
            with _LOCK:
                _CANCEL.pop(identity, None)

    threading.Thread(target=work, name=f"research-{kind}-{identity[:8]}", daemon=True).start()
    return _public(task)


def get(identity: str) -> dict | None:
    with _LOCK:
        task = _TASKS.get(identity)
        return _public(task) if task else None


def list_tasks() -> list[dict]:
    with _LOCK:
        return [_public(task) for task in sorted(_TASKS.values(), key=lambda item: item["created"], reverse=True)[:20]]


def cancel(identity: str) -> dict | None:
    with _LOCK:
        task = _TASKS.get(identity)
        event = _CANCEL.get(identity)
        if not task:
            return None
        if event and task["state"] in ("queued", "running"):
            event.set()
            task.update(state="cancelling", phase="cancelling", message=tr("正在取消工作…"), updated=time.time())
        return _public(task)
