"""題材與論點（ticket 57）：題材頁、論點、因果鏈環節、證據，以及論點狀態的帳本紀錄。

- 題材是 theme 類型的追蹤對象（entities）。題材頁和論點的內容都存成版本，每個版本標 draft（草稿）或 final（定稿）；
  版本只能新增，草稿不會蓋掉定稿：畫面看的定稿是最新一版 final，草稿是比它新的最新一版 draft。
- AI 只能寫草稿，而且要指向 ContextManifest；同時在帳本記一筆 draft 紀錄（跟版本在同一個交易裡）。
- 因果鏈環節放在題材頁的版本裡。沒有出處的環節是「AI 推論」（inferred），不能進定稿，除非我手動確認（confirmed）；
  沒有出處的營收占比一律是 unknown。營收占比和 role 只在環節連到公司時才有。
- 證據（Evidence）只能新增：一則 Item 或 Story 對一個論點的關係、等級、理由、出處、by（ai / me）。
- 論點狀態（open / strengthening / weakening / refuted / retired）的變化都是帳本的 thesis_status 紀錄：
  AI 寫的是「提議」，不改狀態；我確認（who = me）才生效。加強、削弱、推翻一定要指向這個論點的證據，
  而且方向要對得上（加強要有 strengthens 的證據，削弱、推翻要有 weakens 的證據）。
- 不洩漏還沒判斷的新資料：題材頁列出的證據、證據等級和「缺第一手確認」只用「看得到的」證據算：
  我加的、已經揭露過（exposures）、我判斷過（帳本裡 who = me 的 judgment），或被我確認的狀態變化引用過的。
- 所有讀取都可以帶時間點 at，回答「那時候的題材頁和論點長什麼樣」（給打分和 golden set 用）。
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path

from . import entities, ledger
from .entities import EntityError, NotFound
from .i18n import tr

STATUSES = ("open", "strengthening", "weakening", "refuted", "retired")
NEEDS_EVIDENCE = {"strengthening": "strengthens", "weakening": "weakens", "refuted": "weakens"}  # 狀態 → 證據要有的關係
RELATIONS = ("strengthens", "weakens", "related_no_change")
GRADES = ("A", "B", "C", "D")   # A 公司公告、財報、法說會、官方數據 / B 具名媒體 / C KOL、分析師 / D 未證實
FIRST_HAND = ("A", "B")         # 只有 C、D 級證據 = 缺第一手確認
ORIGINS = ("market_first", "news_first")
TIMINGS = ("now", "roadmap")
DIRECTIONS = ("bull", "bear")
ROLES = ("leader", "laggard", "unknown")
VERSION_STATUSES = ("draft", "final")
ME = "me"

MAX_BODY = 256 * 1024     # 一次寫入的請求大小
# 下面三個是永久上限：版本、論點、證據都只能新增，到了上限就寫不進去（退休的論點也算）。
MAX_VERSIONS = 500        # 一個題材頁或論點最多幾個版本
MAX_THESES = 50           # 一個題材最多幾個論點
MAX_EVIDENCE = 2000       # 一個論點最多幾則證據
MAX_LIST_EVIDENCE = 50    # 題材頁每個論點最多列幾則證據（A、B 優先，再依時間由新到舊）
MAX_STORY_ITEMS = 200     # 判斷 Story 證據看不看得到時，每個 Story 最多看幾則成員
CHUNK = 500               # IN 清單每批幾個
MAX_PROPOSALS = 50        # 每個論點最多列幾筆待確認的提議
MAX_LINKS = 100           # 因果鏈最多幾環
MAX_SECOND_ORDER = 20
MAX_TARGETS = 20
MAX_CITED = 50            # 一次狀態變化最多引用幾則證據
MAX_SHORT = 60            # 環節名稱、階段名稱、horizon
MAX_LINE = 300            # 一句話故事、論點、賺什麼錢、第二層效應每一點
MAX_TEXT = 1000           # 類比、推翻條件、下車條件、理由
MAX_URL = 500
_THEME = re.compile(r"E-[0-9a-f]{32}")
_THESIS = re.compile(r"T-[0-9a-f]{32}")
_EVIDENCE = re.compile(r"EV-[0-9a-f]{32}")
_RECORD = re.compile(r"L-[0-9a-f]{32}")
_STORY = re.compile(r"S-[0-9a-f]{32}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS theme_versions (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  theme_id TEXT NOT NULL REFERENCES entities(id),
  version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft', 'final')),
  by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  body TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  context_manifest TEXT REFERENCES context_manifests(id),
  UNIQUE (theme_id, version)
);
CREATE TABLE IF NOT EXISTS theses (
  id TEXT PRIMARY KEY,
  theme_id TEXT NOT NULL REFERENCES entities(id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS theses_by_theme ON theses (theme_id, created_at);
CREATE TABLE IF NOT EXISTS thesis_versions (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  thesis_id TEXT NOT NULL REFERENCES theses(id),
  version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft', 'final')),
  by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  body TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  context_manifest TEXT REFERENCES context_manifests(id),
  UNIQUE (thesis_id, version)
);
CREATE TABLE IF NOT EXISTS evidence (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  thesis_id TEXT NOT NULL REFERENCES theses(id),
  item_id TEXT,
  story_id TEXT,
  relation TEXT NOT NULL CHECK (relation IN ('strengthens', 'weakens', 'related_no_change')),
  grade TEXT NOT NULL CHECK (grade IN ('A', 'B', 'C', 'D')),
  reason TEXT NOT NULL,
  source TEXT,
  by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  context_manifest TEXT REFERENCES context_manifests(id),
  CHECK ((item_id IS NULL) != (story_id IS NULL))
);
CREATE INDEX IF NOT EXISTS evidence_by_thesis ON evidence (thesis_id, seq);
CREATE INDEX IF NOT EXISTS ledger_thesis_status ON ledger (kind, json_extract(payload, '$.thesis_id'), who, seq);
CREATE INDEX IF NOT EXISTS ledger_judgment_item ON ledger (kind, who, json_extract(payload, '$.item'));
CREATE INDEX IF NOT EXISTS item_story_by_story ON item_story (story_id);
"""
APPEND_ONLY = ("theme_versions", "theses", "thesis_versions", "evidence")


