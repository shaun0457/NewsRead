"""訂閱額度保護（ticket 68）：背景工作能不能用訂閱、什麼時候暫停或改用 API key，以及每次觸發保護的事件。

決定由 ai_engines.Engines.run 做（其他模組不直接呼叫引擎）；這裡放設定、判斷用的純函式和事件表。

- 條款（ticket 68 的「條款查證」）：Anthropic、OpenAI 都沒有明文允許第三方程式在背景用個人訂閱，
  所以背景工作預設不用任何訂閱 CLI，改用 API key 或本機模型；設定 background_subscription 打開才用訂閱。
- 門檻：Claude Code 回報的 5 小時額度（整個帳號的數字，含使用者自己寫程式用掉的）到 threshold% 時，
  背景工作暫停到重置時間（on_exceed = wait）或改用 API key（on_exceed = api）。手動觸發的照跑，但會提醒。
  額度只在 Claude Code 有回應時才更新，暫停期間不會有新數字：過了重置時間就當作已經重置。
  重置時間不明、或比記下的時間晚超過 WINDOW，最多暫停到「記下的時間 + WINDOW」。
- API 每月上限（台北時間的月份；只算有費用的呼叫，費用不明的不算）：到 WARN_RATIO 記一筆並通知一次，
  到上限記一筆並通知一次。到上限後背景的翻譯和起草停下，分類和論點變化偵測不用 API、改等訂閱額度。
- 事件只記代碼、工作和固定欄位的數字，不存上游原文；表最多 MAX_EVENTS 筆，多的刪最舊的。
- 通知：Telegram（ticket 16）還沒做。set_notifier 換成真的通知；預設什麼都不送。
"""
from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import ledger
from .i18n import tr
from .log import log

THRESHOLD = 70               # 〔預設〕5 小時額度到幾 % 就保護
ON_EXCEED = ("wait", "api")  # 超過門檻時：等重置 / 改用 API key
API_MONTHLY_USD = 15.0       # 〔預設〕API 每月上限（美元）
MAX_API_MONTHLY_USD = 100_000.0
WARN_RATIO = 0.8             # 到上限的這個比例時通知
WINDOW = 5 * 3600.0          # Claude Code 的 5 小時額度：最多暫停這麼久（從記下額度的時間算）
CATCHUP_MAX = 50             # 〔預設〕暫停結束後，每一輪最多補做幾則
BACKGROUND_TASKS = frozenset({"triage", "translate", "draft", "thesis_change"})
STOP_AT_CAP = frozenset({"translate", "draft"})  # API 到上限就停掉；其他背景工作改等訂閱額度
MAX_EVENTS = 1000
MAX_LIST = 200
TAIPEI = timezone(timedelta(hours=8))

EVENT_CODES = ("QUOTA_PAUSED", "QUOTA_SWITCHED_API", "BACKGROUND_NO_API", "API_CAP_WARN", "API_CAP_REACHED",
               "API_CAP_STOPPED", "CATCHUP_DONE", "RATE_LIMITED")
PAUSE_EVENTS = ("QUOTA_PAUSED", "BACKGROUND_NO_API", "API_CAP_STOPPED")  # 這些之後要補做，直到 CATCHUP_DONE
_MONTH = re.compile(r"\d{4}-\d{2}")

SCHEMA = """
-- 額度保護、API 上限的事件（ticket 68）。只記代碼和固定欄位的數字，給用量頁（ticket 29）讀。
CREATE TABLE IF NOT EXISTS ai_guard_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  code TEXT NOT NULL,
  task TEXT NOT NULL,
  key TEXT NOT NULL,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_guard_events_task ON ai_guard_events (task, seq);
"""


