"""Ticket 15：今日新聞 API。用 test_triage 的假 AI 和虛構資料；時鐘固定在台北 2026-11-12 20:00。"""
from __future__ import annotations

import sqlite3
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from easyread import ai_engines, ledger, today
from easyread.store import DataReadError
from tests.doubles import ApiTestCase
from tests.test_triage import Base

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)  # 台北 20:00


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def rated(ref: str, importance: str, relation: str = "bull", reason: str = "理由（範例）", noise_kind=None) -> dict:
    return {"ref": ref, "importance": importance, "noise_kind": noise_kind, "relation": relation, "confidence": "mid", "reason": reason}


def thesis(ref: str, importance: str, relation: str = "strengthens", reason: str = "論點理由（範例）", noise_kind=None) -> dict:
    return {"ref": ref, "relation": relation, "grade": "B", "importance": importance, "noise_kind": noise_kind,
            "confidence": "high", "reason": reason}


class TodayBase(Base):
    def setUp(self):
        super().setUp()
        self.index.clock = lambda: NOW
        self.n = 0

    def item(self, importance: str | None, *, hours: float = 1, entities=None, theses=None, title: str | None = None) -> str:
        """加一則資料並分類完。importance = None 表示不分類（留在待分類）。"""
        self.n += 1
        item = self.add(ago(hours), text=f"第 {self.n} 則範例新聞內容。\n\n第二段（範例）。", title=title or f"範例新聞 {self.n}")
        if importance is not None:
            ents = entities if entities is not None else [rated("@範例科技", importance)]
            ths = theses if theses is not None else []
            counts = self.triage_round(self.answer(entities=ents, theses=ths, points=[]))
            self.assertEqual(counts["done"], 1)
        return item

    def build(self, **query):
        return today.build(self.app, {k: str(v) for k, v in query.items()}, engine=self.engine())

    def exposed(self) -> set:
        return {r["item_id"] for r in self.rows("SELECT item_id FROM exposures WHERE place='today'")}

    def sql(self, statement: str, *args):
        """直接改資料庫（模擬舊資料、壞資料；暫時拿掉只能新增的保護）。"""
        db = sqlite3.connect(self.app.ledger_path)
        try:
            with db:
                db.execute("DROP TRIGGER IF EXISTS triage_results_no_update")
                db.execute(statement, args)
        finally:
            db.close()