def _guards() -> str:
    return "\n".join(f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                     f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;"
                     for t in APPEND_ONLY for op in ("UPDATE", "DELETE"))


# ---------- 輸入檢查 ----------
def _bad(field: str, message: str | None = None):
    return EntityError(message or tr("資料格式不對。"), field)


def _text(value, field: str, limit: int, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise _bad(field, tr("這一欄要填。"))
        return None
    if not isinstance(value, str):
        raise _bad(field, tr("這個欄位要是文字。"))
    value = value.strip()
    if required and not value:
        raise _bad(field, tr("這一欄要填。"))
    if len(value) > limit:
        raise _bad(field, tr("最多 {n} 個字。", n=limit))
    return value or None


def _choice(value, field: str, options, required: bool = True, default=None):
    if value is None and not required:
        return default
    if value not in options:
        raise _bad(field)
    return value


def _list(value, field: str, limit: int) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _bad(field)
    if len(value) > limit:
        raise _bad(field, tr("最多 {n} 項。", n=limit))
    return value


def _item_id(value, field: str) -> str:
    try:
        return entities.check_item_id(value)
    except EntityError:
        raise _bad(field) from None


def _source(value, field: str) -> dict | None:
    """出處：一則資料（item_id）或一個網址。沒有就是 None。"""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict) or len(value) != 1:
        raise _bad(field)
    if "item_id" in value:
        return {"item_id": _item_id(value["item_id"], field)}
    url = _text(value.get("url"), field, MAX_URL, required=True)
    if not url.startswith(("https://", "http://")) or any(c.isspace() for c in url):
        raise _bad(field, tr("出處要是 http 或 https 網址。"))
    return {"url": url}


def is_ai(by: str) -> bool:
    return ledger.is_ai(by)


def _check_by(by) -> str:
    if by == ME or (isinstance(by, str) and is_ai(by) and len(by) <= 200):
        return by
    raise _bad("by")


class _Ctx:
    """驗證時要查資料庫（追蹤對象存不存在、是不是公司）。"""

    def __init__(self, db):
        self.db = db
        self.types: dict[str, str | None] = {}

    def entity_type(self, entity_id) -> str | None:
        if not isinstance(entity_id, str) or not _THEME.fullmatch(entity_id):
            return None
        if entity_id not in self.types:
            row = self.db.execute("SELECT type FROM entities WHERE id=?", (entity_id,)).fetchone()
            self.types[entity_id] = row["type"] if row else None
        return self.types[entity_id]


def _node(value, field: str, ctx: _Ctx) -> dict:
    """因果鏈的節點：追蹤對象（entity_id）或自由文字的環節名稱（label，例如「CoWoS 產能」）。"""
    if not isinstance(value, dict) or len(value) != 1:
        raise _bad(field)
    if "entity_id" in value:
        if not ctx.entity_type(value["entity_id"]):
            raise _bad(field, tr("找不到這個追蹤對象。"))
        return {"entity_id": value["entity_id"]}
    return {"label": _text(value.get("label"), field, MAX_SHORT, required=True)}


def _share(value, field: str) -> dict | str:
    """營收占比：{value 或 range, source}；沒有出處一律 unknown（AI 不能估）。"""
    if value in (None, "unknown"):
        return "unknown"
    if not isinstance(value, dict):
        raise _bad(field)
    source = _source(value.get("source"), field + ".source")
    if not source:
        return "unknown"

    def pct(x, f):
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 100:
            raise _bad(f, tr("營收占比要是 0 到 100 的數字。"))
        return x
    if "range" in value:
        rng = value["range"]
        if not isinstance(rng, list) or len(rng) != 2:
            raise _bad(field + ".range")
        lo, hi = pct(rng[0], field + ".range"), pct(rng[1], field + ".range")
        if lo > hi:
            raise _bad(field + ".range")
        return {"range": [lo, hi], "source": source}
    return {"value": pct(value.get("value"), field + ".value"), "source": source}


