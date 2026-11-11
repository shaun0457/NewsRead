"""Ticket 13：追蹤對象的 HTTP API（建立、編輯、代號驗證、別名、對照基準、封存、資料連結）。"""
from __future__ import annotations

import io
import re
import sqlite3
import tempfile
import types
from datetime import timedelta
from pathlib import Path
from unittest import mock

from easyread import entities, ledger, server

from tests.doubles import ApiTestCase

TSMC = {"type": "company", "name": "範例晶圓廠", "aliases": ["SFAB", "晶圓一哥"],
        "listings": [{"market": "TW", "symbol": "9901"}, {"market": "US", "symbol": "sfb"}]}


class EntitiesApiCase(ApiTestCase):
    def make_app(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "newsread.sqlite3"
        self.addCleanup(entities._STORES.pop, self.db, None)
        return {"ledger_path": self.db}

    def create(self, body):
        status, data = self.request("POST", "/api/entities", body)
        self.assertEqual(status, 200, data)
        return data

    def assertBad(self, body, field, path="/api/entities"):
        status, data = self.request("POST", path, body)
        self.assertEqual(status, 400, data)
        self.assertEqual(data["field"], field, data)
        self.assertTrue(data["error"])
        return data


class CreateAndListTest(EntitiesApiCase):
    def test_the_page_is_served(self):
        status, html = self.request("GET", "/entities")
        self.assertEqual(status, 200)
        text = html if isinstance(html, str) else html.decode("utf-8")
        self.assertIn("/web/js/entities/app.js", text)
        self.assertIn('href="/entities" aria-current="page"', text)

    def test_traditional_strings_survive_the_zh_tw_conversion(self):
        # 字串本來就是繁體；s2twp 會把「對象」換成「物件」、「類型」換成「型別」，zh-TW.json 要把它們固定住
        from easyread import i18n
        if not i18n._tw_converter():
            self.skipTest("opencc not installed")
        root = Path(entities.__file__).parent
        keys = re.findall(r'PR\.t\("((?:[^"\\]|\\.)*)"', (root / "web/js/entities/app.js").read_text(encoding="utf-8"))
        keys += re.findall(r'tr\("((?:[^"\\]|\\.)*)"', (root / "entities.py").read_text(encoding="utf-8"))
        self.assertGreater(len(keys), 60)
        for key in keys:
            self.assertEqual(i18n._tw_text(key), key, key)
        page = i18n.inject((root / "web/entities.html").read_text(encoding="utf-8"), "zh-TW")
        self.assertIn("<h1>追蹤對象</h1>", page)
        self.assertIn("<title>追蹤對象 · NewsRead</title>", page)

    def test_list_is_empty_and_does_not_create_the_database(self):
        status, data = self.request("GET", "/api/entities")
        self.assertEqual(status, 200)
        self.assertEqual(data["entities"], [])
        self.assertEqual(data["total"], 0)
        self.assertFalse(self.db.exists())

    def test_company_with_two_listings_aliases_and_default_benchmark(self):
        made = self.create(TSMC)
        self.assertRegex(made["id"], r"^E-[0-9a-f]{32}$")
        self.assertEqual(made["listings"], [{"market": "TW", "symbol": "9901.TW"}, {"market": "US", "symbol": "SFB"}])
        self.assertEqual(made["primary"], "9901.TW")
        self.assertEqual(made["aliases"], ["SFAB", "晶圓一哥"])
        self.assertEqual(made["benchmark"], "發行量加權股價報酬指數")
        self.assertTrue(made["benchmark_default"])
        self.assertIsNone(made["industry_index"])
        self.assertEqual(self.request("GET", "/api/entities/" + made["id"]), (200, {**made}))

    def test_us_primary_listing_defaults_to_a_total_return_benchmark(self):
        made = self.create({"type": "company", "name": "範例 GPU 廠", "listings": [{"market": "US", "symbol": "SGPU"}]})
        self.assertEqual(made["benchmark"], "S&P 500 Total Return")

    def test_benchmark_and_industry_index_can_be_overridden_and_reset(self):
        made = self.create({**TSMC, "benchmark": "加權指數", "industry_index": "半導體類報酬指數"})
        self.assertEqual((made["benchmark"], made["benchmark_default"], made["industry_index"]), ("加權指數", False, "半導體類報酬指數"))
        status, reset = self.request("POST", "/api/entities/" + made["id"], {**TSMC, "benchmark": None, "industry_index": ""})
        self.assertEqual(status, 200)
        self.assertEqual((reset["benchmark"], reset["benchmark_default"], reset["industry_index"]), ("發行量加權股價報酬指數", True, None))

    def test_all_five_types_and_type_counts(self):
        for kind, name in (("company", "A 公司"), ("industry", "CoWoS 供應鏈"), ("macro", "Fed 利率"), ("event", "法說會"), ("theme", "AI 伺服器")):
            made = self.create({"type": kind, "name": name})
            if kind != "company":
                self.assertIsNone(made["benchmark"])
        status, data = self.request("GET", "/api/entities")
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["counts"], {t: 1 for t in entities.TYPES})
        status, themes = self.request("GET", "/api/entities?type=theme")
        self.assertEqual([e["name"] for e in themes["entities"]], ["AI 伺服器"])
        self.assertEqual(self.request("GET", "/api/entities?type=stock")[0], 400)

    def test_only_companies_can_have_listings(self):
        self.assertBad({"type": "theme", "name": "HBM", "listings": [{"market": "US", "symbol": "MU"}]}, "listings")

    def test_writes_need_the_token(self):
        self.assertEqual(self.request("POST", "/api/entities", TSMC, token="nope")[0], 403)


