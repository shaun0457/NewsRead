"""用量頁（ticket 29）的唯讀報表：GET /api/usage。

資料來自 ai_usage（每次 AI 呼叫一筆）、Claude Code 最近一次回報的額度（usage.latest）、triage_results 和 evidence。
只讀：帳本檔還沒建就回空的，不建檔、不寫任何東西。日期和月份都用台北時間。

- token = 輸入 + 輸出（cached 是輸入的一部分，不重複算）。
- 訂閱不折算成金額：cost_usd 是 NULL 的呼叫，花費欄位就是 None；只有 API 有費用。
- 「來源」是 ai_usage.source：呼叫 AI 的程式入口（分類是 triage，翻譯和閱讀器問 AI 是 newsread）。
  ai_usage 還沒有記是哪一則資料、哪個媒體，所以不能依媒體分；等來源（RSS 等，ticket 19）接上再補。
  資料數和「掛到論點的比例」只有分類（triage）算得出來：分類過的資料中，有幾則有證據（evidence）掛在論點上。
- 每個清單都有上限：工作 MAX_TASKS 列、來源 MAX_SOURCES 列、每日 DAILY_DAYS 天、Claude 額度視窗 WINDOW_5H 秒。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from . import ai_engines, ledger, quota_guard
from .log import log

PREFIX = "/api/usage"
PERIODS = ("month", "day")
DAILY_DAYS = 14
MAX_TASKS = 50
MAX_SOURCES = 50
WINDOW_5H = 5 * 3600.0
TOKENS = "SUM(input_tokens + output_tokens)"
# 引擎名稱的白名單：openai 相容服務的 id 不外露；不認得的引擎一律叫 other
ENGINES = ("claude", "codex", "antigravity", "anthropic", "openai", "ollama")
LIMIT_KEYS = ("five_hour", "seven_day")
# 先在 SQL 裡把引擎名稱歸成白名單再分組：多個 openai 相容服務（openai:<id>）合成一列 openai
_BASE = "CASE WHEN instr(engine, ':') > 0 THEN substr(engine, 1, instr(engine, ':') - 1) ELSE engine END"
ENGINE_SQL = f"CASE WHEN ({_BASE}) IN ({', '.join(chr(39) + e + chr(39) for e in ENGINES)}) THEN ({_BASE}) ELSE 'other' END"


def handles(path: str) -> bool:
    return path == PREFIX


def _num(value) -> float | None:
    """有限的數字才收（NaN、inf 會讓回應不是合法 JSON）。"""
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return float(value) if ok else None


def _limits(latest) -> dict:
    """Claude Code 回報的額度：只留 five_hour / seven_day 的 used 和 resets_at，和記下的時間。"""
    latest = latest if isinstance(latest, dict) else {}
    raw = latest.get("limits") if isinstance(latest.get("limits"), dict) else {}
    out = {}
    for key in LIMIT_KEYS:
        w = raw.get(key) if isinstance(raw.get(key), dict) else None
        if w is not None:
            out[key] = {"used": _num(w.get("used")), "resets_at": _num(w.get("resets_at"))}
    return {"limits": out, "at": _num(latest.get("at"))}


def _tables(db) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _empty(period: str, label: str, now: float) -> dict:
    return {"period": period, "label": label, "now": int(now), "empty": True,
            "claude": {"limits": {}, "at": None, "window": {"calls": 0, "tokens": 0}},
            "cli": {e: {"calls": 0, "tokens": 0} for e in ("codex", "antigravity")},
            "api": {"month": label[:7], "spent_usd": 0.0, "by_engine": []},
            "tasks": [], "tasks_truncated": False, "sources": [], "sources_truncated": False,
            "daily": [], "daily_days": DAILY_DAYS}


def build(app, period: str = "month") -> dict:
    """GET /api/usage?period=month|day 的回應。"""
    if period not in PERIODS:
        raise ai_engines.InputError("bad period", "period")
    eng = ai_engines.for_app(app, create_index=False)
    now = float(eng.now())
    today = datetime.fromtimestamp(now, ai_engines.TAIPEI).replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    start = month if period == "month" else today
    label = month.strftime("%Y-%m") if period == "month" else today.strftime("%Y-%m-%d")
    try:
        quota = _limits(eng.quota())
    except Exception as e:  # noqa: BLE001 額度檔壞了或被鎖住：當作沒有額度資料；log 只記類型
        log.warning("Claude Code 額度讀不到 %s", type(e).__name__)
        quota = _limits(None)
    if eng.index is None:
        out = _empty(period, label, now)
        out["claude"].update(quota)
        return out
    since, month_iso = ledger.iso(start), ledger.iso(month)
    first_day = today - timedelta(days=DAILY_DAYS - 1)
    with eng.index.read() as db:
        used = db.execute("SELECT 1 FROM ai_usage LIMIT 1").fetchone() is not None  # 不數整張表
        out = _empty(period, label, now)
        out["empty"] = not used
        out["claude"].update(quota)
        if not used:
            return out
        # 工作 × 引擎 × 模型：多取一列，看有沒有超過上限
        rows = db.execute(f"SELECT task, {ENGINE_SQL} AS eng, model, COUNT(*) AS calls, {TOKENS} AS tokens, SUM(cost_usd) AS cost "
                          "FROM ai_usage WHERE at >= ? GROUP BY task, eng, model ORDER BY tokens DESC, calls DESC LIMIT ?",
                          (since, MAX_TASKS + 1)).fetchall()
        out["tasks_truncated"] = len(rows) > MAX_TASKS
        out["tasks"] = [{"task": r["task"], "engine": r["eng"], "model": r["model"], "calls": r["calls"],
                         "tokens": int(r["tokens"] or 0), "cost_usd": None if r["cost"] is None else round(float(r["cost"]), 6)}
                        for r in rows[:MAX_TASKS]]
        # 各引擎（這段期間）：只回報 token 的 CLI 各一格
        for r in db.execute(f"SELECT engine, COUNT(*) AS calls, {TOKENS} AS tokens FROM ai_usage WHERE at >= ? "
                            "AND engine IN ('codex', 'antigravity') GROUP BY engine", (since,)):
            out["cli"][r["engine"]] = {"calls": r["calls"], "tokens": int(r["tokens"] or 0)}
        w = db.execute(f"SELECT COUNT(*) AS calls, {TOKENS} AS tokens FROM ai_usage WHERE engine = 'claude' AND at >= ?",
                       (ledger.iso(datetime.fromtimestamp(now - WINDOW_5H, ai_engines.TAIPEI)),)).fetchone()
        out["claude"]["window"] = {"calls": w["calls"], "tokens": int(w["tokens"] or 0)}
        # API 本月花費（只算有費用的呼叫；跟額度保護算的是同一個數字）
        out["api"] = {"month": month.strftime("%Y-%m"), "spent_usd": quota_guard.api_spent(db, now),
                      # 歸併後最多 len(ENGINES) + 1 種，不用另外設上限
                      "by_engine": [{"engine": r["eng"], "spent_usd": round(float(r["cost"]), 6)}
                                    for r in db.execute(f"SELECT {ENGINE_SQL} AS eng, SUM(cost_usd) AS cost FROM ai_usage "
                                                        "WHERE cost_usd IS NOT NULL AND at >= ? GROUP BY eng ORDER BY cost DESC",
                                                        (month_iso,))]}
        # 每天的 token（最近 DAILY_DAYS 天，沒有呼叫的日子補 0）
        by_day = {r["d"]: int(r["tokens"] or 0) for r in db.execute(
            f"SELECT date(at, '+8 hours') AS d, {TOKENS} AS tokens FROM ai_usage WHERE at >= ? GROUP BY d LIMIT ?",
            (ledger.iso(first_day), DAILY_DAYS + 2))}
        days = [first_day + timedelta(days=i) for i in range(DAILY_DAYS)]
        out["daily"] = [{"date": d.strftime("%Y-%m-%d"), "tokens": by_day.get(d.strftime("%Y-%m-%d"), 0)} for d in days]
        # 來源
        src = db.execute(f"SELECT source, COUNT(*) AS calls, {TOKENS} AS tokens FROM ai_usage WHERE at >= ? GROUP BY source "
                         "ORDER BY tokens DESC, calls DESC LIMIT ?", (since, MAX_SOURCES + 1)).fetchall()
        out["sources_truncated"] = len(src) > MAX_SOURCES
        out["sources"] = [{"source": r["source"], "calls": r["calls"], "tokens": int(r["tokens"] or 0), "items": None, "linked": None}
                          for r in src[:MAX_SOURCES]]
        triage = next((s for s in out["sources"] if s["source"] == "triage"), None)
        if triage and {"triage_results", "evidence"} <= _tables(db):
            # evidence 沒有 item_id 的索引：用不相關的子查詢（SQLite 只算一次），不要每一列掃一次 evidence
            r = db.execute("SELECT COUNT(DISTINCT item_id) AS items, COUNT(DISTINCT CASE WHEN item_id IN "
                           "(SELECT item_id FROM evidence WHERE item_id IS NOT NULL) THEN item_id END) AS linked "
                           "FROM triage_results WHERE created_at >= ?", (since,)).fetchone()
            triage["items"], triage["linked"] = r["items"], r["linked"]
    return out