def _link(value, i: int, ctx: _Ctx, by: str, final: bool) -> dict:
    field = f"chain.{i}"
    if not isinstance(value, dict):
        raise _bad(field)
    to = _node(value.get("to"), field + ".to", ctx)
    out = {"from": _node(value.get("from"), field + ".from", ctx), "to": to,
           "relation": _text(value.get("relation"), field + ".relation", MAX_LINE, required=True),
           "source": _source(value.get("source"), field + ".source")}
    if ctx.entity_type(to.get("entity_id")) == "company":
        out["revenue_share"] = _share(value.get("revenue_share"), field + ".revenue_share")
        out["role"] = _choice(value.get("role"), field + ".role", ROLES, required=False, default="unknown")
    elif value.get("revenue_share") not in (None, "unknown") or value.get("role") not in (None, "unknown"):
        raise _bad(field, tr("營收占比和領漲 / 補漲只在連到公司時填。"))
    out["inferred"] = out["source"] is None  # 畫面上顯示成虛線、標「AI 推論」
    confirmed = value.get("confirmed", False)
    if not isinstance(confirmed, bool):
        raise _bad(field + ".confirmed")
    out["confirmed"] = bool(confirmed and out["inferred"] and by == ME)  # 只有我能確認沒有出處的環節
    if final and out["inferred"] and not out["confirmed"]:
        raise _bad(field, tr("沒有出處的環節（AI 推論）要先確認，才能放進定稿。"))
    return out


def theme_body(value, ctx: _Ctx, by: str, final: bool) -> dict:
    if not isinstance(value, dict):
        raise _bad("body")
    origin = value.get("origin")
    if origin is not None:
        if not isinstance(origin, dict):
            raise _bad("origin")
        origin = {"kind": _choice(origin.get("kind"), "origin.kind", ORIGINS),
                  "item_id": _item_id(origin["item_id"], "origin.item_id") if origin.get("item_id") else None,
                  "rotation_event": _text(origin.get("rotation_event"), "origin.rotation_event", MAX_LINE)}
    stage = value.get("stage")
    if stage is not None:
        if not isinstance(stage, dict):
            raise _bad("stage")
        stage = {"name": _text(stage.get("name"), "stage.name", MAX_SHORT, required=True),
                 "basis": _text(stage.get("basis"), "stage.basis", MAX_TEXT)}
    return {
        "one_liner": _text(value.get("one_liner"), "one_liner", MAX_LINE, required=final),
        "analogy": _text(value.get("analogy"), "analogy", MAX_TEXT),
        "origin": origin,
        "second_order": [_text(x, f"second_order.{i}", MAX_LINE, required=True)
                         for i, x in enumerate(_list(value.get("second_order"), "second_order", MAX_SECOND_ORDER))],
        "stage": stage,
        "chain": [_link(x, i, ctx, by, final) for i, x in enumerate(_list(value.get("chain"), "chain", MAX_LINKS))],
    }


def thesis_body(value, ctx: _Ctx, final: bool) -> dict:
    if not isinstance(value, dict):
        raise _bad("body")
    direction = value.get("direction_implication")
    if direction is None and not final:
        implication = None
    else:
        if not isinstance(direction, dict):
            raise _bad("direction_implication")
        targets = _list(direction.get("targets"), "direction_implication.targets", MAX_TARGETS)
        for i, t in enumerate(targets):
            if not ctx.entity_type(t):
                raise _bad(f"direction_implication.targets.{i}", tr("找不到這個追蹤對象。"))
        if final and not targets:
            raise _bad("direction_implication.targets", tr("這一欄要填。"))
        implication = {"direction": _choice(direction.get("direction"), "direction_implication.direction", DIRECTIONS),
                       "targets": list(dict.fromkeys(targets))}
    return {
        "claim": _text(value.get("claim"), "claim", MAX_LINE, required=True),  # 一句可以被推翻的說法
        "direction_implication": implication,
        "timing": _choice(value.get("timing"), "timing", TIMINGS, required=final),
        "edge": _text(value.get("edge"), "edge", MAX_LINE, required=final),  # 賺什麼錢
        "horizon": _text(value.get("horizon"), "horizon", MAX_SHORT, required=final),
        "refute_if": _text(value.get("refute_if"), "refute_if", MAX_TEXT, required=final),
        "exit_if": _text(value.get("exit_if"), "exit_if", MAX_TEXT),  # 交易下車條件（價格），可選
    }


def _at(value) -> str | None:
    if value in (None, ""):
        return None
    try:
        return ledger.iso(ledger.parse_time(value, "at"))
    except ValueError:
        raise _bad("at", tr("時間格式不對。")) from None


