"""Ticket 29：用量頁的報表（GET /api/usage）。時鐘固定、資料是虛構的範例，不呼叫真的 CLI。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from easyread import ai_engines as ai
from easyread import ledger, narratives, quota_guard, triage, usage_report
from tests.test_ai_engines import AiApiCase, FakeAdapter
from tests.test_quota_guard import GuardBase

TAIPEI = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=TAIPEI)  # 台北時間 2026-11-15 12:00（週日）


def at(days=0, hours=0):
    """距離 NOW 多久以前的時間（UTC，跟帳本一樣）。"""
    return (NOW - timedelta(days=days, hours=hours)).astimezone(timezone.utc)


class ReportCase(AiApiCase):
    def make_app(self):
        app = super().make_app()
        self.limits = None
        app["ai_options"]["now"] = lambda: NOW.timestamp()
        app["ai_options"]["quota"] = lambda: self.limits
        return app

    def put(self, when, task="triage", engine="claude", model="claude-haiku-5-5", source="triage", inp=100, out=50, cost=None):
        """在指定時間記一筆用量（直接用帳本寫，時鐘撥到那個時間）。"""
        index = ledger.Index(self.db, clock=lambda: when)
        index.record_usage(source=source, task=task, engine=engine, model=model, input_tokens=inp, cached_tokens=0,
                           output_tokens=out, cost_usd=cost)

    def report(self, period="month"):
        status, data = self.get("/api/usage?period=" + period)
        self.assertEqual(status, 200, data)
        return data


class EmptyAndErrorTest(ReportCase):
    def test_missing_ledger_gives_an_empty_report_and_creates_nothing(self):
        data = self.report()
        self.assertTrue(data["empty"])
        self.assertEqual((data["tasks"], data["sources"], data["daily"]), ([], [], []))
        self.assertEqual(data["api"]["spent_usd"], 0.0)
        self.assertFalse(self.db.exists())  # 唯讀的 GET 不建檔

    def test_quota_is_shown_even_before_any_call_is_recorded(self):
        self.limits = {"limits": {"five_hour": {"used": 0.42, "resets_at": NOW.timestamp() + 3600}}, "at": NOW.timestamp() - 60}
        data = self.report()
        self.assertEqual(data["claude"]["limits"]["five_hour"], {"used": 0.42, "resets_at": NOW.timestamp() + 3600})
        self.assertEqual(data["claude"]["at"], NOW.timestamp() - 60)

    def test_empty_database_is_reported_as_empty(self):
        ledger.Index(self.db)
        data = self.report()
        self.assertTrue(data["empty"])

    def test_bad_period_is_a_400_with_the_field(self):
        status, data = self.get("/api/usage?period=year")
        self.assertEqual((status, data["field"]), (400, "period"))
        self.assertEqual(self.get("/api/usage?period=MONTH")[0], 400)  # 大小寫不同也不收
        self.assertEqual(self.get("/api/usage")[0], 200)  # 沒給 = 每月

    def test_the_page_is_served(self):
        status, html = self.get("/usage")
        self.assertEqual(status, 200)
        self.assertIn("/web/js/usage/app.js", html)

    def test_garbled_quota_file_does_not_fail_the_page(self):
        self.limits = {"limits": {"five_hour": {"used": "x", "resets_at": None}, "seven_day": "bad", "other": {"used": 1}}, "at": "x"}
        data = self.report()
        self.assertEqual(data["claude"]["limits"], {"five_hour": {"used": None, "resets_at": None}})
        self.assertIsNone(data["claude"]["at"])
        # 1e999 讀進來是 inf：不能讓回應變成不合法的 JSON（Infinity）
        self.limits = {"limits": {"five_hour": {"used": float("inf"), "resets_at": float("-inf")}}, "at": float("nan")}
        data = self.report()
        self.assertEqual(data["claude"]["limits"], {"five_hour": {"used": None, "resets_at": None}})
        self.assertIsNone(data["claude"]["at"])


class TotalsTest(ReportCase):
    def setUp(self):
        super().setUp()
        self.put(at(hours=1), task="triage", inp=1000, out=200)                                 # 今天、5 小時內
        self.put(at(hours=2), task="triage", inp=500, out=100)
        self.put(at(hours=8), task="translate", engine="codex", model="", source="newsread", inp=4000, out=1000)  # 今天、5 小時外
        self.put(at(days=3), task="draft", model="claude-opus-5-1", source="newsread", inp=3000, out=700)        # 本月、不是今天
        self.put(at(days=3), task="thesis_change", engine="anthropic", model="claude-sonnet-5-5", source="newsread",
                 inp=2000, out=300, cost=2.5)
        self.put(at(days=2), task="ask", engine="openai:o1a2b3c4d5e6", model="gpt-x", source="newsread", inp=100, out=10, cost=0.5)
        self.put(at(days=20), task="triage", inp=9000, out=1000)                                 # 上個月

    def test_month_groups_by_task_engine_and_model(self):
        data = self.report("month")
        self.assertFalse(data["empty"])
        self.assertEqual((data["period"], data["label"]), ("month", "2026-11"))
        tasks = {(t["task"], t["engine"], t["model"]): t for t in data["tasks"]}
        self.assertEqual(tasks[("triage", "claude", "claude-haiku-5-5")]["calls"], 2)
        self.assertEqual(tasks[("triage", "claude", "claude-haiku-5-5")]["tokens"], 1800)  # 輸入 + 輸出
        self.assertIsNone(tasks[("triage", "claude", "claude-haiku-5-5")]["cost_usd"])     # 訂閱不折算成金額
        self.assertEqual(tasks[("thesis_change", "anthropic", "claude-sonnet-5-5")]["cost_usd"], 2.5)
        self.assertEqual(len(data["tasks"]), 5)  # 上個月那筆不算
        self.assertEqual([t["tokens"] for t in data["tasks"]], sorted((t["tokens"] for t in data["tasks"]), reverse=True))

    def test_openai_compatible_entry_id_is_not_exposed(self):
        data = self.report("month")
        self.assertIn(("ask", "openai"), {(t["task"], t["engine"]) for t in data["tasks"]})
        self.assertNotIn("o1a2b3c4d5e6", json.dumps(data))
        self.assertEqual({e["engine"] for e in data["api"]["by_engine"]}, {"anthropic", "openai"})

    def test_several_openai_compatible_services_are_one_row(self):
        self.put(at(days=1), task="ask", engine="openai:zz9988776655", model="gpt-x", source="newsread", inp=100, out=10, cost=0.25)
        self.put(at(days=1), task="ask", engine="mystery:abc", model="m", source="newsread", inp=1, out=1)
        data = self.report("month")
        asks = [t for t in data["tasks"] if (t["task"], t["engine"], t["model"]) == ("ask", "openai", "gpt-x")]
        self.assertEqual(len(asks), 1)
        self.assertEqual((asks[0]["calls"], asks[0]["cost_usd"]), (2, 0.75))
        self.assertEqual([e["spent_usd"] for e in data["api"]["by_engine"] if e["engine"] == "openai"], [0.75])
        self.assertIn(("ask", "other"), {(t["task"], t["engine"]) for t in data["tasks"]})
        self.assertNotIn("zz9988776655", json.dumps(data))

    def test_day_only_counts_today_in_taipei_time(self):
        data = self.report("day")
        self.assertEqual((data["period"], data["label"]), ("day", "2026-11-15"))
        self.assertEqual({t["task"] for t in data["tasks"]}, {"triage", "translate"})
        self.assertEqual(data["cli"]["codex"], {"calls": 1, "tokens": 5000})
        self.assertEqual(data["api"]["month"], "2026-11")
        self.assertEqual(data["api"]["spent_usd"], 3.0)  # 花費固定算整個月，不跟著切到「每天」
        self.assertEqual(data["cli"]["antigravity"], {"calls": 0, "tokens": 0})

    def test_claude_window_is_the_last_five_hours_of_claude_calls(self):
        data = self.report("month")
        self.assertEqual(data["claude"]["window"], {"calls": 2, "tokens": 1800})  # codex 的和 8 小時前的不算

    def test_api_spend_matches_what_the_guard_counts(self):
        data = self.report("month")
        index = ledger.shared(self.db)
        with index.read() as db:
            self.assertEqual(data["api"]["spent_usd"], quota_guard.api_spent(db, NOW.timestamp()))

    def test_daily_is_fourteen_days_filled_with_zero_and_cut_at_taipei_midnight(self):
        self.put(datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc), inp=10, out=5)  # 台北 11/15 01:00
        self.put(datetime(2026, 11, 14, 15, 59, tzinfo=timezone.utc), inp=7, out=3)  # 台北 11/14 23:59
        daily = self.report()["daily"]
        self.assertEqual(len(daily), usage_report.DAILY_DAYS)
        self.assertEqual((daily[0]["date"], daily[-1]["date"]), ("2026-11-02", "2026-11-15"))
        by = {d["date"]: d["tokens"] for d in daily}
        self.assertEqual(by["2026-11-15"], 1800 + 5000 + 15)  # 今天：兩筆分類 + codex + 凌晨那筆
        self.assertEqual(by["2026-11-14"], 10)
        self.assertEqual(by["2026-11-12"], 3700 + 2300)  # 3 天前的起草和論點變化偵測
        self.assertEqual(by["2026-11-13"], 110)
        self.assertEqual(by["2026-11-10"], 0)
        self.assertNotIn("2026-10-26", by)  # 20 天前的在 14 天之外

    def test_sources_group_by_caller(self):
        sources = {s["source"]: s for s in self.report("month")["sources"]}
        self.assertEqual((sources["triage"]["calls"], sources["triage"]["tokens"]), (2, 1800))
        self.assertEqual(sources["newsread"]["calls"], 4)
        self.assertIsNone(sources["newsread"]["items"])  # 只有分類算得出資料數


class CapsTest(ReportCase):
    def many(self, n, **kw):
        index = ledger.Index(self.db, clock=lambda: at(hours=1))
        for i in range(n):
            index.record_usage(source=kw.get("source", "triage"), task="triage", engine="ollama", model=kw.get("model", f"m{i}"),
                               input_tokens=i + 1, output_tokens=0)

    def test_task_rows_stop_at_the_cap(self):
        self.many(usage_report.MAX_TASKS + 5, source="triage")
        data = self.report()
        self.assertEqual(len(data["tasks"]), usage_report.MAX_TASKS)
        self.assertTrue(data["tasks_truncated"])
        self.assertEqual(data["tasks"][0]["tokens"], usage_report.MAX_TASKS + 5)  # 留下的是用最多的

    def test_exactly_at_the_cap_is_not_truncated(self):
        self.many(usage_report.MAX_TASKS)
        data = self.report()
        self.assertEqual((len(data["tasks"]), data["tasks_truncated"]), (usage_report.MAX_TASKS, False))

    def test_source_rows_stop_at_the_cap(self):
        index = ledger.Index(self.db, clock=lambda: at(hours=1))
        for i in range(usage_report.MAX_SOURCES + 3):
            index.record_usage(source=f"s{i}", task="triage", engine="ollama", model="m", input_tokens=i + 1)
        data = self.report()
        self.assertEqual(len(data["sources"]), usage_report.MAX_SOURCES)
        self.assertTrue(data["sources_truncated"])

    def test_unknown_engine_names_are_not_echoed(self):
        index = ledger.Index(self.db, clock=lambda: at(hours=1))
        index.record_usage(source="x", task="triage", engine="mystery:secret-id", model="m", input_tokens=1)
        data = self.report()
        self.assertEqual(data["tasks"][0]["engine"], "other")
        self.assertNotIn("secret-id", json.dumps(data))


class TriageLinkTest(ReportCase):
    """分類過的資料有幾則有證據掛在論點上（只有 source = triage 算得出來）。"""

    def setUp(self):
        super().setUp()
        self.put(at(hours=1), source="triage", inp=100, out=0)
        self.put(at(hours=1), source="newsread", task="ask", inp=100, out=0)
        con = sqlite3.connect(self.db)  # 外鍵預設不檢查：只建這個報表用到的兩張表，不必先造整套論點資料
        con.executescript(triage.SCHEMA + narratives.SCHEMA)
        self.con = con

    def tearDown(self):
        self.con.close()

    def result(self, n, item, when):
        self.con.execute("INSERT INTO triage_results (id, item_id, content_hash, who, created_at, body, context_manifest) VALUES (?,?,?,?,?,?,?)",
                         (f"R{n}", item, "h", "ai:x", ledger.iso(when), "{}", "M"))

    def evidence(self, n, item):
        self.con.execute("INSERT INTO evidence (id, thesis_id, item_id, relation, grade, reason, by, created_at) VALUES (?,?,?,?,?,?,?,?)",
                         (f"E{n}", "T1", item, "strengthens", "B", "r", "ai", ledger.iso(NOW)))

    def test_share_of_triaged_items_with_evidence(self):
        for n, item in enumerate(["a", "b", "c", "d"]):
            self.result(n, item, at(hours=2))
        self.result(9, "a", at(hours=1))  # 同一則重新分類：不重複算
        self.result(10, "old", at(days=40))  # 上個月的不算
        self.evidence(1, "a")
        self.evidence(2, "a")  # 一則有兩條證據：還是一則
        self.evidence(3, "c")
        self.con.commit()
        src = {s["source"]: s for s in self.report("month")["sources"]}
        self.assertEqual((src["triage"]["items"], src["triage"]["linked"]), (4, 2))
        self.assertIsNone(src["newsread"]["linked"])

    def test_tables_not_created_yet_leaves_the_ratio_empty(self):
        self.con.executescript("DROP TABLE evidence; DROP TABLE triage_results;")
        src = {s["source"]: s for s in self.report("month")["sources"]}
        self.assertEqual((src["triage"]["items"], src["triage"]["linked"]), (None, None))


class RateLimitEventTest(GuardBase):
    SECRET = "upstream-secret-text-xyz"

    def steps(self, runs):
        return [ai.AIError("RATE_LIMITED", self.SECRET) for _ in range(ai.MAX_ATTEMPTS * runs)]

    def test_exhausted_retries_record_one_event_per_bucket_without_upstream_text(self):
        self.adapters["claude"] = FakeAdapter(*self.steps(3))
        eng = self.engines()
        for _ in range(2):
            with self.assertRaises(ai.AIError):
                eng.run("ask", "p", prompt_version="v1", trigger="manual")
        events = self.events()
        self.assertEqual([e["code"] for e in events], ["RATE_LIMITED"])  # 同一個時段只記一筆
        self.assertEqual(events[0]["task"], "ask")
        self.assertEqual(events[0]["message"], quota_guard.message("RATE_LIMITED"))
        self.assertNotIn(self.SECRET, json.dumps(events))
        self.t += ai.RATE_EVENT_BUCKET
        with self.assertRaises(ai.AIError):
            eng.run("ask", "p", prompt_version="v1", trigger="manual")
        self.assertEqual(self.codes(), ["RATE_LIMITED", "RATE_LIMITED"])

    def test_a_call_that_recovers_after_a_retry_records_nothing(self):
        from tests.test_ai_engines import ok
        self.adapters["claude"] = FakeAdapter(ai.AIError("RATE_LIMITED"), ok())
        self.engines().run("ask", "p", prompt_version="v1", trigger="manual")
        self.assertEqual(self.events(), [])
