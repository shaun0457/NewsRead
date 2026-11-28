"""今日新聞（ticket 15）：今天（台北時間）的資料，依重要度和追蹤對象列出。

- 重要度顯示它對各論點最高的一級（沒有論點時才看各追蹤對象，見規格「雜訊是相對的」），取自 AI 分類結果（triage.py）；
  列表上的理由取自同一個判斷。每則另外附相對於每個論點 / 追蹤對象的判斷，畫面點開可以看。
- 這頁顯示的是 AI 的看法，所以是 POST（要 X-Token，別的網站觸發不了）。讀取全部做完之後，用一個交易替每則實際回給畫面、
  而且有分類結果的資料寫揭露紀錄（地點 = today），寫完才回傳；寫不進去就整個請求失敗，不回任何 AI 的看法。
  被篩掉或超過上限沒回的資料不寫。
- 哪一天：發布時間（時間不明就用匯入時間，跟分類一樣）換成台北時間的日期。
- 上限：一次最多掃 MAX_SCAN 則待分類 / 已分類的資料（超過回 truncated）、最多回 MAX_LIMIT 則。
- 今天有待分類的資料、而分類因為只有關不掉工具的 CLI（Codex、Antigravity）跑不了時，回 triage_block 說明（ticket 104）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from . import ai_engines, entities, ledger, textitem, triage
from .entities import EntityError
from .i18n import tr
from .store import DataReadError

log = logging.getLogger(__name__)

PREFIX = "/api/today"
LEVELS = ("high", "mid", "none", "low", "noise")  # 顯示順序；none = 還沒有重要度（待分類、失敗、或沒有相關對象）
DEFAULT_LEVELS = ("high", "mid", "none")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_SCAN = 1000          # 一次最多讀幾則資料（依分類狀態更新時間，新的在前）
SCAN_DAYS = 2            # 只看這麼多天內有動靜的：今天發布的資料不會比這更早排進分類
CHUNK = 400              # SQL 一次放幾個參數
MAX_FACETS = 200         # 追蹤對象篩選最多列幾個
MAX_BODY = 1024          # POST body 上限（bytes）
TZ = triage.TAIPEI
_RANK = {level: i for i, level in enumerate(LEVELS)}


def handles(path: str) -> bool:
    return path == PREFIX


def _levels(raw) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_LEVELS
    parts = str(raw).split(",")
    if len(parts) > len(LEVELS) or any(p not in LEVELS for p in parts) or len(set(parts)) != len(parts):
        raise EntityError(tr("重要度不對。"), "importance")
    return tuple(parts)


def _limit(raw) -> int:
    if raw is None:
        return DEFAULT_LIMIT
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise EntityError(tr("數量不對。"), "limit") from None
    if n < 1:
        raise EntityError(tr("數量不對。"), "limit")
    return min(n, MAX_LIMIT)


def _entity(raw) -> str | None:
    if not raw:
        return None
    if not isinstance(raw, str) or not entities._ENTITY_ID.fullmatch(raw):
        raise EntityError(tr("追蹤對象不對。"), "entity")
    return raw


def _chunks(values: list, size: int = CHUNK):
    for i in range(0, len(values), size):
        yield values[i:i + size]


_JUDGE_KEYS = ("id", "relation", "importance", "noise_kind", "confidence", "reason")


def _judgments(raw, extra: tuple[str, ...] = ()) -> list[dict]:
    """分類結果裡的判斷：只留格式對的（triage 寫入前驗過，這裡再擋一次舊資料或壞資料，不讓一則壞資料讓整頁失敗）。"""
    out = []
    for j in raw if isinstance(raw, list) else []:
        if isinstance(j, dict) and isinstance(j.get("id"), str) and j.get("importance") in triage.IMPORTANCE:
            row = {k: j.get(k) for k in (*_JUDGE_KEYS, *extra)} | {"name": j.get("name")}
            if "theme_id" in row and not isinstance(row["theme_id"], str):
                row["theme_id"] = None
            out.append(row)
    return out


def _clean(body: dict) -> dict:
    return {"entities": _judgments(body.get("entities")), "theses": _judgments(body.get("theses"), ("grade", "theme_id")),
            "retrospective": bool(body.get("retrospective"))}


def _pool(result: dict) -> list[tuple[str, dict]]:
    """決定重要度的那組判斷：有論點只看論點，沒有論點才看追蹤對象（規格：對各論點最高的那一級）。"""
    return [("thesis", t) for t in result["theses"]] or [("entity", e) for e in result["entities"]]


def _linked(result: dict) -> set[str]:
    """這則資料連到哪些追蹤對象 / 題材：不是「無關」的追蹤對象，加上不是「無關」的論點所屬的題材。"""
    out = {e["id"] for e in result["entities"] if e.get("noise_kind") != "unrelated"}
    out |= {t["theme_id"] for t in result["theses"] if t.get("theme_id") and t.get("noise_kind") != "unrelated"}
    return out


def _empty(date: str, levels, limit: int) -> dict:
    return {"date": date, "tz": "Asia/Taipei", "levels": list(levels), "limit": limit, "items": [], "total": 0, "more": False,
            "truncated": False, "counts": {level: 0 for level in LEVELS}, "entities": [], "pending": 0, "triage_block": None}


def _triage_block(app, engine) -> dict | None:
    """分類為什麼停著（ai_engines.Engines.triage_block）。AI 設定讀不到時不讓今日新聞失敗，當作沒有說明；log 只記類型。"""
    try:
        return (engine or ai_engines.for_app(app, create_index=False)).triage_block()
    except Exception as e:  # noqa: BLE001
        log.warning("今日新聞讀不到分類引擎的狀態 %s", type(e).__name__)
        return None


def _scan(s, lib, today, now) -> tuple[list[dict], bool]:
    """今天的資料（只有 ID、標題、時間等，還沒有 AI 的看法），和有沒有因為上限沒掃完。"""
    start = (now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=SCAN_DAYS)).astimezone(timezone.utc)
    with s.index.read() as db:
        rows = db.execute("SELECT item_id, state FROM triage_state WHERE updated_at>=? ORDER BY updated_at DESC, item_id LIMIT ?",
                          (ledger.iso(start), MAX_SCAN + 1)).fetchall()
    truncated = len(rows) > MAX_SCAN
    out = []
    for row in rows[:MAX_SCAN]:
        try:
            found = _item(lib, row["item_id"], today)
        except (DataReadError, OSError) as e:  # 一則讀不出來就跳過這則；log 只記 ID 和錯誤類型（原文可能帶本機路徑）
            log.warning("今日新聞略過讀不出來的資料 %s %s", row["item_id"], type(e).__name__)
            continue
        if found:
            out.append(found | {"id": row["item_id"], "state": row["state"]})
    return out, truncated


def _item(lib, item_id: str, today) -> dict | None:
    ws = lib.ws(item_id) if lib is not None else None
    if ws is None:
        return None
    meta = (ws.load("paper") or {}).get("meta") or {}
    if not textitem.is_text(meta):
        return None
    item = ws.load("item") or {}
    published = meta.get("published_at") or ""
    known = meta.get("time_source", "unknown") != "unknown" and bool(published)  # 哪一天跟分類一樣看原始 meta，不看使用者改的
    try:
        at = ledger.parse_time(published if known else (item.get("added") or ""))
    except ValueError:
        return None
    if at.astimezone(TZ).date() != today:
        return None
    shown = dict(meta)
    override = item.get("meta_override")
    if isinstance(override, dict):  # 標題、來源顯示使用者改過的（跟資料庫列表一樣）
        shown.update({k: v for k, v in override.items() if v})
    return {"at": at, "time_known": known, "title": str(shown.get("title_en") or shown.get("title_zh") or item_id),
            "publisher": str(shown.get("publisher") or ""), "published_at": published if known else "",
            "url": meta.get("source_url") or "", "preview_only": bool(meta.get("preview_only"))}


def _results(s, ids: list[str]) -> dict[str, dict]:
    out = {}
    with s.index.read() as db:
        for part in _chunks(ids):
            marks = ",".join("?" * len(part))
            for r in db.execute(f"SELECT item_id, content_hash, body FROM triage_results WHERE seq IN "
                                f"(SELECT MAX(seq) FROM triage_results WHERE item_id IN ({marks}) GROUP BY item_id)", part):
                try:
                    body = json.loads(r["body"])
                except (ValueError, RecursionError):
                    body = None
                if not isinstance(body, dict):  # 壞掉的結果當成沒有分類結果，不讓整頁失敗
                    log.warning("今日新聞略過讀不出來的分類結果 %s", r["item_id"])
                    continue
                out[r["item_id"]] = _clean(body) | {"_hash": r["content_hash"]}
            for r in db.execute(f"SELECT item_id, content_hash FROM triage_state WHERE item_id IN ({marks})", part):
                if r["item_id"] in out:
                    out[r["item_id"]]["_state_hash"] = r["content_hash"]
    return out


def _names(s, ids: set[str]) -> dict[str, dict]:
    out = {}
    with s.index.read() as db:
        for part in _chunks(sorted(ids)):
            marks = ",".join("?" * len(part))
            for r in db.execute(f"SELECT id, name, type FROM entities WHERE id IN ({marks})", part):
                out[r["id"]] = {"name": r["name"], "type": r["type"]}
    return out


def _claims(s, ids: set[str]) -> dict[str, str]:
    out = {}
    with s.index.read() as db:
        for part in _chunks(sorted(ids)):
            marks = ",".join("?" * len(part))
            for r in db.execute(f"SELECT thesis_id, body FROM thesis_versions WHERE status='final' AND thesis_id IN ({marks}) "
                                f"ORDER BY version", part):
                try:
                    body = json.loads(r["body"])
                except (ValueError, RecursionError):
                    continue
                if isinstance(body, dict):
                    out[r["thesis_id"]] = str(body.get("claim") or "")
    return out


def _top(result: dict) -> dict | None:
    """最高那一級的判斷（同 _pool）：重要度標籤和列表上的理由都用它，兩者不會對不上。"""
    best = None
    for kind, r in _pool(result):
        if best is None or triage.IMPORTANCE.index(r["importance"]) < triage.IMPORTANCE.index(best[1]["importance"]):
            best = (kind, r)
    if best is None:
        return None
    kind, r = best
    return {"kind": kind, "id": r["id"], "relation": r["relation"], "importance": r["importance"],
            "confidence": r["confidence"], "reason": r["reason"]}


def build(app, query: dict, engine=None) -> dict:
    """{"importance": "high,mid,none", "entity": "<id>", "limit": 50} → 今天的資料。輸入不對丟 EntityError，資料庫出錯丟 sqlite3.Error。
    engine：測試用的 ai_engines.Engines；沒給就用伺服器共用的。"""
    levels, limit, entity = _levels(query.get("importance")), _limit(query.get("limit")), _entity(query.get("entity"))
    s = triage.store(app, create=False)
    if s is None:  # 資料庫還沒建：空狀態，不建檔
        return _empty(_today_of(datetime.now(timezone.utc)), levels, limit)
    now = s.index.clock()
    today = now.astimezone(TZ).date()
    found, truncated = _scan(s, getattr(app, "lib", None), today, now)
    results = _results(s, [i["id"] for i in found])
    for item in found:
        result = results.get(item["id"])
        item["result"] = result
        item["top"] = _top(result) if result else None
        item["importance"] = item["top"]["importance"] if item["top"] else "none"
        item["linked"] = _linked(result) if result else set()

    # 篩選的數量：重要度的數量看已選的追蹤對象，追蹤對象的數量看已選的重要度
    counts = {level: 0 for level in LEVELS}
    facets: dict[str, int] = {}
    for item in found:
        if entity is None or entity in item["linked"]:
            counts[item["importance"]] += 1
        if item["importance"] in levels:
            for e in item["linked"]:
                facets[e] = facets.get(e, 0) + 1
    names = _names(s, set(facets))
    ents = sorted(({"id": i, "name": names[i]["name"], "type": names[i]["type"], "count": n} for i, n in facets.items() if i in names),
                  key=lambda e: (-e["count"], e["name"], e["id"]))[:MAX_FACETS]

    matching = [i for i in found if i["importance"] in levels and (entity is None or entity in i["linked"])]
    matching.sort(key=lambda i: (_RANK[i["importance"]], -i["at"].timestamp(), i["id"]))
    shown = matching[:limit]

    thesis_ids = {t["id"] for i in shown if i["result"] for t in i["result"]["theses"]}
    theme_ids = {t["theme_id"] for i in shown if i["result"] for t in i["result"]["theses"] if t.get("theme_id")}
    claims = _claims(s, thesis_ids)
    detail_names = _names(s, theme_ids | {e["id"] for i in shown if i["result"] for e in i["result"]["entities"]})
    items = []
    for item in shown:
        result = item["result"]
        row = {k: item[k] for k in ("id", "title", "publisher", "published_at", "time_known", "url", "preview_only", "state", "importance")}
        row["at"] = ledger.iso(item["at"])
        row["reader_url"] = f"/read/{item['id']}"
        row.update(stale=False, top=None, entities=[], theses=[], retrospective=False)
        if result:
            row["stale"] = result.get("_state_hash") not in (None, result.get("_hash"))
            row["retrospective"] = result["retrospective"]
            row["top"] = item["top"]
            row["entities"] = [{**{k: e[k] for k in _JUDGE_KEYS}, "name": detail_names.get(e["id"], {}).get("name") or e.get("name") or ""}
                               for e in result["entities"]]
            row["theses"] = [{**{k: t[k] for k in (*_JUDGE_KEYS, "grade", "theme_id")},
                              "claim": claims.get(t["id"], ""), "theme_name": detail_names.get(t.get("theme_id"), {}).get("name") or ""}
                             for t in result["theses"]]
        items.append(row)
    # 待分類的數量不看篩選；有待分類的才去問分類為什麼停著（要讀 AI 設定和偵測結果）
    pending = sum(1 for i in found if i["state"] == "pending")
    block = _triage_block(app, engine) if pending else None
    # 讀取都做完了才寫揭露紀錄（一個交易），寫完直接回傳：寫失敗就整個請求失敗，不會留下「記了但沒顯示」的紀錄
    s.index.record_exposures([i["id"] for i in shown if i["result"]], "today")
    return {"date": today.isoformat(), "tz": "Asia/Taipei", "levels": list(levels), "limit": limit, "items": items,
            "total": len(matching), "more": len(matching) > len(shown), "truncated": truncated, "counts": counts, "entities": ents,
            "pending": pending, "triage_block": block}


def _today_of(now) -> str:
    return now.astimezone(TZ).date().isoformat()


def api_post(app, path: str, data) -> dict | None:
    if not handles(path):
        return None
    if not isinstance(data, dict):
        raise EntityError(tr("資料格式不對。"), "body")
    return build(app, data)