class Store:
    """題材與論點的讀寫。共用帳本的 Index（同一個 SQLite 檔）。"""

    def __init__(self, index: ledger.Index):
        self.index = index
        entities.Store(index)  # 追蹤對象的表要先在
        with index.read() as db:
            db.executescript(SCHEMA + _guards())

    # ---------- 寫：版本 ----------
    def _theme(self, db, theme_id: str) -> None:
        row = db.execute("SELECT type FROM entities WHERE id=?", (theme_id,)).fetchone() if _THEME.fullmatch(theme_id or "") else None
        if not row:
            raise NotFound(theme_id)
        if row["type"] != "theme":
            raise _bad("theme_id", tr("只有題材類型的追蹤對象才有題材頁。"))

    def _thesis_theme(self, db, thesis_id: str) -> str:
        row = db.execute("SELECT theme_id FROM theses WHERE id=?", (thesis_id,)).fetchone() if _THESIS.fullmatch(thesis_id or "") else None
        if not row:
            raise NotFound(thesis_id)
        return row["theme_id"]

    def _add_version(self, db, table: str, key: str, owner: str, status: str, body: dict, by: str,
                     manifest: str | None, target: str) -> dict:
        if is_ai(by):
            if status != "draft":
                raise _bad("status", tr("AI 只能寫草稿。"))
            if not manifest:
                raise _bad("context_manifest")
        elif manifest:
            raise _bad("context_manifest")
        if manifest:
            self._check_manifest(db, by, manifest)
        last = db.execute(f"SELECT max(version) AS v, count(*) AS n FROM {table} WHERE {key}=?", (owner,)).fetchone()
        if last["n"] >= MAX_VERSIONS:
            raise _bad("status", tr("版本最多 {n} 個。", n=MAX_VERSIONS))
        text = ledger.canonical(body)
        row = {"id": ("TV-" if table == "theme_versions" else "PV-") + uuid.uuid4().hex, "owner": owner,
               "version": (last["v"] or 0) + 1, "status": status, "by": by, "created_at": self.index.now(),
               "body": text, "content_hash": ledger.sha256(text), "context_manifest": manifest}
        db.execute(f"INSERT INTO {table} (id, {key}, version, status, by, created_at, body, content_hash, context_manifest) "
                   "VALUES (:id,:owner,:version,:status,:by,:created_at,:body,:content_hash,:context_manifest)", row)
        if is_ai(by):  # AI 草稿也是帳本紀錄，指向當時送進去的 context（同一個交易）
            self.index.append_in(db, "draft", by, {"target": target, "of": owner, "version_id": row["id"],
                                                    "version": row["version"], "content_hash": row["content_hash"]},
                                 context_manifest=manifest)
        return row

    def _check_manifest(self, db, by: str, manifest) -> None:
        """跟帳本同一套規則：manifest 要存在、時間不晚於現在、prompt 版本跟 by 一致。"""
        if not isinstance(manifest, str):
            raise _bad("context_manifest")
        try:
            ledger.check_manifest(db, by, manifest, self.index.now())
        except ValueError:
            raise _bad("context_manifest", tr("ContextManifest 不對。")) from None

    def add_theme_version(self, theme_id: str, status: str, body, by: str = ME, context_manifest: str | None = None) -> dict:
        status = _choice(status, "status", VERSION_STATUSES)
        by = _check_by(by)
        with self.index.write() as db:
            self._theme(db, theme_id)
            clean = theme_body(body, _Ctx(db), by, status == "final")
            row = self._add_version(db, "theme_versions", "theme_id", theme_id, status, clean, by, context_manifest, "theme")
        return {"id": row["id"], "version": row["version"]}

    def add_thesis(self, theme_id: str, status: str, body, by: str = ME, context_manifest: str | None = None) -> dict:
        status = _choice(status, "status", VERSION_STATUSES)
        by = _check_by(by)
        with self.index.write() as db:
            self._theme(db, theme_id)
            if db.execute("SELECT count(*) FROM theses WHERE theme_id=?", (theme_id,)).fetchone()[0] >= MAX_THESES:
                raise _bad("theme_id", tr("一個題材最多 {n} 個論點。", n=MAX_THESES))
            clean = thesis_body(body, _Ctx(db), status == "final")
            thesis_id = "T-" + uuid.uuid4().hex
            db.execute("INSERT INTO theses VALUES (?,?,?)", (thesis_id, theme_id, self.index.now()))
            row = self._add_version(db, "thesis_versions", "thesis_id", thesis_id, status, clean, by, context_manifest, "thesis")
        return {"id": thesis_id, "version": row["version"]}

    def add_thesis_version(self, thesis_id: str, status: str, body, by: str = ME, context_manifest: str | None = None) -> dict:
        status = _choice(status, "status", VERSION_STATUSES)
        by = _check_by(by)
        with self.index.write() as db:
            self._thesis_theme(db, thesis_id)
            clean = thesis_body(body, _Ctx(db), status == "final")
            row = self._add_version(db, "thesis_versions", "thesis_id", thesis_id, status, clean, by, context_manifest, "thesis")
        return {"id": row["id"], "version": row["version"]}

    # ---------- 寫：證據 ----------
    def add_evidence(self, thesis_id: str, body, by: str = ME, context_manifest: str | None = None) -> dict:
        fields = self._evidence_fields(body, by, context_manifest)
        with self.index.write() as db:
            return self._insert_evidence(db, thesis_id, fields)

    def add_evidence_in(self, db, thesis_id: str, body, by: str, context_manifest: str | None = None) -> dict:
        """同 add_evidence，寫在呼叫端已經開好的寫入交易裡（AI 分類的證據跟帳本判斷一起寫）。"""
        if not db.in_transaction:
            raise RuntimeError("add_evidence_in must run inside Index.write()")
        return self._insert_evidence(db, thesis_id, self._evidence_fields(body, by, context_manifest))

    def _evidence_fields(self, body, by: str, context_manifest) -> dict:
        if not isinstance(body, dict):
            raise _bad("body")
        by = _check_by(by)
        item = _item_id(body["item_id"], "item_id") if body.get("item_id") is not None else None
        story = body.get("story_id")
        if story is not None and (not isinstance(story, str) or not _STORY.fullmatch(story)):
            raise _bad("story_id")
        if (item is None) == (story is None):
            raise _bad("item_id", tr("證據要指向一則資料或一個 Story。"))
        relation = _choice(body.get("relation"), "relation", RELATIONS)
        grade = _choice(body.get("grade"), "grade", GRADES)
        reason = _text(body.get("reason"), "reason", MAX_TEXT, required=True)
        source = _source(body.get("source"), "source")
        if is_ai(by) != bool(context_manifest):
            raise _bad("context_manifest")
        return {"item": item, "story": story, "relation": relation, "grade": grade, "reason": reason, "source": source,
                "by": by, "manifest": context_manifest}

    def _insert_evidence(self, db, thesis_id: str, f: dict) -> dict:
        self._thesis_theme(db, thesis_id)
        if f["story"] and not db.execute("SELECT 1 FROM stories WHERE id=?", (f["story"],)).fetchone():
            raise _bad("story_id", tr("找不到這個 Story。"))
        if f["manifest"]:
            self._check_manifest(db, f["by"], f["manifest"])
        if db.execute("SELECT count(*) FROM evidence WHERE thesis_id=?", (thesis_id,)).fetchone()[0] >= MAX_EVIDENCE:
            raise _bad("thesis_id", tr("一個論點最多 {n} 則證據。", n=MAX_EVIDENCE))
        evidence_id = "EV-" + uuid.uuid4().hex
        db.execute("INSERT INTO evidence (id, thesis_id, item_id, story_id, relation, grade, reason, source, by, created_at, "
                   "context_manifest) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (evidence_id, thesis_id, f["item"], f["story"], f["relation"], f["grade"], f["reason"],
                    ledger.canonical(f["source"]) if f["source"] else None, f["by"], self.index.now(), f["manifest"]))
        return {"id": evidence_id}

    def final_theses(self, db, limit: int) -> list[dict]:
        """每個論點最新的定稿版本（沒有定稿的不列；退休的不列）。給 AI 分類當 context：草稿不送，免得 AI 的草稿自我強化。"""
        rows = db.execute(
            "SELECT t.id, t.theme_id, v.version, v.content_hash, v.body, e.name AS theme_name FROM theses t "
            "JOIN thesis_versions v ON v.thesis_id = t.id JOIN entities e ON e.id = t.theme_id "
            "WHERE v.status = 'final' AND v.version = (SELECT max(w.version) FROM thesis_versions w "
            "WHERE w.thesis_id = t.id AND w.status = 'final') ORDER BY t.created_at, t.id")  # 游標逐筆讀，到 limit 就停
        out = []
        for r in rows:
            if len(out) >= limit:
                break
            if self._status(db, r["id"])[0] == "retired":
                continue
            out.append({"id": r["id"], "theme_id": r["theme_id"], "theme_name": r["theme_name"], "version": r["version"],
                        "hash": r["content_hash"], "body": json.loads(r["body"])})
        return out

    # ---------- 寫：論點狀態 ----------
    def _status(self, db, thesis_id: str, at: str | None = None) -> tuple[str, dict | None]:
        """目前（或 at 那時）的狀態：只看我確認過的變化。"""
        sql = ("SELECT * FROM ledger WHERE kind='thesis_status' AND json_extract(payload, '$.thesis_id')=? AND who=? "
               "AND json_extract(payload, '$.to') IS NOT NULL")
        args: list = [thesis_id, ME]
        if at:
            sql += " AND recorded_at<=?"
            args.append(at)
        row = db.execute(sql + " ORDER BY seq DESC LIMIT 1", args).fetchone()
        if not row:
            return "open", None
        record = ledger._public(dict(row))
        return record["payload"]["to"], record

    def _cited(self, db, thesis_id: str, to: str, cited, field: str = "evidence") -> list[str]:
        raw = _list(cited, field, MAX_CITED)
        if any(not isinstance(e, str) or not _EVIDENCE.fullmatch(e) for e in raw):
            raise _bad(field)
        ids = list(dict.fromkeys(raw))
        rows = {r["id"]: r["relation"] for r in db.execute(
            f"SELECT id, relation FROM evidence WHERE thesis_id=? AND id IN ({','.join('?' * len(ids))})", [thesis_id, *ids])} if ids else {}
        if len(rows) != len(ids):
            raise _bad(field, tr("引用的證據不屬於這個論點。"))
        need = NEEDS_EVIDENCE.get(to)
        if need and need not in rows.values():
            raise _bad(field, tr("這個狀態變化要指向至少一則方向相符的證據。"))
        return ids

    def propose_status(self, thesis_id: str, to: str, evidence, reason: str, by: str, context_manifest: str) -> dict:
        """AI 提議論點狀態變化：寫進帳本，但不改狀態。"""
        if not is_ai(_check_by(by)):
            raise _bad("by")
        to = _choice(to, "to", STATUSES)
        reason = _text(reason, "reason", MAX_TEXT, required=True)
        with self.index.write() as db:
            self._thesis_theme(db, thesis_id)
            ids = self._cited(db, thesis_id, to, evidence)
            current, _ = self._status(db, thesis_id)
            if to == current:
                raise _bad("to", tr("論點已經是這個狀態。"))
            self._check_manifest(db, by, context_manifest)
            return self.index.append_in(db, "thesis_status", by, {"thesis_id": thesis_id, "proposal": True, "from": current,
                                                                   "to": to, "evidence": ids, "reason": reason},
                                        context_manifest=context_manifest)

    def _proposal(self, db, thesis_id: str, proposal_id) -> dict:
        if not isinstance(proposal_id, str) or not _RECORD.fullmatch(proposal_id):
            raise _bad("confirms")
        row = db.execute("SELECT * FROM ledger WHERE id=? AND kind='thesis_status'", (proposal_id,)).fetchone()
        record = ledger._public(dict(row)) if row else None
        if not record or record["payload"].get("thesis_id") != thesis_id or not record["payload"].get("proposal"):
            raise _bad("confirms", tr("找不到這筆提議。"))
        if db.execute("SELECT 1 FROM ledger WHERE kind='thesis_status' AND who=? AND "
                      "(json_extract(payload, '$.confirms')=? OR json_extract(payload, '$.rejects')=?)",
                      (ME, proposal_id, proposal_id)).fetchone():
            raise _bad("confirms", tr("這筆提議已經處理過了。"))
        return record

    def set_status(self, thesis_id: str, to: str, evidence=None, reason: str | None = None, confirms: str | None = None) -> dict:
        """我改論點狀態（或確認 AI 的提議）。加強、削弱、推翻要指向方向相符的證據。"""
        to = _choice(to, "to", STATUSES)
        reason = _text(reason, "reason", MAX_TEXT)
        if confirms is not None and not isinstance(confirms, str):
            raise _bad("confirms")
        confirms = confirms or None
        with self.index.write() as db:
            self._thesis_theme(db, thesis_id)
            if confirms:
                proposal = self._proposal(db, thesis_id, confirms)
                if proposal["payload"]["to"] != to:
                    raise _bad("to", tr("確認的狀態要跟提議一樣。"))
                evidence = evidence if evidence is not None else proposal["payload"]["evidence"]
                reason = reason or proposal["payload"].get("reason")
            if not reason and to not in NEEDS_EVIDENCE:  # 退休、重新打開：寫為什麼
                raise _bad("reason", tr("這一欄要填。"))
            ids = self._cited(db, thesis_id, to, evidence)
            current, _ = self._status(db, thesis_id)
            if to == current:
                raise _bad("to", tr("論點已經是這個狀態。"))
            return self.index.append_in(db, "thesis_status", ME, {"thesis_id": thesis_id, "from": current, "to": to,
                                                                   "evidence": ids, "reason": reason, "confirms": confirms})

    def reject_proposal(self, thesis_id: str, proposal_id: str, reason: str | None = None) -> dict:
        with self.index.write() as db:
            self._thesis_theme(db, thesis_id)
            self._proposal(db, thesis_id, proposal_id)
            return self.index.append_in(db, "thesis_status", ME, {"thesis_id": thesis_id, "rejects": proposal_id,
                                                                   "reason": _text(reason, "reason", MAX_TEXT)})

    # ---------- 讀 ----------
    @staticmethod
    def _versions(db, table: str, key: str, owner: str, at: str | None) -> tuple[dict | None, dict | None]:
        """(定稿, 草稿)：定稿是 at 之前最新的 final；草稿是比它新的最新 draft（沒有就是 None）。"""
        cond, args = f"{key}=?", [owner]
        if at:
            cond += " AND created_at<=?"
            args.append(at)
        final = db.execute(f"SELECT * FROM {table} WHERE {cond} AND status='final' ORDER BY version DESC LIMIT 1", args).fetchone()
        draft = db.execute(f"SELECT * FROM {table} WHERE {cond} AND status='draft' AND version>? ORDER BY version DESC LIMIT 1",
                           [*args, final["version"] if final else 0]).fetchone()

        def show(row):
            if not row:
                return None
            return {"id": row["id"], "version": row["version"], "status": row["status"], "by": row["by"],
                    "created_at": row["created_at"], "content_hash": row["content_hash"],
                    "context_manifest": row["context_manifest"], "body": json.loads(row["body"])}
        return show(final), show(draft)

    @staticmethod
    def _matching(db, sql: str, values, args_before: list, args_after: list) -> set:
        """sql 裡的 {marks} 換成 IN 清單，分批查（每批 CHUNK 個），回傳第一欄的值。"""
        found: set = set()
        values = list(values)
        for i in range(0, len(values), CHUNK):
            part = values[i:i + CHUNK]
            found.update(r[0] for r in db.execute(sql.format(marks=",".join("?" * len(part))), [*args_before, *part, *args_after]))
        return found

    def _seen_items(self, db, items: set, at: str | None) -> set:
        """這些資料裡揭露過或我判斷過的（at 之前）。兩個查詢都走索引（exposures_item、ledger_judgment_item）。"""
        when, when_args = (" AND {col}<=?", [at]) if at else ("", [])
        exposed = self._matching(db, "SELECT DISTINCT item_id FROM exposures WHERE item_id IN ({marks})" + when.format(col="at"),
                                 items, [], when_args)
        judged = self._matching(db, "SELECT DISTINCT json_extract(payload, '$.item') FROM ledger WHERE kind='judgment' AND who=? "
                                "AND json_extract(payload, '$.item') IN ({marks})" + when.format(col="recorded_at"),
                                items - exposed, [ME], when_args)
        return exposed | judged

    def _evidence(self, db, thesis_id: str, at: str | None) -> tuple[list[dict], bool, dict]:
        """(看得到的證據 [最多 MAX_LIST_EVIDENCE 則], 缺第一手確認, {證據 id: 看不到時要揭露的資料 id}）。

        看得到 = 我加的、揭露過、我判斷過，或被我確認的狀態變化引用過；Story 的證據：Story 裡任何一則看得到就算。
        每個論點固定幾個查詢（IN 清單分批），不對每則證據跑子查詢。Story 的成員用現在的歸屬（目前還沒有合併 Story）。"""
        sql = "SELECT * FROM evidence WHERE thesis_id=?" + (" AND created_at<=?" if at else "") + " ORDER BY seq LIMIT ?"
        rows = db.execute(sql, [thesis_id, *([at] if at else []), MAX_EVIDENCE]).fetchall()
        cited_sql = ("SELECT c.value FROM ledger s, json_each(s.payload, '$.evidence') c WHERE s.kind='thesis_status' AND s.who=? "
                     "AND json_extract(s.payload, '$.thesis_id')=?" + (" AND s.recorded_at<=?" if at else ""))
        cited = {r[0] for r in db.execute(cited_sql, [ME, thesis_id, *([at] if at else [])])}
        pending = [r for r in rows if r["by"] != ME and r["id"] not in cited]
        stories = sorted({r["story_id"] for r in pending if r["story_id"]})
        members: dict[str, set] = {s: set() for s in stories}
        for i in range(0, len(stories), CHUNK):  # 每個 Story 最多看 MAX_STORY_ITEMS 則（item_story_by_story 索引）
            part = stories[i:i + CHUNK]
            for story, item in db.execute(
                    "SELECT story_id, item_id FROM (SELECT story_id, item_id, row_number() OVER (PARTITION BY story_id ORDER BY item_id) AS n "
                    f"FROM item_story WHERE story_id IN ({','.join('?' * len(part))})) WHERE n<=?", [*part, MAX_STORY_ITEMS]):
                members[story].add(item)
        seen = self._seen_items(db, {r["item_id"] for r in pending if r["item_id"]} | set().union(*members.values()), at)
        hidden: dict[str, list] = {}
        for r in pending:
            items = {r["item_id"]} if r["item_id"] else members.get(r["story_id"], set())
            if not items & seen:
                hidden[r["id"]] = sorted(items)[:MAX_STORY_ITEMS]
        visible = [r for r in rows if r["id"] not in hidden]
        visible.sort(key=lambda r: (r["grade"] in FIRST_HAND, r["created_at"], r["seq"]), reverse=True)  # A、B 優先，再由新到舊
        grades = {r["grade"] for r in visible}
        out = [{"id": r["id"], "item_id": r["item_id"], "story_id": r["story_id"], "relation": r["relation"], "grade": r["grade"],
                "reason": r["reason"], "source": json.loads(r["source"]) if r["source"] else None, "by": r["by"],
                "created_at": r["created_at"]} for r in visible[:MAX_LIST_EVIDENCE]]
        return out, bool(grades) and not grades & set(FIRST_HAND), hidden  # 只有 C、D 級：缺第一手確認

    def _proposals(self, db, thesis_id: str, at: str | None) -> list[dict]:
        sql = ("SELECT p.* FROM ledger p WHERE p.kind='thesis_status' AND json_extract(p.payload, '$.thesis_id')=? "
               "AND json_extract(p.payload, '$.proposal')=1 AND NOT EXISTS (SELECT 1 FROM ledger d WHERE d.kind='thesis_status' "
               "AND d.who=? AND (json_extract(d.payload, '$.confirms')=p.id OR json_extract(d.payload, '$.rejects')=p.id)"
               + (" AND d.recorded_at<=?" if at else "") + ")")
        args: list = [thesis_id, ME] + ([at] if at else [])
        if at:
            sql += " AND p.recorded_at<=?"
            args.append(at)
        rows = db.execute(sql + " ORDER BY p.seq DESC LIMIT ?", [*args, MAX_PROPOSALS]).fetchall()
        return [{k: v for k, v in ledger._public(dict(r)).items() if k in ("id", "who", "recorded_at", "payload", "context_manifest")}
                for r in rows]

    def page(self, theme_id: str, at: str | None = None) -> dict:
        """題材頁：定稿和草稿、論點（各自的定稿和草稿、狀態、看得到的證據、待確認的提議）。at 是時間點（預設現在）。"""
        at = _at(at)
        with self.index.read() as db:
            db.execute("BEGIN")  # 同一個快照
            self._theme(db, theme_id)
            final, draft = self._versions(db, "theme_versions", "theme_id", theme_id, at)
            theses = []
            sql = "SELECT id, created_at FROM theses WHERE theme_id=?" + (" AND created_at<=?" if at else "") + " ORDER BY created_at, id LIMIT ?"
            for t in db.execute(sql, [theme_id, *([at] if at else []), MAX_THESES]).fetchall():
                t_final, t_draft = self._versions(db, "thesis_versions", "thesis_id", t["id"], at)
                status, record = self._status(db, t["id"], at)
                evidence, missing, hidden = self._evidence(db, t["id"], at)
                proposals = self._proposals(db, t["id"], at)
                for p in proposals:  # 顯示這筆提議 = 揭露 AI 對這些資料的看法：畫面要先替它們寫揭露紀錄（地點 theme）
                    p["exposes"] = sorted({i for e in p["payload"].get("evidence", []) for i in hidden.get(e, [])})
                theses.append({"id": t["id"], "created_at": t["created_at"], "final": t_final, "draft": t_draft,
                               "status": status, "status_record": record["id"] if record else None,
                               "missing_first_hand": missing, "evidence": evidence, "proposals": proposals})
            return {"theme_id": theme_id, "at": at, "final": final, "draft": draft, "theses": theses}

    def history(self, thesis_id: str, limit: int = 200) -> list[dict]:
        """論點狀態的帳本紀錄（提議、確認、駁回），由舊到新。"""
        with self.index.read() as db:
            self._thesis_theme(db, thesis_id)
            rows = db.execute("SELECT * FROM ledger WHERE kind='thesis_status' AND json_extract(payload, '$.thesis_id')=? "
                              "ORDER BY seq LIMIT ?", (thesis_id, max(1, min(int(limit), ledger.MAX_LIST)))).fetchall()
        return [ledger._public(dict(r)) for r in rows]


