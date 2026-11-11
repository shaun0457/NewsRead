"""追蹤對象（ticket 13）：公司、產業 / 供應鏈、總經 / 政策、事件、題材，加上別名、代號、對照基準、和資料的連結。

- 存在帳本同一個 SQLite 檔（newsread.sqlite3），但不是只能新增的表：追蹤對象可以編輯、封存。
  封存不刪資料，帳本裡跟它有關的判斷照樣指得到它。
- 代號只驗格式（台股 4–6 碼數字，可帶 .TW / .TWO；美股 1–5 個英文字母，可帶 .B 這類類別）。
  代號存不存在要等行情資料（#30）才查得到。
- 基準指數、產業指數存 NULL 代表「用預設」，預設值依主要代號（第一個）的市場決定；手動改過就存下來。
  產業指數沒有預設值：要知道公司屬於哪個產業，得等行情資料。
- 資料和追蹤對象的連結（Mention）分 AI 和手動。手動移除會留下一筆「已移除」，之後 AI 重新分類不會再把它連回去。
"""
from __future__ import annotations

import re
import threading
import unicodedata
import uuid
from datetime import timedelta
from pathlib import Path

from . import ledger
from .i18n import tr

TYPES = ("company", "industry", "macro", "event", "theme")
MARKETS = ("TW", "US")
DEFAULT_BENCHMARK = {
    "TW": "發行量加權股價報酬指數",  # i18n-ok：指數名稱是資料，不是介面文字
    "US": "S&P 500 Total Return",
}
MAX_ENTITIES = 2000     # 追蹤對象總數上限（列表一次全回傳，所以要有上限）
MAX_NAME = 100
MAX_LISTINGS = 5
MAX_ALIASES = 20
MAX_ALIAS = 60
MAX_INDEX_NAME = 80
MAX_MENTIONS = 50       # 追蹤對象頁一次列出的最近連結
MAX_LINKS = 5000        # 一個追蹤對象最多連幾則資料（含手動移除留下的紀錄）
RECENT_DAYS = 7         # 列表「近 7 天」欄：這段時間內連上的資料數
MAX_BODY = 64 * 1024    # 一次建立 / 編輯的請求大小上限
# re.ASCII：\d 只認 0-9。全形數字先用 NFKC 轉成半形，其他文字的數字直接拒絕
_TW = re.compile(r"(\d{4,6}[A-Z]?)(?:\.(TW|TWO))?", re.ASCII)
_US = re.compile(r"[A-Z]{1,5}(?:[.-][A-Z])?", re.ASCII)
_ITEM = re.compile(r"[A-Za-z0-9_\-:.]{1,128}")
_ENTITY_ID = re.compile(r"E-[0-9a-f]{32}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  benchmark TEXT,
  industry_index TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_listings (
  entity_id TEXT NOT NULL REFERENCES entities(id),
  position INTEGER NOT NULL,
  market TEXT NOT NULL,
  symbol TEXT NOT NULL,
  PRIMARY KEY (entity_id, position),
  UNIQUE (market, symbol)
);
CREATE TABLE IF NOT EXISTS entity_aliases (
  entity_id TEXT NOT NULL REFERENCES entities(id),
  position INTEGER NOT NULL,
  alias TEXT NOT NULL,
  folded TEXT NOT NULL,
  PRIMARY KEY (entity_id, folded)
);
-- Item 與追蹤對象的連結。removed=1 是手動移除留下的紀錄，AI 不能再連回去。
CREATE TABLE IF NOT EXISTS mentions (
  item_id TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES entities(id),
  source TEXT NOT NULL CHECK (source IN ('ai', 'manual')),
  removed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (item_id, entity_id)
);
CREATE INDEX IF NOT EXISTS mentions_by_entity ON mentions (entity_id, removed, updated_at);
"""


class EntityError(ValueError):
    """輸入不對（回 400）。field 指出是哪個欄位，畫面用來標紅框。"""

    def __init__(self, message: str, field: str = ""):
        super().__init__(message)
        self.field = field


class NotFound(LookupError):
    """找不到這個追蹤對象（回 404）。"""


def _text(value, field: str, limit: int, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise EntityError(tr("請填寫名稱。"), field)
        return None
    if not isinstance(value, str):
        raise EntityError(tr("這個欄位要是文字。"), field)
    value = " ".join(value.split())
    if required and not value:
        raise EntityError(tr("請填寫名稱。"), field)
    if len(value) > limit:
        raise EntityError(tr("最多 {n} 個字。", n=limit), field)
    return value or None


def normalize_symbol(market: str, raw) -> str:
    """把使用者打的代號整理成存的格式：台股「2330.TW」、美股「NVDA」。格式不對丟 EntityError。"""
    if not isinstance(raw, str) or not raw.strip():
        raise EntityError(tr("請填寫代號。"))
    text = unicodedata.normalize("NFKC", raw).strip().upper()  # 全形「２３３０」= 2330
    if market == "TW":
        m = _TW.fullmatch(text)
        if not m:
            raise EntityError(tr("台股代號是 4 到 6 碼數字，例如 2330 或 6488.TWO。"))
        return f"{m[1]}.{m[2] or 'TW'}"
    if market == "US":
        if not _US.fullmatch(text):
            raise EntityError(tr("美股代號是 1 到 5 個英文字母，例如 NVDA 或 BRK.B。"))
        return text.replace("-", ".")
    raise EntityError(tr("市場只能是台股或美股。"))


def _listings(value) -> list[tuple[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EntityError(tr("代號格式不對。"), "listings")
    if len(value) > MAX_LISTINGS:
        raise EntityError(tr("代號最多 {n} 個。", n=MAX_LISTINGS), "listings")
    out, seen = [], set()
    for i, item in enumerate(value):
        field = f"listings.{i}"
        if not isinstance(item, dict):
            raise EntityError(tr("代號格式不對。"), field)
        market = item.get("market")
        if market not in MARKETS:
            raise EntityError(tr("市場只能是台股或美股。"), field + ".market")
        try:
            symbol = normalize_symbol(market, item.get("symbol"))
        except EntityError as e:
            raise EntityError(str(e), field + ".symbol") from None
        if (market, symbol) in seen:
            raise EntityError(tr("同一個代號填了兩次。"), field + ".symbol")
        seen.add((market, symbol))
        out.append((market, symbol))
    return out


def _fold(text: str) -> str:
    """比對別名用：全形半形、大小寫都當成一樣。"""
    return unicodedata.normalize("NFKC", text).casefold()


def _aliases(value, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EntityError(tr("別名格式不對。"), "aliases")
    if len(value) > MAX_ALIASES:
        raise EntityError(tr("別名最多 {n} 個。", n=MAX_ALIASES), "aliases")
    out, seen = [], {_fold(name)}
    for i, raw in enumerate(value):
        alias = _text(raw, f"aliases.{i}", MAX_ALIAS)
        if alias and _fold(alias) not in seen:  # 跟名稱或別的別名一樣的，安靜地略過
            seen.add(_fold(alias))
            out.append(alias)
    return out


def validate(body) -> dict:
    """整理建立 / 編輯的輸入。回傳要存的欄位；不對就丟 EntityError。"""
    if not isinstance(body, dict):
        raise EntityError(tr("資料格式不對。"))
    kind = body.get("type")
    if kind not in TYPES:
        raise EntityError(tr("請選擇類型。"), "type")
    name = _text(body.get("name"), "name", MAX_NAME, required=True)
    listings = _listings(body.get("listings"))
    if listings and kind != "company":
        raise EntityError(tr("只有公司可以填代號。"), "listings")
    benchmark = _text(body.get("benchmark"), "benchmark", MAX_INDEX_NAME)
    industry = _text(body.get("industry_index"), "industry_index", MAX_INDEX_NAME)
    if kind != "company":
        benchmark = industry = None
    return {"type": kind, "name": name, "listings": listings, "aliases": _aliases(body.get("aliases"), name),
            "benchmark": benchmark, "industry_index": industry}


def check_item_id(item_id) -> str:
    if not isinstance(item_id, str) or not _ITEM.fullmatch(item_id):
        raise EntityError(tr("資料編號格式不對。"), "item_id")
    return item_id


class Store:
    """追蹤對象的讀寫。共用帳本的 Index（同一個 SQLite 檔、同一套連線設定）。"""

    def __init__(self, index: ledger.Index):
        self.index = index
        with index.read() as db:  # executescript 會自己 COMMIT，所以不放在 write() 的 BEGIN 裡
            db.executescript(SCHEMA)

    # ---------- 讀 ----------
    def _load(self, db, rows) -> list[dict]:
        ids = [r["id"] for r in rows]
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        listings: dict[str, list] = {i: [] for i in ids}
        for r in db.execute(f"SELECT entity_id, market, symbol FROM entity_listings WHERE entity_id IN ({marks}) ORDER BY position", ids):
            listings[r["entity_id"]].append({"market": r["market"], "symbol": r["symbol"]})
        aliases: dict[str, list] = {i: [] for i in ids}
        for r in db.execute(f"SELECT entity_id, alias FROM entity_aliases WHERE entity_id IN ({marks}) ORDER BY position", ids):
            aliases[r["entity_id"]].append(r["alias"])
        recent = dict.fromkeys(ids, 0)
        since = ledger.iso(self.index.clock() - timedelta(days=RECENT_DAYS))
        for r in db.execute(f"SELECT entity_id, count(*) AS n FROM mentions WHERE removed=0 AND created_at>=? "
                            f"AND entity_id IN ({marks}) GROUP BY entity_id", [since, *ids]):
            recent[r["entity_id"]] = r["n"]
        out = []
        for r in rows:
            own = listings[r["id"]]
            company = r["type"] == "company"
            default_benchmark = DEFAULT_BENCHMARK.get(own[0]["market"]) if company and own else None
            out.append({
                "id": r["id"], "type": r["type"], "name": r["name"], "aliases": aliases[r["id"]], "listings": own,
                "primary": own[0]["symbol"] if own else None,
                "benchmark": (r["benchmark"] or default_benchmark) if company else None,
                "benchmark_default": company and not r["benchmark"],
                "industry_index": r["industry_index"] if company else None,
                "recent_mentions": recent[r["id"]],
                "archived": bool(r["archived"]), "created_at": r["created_at"], "updated_at": r["updated_at"],
            })
        return out

    def list(self, kind: str | None = None, include_archived: bool = False) -> dict:
        if kind is not None and kind not in TYPES:
            raise EntityError(tr("類型不對。"), "type")
        with self.index.read() as db:
            db.execute("BEGIN")  # 同一個快照（WAL 下讀交易不擋寫入；連線關掉就結束）
            where, args = [], []
            if not include_archived:
                where.append("archived=0")
            if kind:
                where.append("type=?")
                args.append(kind)
            sql = "SELECT * FROM entities" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY name COLLATE NOCASE, id LIMIT ?"
            rows = db.execute(sql, [*args, MAX_ENTITIES]).fetchall()
            counts = {t: 0 for t in TYPES}
            for r in db.execute("SELECT type, count(*) AS n FROM entities WHERE archived=0 GROUP BY type"):
                counts[r["type"]] = r["n"]
            archived = db.execute("SELECT count(*) FROM entities WHERE archived=1").fetchone()[0]
            return {"entities": self._load(db, rows), "counts": counts, "total": sum(counts.values()), "archived": archived}

    def get(self, entity_id: str) -> dict:
        with self.index.read() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
            if not row:
                raise NotFound(entity_id)
            entity = self._load(db, [row])[0]
            entity["mentions"] = [dict(r) for r in db.execute(
                "SELECT item_id, source, created_at, updated_at FROM mentions WHERE entity_id=? AND removed=0 "
                "ORDER BY created_at DESC, item_id LIMIT ?", (entity_id, MAX_MENTIONS))]
            return entity

    # ---------- 寫 ----------
    def _save_children(self, db, entity_id: str, data: dict):
        db.execute("DELETE FROM entity_listings WHERE entity_id=?", (entity_id,))
        db.execute("DELETE FROM entity_aliases WHERE entity_id=?", (entity_id,))
        for i, (market, symbol) in enumerate(data["listings"]):
            taken = db.execute("SELECT e.name FROM entity_listings l JOIN entities e ON e.id=l.entity_id "
                               "WHERE l.market=? AND l.symbol=?", (market, symbol)).fetchone()
            if taken:
                raise EntityError(tr("代號 {symbol} 已經用在「{name}」。", symbol=symbol, name=taken["name"]), f"listings.{i}.symbol")
            db.execute("INSERT INTO entity_listings VALUES (?,?,?,?)", (entity_id, i, market, symbol))
        for i, alias in enumerate(data["aliases"]):
            db.execute("INSERT INTO entity_aliases VALUES (?,?,?,?)", (entity_id, i, alias, _fold(alias)))

    def create(self, body) -> dict:
        data = validate(body)
        entity_id = "E-" + uuid.uuid4().hex
        with self.index.write() as db:
            if db.execute("SELECT count(*) FROM entities").fetchone()[0] >= MAX_ENTITIES:
                raise EntityError(tr("追蹤對象最多 {n} 個，請先封存或整理。", n=MAX_ENTITIES))
            now = self.index.now()
            db.execute("INSERT INTO entities VALUES (?,?,?,?,?,0,?,?)",
                       (entity_id, data["type"], data["name"], data["benchmark"], data["industry_index"], now, now))
            self._save_children(db, entity_id, data)
        return self.get(entity_id)

    def update(self, entity_id: str, body) -> dict:
        data = validate(body)
        with self.index.write() as db:
            if not db.execute("SELECT 1 FROM entities WHERE id=?", (entity_id,)).fetchone():
                raise NotFound(entity_id)
            db.execute("UPDATE entities SET type=?, name=?, benchmark=?, industry_index=?, updated_at=? WHERE id=?",
                       (data["type"], data["name"], data["benchmark"], data["industry_index"], self.index.now(), entity_id))
            self._save_children(db, entity_id, data)
        return self.get(entity_id)

    def set_archived(self, entity_id: str, archived: bool) -> dict:
        with self.index.write() as db:
            cur = db.execute("UPDATE entities SET archived=?, updated_at=? WHERE id=?", (int(bool(archived)), self.index.now(), entity_id))
            if not cur.rowcount:
                raise NotFound(entity_id)
        return self.get(entity_id)

    def link(self, item_id: str, entity_id: str, source: str = "manual") -> bool:
        """把一則資料連到追蹤對象。手動一定成功；AI 不會蓋掉手動的連結，也不會連回被手動移除的。回傳有沒有連上。"""
        check_item_id(item_id)
        if source not in ("ai", "manual"):
            raise EntityError(tr("連結來源只能是 AI 或手動。"), "source")
        with self.index.write() as db:
            if not db.execute("SELECT 1 FROM entities WHERE id=?", (entity_id,)).fetchone():
                raise NotFound(entity_id)
            now = self.index.now()
            exists = db.execute("SELECT 1 FROM mentions WHERE item_id=? AND entity_id=?", (item_id, entity_id)).fetchone()
            if not exists and db.execute("SELECT count(*) FROM mentions WHERE entity_id=?", (entity_id,)).fetchone()[0] >= MAX_LINKS:
                if source == "ai":
                    return False
                raise EntityError(tr("這個追蹤對象連的資料太多了（最多 {n} 則）。", n=MAX_LINKS), "item_id")
            if source == "manual":
                # created_at 是「連上的時間」：手動移除後再連回來才重算
                db.execute("INSERT INTO mentions VALUES (?,?,'manual',0,?,?) ON CONFLICT (item_id, entity_id) "
                           "DO UPDATE SET source='manual', created_at=CASE WHEN removed=1 THEN excluded.created_at ELSE created_at END, "
                           "removed=0, updated_at=excluded.updated_at", (item_id, entity_id, now, now))
                return True
            cur = db.execute("INSERT INTO mentions VALUES (?,?,'ai',0,?,?) ON CONFLICT (item_id, entity_id) DO NOTHING",
                             (item_id, entity_id, now, now))
            return bool(cur.rowcount)

    def unlink(self, item_id: str, entity_id: str) -> None:
        """手動移除連結：那筆紀錄改成 removed=1，AI 之後不會再連回去。沒連過的資料不留紀錄。"""
        check_item_id(item_id)
        with self.index.write() as db:
            if not db.execute("SELECT 1 FROM entities WHERE id=?", (entity_id,)).fetchone():
                raise NotFound(entity_id)
            db.execute("UPDATE mentions SET source='manual', removed=1, updated_at=? WHERE item_id=? AND entity_id=?",
                       (self.index.now(), item_id, entity_id))


# ---------- HTTP ----------
PREFIX = "/api/entities"
_STORES: dict[Path, Store] = {}
_STORES_LOCK = threading.Lock()


def _store(app, create: bool) -> Store | None:
    path = Path(getattr(app, "ledger_path", None) or ledger.default_path())
    with _STORES_LOCK:
        if path not in _STORES:
            if not create and not path.exists():
                return None  # 唯讀的 GET 不建檔
            _STORES[path] = Store(ledger.shared(path) or ledger.Index(path))
        return _STORES[path]


def _route(path: str) -> list[str] | None:
    if path != PREFIX and not path.startswith(PREFIX + "/"):
        return None
    return [p for p in path[len(PREFIX):].split("/") if p]


def _entity_id(value: str) -> str:
    if not _ENTITY_ID.fullmatch(value):
        raise NotFound(value)
    return value


def api_get(app, path: str, query: dict) -> dict | None:
    """GET /api/entities[?type=&archived=1]、GET /api/entities/<id>。不是這組 API 回 None。"""
    parts = _route(path)
    if parts is None:
        return None
    store = _store(app, create=False)
    if not parts:
        if store is None:
            return {"entities": [], "counts": {t: 0 for t in TYPES}, "total": 0, "archived": 0}
        return store.list(query.get("type") or None, include_archived=query.get("archived") == "1")
    if len(parts) == 1:
        if store is None:
            raise NotFound(parts[0])
        return store.get(_entity_id(parts[0]))
    raise NotFound(path)


def api_post(app, path: str, body) -> dict | None:
    """POST：建立、編輯、封存、手動新增 / 移除連結。不是這組 API 回 None。"""
    parts = _route(path)
    if parts is None:
        return None
    store = _store(app, create=True)
    body = body if isinstance(body, dict) else {}
    if not parts:
        return store.create(body)
    entity_id = _entity_id(parts[0])
    if len(parts) == 1:
        return store.update(entity_id, body)
    if parts[1:] == ["archive"]:
        archived = body.get("archived", True)
        if not isinstance(archived, bool):
            raise EntityError(tr("資料格式不對。"), "archived")
        return store.set_archived(entity_id, archived)
    if parts[1:] == ["mentions"]:
        store.link(body.get("item_id"), entity_id, "manual")
        return store.get(entity_id)
    if len(parts) == 4 and parts[1] == "mentions" and parts[3] == "remove":
        store.unlink(parts[2], entity_id)
        return store.get(entity_id)
    raise NotFound(path)
