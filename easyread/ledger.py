"""帳本與索引核心：SQLite 索引、Story、只能新增的帳本、AI 用量、prompt 版本、ContextManifest。

- 帳本只能新增：資料庫 trigger 擋掉 UPDATE / DELETE（含 INSERT OR REPLACE 造成的刪除）。
  修正是新增一筆，帶 supersedes 指向原紀錄。
- 每筆紀錄存內容雜湊，並串成雜湊鏈（含前一筆的雜湊）。能驗出：內容被改、中間被刪、順序被調換。
  驗不出：鏈尾幾筆被整段刪掉（剩下的鏈仍然完整），以及能改檔案的人重算整條鏈。
  所以 verify() 會回傳最後一筆的 seq 和雜湊（head）；呼叫端把 head 另外存起來（目前還沒有自動存），
  之後拿來比對就能發現鏈尾被截斷。這是防意外和隨手修改的竄改偵測，不是防有檔案權限的攻擊者；
  例如 recursive_triggers 只在透過 Index 開的連線上生效，用別的工具直接改檔不受限制。
- AI 的帳本紀錄（who 以 "ai:" 開頭，不分大小寫）一定要指向一份已存在的 ContextManifest；
  manifest 的判斷時間不能晚於這筆紀錄寫入的時間，prompt 版本要跟 who 裡寫的一致。
- ContextManifest 只存 ID 和雜湊，不存全文；裡面的 Item 都必須早於這次判斷的時間，判斷時間也不能在未來。
- 資料庫放在本機資料目錄（不放在文獻庫，文獻庫可能在雲端同步資料夾，SQLite 的 WAL 檔在那裡會壞）。
  測試或臨時指定文獻庫（EASYREAD_LIBRARY）時才放在文獻庫底下，跟 usage.py 的做法一樣。
- 用 WAL 模式；備份走 SQLite 的備份機制，服務執行中也能安全備份。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from . import config

DB_NAME = "newsread.sqlite3"
KINDS = frozenset({"judgment", "prediction", "resolution", "thesis_status", "draft"})
MAX_LIST = 500                  # 唯讀 API 一次最多回幾筆
DEFAULT_LIST = 100
MAX_PAYLOAD_BYTES = 256 * 1024  # 單筆帳本紀錄的內容上限
MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 一次列表回傳的內容總量上限（超過就停在這裡，用 next_after 接著拿）
MAX_BROKEN = 50                 # verify 最多列出幾筆對不上的紀錄
MAX_SEQ = 2 ** 63 - 1
GENESIS = "0" * 64              # 第一筆紀錄的「前一筆雜湊」
BUSY_MS = 20000                 # 等別的寫入釋放鎖最多幾毫秒

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
  id TEXT PRIMARY KEY,
  first_item_id TEXT NOT NULL,
  first_published_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
-- Item 屬於哪個 Story。之後合併 Story 只改這張表，不改帳本裡既有判斷引用的 Item。
CREATE TABLE IF NOT EXISTS item_story (
  item_id TEXT PRIMARY KEY,
  story_id TEXT NOT NULL REFERENCES stories(id),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  who TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  supersedes TEXT REFERENCES ledger(id),
  context_manifest TEXT REFERENCES context_manifests(id),
  prev_hash TEXT NOT NULL,
  content_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ledger_kind ON ledger(kind, seq);
CREATE INDEX IF NOT EXISTS ledger_supersedes ON ledger(supersedes);
CREATE TABLE IF NOT EXISTS context_manifests (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  task TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  body TEXT NOT NULL,
  content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_usage (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  source TEXT NOT NULL,
  task TEXT NOT NULL,
  engine TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  cached_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cost_usd REAL,
  quota TEXT,
  context_manifest TEXT REFERENCES context_manifests(id)
);
CREATE TABLE IF NOT EXISTS prompt_versions (
  task TEXT NOT NULL,
  version TEXT NOT NULL,
  text_hash TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  PRIMARY KEY (task, version)
);
-- 每個 AI 任務目前用哪一版。這張表可以改；版本本身（prompt_versions）只能新增。
CREATE TABLE IF NOT EXISTS prompt_current (
  task TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  set_at TEXT NOT NULL,
  FOREIGN KEY (task, version) REFERENCES prompt_versions(task, version)
);
"""