# ---------- HTTP ----------
THEMES = "/api/themes"
THESES = "/api/theses"
_STORES: dict[Path, Store] = {}
_STORES_LOCK = threading.Lock()


def handles(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in (THEMES, THESES))


def _store(app, create: bool) -> Store | None:
    path = Path(getattr(app, "ledger_path", None) or ledger.default_path())
    with _STORES_LOCK:
        if path not in _STORES:
            if not create and not path.exists():
                return None
            _STORES[path] = Store(ledger.shared(path, create=True))
        return _STORES[path]


def _parts(path: str, prefix: str) -> list[str]:
    return [p for p in path[len(prefix):].split("/") if p]


def api_get(app, path: str, query: dict) -> dict | None:
    """GET /api/themes/<題材 id>[?at=]：題材頁。GET /api/theses/<論點 id>/history：狀態紀錄。"""
    if not handles(path):
        return None
    store = _store(app, create=False)
    if store is None:
        raise NotFound(path)
    if path.startswith(THEMES):
        parts = _parts(path, THEMES)
        if len(parts) == 1:
            return store.page(parts[0], query.get("at"))
    else:
        parts = _parts(path, THESES)
        if len(parts) == 2 and parts[1] == "history":
            return {"records": store.history(parts[0])}
    raise NotFound(path)