class TodayTest(TodayBase):
    def test_lists_today_grouped_by_importance_and_excludes_other_days(self):
        low = self.item("low", hours=2)
        high = self.item("high", hours=3)
        mid_new = self.item("mid", hours=1)
        mid_old = self.item("mid", hours=4)
        self.item("high", hours=30)  # 昨天（台北）：不列
        data = self.build(importance="high,mid,low,noise,none")
        self.assertEqual(data["date"], "2026-11-12")
        self.assertEqual([i["id"] for i in data["items"]], [high, mid_new, mid_old, low])  # 重要度，同級新的在前
        self.assertEqual(data["counts"], {"high": 1, "mid": 2, "none": 0, "low": 1, "noise": 0})
        self.assertEqual(data["total"], 4)
        first = data["items"][0]
        self.assertEqual((first["title"], first["state"], first["importance"]), ("範例新聞 2", "done", "high"))
        self.assertEqual(first["top"]["reason"], "理由（範例）")
        self.assertEqual(first["reader_url"], f"/read/{high}")

    def test_default_filter_shows_high_mid_and_unclassified(self):
        self.item("high")
        self.item("low")
        self.item("noise", entities=[rated("@範例科技", "noise", "noise", noise_kind="rehash")])
        waiting = self.item(None)
        data = self.build()
        self.assertEqual(data["levels"], ["high", "mid", "none"])
        self.assertEqual(len(data["items"]), 2)
        self.assertIn(waiting, [i["id"] for i in data["items"]])
        self.assertEqual(data["counts"]["low"], 1)  # 沒顯示的也有數量
        self.assertEqual(data["counts"]["noise"], 1)

    def test_importance_follows_theses_when_there_are_any_and_detail_is_per_thesis(self):
        item = self.item("low", entities=[rated("@範例科技", "low")],
                         theses=[thesis("@T1", "noise", "related_no_change", noise_kind="short_term", reason="對這個論點只是短期波動")])
        data = self.build(importance="high,mid,low,noise")
        row = data["items"][0]
        self.assertEqual((row["id"], row["importance"]), (item, "noise"))  # 有論點只看論點（規格：對各論點最高的那一級）
        self.assertEqual((row["top"]["kind"], row["top"]["reason"]), ("thesis", "對這個論點只是短期波動"))
        t = row["theses"][0]
        self.assertEqual((t["id"], t["importance"], t["noise_kind"], t["relation"]), (self.thesis, "noise", "short_term", "related_no_change"))
        self.assertEqual(t["claim"], "AI 伺服器需求兩年向上（範例）")
        self.assertEqual((t["theme_id"], t["theme_name"]), (self.theme, "AI 伺服器（範例）"))
        self.assertEqual(row["entities"][0]["name"], "範例科技")
        self.assertEqual(row["entities"][0]["importance"], "low")

    def test_label_and_reason_come_from_the_same_judgment(self):
        self.item("high", entities=[rated("@範例科技", "high", reason="ENTITY-HIGH")], theses=[thesis("@T1", "mid", reason="THESIS-MID")])
        row = self.build()["items"][0]
        self.assertEqual((row["importance"], row["top"]["importance"], row["top"]["reason"]), ("mid", "mid", "THESIS-MID"))

    def test_without_theses_importance_is_the_highest_entity(self):
        self.ents.create({"type": "company", "name": "範例材料"})
        self.item("low", entities=[rated("@範例科技", "low", reason="低"), rated("@範例材料", "high", reason="高")])
        row = self.build()["items"][0]
        self.assertEqual((row["importance"], row["top"]["reason"]), ("high", "高"))

    def test_entity_filter_matches_entities_and_theme_of_thesis(self):
        a = self.item("high", entities=[rated("@範例科技", "high")])
        b = self.item("mid", entities=[], theses=[thesis("@T1", "mid")])
        data = self.build(entity=self.company)
        self.assertEqual([i["id"] for i in data["items"]], [a])
        data = self.build(entity=self.theme)  # 題材：透過論點的題材
        self.assertEqual([i["id"] for i in data["items"]], [b])
        by_id = {e["id"]: e for e in self.build()["entities"]}
        self.assertEqual((by_id[self.company]["count"], by_id[self.theme]["count"]), (1, 1))
        self.assertEqual(by_id[self.theme]["name"], "AI 伺服器（範例）")

    def test_unrelated_entities_do_not_count_as_linked(self):
        self.item("noise", entities=[rated("@範例科技", "noise", "noise", noise_kind="unrelated")])
        data = self.build(importance="noise", entity=self.company)
        self.assertEqual(data["items"], [])

    def test_unrelated_theses_do_not_link_their_theme(self):
        self.item("noise", entities=[], theses=[thesis("@T1", "noise", "related_no_change", noise_kind="unrelated")])
        self.assertEqual(self.build(importance="noise", entity=self.theme)["items"], [])

    def test_taipei_day_boundary(self):
        morning = self.item("high", hours=13)   # UTC 11/11 23:00 = 台北 11/12 07:00：今天
        self.item("high", hours=20.5)           # UTC 11/11 15:30 = 台北 11/11 23:30：昨天
        self.assertEqual([i["id"] for i in self.build()["items"]], [morning])

    def test_unknown_publish_time_uses_import_time(self):
        item = self.item("high", hours=1)
        ws = self.app.lib.ws(item)
        ws.update("paper", lambda paper: paper["meta"].update(time_source="unknown"))
        ws.update("item", lambda it: it.update(added=ledger.iso(ago(30))))  # 昨天匯入：不列
        self.assertEqual(self.build()["items"], [])
        ws.update("item", lambda it: it.update(added=ledger.iso(ago(2))))
        row = self.build()["items"][0]
        self.assertEqual((row["id"], row["time_known"], row["published_at"]), (item, False, ""))

    def test_items_not_touched_within_the_scan_window_are_not_read(self):
        item = self.item("high")
        self.sql("UPDATE triage_state SET updated_at=? WHERE item_id=?", ledger.iso(NOW - timedelta(days=today.SCAN_DAYS + 1)), item)
        self.assertEqual(self.build()["items"], [])

    def test_user_title_override_is_shown(self):
        item = self.item("high")
        self.app.lib.ws(item).patch_item({"meta_override": {"title_en": "使用者改的標題", "publisher": "使用者改的來源"}})
        row = self.build()["items"][0]
        self.assertEqual((row["id"], row["title"], row["publisher"]), (item, "使用者改的標題", "使用者改的來源"))

    def test_sql_chunks_cover_every_item(self):
        items = {self.item("high", hours=h) for h in (1, 2, 3)}
        with mock.patch.object(today, "CHUNK", 1):
            data = self.build()
        self.assertEqual({i["id"] for i in data["items"]}, items)
        self.assertTrue(all(i["top"] for i in data["items"]))

    def test_entity_facets_are_capped(self):
        self.ents.create({"type": "company", "name": "範例材料"})
        self.item("high", entities=[rated("@範例科技", "high"), rated("@範例材料", "high")])
        with mock.patch.object(today, "MAX_FACETS", 1):
            self.assertEqual(len(self.build()["entities"]), 1)