APPEND_ONLY = ("ledger", "context_manifests", "ai_usage", "prompt_versions")


def _guards() -> str:
    out = []
    for table in APPEND_ONLY:
        for op in ("UPDATE", "DELETE"):
            out.append(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()} BEFORE {op} ON {table} "
                       f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;")
    return "\n".join(out)


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def parse_time(value: str, field: str = "time") -> datetime:
    """ISO 8601，必須帶時區。比較 Item 時間和判斷時間時，沒有時區就沒辦法比。"""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is required")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise ValueError(f"{field} is not an ISO 8601 time") from None
    if dt.tzinfo is None:
        raise ValueError(f"{field} needs a timezone")
    return dt


def is_ai(who: str) -> bool:
    return who.strip().lower().startswith("ai:")


def default_path() -> Path:
    base = config.library_dir() if config.temp_library() else config.HOME
    return Path(base) / DB_NAME


def _record_hash(prev_hash: str, row: dict) -> str:
    fields = {k: row[k] for k in ("id", "kind", "who", "recorded_at", "payload", "supersedes", "context_manifest")}
    return sha256(prev_hash + canonical(fields))


def _manifest_hash(row) -> str:
    return sha256(canonical({k: row[k] for k in ("id", "created_at", "task", "prompt_version", "decided_at", "body")}))