def api_post(app, path: str, body) -> dict | None:
    """寫入都是「我」（who = me）；AI 的草稿、證據、提議走 Python 介面，帶 ContextManifest。回傳更新後的題材頁。"""
    if not handles(path):
        return None
    store = _store(app, create=True)
    body = body if isinstance(body, dict) else {}
    if path.startswith(THEMES):
        parts = _parts(path, THEMES)
        if len(parts) == 2 and parts[1] == "versions":
            store.add_theme_version(parts[0], body.get("status"), body.get("body"))
            return store.page(parts[0])
        if len(parts) == 2 and parts[1] == "theses":
            store.add_thesis(parts[0], body.get("status"), body.get("body"))
            return store.page(parts[0])
        raise NotFound(path)
    parts = _parts(path, THESES)
    if not parts:
        raise NotFound(path)
    thesis_id = parts[0]
    if parts[1:] == ["versions"]:
        store.add_thesis_version(thesis_id, body.get("status"), body.get("body"))
    elif parts[1:] == ["evidence"]:
        store.add_evidence(thesis_id, body)
    elif parts[1:] == ["status"]:
        store.set_status(thesis_id, body.get("to"), body.get("evidence"), body.get("reason"), body.get("confirms"))
    elif len(parts) == 4 and parts[1] == "proposals" and parts[3] == "reject":
        store.reject_proposal(thesis_id, parts[2], body.get("reason"))
    else:
        raise NotFound(path)
    with store.index.read() as db:
        theme_id = store._thesis_theme(db, thesis_id)
    return store.page(theme_id)