class ValidationTest(EntitiesApiCase):
    def test_ticker_formats(self):
        cases = [("TW", "2330", "2330.TW"), ("TW", "6488.two", "6488.TWO"), ("TW", "00878", "00878.TW"),
                 ("US", "nvda", "NVDA"), ("US", "BRK-B", "BRK.B")]
        for i, (market, raw, stored) in enumerate(cases):
            made = self.create({"type": "company", "name": f"c{i}", "listings": [{"market": market, "symbol": raw}]})
            self.assertEqual(made["primary"], stored)
        for market, raw in (("TW", "23A0"), ("TW", "233"), ("TW", "2330.US"), ("US", "SFAB12"), ("US", "TSM.TW"), ("US", ""), ("US", 7)):
            self.assertBad({"type": "company", "name": "x", "listings": [{"market": market, "symbol": raw}]}, "listings.0.symbol")
        self.assertBad({"type": "company", "name": "x", "listings": [{"market": "JP", "symbol": "7203"}]}, "listings.0.market")

    def test_required_and_typed_fields(self):
        self.assertBad({"name": "x"}, "type")
        self.assertBad({"type": "company", "name": "   "}, "name")
        self.assertBad({"type": "company", "name": ["x"]}, "name")
        self.assertBad({"type": "company", "name": "x", "aliases": "SFAB"}, "aliases")

    def test_a_symbol_belongs_to_one_entity(self):
        self.create(TSMC)
        data = self.assertBad({"type": "company", "name": "另一家", "listings": [{"market": "TW", "symbol": "9901.TW"}]}, "listings.0.symbol")
        self.assertIn("範例晶圓廠", data["error"])
        self.assertBad({"type": "company", "name": "重複", "listings": [{"market": "US", "symbol": "AA"}, {"market": "US", "symbol": "aa"}]},
                       "listings.1.symbol")

    def test_aliases_are_trimmed_and_deduplicated(self):
        made = self.create({"type": "theme", "name": "AI 伺服器", "aliases": ["  AI   server ", "ai server", "AI 伺服器", ""]})
        self.assertEqual(made["aliases"], ["AI server"])

    def test_limits(self):
        many = [{"market": "US", "symbol": s} for s in ("AA", "BB", "CC", "DD", "EE", "FF")]
        self.assertBad({"type": "company", "name": "x", "listings": many}, "listings")
        self.create({"type": "company", "name": "five", "listings": many[:5]})
        self.assertBad({"type": "theme", "name": "x", "aliases": [f"a{i}" for i in range(21)]}, "aliases")
        self.assertBad({"type": "theme", "name": "x" * 101}, "name")
        self.assertBad({"type": "theme", "name": "x", "aliases": ["y" * 61]}, "aliases.0")
        self.assertBad({"type": "company", "name": "x", "benchmark": "z" * 81}, "benchmark")
        status, _ = self.request("POST", "/api/entities", b'{"type":"theme","name":"' + b"x" * entities.MAX_BODY + b'"}')
        self.assertEqual(status, 413)
        with mock.patch.object(entities, "MAX_ENTITIES", 2):
            self.create({"type": "theme", "name": "second"})
            self.assertBad({"type": "theme", "name": "third"}, "")
        status, _ = self.request("POST", "/api/entities", b"{not json")
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/api/entities", b"[" * 30000 + b"]" * 30000)  # 很深的巢狀
        self.assertEqual(status, 400)

    def test_full_width_digits_are_the_same_ticker(self):
        made = self.create({"type": "company", "name": "全形", "listings": [{"market": "TW", "symbol": "２３３０"}]})
        self.assertEqual(made["primary"], "2330.TW")
        self.assertBad({"type": "company", "name": "半形", "listings": [{"market": "TW", "symbol": "2330"}]}, "listings.0.symbol")
        self.assertBad({"type": "company", "name": "x", "listings": [{"market": "TW", "symbol": "٢٣٣٠"}]}, "listings.0.symbol")
        self.assertEqual(entities.normalize_symbol("US", "ｎｖｄａ"), "NVDA")

    def test_full_width_aliases_count_as_duplicates(self):
        made = self.create({"type": "theme", "name": "SFAB", "aliases": ["ＳＦＡＢ", "晶圓", "晶圓"]})
        self.assertEqual(made["aliases"], ["晶圓"])

    def test_database_errors_return_a_fixed_message(self):
        with mock.patch.object(entities.Store, "list", side_effect=sqlite3.OperationalError("no such table: secret_x")):
            self.request("POST", "/api/entities", {"type": "theme", "name": "建檔"})
            status, data = self.request("GET", "/api/entities")
        self.assertEqual(status, 500)
        self.assertNotIn("secret_x", str(data))
        self.assertNotIn("OperationalError", str(data))