class Index:
    """NewsRead 的 SQLite 索引。每次操作開一條連線，多執行緒共用同一個 Index 也安全。"""

    def __init__(self, path: Path | str | None = None, clock: Callable[[], datetime] = _utcnow, busy_ms: int = BUSY_MS):
        self.path = Path(path) if path else default_path()
        self.clock = clock
        self.busy_ms = busy_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA + _guards())

    # ---------- 連線 ----------
    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=self.busy_ms / 1000, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute(f"PRAGMA busy_timeout={int(self.busy_ms)}")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA recursive_triggers=ON")  # INSERT OR REPLACE 刪掉舊列時也要觸發 DELETE trigger
        return db

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = self._open()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE：先拿寫入鎖，讀「最後一筆雜湊」和寫入之間不會被別的寫入插隊。"""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def read(self):
        """給同一個資料庫裡其他模組（例如 entities）用的連線，設定跟帳本一樣。"""
        return self._connect()

    def write(self):
        """BEGIN IMMEDIATE 的寫入交易，給其他模組用。"""
        return self._write()

    def now(self) -> str:
        return iso(self.clock())

    # ---------- Story ----------
    def ensure_story(self, item_id: str, published_at: str) -> str:
        """每則 Item 一進來就屬於一個 Story，預設自己一個。已經有歸屬就沿用。"""
        if not item_id:
            raise ValueError("item_id is required")
        parse_time(published_at, "published_at")
        with self._write() as db:
            row = db.execute("SELECT story_id FROM item_story WHERE item_id=?", (item_id,)).fetchone()
            if row:
                return row["story_id"]
            story_id = "S-" + uuid.uuid4().hex
            now = self.now()
            db.execute("INSERT INTO stories VALUES (?,?,?,?)", (story_id, item_id, published_at, now))
            db.execute("INSERT INTO item_story VALUES (?,?,?)", (item_id, story_id, now))
            return story_id

    def story_of(self, item_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT story_id FROM item_story WHERE item_id=?", (item_id,)).fetchone()
            return row["story_id"] if row else None

    # ---------- ContextManifest ----------
    def add_manifest(self, *, task: str, prompt_version: str, items: list[dict], decided_at: str | None = None,
                     theses: list[dict] | None = None, themes: list[dict] | None = None,
                     concepts: list[dict] | None = None, market_context_date: str | None = None) -> str:
        """記下一次 AI 呼叫送進去的東西。items 每筆是 {id, hash, published_at}；只存 ID 和雜湊。

        decided_at 預設是現在，不能在未來。Item 的 published_at 必須早於 decided_at，
        不然就是用了判斷當下還不存在的資料。
        """
        if not task or not prompt_version:
            raise ValueError("task and prompt_version are required")
        now = self.clock()
        decided_at = decided_at or iso(now)
        decided = parse_time(decided_at, "decided_at")
        if decided > now:
            raise ValueError("decided_at cannot be in the future")
        clean_items = []
        for item in items or []:
            if not item.get("id") or not item.get("hash"):
                raise ValueError("manifest items need id and hash")
            if parse_time(item.get("published_at"), "item published_at") >= decided:
                raise ValueError(f"manifest item {item['id']} is not earlier than decided_at")
            clean_items.append({"id": item["id"], "hash": item["hash"], "published_at": item["published_at"]})

        def refs(rows, name):
            out = []
            for r in rows or []:
                if not r.get("id") or not (r.get("hash") or r.get("version")):
                    raise ValueError(f"manifest {name} need id and hash or version")
                out.append({k: r[k] for k in ("id", "hash", "version") if r.get(k)})
            return out

        body = {"items": clean_items, "theses": refs(theses, "theses"), "themes": refs(themes, "themes"),
                "concepts": refs(concepts, "concepts"), "market_context_date": market_context_date}
        row = {"id": "M-" + uuid.uuid4().hex, "created_at": iso(now), "decided_at": iso(decided), "task": task,
               "prompt_version": prompt_version, "body": canonical(body)}
        row["content_hash"] = _manifest_hash(row)
        with self._write() as db:
            db.execute("INSERT INTO context_manifests VALUES (:id,:created_at,:decided_at,:task,:prompt_version,:body,:content_hash)", row)
        return row["id"]

    def manifest(self, manifest_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM context_manifests WHERE id=?", (manifest_id,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out.update(json.loads(out.pop("body")))
        return out

    # ---------- 帳本 ----------
    def append(self, kind: str, who: str, payload: dict, *, supersedes: str | None = None,
               context_manifest: str | None = None) -> dict:
        """新增一筆帳本紀錄並回傳。修正時帶 supersedes（原紀錄保留）。

        AI 紀錄的 who 寫成 ai:<model>@<prompt 版本>，prompt 版本要跟 manifest 的一致。
        """
        if kind not in KINDS:
            raise ValueError(f"unknown ledger kind: {kind}")
        if not who or not who.strip():
            raise ValueError("who is required")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        text = canonical(payload)
        if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload is too large")
        ai = is_ai(who)
        if ai and not context_manifest:
            raise ValueError("AI ledger records must point to a context manifest")
        with self._write() as db:
            recorded_at = self.now()
            if context_manifest:
                m = db.execute("SELECT decided_at, prompt_version FROM context_manifests WHERE id=?", (context_manifest,)).fetchone()
                if not m:
                    raise ValueError("context manifest not found")
                if parse_time(m["decided_at"]) > parse_time(recorded_at):
                    raise ValueError("context manifest is dated after this record")
                if ai and not who.endswith("@" + m["prompt_version"]):
                    raise ValueError("who does not match the manifest prompt version")
            if supersedes:
                old = db.execute("SELECT kind FROM ledger WHERE id=?", (supersedes,)).fetchone()
                if not old:
                    raise ValueError("superseded record not found")
                if old["kind"] != kind:
                    raise ValueError("a correction must keep the same kind")
                if db.execute("SELECT 1 FROM ledger WHERE supersedes=?", (supersedes,)).fetchone():
                    raise ValueError("record was already corrected; correct the latest version")
            last = db.execute("SELECT content_hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
            prev_hash = last["content_hash"] if last else GENESIS
            row = {"id": "L-" + uuid.uuid4().hex, "kind": kind, "who": who, "recorded_at": recorded_at,
                   "payload": text, "supersedes": supersedes, "context_manifest": context_manifest}
            row["prev_hash"] = prev_hash
            row["content_hash"] = _record_hash(prev_hash, row)
            cur = db.execute("INSERT INTO ledger (id, kind, who, recorded_at, payload, supersedes, context_manifest, prev_hash, content_hash) "
                             "VALUES (:id,:kind,:who,:recorded_at,:payload,:supersedes,:context_manifest,:prev_hash,:content_hash)", row)
            row["seq"] = cur.lastrowid
        return _public(row)

    def records(self, kind: str | None = None, after: int = 0, limit: int = DEFAULT_LIST, current_only: bool = False,
                max_bytes: int = MAX_RESPONSE_BYTES) -> list[dict]:
        """依寫入順序列出紀錄。最多 limit 筆（上限 MAX_LIST），內容總量超過 max_bytes 就提早停（至少回一筆）。
        current_only 只列沒有被修正過的版本。"""
        limit = max(1, min(int(limit), MAX_LIST))
        sql = "SELECT * FROM ledger l WHERE seq > ?"
        args: list = [max(0, min(int(after), MAX_SEQ))]
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if current_only:
            sql += " AND NOT EXISTS (SELECT 1 FROM ledger n WHERE n.supersedes = l.id)"
        sql += " ORDER BY seq LIMIT ?"
        args.append(limit)
        out, size = [], 0
        with self._connect() as db:
            for r in db.execute(sql, args):
                size += len(r["payload"].encode("utf-8"))
                if out and size > max_bytes:
                    break
                out.append(_public(dict(r)))
        return out

    def verify(self) -> dict:
        """重算整條雜湊鏈和每份 manifest 的雜湊。

        回傳 {ok, checked, head_seq, head_hash, broken: [對不上的 id，最多 MAX_BROKEN 筆], truncated}。
        head 要另外存起來比對，才驗得出鏈尾被截斷（見模組說明）。
        """
        prev = GENESIS
        checked, bad = 0, 0
        broken: list[str] = []
        head_seq = 0

        def flag(rid):
            nonlocal bad
            bad += 1
            if len(broken) < MAX_BROKEN:
                broken.append(rid)

        with self._connect() as db:
            for r in db.execute("SELECT * FROM ledger ORDER BY seq"):
                row = dict(r)
                checked += 1
                if row["prev_hash"] != prev or _record_hash(prev, row) != row["content_hash"]:
                    flag(row["id"])
                prev, head_seq = row["content_hash"], row["seq"]
            for r in db.execute("SELECT * FROM context_manifests"):
                if _manifest_hash(r) != r["content_hash"]:
                    flag(r["id"])
        return {"ok": bad == 0, "checked": checked, "head_seq": head_seq, "head_hash": prev if checked else None,
                "broken": broken, "truncated": bad > len(broken)}

    # ---------- AI 用量 ----------
    def record_usage(self, *, source: str, task: str, engine: str, model: str, input_tokens: int = 0,
                     cached_tokens: int = 0, output_tokens: int = 0, cost_usd: float | None = None,
                     quota: dict | None = None, context_manifest: str | None = None) -> int:
        """每次 AI 呼叫一筆。cost_usd=None 表示費用不明（訂閱制的本機 CLI 不折算成金額）；
        quota 是引擎回報的額度使用率和重置時間（有回報時）。"""
        if not (source and task and engine):
            raise ValueError("source, task and engine are required")
        tokens = [int(input_tokens or 0), int(cached_tokens or 0), int(output_tokens or 0)]
        if any(t < 0 for t in tokens):
            raise ValueError("token counts cannot be negative")
        with self._write() as db:
            if context_manifest and not db.execute("SELECT 1 FROM context_manifests WHERE id=?", (context_manifest,)).fetchone():
                raise ValueError("context manifest not found")
            cur = db.execute("INSERT INTO ai_usage (at, source, task, engine, model, input_tokens, cached_tokens, output_tokens, "
                             "cost_usd, quota, context_manifest) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (self.now(), source, task, engine, model or "", *tokens,
                              None if cost_usd is None else float(cost_usd),
                              canonical(quota) if quota else None, context_manifest))
            return cur.lastrowid

    def usage(self, after: int = 0, limit: int = DEFAULT_LIST) -> list[dict]:
        limit = max(1, min(int(limit), MAX_LIST))
        with self._connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM ai_usage WHERE seq > ? ORDER BY seq LIMIT ?",
                                                (max(0, min(int(after), MAX_SEQ)), limit))]
        for r in rows:
            r["cost"] = "unknown" if r["cost_usd"] is None else r["cost_usd"]
            r["quota"] = json.loads(r["quota"]) if r["quota"] else None
        return rows

    # ---------- prompt 版本 ----------
    def register_prompt(self, task: str, version: str, text: str, make_current: bool = True) -> None:
        """登記一個 prompt 版本（同任務同版本號的內容不能換）。make_current 設成這個任務目前的版本。"""
        if not task or not version:
            raise ValueError("task and version are required")
        text_hash = sha256(text or "")
        with self._write() as db:
            row = db.execute("SELECT text_hash FROM prompt_versions WHERE task=? AND version=?", (task, version)).fetchone()
            if row and row["text_hash"] != text_hash:
                raise ValueError(f"prompt {task}@{version} already registered with different text; bump the version")
            if not row:
                db.execute("INSERT INTO prompt_versions VALUES (?,?,?,?)", (task, version, text_hash, self.now()))
            if make_current:
                db.execute("INSERT INTO prompt_current VALUES (?,?,?) ON CONFLICT(task) DO UPDATE SET version=excluded.version, "
                           "set_at=excluded.set_at", (task, version, self.now()))

    def current_prompt(self, task: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT version FROM prompt_current WHERE task=?", (task,)).fetchone()
            return row["version"] if row else None

    # ---------- 備份 ----------
    def backup(self, dest: Path | str) -> Path:
        """用 SQLite 的備份機制複製一份一致的快照；服務執行中、有人正在寫入也安全。

        dest 不能已經存在（不覆蓋別的檔案）。先寫到暫存檔，完成後才改名，失敗不會留下半份檔案。
        """
        dest = Path(dest)
        if dest.exists():
            raise ValueError("backup destination already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() == self.path.resolve():
            raise ValueError("backup destination is the live database")
        tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
        try:
            with self._connect() as src:
                out = sqlite3.connect(tmp)
                try:
                    src.backup(out)
                finally:
                    out.close()
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
        return dest


def _public(row: dict) -> dict:
    out = {k: row.get(k) for k in ("seq", "id", "kind", "who", "recorded_at", "supersedes", "context_manifest", "content_hash")}
    out["payload"] = json.loads(row["payload"])
    return out


# ---------- 唯讀 API ----------
_SHARED: dict[Path, Index] = {}
_SHARED_LOCK = threading.Lock()


def shared(path: Path | str | None = None) -> Index | None:
    """伺服器共用的 Index；資料庫檔還不存在就回 None（唯讀的 GET 不建檔）。"""
    path = Path(path) if path else default_path()
    with _SHARED_LOCK:
        if path not in _SHARED:
            if not path.exists():
                return None
            _SHARED[path] = Index(path)
        return _SHARED[path]


class QueryError(ValueError):
    """唯讀 API 的查詢參數不對（回 400）。跟資料庫內容壞掉的錯誤分開。"""


def api_get(path: Path | str | None, query: dict) -> dict:
    """GET /api/ledger 的唯讀回應。query 的值是字串：kind、after、limit、current=1、verify=1。"""
    try:
        after = int(query.get("after") or 0)
        limit = int(query.get("limit") or DEFAULT_LIST)
    except ValueError:
        raise QueryError("after and limit must be integers") from None
    if not 0 <= after <= MAX_SEQ:
        raise QueryError("after is out of range")
    limit = max(1, min(limit, MAX_LIST))
    index = shared(path)
    records = index.records(kind=query.get("kind") or None, after=after, limit=limit,
                            current_only=query.get("current") == "1") if index else []
    out = {"records": records, "next_after": records[-1]["seq"] if records else after, "limit": limit}
    if query.get("verify") == "1":
        out["verify"] = index.verify() if index else {"ok": True, "checked": 0, "head_seq": 0, "head_hash": None,
                                                      "broken": [], "truncated": False}
    return out
