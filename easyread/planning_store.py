"""文獻庫的 SQLite 狀態：閱讀狀態清單和心智圖快取。

研究工作區（文獻搜尋、候選論文、摘要、閱讀路徑、里程碑、追蹤、跨論文關鍵字）在 ticket 04 移除。
那些資料表留在使用者的 .paperread-planning.sqlite3 裡不刪，只是不再建立也不再讀取。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATUSES = [
    {"id": "unread", "label": "待閱讀", "color": "#8b8b8b", "position": 0, "builtin": True},  # i18n-ok: Research 工作區訊息依產品規格固定使用繁體中文。
    {"id": "reading", "label": "閱讀中", "color": "#6b9eb1", "position": 1, "builtin": True},  # i18n-ok: Research 工作區訊息依產品規格固定使用繁體中文。
    {"id": "organizing", "label": "待整理", "color": "#b68a54", "position": 2, "builtin": True},  # i18n-ok: Research 工作區訊息依產品規格固定使用繁體中文。
    {"id": "done", "label": "已完成", "color": "#719879", "position": 3, "builtin": True},  # i18n-ok: Research 工作區訊息依產品規格固定使用繁體中文。
    {"id": "paused", "label": "暫停", "color": "#9a819e", "position": 4, "builtin": True},  # i18n-ok: Research 工作區訊息依產品規格固定使用繁體中文。
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(root: Path):
    path = Path(root) / ".paperread-planning.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS statuses (
        id TEXT PRIMARY KEY, label TEXT NOT NULL, color TEXT NOT NULL,
        position INTEGER NOT NULL, builtin INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS cache (
        cache_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated TEXT NOT NULL
      );
    """)
    existing = db.execute("SELECT count(*) FROM statuses").fetchone()[0]
    if not existing:
        db.executemany("INSERT INTO statuses(id,label,color,position,builtin) VALUES(?,?,?,?,?)",
                        [(s["id"], s["label"], s["color"], s["position"], 1) for s in DEFAULT_STATUSES])
    db.commit()
    return db


@contextmanager
def _db(root: Path):
    db = _connect(root)
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def statuses(root: Path) -> list[dict]:
    with _db(root) as db:
        return [dict(r) for r in db.execute("SELECT * FROM statuses ORDER BY position,id")]


def cache_get(root: Path, key: str):
    with _db(root) as db:
        row = db.execute("SELECT payload_json,updated FROM cache WHERE cache_key=?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else (None, "")


def cache_put(root: Path, key: str, payload: dict):
    with _db(root) as db:
        db.execute("INSERT INTO cache(cache_key,payload_json,updated) VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET payload_json=excluded.payload_json,updated=excluded.updated",
                   (key, json.dumps(payload, ensure_ascii=False), _now()))
        db.commit()