class BodyLimitTest(EntitiesApiCase):
    """server._body 的上限：剛好上限收下；超過但不大就分段讀掉；太大或不是數字就不讀。"""

    def handler(self, length, data=b""):
        h = types.SimpleNamespace(headers={"Content-Length": length}, rfile=io.BytesIO(data), close_connection=False)
        return h

    def test_exactly_the_limit_is_accepted(self):
        h = self.handler(str(entities.MAX_BODY), b"x" * entities.MAX_BODY)
        self.assertEqual(len(server.Handler._body(h, entities.MAX_BODY)), entities.MAX_BODY)
        self.assertFalse(h.close_connection)

    def test_small_oversize_bodies_are_drained_in_chunks(self):
        n = entities.MAX_BODY + server.DRAIN_CHUNK * 3 + 5
        h = self.handler(str(n), b"x" * (n + 10))
        reads = []
        real = h.rfile.read
        h.rfile.read = lambda k: reads.append(k) or real(k)
        with self.assertRaises(ValueError):
            server.Handler._body(h, entities.MAX_BODY)
        self.assertTrue(h.close_connection)
        self.assertEqual(h.rfile.tell(), n)  # 只讀宣告的長度
        self.assertLessEqual(max(reads), server.DRAIN_CHUNK)

    def test_huge_negative_or_bad_lengths_are_not_read(self):
        for length in (str(entities.MAX_BODY + server.DRAIN_MAX + 1), "-1", "abc", " 5", "٥"):
            h = self.handler(length, b"x" * 100)
            with self.assertRaises(ValueError):
                server.Handler._body(h, entities.MAX_BODY)
            self.assertTrue(h.close_connection, length)
            self.assertEqual(h.rfile.tell(), 0, length)

    def test_bad_token_bodies_are_not_kept(self):
        h = self.handler(str(server.DRAIN_MAX + 1), b"x" * 100)
        with self.assertRaises(ValueError):
            server.Handler._body(h, 0)  # do_POST 用 _body(0) 處理 token 錯誤的請求
        self.assertEqual(h.rfile.tell(), 0)
        status, data = self.request("POST", "/api/entities", {"type": "theme", "name": "x"}, token="wrong")
        self.assertEqual(status, 403)