def message(code: str) -> str:
    """事件代碼對應的固定說明。"""
    return {
        "QUOTA_PAUSED": tr("Claude Code 5 小時額度超過門檻，背景工作暫停到額度重置。"),
        "QUOTA_SWITCHED_API": tr("Claude Code 5 小時額度超過門檻，背景工作改用 API key。"),
        "BACKGROUND_NO_API": tr("背景工作不用訂閱，也沒有可以用的 API key 或本機模型，先暫停。"),
        "API_CAP_WARN": tr("API 這個月的花費到了上限的 80%。"),
        "API_CAP_REACHED": tr("API 這個月的花費到了上限：背景的起草停下，分類改等訂閱額度。翻譯還沒接上這個上限。"),
        "API_CAP_STOPPED": tr("API 這個月的花費到了上限，這個背景工作先停下。"),
        "CATCHUP_DONE": tr("暫停期間排隊的工作補做完了。"),
        "RATE_LIMITED": tr("AI 引擎回報限流，重試幾次後仍然失敗。"),
    }.get(code, tr("額度保護事件。"))


# ---------- 設定 ----------
def defaults() -> dict:
    return {"background_subscription": False, "threshold": THRESHOLD, "on_exceed": "wait", "api_monthly_usd": API_MONTHLY_USD}


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def valid_threshold(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100


def valid_cap(value) -> bool:
    n = _number(value)
    return n is not None and 0 <= n <= MAX_API_MONTHLY_USD


def clean(raw) -> dict:
    """ai.json 的 guard 一段：手改壞的欄位用預設值。"""
    out = defaults()
    if not isinstance(raw, dict):
        return out
    if isinstance(raw.get("background_subscription"), bool):
        out["background_subscription"] = raw["background_subscription"]
    if valid_threshold(raw.get("threshold")):
        out["threshold"] = raw["threshold"]
    if raw.get("on_exceed") in ON_EXCEED:
        out["on_exceed"] = raw["on_exceed"]
    if valid_cap(raw.get("api_monthly_usd")):
        out["api_monthly_usd"] = round(float(raw["api_monthly_usd"]), 2)
    return out


# ---------- 判斷 ----------
def quota_state(latest, threshold: int, now: float) -> dict:
    """最近一次記下的 Claude Code 額度（usage.latest() 的格式）現在算不算超過門檻。

    used 是 0–1；resets_at 和 at 是 Unix 秒。沒有記下時間（at）的數字無法判斷多舊，當作沒超過。"""
    latest = latest if isinstance(latest, dict) else {}
    limits = latest.get("limits") if isinstance(latest.get("limits"), dict) else {}
    five = limits.get("five_hour") if isinstance(limits.get("five_hour"), dict) else {}
    used, resets, at = _number(five.get("used")), _number(five.get("resets_at")), _number(latest.get("at"))
    until = None
    if used is not None and at is not None:
        cap = at + WINDOW
        until = cap if resets is None else min(resets, cap)
    over = until is not None and until > now and used >= threshold / 100
    return {"used": used, "resets_at": resets, "at": at, "over": over, "until": until if over else None}


def month_start(now: float) -> datetime:
    return datetime.fromtimestamp(now, TAIPEI).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_key(now: float) -> str:
    return month_start(now).strftime("%Y-%m")


def api_spent(db, now: float) -> float:
    """這個月（台北時間）有費用的 AI 呼叫加起來多少美元。訂閱（費用 NULL）和費用不明的不算。"""
    row = db.execute("SELECT COALESCE(SUM(cost_usd), 0) AS s FROM ai_usage WHERE cost_usd IS NOT NULL AND at >= ?",
                     (ledger.iso(month_start(now)),)).fetchone()
    return round(float(row["s"] or 0), 6)


# ---------- 通知（等 ticket 16 的 Telegram 接上） ----------
_notifier: Callable[[dict], None] | None = None
_notifier_lock = threading.Lock()


def set_notifier(fn: Callable[[dict], None] | None) -> None:
    """換成真的通知（ticket 16）。fn 收到 {code, message, data}；None = 不送。"""
    global _notifier
    with _notifier_lock:
        _notifier = fn


def notify(event: dict) -> None:
    with _notifier_lock:
        fn = _notifier
    if fn is None:
        return
    try:
        fn(event)
    except Exception as e:  # noqa: BLE001 通知送不出去不影響 AI 呼叫；只記類型
        log.warning("額度通知送不出去 %s", type(e).__name__)


# ---------- 事件 ----------
def _clean_data(data: dict | None) -> dict:
    """只留固定欄位，數字或月份字串；其他一律丟掉（不會有上游原文）。"""
    out = {}
    for k, v in (data or {}).items():
        if k in ("used", "until", "spent_usd", "cap_usd") and _number(v) is not None:
            out[k] = round(float(v), 4) if k != "until" else int(v)
        elif k in ("threshold", "count") and isinstance(v, int) and not isinstance(v, bool):
            out[k] = v
        elif k == "month" and isinstance(v, str) and _MONTH.fullmatch(v):
            out[k] = v
    return out


# 每個時段記一筆的事件（once=True）：找「這個工作最近一筆」時跳過，不打斷其他事件的去重
QUIET_CODES = ("RATE_LIMITED",)


class Events:
    def __init__(self, index: ledger.Index):
        self.index = index
        with index.read() as db:
            db.executescript(SCHEMA)

    def add(self, code: str, task: str = "", data: dict | None = None, key: str = "", once: bool = False) -> dict | None:
        """記一筆。once：同代碼、同工作、同 key 記過就不再記（每月一次的通知）；
        否則這個工作最近一筆（不算 QUIET_CODES）是同代碼、同 key 就不再記（暫停期間每一輪都會碰到，不重複記）。
        回傳記下的事件或 None。"""
        if code not in EVENT_CODES:
            raise ValueError(f"unknown guard event {code!r}")
        clean = _clean_data(data)
        with self.index.write() as db:
            if once:
                dup = db.execute("SELECT 1 FROM ai_guard_events WHERE code=? AND task=? AND key=? LIMIT 1",
                                 (code, task, key)).fetchone()
            else:
                last = db.execute(f"SELECT code, key FROM ai_guard_events WHERE task=? AND code NOT IN "
                                  f"({','.join('?' * len(QUIET_CODES))}) ORDER BY seq DESC LIMIT 1",
                                  (task, *QUIET_CODES)).fetchone()
                dup = last is not None and last["code"] == code and last["key"] == key
            if dup:
                return None
            at = self.index.now()
            cur = db.execute("INSERT INTO ai_guard_events (at, code, task, key, data) VALUES (?,?,?,?,?)",
                             (at, code, task, key, ledger.canonical(clean)))
            db.execute("DELETE FROM ai_guard_events WHERE seq <= ?", (cur.lastrowid - MAX_EVENTS,))
        log.info("額度保護事件 code=%s task=%s", code, task or "-")
        return {"seq": cur.lastrowid, "at": at, "code": code, "task": task, "message": message(code), "data": clean}

    def catchup_open(self, task: str) -> bool:
        """這個工作最近一次暫停之後還沒補做完。"""
        marks = PAUSE_EVENTS + ("CATCHUP_DONE",)
        with self.index.read() as db:
            row = db.execute(f"SELECT code FROM ai_guard_events WHERE task=? AND code IN ({','.join('?' * len(marks))}) "
                             "ORDER BY seq DESC LIMIT 1", (task, *marks)).fetchone()
        return bool(row) and row["code"] in PAUSE_EVENTS

    def list(self, limit: int = MAX_LIST) -> list[dict]:
        """新的在前，最多 MAX_LIST 筆。"""
        limit = max(1, min(int(limit), MAX_LIST))
        with self.index.read() as db:
            rows = db.execute("SELECT seq, at, code, task, data FROM ai_guard_events ORDER BY seq DESC LIMIT ?",
                              (limit,)).fetchall()
        out = []
        for r in rows:
            try:
                data = json.loads(r["data"])
            except (ValueError, RecursionError):
                data = {}
            out.append({"seq": r["seq"], "at": r["at"], "code": r["code"], "task": r["task"], "message": message(r["code"]),
                        "data": _clean_data(data if isinstance(data, dict) else {})})
        return out