class TodayBadDataTest(TodayBase):
    def test_unreadable_triage_result_is_shown_without_ai_view(self):
        item = self.item("high")
        self.sql("UPDATE triage_results SET body='not json' WHERE item_id=?", item)
        row = self.build()["items"][0]
        self.assertEqual((row["id"], row["importance"], row["top"]), (item, "none", None))
        self.assertEqual(self.exposed(), set())

    def test_malformed_judgments_are_dropped(self):
        item = self.item("high")
        self.sql("UPDATE triage_results SET body=? WHERE item_id=?",
                 '{"entities": [{"id": 5}, {"importance": "urgent", "id": "E-x"}, "x"], "theses": "bad"}', item)
        row = self.build()["items"][0]
        self.assertEqual((row["importance"], row["entities"], row["theses"]), ("none", [], []))

    def test_unreadable_workspace_is_skipped_not_fatal(self):
        bad, good = self.item("high", hours=1), self.item("high", hours=2)
        real = today._item

        def item(lib, item_id, day):
            if item_id == bad:
                raise DataReadError("C:/secret/path/paper.json")
            return real(lib, item_id, day)
        with mock.patch.object(today, "_item", side_effect=item), self.assertLogs("easyread.today", "WARNING") as logs:
            data = self.build()
        self.assertEqual([i["id"] for i in data["items"]], [good])
        self.assertNotIn("secret", "".join(logs.output))

    def test_unclassified_items_show_without_ai_view(self):
        waiting = self.item(None)
        row = self.build()["items"][0]
        self.assertEqual((row["id"], row["state"], row["importance"]), (waiting, "pending", "none"))
        self.assertIsNone(row["top"])
        self.assertEqual((row["entities"], row["theses"]), ([], []))
        self.assertEqual(self.exposed(), set())  # 沒有 AI 看法 = 沒有揭露

    def test_pending_items_say_why_triage_waits_when_only_a_cli_with_tools_is_found(self):
        """Ticket 104：待分類的數量不看篩選；只有 Codex 時回 triage_block，Claude Code 找得到時不回。"""
        self.item("high")
        self.item(None)
        self.item(None)
        data = self.build(importance="high")
        self.assertEqual((data["pending"], data["triage_block"]), (2, None))  # Claude Code 找得到：分類只是還沒輪到
        self.found = {"claude": {"found": False}, "codex": {"found": True}, "antigravity": {"found": False},
                      "ollama": {"running": False, "models": []}}
        data = self.build(importance="high")
        self.assertEqual((data["pending"], data["triage_block"]), (2, {"reason": "no_tools", "engines": ["codex"]}))
        self.assertEqual(today._empty("2026-11-12", today.DEFAULT_LEVELS, 50)["triage_block"], None)

    def test_triage_block_is_only_asked_when_something_waits_and_never_fails_the_page(self):
        self.item("high")
        broken = mock.Mock()
        broken.triage_block.side_effect = AssertionError("should not be asked")
        self.assertEqual(today.build(self.app, {}, engine=broken)["triage_block"], None)  # 沒有待分類：不讀 AI 設定
        self.item(None)
        broken.triage_block.side_effect = ValueError("C:/secret/ai.json")
        with self.assertLogs("easyread.today", "WARNING") as logs:
            data = today.build(self.app, {}, engine=broken)
        self.assertEqual((data["pending"], data["triage_block"], len(data["items"])), (1, None, 2))
        self.assertNotIn("secret", "".join(logs.output))

    def test_empty_states(self):
        self.assertEqual(today.build(types.SimpleNamespace(lib=self.app.lib, ledger_path=self.app.ledger_path.parent / "none.sqlite3"),
                                     {})["items"], [])
        data = self.build()
        self.assertEqual((data["items"], data["total"], data["more"]), ([], 0, False))
        self.assertEqual(data["counts"], {"high": 0, "mid": 0, "none": 0, "low": 0, "noise": 0})

    def test_missing_database_is_not_created_by_a_read(self):
        app = types.SimpleNamespace(lib=self.app.lib, ledger_path=self.app.ledger_path.parent / "never.sqlite3")
        self.assertEqual(today.build(app, {})["total"], 0)
        self.assertFalse(app.ledger_path.exists())

    def test_bad_query_values_are_rejected_with_the_field(self):
        for query, field in (({"importance": "urgent"}, "importance"), ({"entity": "bad id"}, "entity"),
                             ({"limit": "0"}, "limit"), ({"limit": "x"}, "limit"), ({"importance": "high," * 20}, "importance")):
            with self.assertRaises(today.EntityError) as cm:
                today.build(self.app, query)
            self.assertEqual(cm.exception.field, field)