class EditAndArchiveTest(EntitiesApiCase):
    def test_update_replaces_listings_and_aliases(self):
        made = self.create(TSMC)
        status, edited = self.request("POST", "/api/entities/" + made["id"], {
            "type": "company", "name": "範例晶圓廠", "aliases": ["9901"], "listings": [{"market": "US", "symbol": "SFB"}]})
        self.assertEqual(status, 200)
        self.assertEqual(edited["listings"], [{"market": "US", "symbol": "SFB"}])
        self.assertEqual(edited["aliases"], ["9901"])
        self.assertEqual(edited["benchmark"], "S&P 500 Total Return")  # 預設跟著主要代號的市場走
        # 拿掉的台股代號可以給別人用
        self.create({"type": "company", "name": "接手", "listings": [{"market": "TW", "symbol": "9901"}]})

    def test_failed_update_changes_nothing(self):
        made = self.create(TSMC)
        other = self.create({"type": "company", "name": "其他", "listings": [{"market": "US", "symbol": "OTH"}]})
        self.assertBad({**TSMC, "name": "改名", "listings": [{"market": "US", "symbol": "OTH"}]}, "listings.0.symbol",
                       path="/api/entities/" + made["id"])
        self.assertEqual(self.request("GET", "/api/entities/" + made["id"])[1]["name"], "範例晶圓廠")
        self.assertEqual(self.request("GET", "/api/entities/" + made["id"])[1]["listings"][0]["symbol"], "9901.TW")
        self.assertEqual(other["primary"], "OTH")

    def test_unknown_entities_are_not_found(self):
        self.create(TSMC)
        for path in ("/api/entities/E-" + "0" * 32, "/api/entities/../x", "/api/entities/nope"):
            self.assertEqual(self.request("GET", path)[0], 404, path)
        self.assertEqual(self.request("POST", "/api/entities/E-" + "0" * 32, TSMC)[0], 404)
        self.assertEqual(self.request("POST", "/api/entities/E-" + "0" * 32 + "/archive", {})[0], 404)

    def test_archive_hides_from_the_list_and_can_be_undone(self):
        made = self.create(TSMC)
        status, archived = self.request("POST", f"/api/entities/{made['id']}/archive", {"archived": True})
        self.assertTrue(archived["archived"])
        listed = self.request("GET", "/api/entities")[1]
        self.assertEqual((listed["entities"], listed["total"], listed["archived"]), ([], 0, 1))
        self.assertEqual(len(self.request("GET", "/api/entities?archived=1")[1]["entities"]), 1)
        self.assertBad({"archived": "yes"}, "archived", path=f"/api/entities/{made['id']}/archive")
        self.request("POST", f"/api/entities/{made['id']}/archive", {"archived": False})
        self.assertEqual(self.request("GET", "/api/entities")[1]["total"], 1)