class TodayExposureTest(TodayBase):
    def test_exposure_is_written_for_every_shown_item_with_an_ai_view_and_only_once(self):
        a, b = self.item("high"), self.item("mid")
        self.item("low")  # 篩掉了：沒顯示，不寫
        self.assertEqual(self.exposed(), set())
        self.build()
        self.assertEqual(self.exposed(), {a, b})
        self.build()
        self.assertEqual(len(self.rows("SELECT * FROM exposures WHERE place='today'")), 2)  # 同一則同一地點只記第一次

    def test_items_beyond_the_limit_are_not_exposed(self):
        items = [self.item("high", hours=h) for h in (1, 2, 3)]
        data = self.build(limit=2)
        self.assertEqual([i["id"] for i in data["items"]], items[:2])
        self.assertEqual(self.exposed(), set(items[:2]))

    def test_exposure_is_written_before_the_data_is_returned_and_failure_returns_nothing(self):
        self.item("high")
        with mock.patch.object(self.index.__class__, "record_exposures", side_effect=sqlite3.OperationalError("locked: secret path")):
            with self.assertRaises(sqlite3.Error):
                self.build()
        self.assertEqual(self.exposed(), set())

    def test_a_failed_read_after_selection_writes_no_exposure(self):
        self.item("high", entities=[], theses=[thesis("@T1", "high")])
        with mock.patch.object(today, "_claims", side_effect=sqlite3.OperationalError("busy")):
            with self.assertRaises(sqlite3.Error):
                self.build()
        self.assertEqual(self.exposed(), set())

    def test_exposures_are_written_in_one_transaction(self):
        a, b = self.item("high"), self.item("mid")
        real = self.index.__class__.record_exposures
        with mock.patch.object(self.index.__class__, "record_exposures", autospec=True, side_effect=real) as spy:
            self.build()
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(self.exposed(), {a, b})


class TodayLimitTest(TodayBase):
    def test_limit_caps_the_list_and_reports_more(self):
        for h in (1, 2, 3):
            self.item("high", hours=h)
        data = self.build(limit=2)
        self.assertEqual((len(data["items"]), data["total"], data["more"], data["limit"]), (2, 3, True, 2))
        self.assertFalse(self.build(limit=3)["more"])

    def test_limit_is_clamped_to_the_maximum(self):
        with mock.patch.object(today, "MAX_LIMIT", 2):
            for h in (1, 2, 3):
                self.item("high", hours=h)
            data = self.build(limit=500)
            self.assertEqual((len(data["items"]), data["limit"], data["more"]), (2, 2, True))

    def test_scan_cap_stops_reading_and_says_so(self):
        for h in (1, 2, 3):
            self.item("high", hours=h)
        with mock.patch.object(today, "MAX_SCAN", 2):
            data = self.build()
        self.assertTrue(data["truncated"])
        self.assertEqual(data["total"], 2)
        self.assertFalse(self.build()["truncated"])


class TodayApiTest(ApiTestCase):
    def make_app(self):
        self.base_case = TodayBase("setUp")
        self.base_case.setUp()
        self.addCleanup(self.base_case.doCleanups)
        self.addCleanup(ai_engines._ENGINES.clear)
        b = self.base_case
        return {"lib": b.app.lib, "ledger_path": b.app.ledger_path, "ai_path": b.settings.path,
                "ai_options": {"adapters": b.adapters, "detector": lambda fresh=False: b.found,
                               "wait": lambda s, c: None, "has_sdk": lambda: True, "quota": lambda: None}}

    def test_post_returns_items_and_writes_exposure(self):
        b = self.base_case
        item = b.item("high")
        status, data = self.post("/api/today", {"importance": "high"})
        self.assertEqual(status, 200)
        self.assertEqual([i["id"] for i in data["items"]], [item])
        self.assertEqual(b.exposed(), {item})

    def test_requests_without_the_token_see_and_write_nothing(self):
        b = self.base_case
        b.item("high")
        status, data = self.get("/api/today?importance=high")  # GET 不帶 token：沒有這個路徑
        self.assertNotEqual(status, 200)
        self.assertNotIn("items", data if isinstance(data, dict) else {})
        self.assertEqual(self.post("/api/today", {"importance": "high"}, token="wrong")[0], 403)
        self.assertEqual(b.exposed(), set())

    def test_post_says_why_triage_waits(self):
        b = self.base_case
        b.item(None)
        b.found = {"claude": {"found": False}, "codex": {"found": True}, "antigravity": {"found": True},
                   "ollama": {"running": False, "models": []}}
        status, data = self.post("/api/today", {})
        self.assertEqual((status, data["pending"], data["triage_block"]), (200, 1, {"reason": "no_tools", "engines": ["codex", "antigravity"]}))

    def test_bad_body_is_400_with_field(self):
        status, data = self.post("/api/today", {"importance": "urgent"})
        self.assertEqual((status, data["field"]), (400, "importance"))
        self.assertEqual(self.post("/api/today", {"limit": 999999})[0], 200)  # 超過上限：照上限回
        self.assertEqual(self.request("POST", "/api/today", b"[1, 2]")[0], 400)
        self.assertEqual(self.request("POST", "/api/today", b"{not json")[0], 400)
        self.assertEqual(self.request("POST", "/api/today", b"{}" + b" " * (today.MAX_BODY + 1))[0], 413)

    def test_database_error_returns_a_fixed_message(self):
        with mock.patch.object(today, "build", side_effect=sqlite3.OperationalError("secret path C:/x")):
            status, data = self.post("/api/today")
        self.assertEqual(status, 500)
        self.assertNotIn("secret", str(data))

    def test_page_is_served(self):
        status, text = self.get("/today")
        self.assertEqual(status, 200)
        self.assertIn("today/app.js", text)


if __name__ == "__main__":
    unittest.main()