class MentionTest(EntitiesApiCase):
    def setUp(self):
        super().setUp()
        self.entity = self.create(TSMC)
        self.store = entities.Store(ledger.Index(self.db))
        self.mpath = f"/api/entities/{self.entity['id']}/mentions"

    def mentions(self):
        return [(m["item_id"], m["source"]) for m in self.request("GET", "/api/entities/" + self.entity["id"])[1]["mentions"]]

    def test_manual_links_are_marked_manual_and_can_be_removed(self):
        status, data = self.request("POST", self.mpath, {"item_id": "item-1"})
        self.assertEqual(status, 200)
        self.assertEqual(self.mentions(), [("item-1", "manual")])
        self.assertEqual(self.request("POST", self.mpath + "/item-1/remove", {})[0], 200)
        self.assertEqual(self.mentions(), [])

    def test_ai_links_never_override_a_manual_decision(self):
        self.assertTrue(self.store.link("item-ai", self.entity["id"], "ai"))
        self.assertEqual(self.mentions(), [("item-ai", "ai")])
        self.request("POST", self.mpath + "/item-ai/remove", {})
        self.assertFalse(self.store.link("item-ai", self.entity["id"], "ai"))  # 手動移除過，AI 不會連回去
        self.assertEqual(self.mentions(), [])
        self.request("POST", self.mpath, {"item_id": "item-m"})
        self.assertFalse(self.store.link("item-m", self.entity["id"], "ai"))
        self.assertEqual(self.mentions(), [("item-m", "manual")])
        self.request("POST", self.mpath, {"item_id": "item-ai"})  # 手動加回來可以
        self.assertIn(("item-ai", "manual"), self.mentions())

    def test_bad_item_ids_and_the_list_limit(self):
        for bad in ("", "a b", "x" * 129, 5, None):
            self.assertBad({"item_id": bad}, "item_id", path=self.mpath)
        with mock.patch.object(entities, "MAX_MENTIONS", 3):
            for i in range(5):
                self.store.link(f"item-{i}", self.entity["id"], "ai")
            self.assertEqual(len(self.mentions()), 3)

    def test_list_counts_links_from_the_last_seven_days(self):
        now = ledger._utcnow()
        old = entities.Store(ledger.Index(self.db, clock=lambda: now - timedelta(days=entities.RECENT_DAYS + 1)))
        old.link("item-old", self.entity["id"], "ai")
        old.link("item-back", self.entity["id"], "ai")
        self.store.link("item-new", self.entity["id"], "ai")
        self.store.link("item-gone", self.entity["id"], "ai")
        self.request("POST", self.mpath + "/item-gone/remove", {})
        self.request("POST", self.mpath, {"item_id": "item-old"})  # 手動確認舊連結：不是新連上的
        recent = lambda: self.request("GET", "/api/entities")[1]["entities"][0]["recent_mentions"]  # noqa: E731
        self.assertEqual(recent(), 1)  # 太舊的、移除的、只是確認過的都不算
        self.request("POST", self.mpath + "/item-back/remove", {})
        self.request("POST", self.mpath, {"item_id": "item-back"})  # 移除後再連回來，算新連上
        self.assertEqual(recent(), 2)

    def test_removing_a_link_that_never_existed_leaves_nothing(self):
        self.assertEqual(self.request("POST", self.mpath + "/item-x/remove", {})[0], 200)
        self.assertTrue(self.store.link("item-x", self.entity["id"], "ai"))

    def test_links_per_entity_are_capped(self):
        with mock.patch.object(entities, "MAX_LINKS", 3):
            for i in range(3):
                self.assertTrue(self.store.link(f"item-{i}", self.entity["id"], "ai"))
            self.assertFalse(self.store.link("item-3", self.entity["id"], "ai"))
            self.assertBad({"item_id": "item-4"}, "item_id", path=self.mpath)
            self.assertEqual(self.request("POST", self.mpath, {"item_id": "item-0"})[0], 200)  # 已經連著的照樣可以改成手動
