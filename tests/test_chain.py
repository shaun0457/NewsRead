"""Ticket 59：因果鏈清單的後端（改一環、確認、定稿、領漲 / 補漲建議）。題材、公司都是虛構的範例。"""
from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from easyread import chain, entities, ledger, narratives

from tests.doubles import ApiTestCase
from tests.test_narratives import SOURCE, StoreCase

APP = types.SimpleNamespace()
SRC_LINK = {"from": {"label": "AI 機櫃功率上升"}, "to": {"label": "配電電流過大"}, "relation": "電壓不變、功率變大，電流就變大", "source": SOURCE}
INFERRED = {"from": {"label": "800V 導入"}, "to": {"label": "直流斷路器需求"}, "relation": "需要新的保護元件"}  # 沒有出處


class ChainCase(StoreCase):
    def edit(self, op, **kw):
        return chain.edit(APP, self.store, self.theme, {"op": op, **kw})

    def head(self):
        return chain.view(APP, self.store, self.theme)

    def add(self, link):
        return self.edit("add", base_version=self.head()["version"], link=link)

    def company_link(self, **kw):
        return {"from": {"label": "電源轉換"}, "to": {"entity_id": self.company}, "relation": "受益", "source": SOURCE, **kw}


class EditTest(ChainCase):
    def test_empty_theme_has_an_empty_chain(self):
        v = self.head()
        self.assertEqual((v["links"], v["version"], v["status"], v["unconfirmed"]), ([], 0, None, 0))

    def test_add_update_remove_write_drafts_and_leave_the_final_alone(self):
        self.store.add_theme_version(self.theme, "final", {"one_liner": "定稿", "chain": [SRC_LINK]})
        self.clock.tick()
        v = self.add({**SRC_LINK, "relation": "新的一環"})
        self.assertEqual((v["status"], v["version"], len(v["links"]), v["final_version"]), ("draft", 2, 2, 1))
        self.assertEqual(len(self.store.page(self.theme)["final"]["body"]["chain"]), 1)  # 定稿沒動
        self.clock.tick()
        v = self.edit("update", base_version=2, index=1, link={**SRC_LINK, "relation": "改過"})
        self.assertEqual(v["links"][1]["relation"], "改過")
        self.clock.tick()
        v = self.edit("remove", base_version=3, index=0)
        self.assertEqual([x["relation"] for x in v["links"]], ["改過"])
        self.assertEqual(self.store.page(self.theme)["draft"]["by"], narratives.ME)

    def test_edit_keeps_the_rest_of_the_page(self):
        self.store.add_theme_version(self.theme, "draft", {"one_liner": "故事", "analogy": "類比", "second_order": ["外溢"]})
        self.clock.tick()
        self.add(SRC_LINK)
        body = self.store.page(self.theme)["draft"]["body"]
        self.assertEqual((body["one_liner"], body["analogy"], body["second_order"]), ("故事", "類比", ["外溢"]))

    def test_sources_show_and_links_without_one_are_inferred(self):
        self.add(SRC_LINK)
        self.clock.tick()
        v = self.add(INFERRED)
        self.assertEqual([(x["inferred"], x["confirmed"]) for x in v["links"]], [(False, False), (True, False)])
        self.assertEqual(v["links"][0]["source"], SOURCE)
        self.assertEqual(v["unconfirmed"], 1)

    def test_confirming_an_inferred_link_lets_the_final_through(self):
        self.store.add_theme_version(self.theme, "draft", {"one_liner": "故事"})
        self.clock.tick()
        v = self.add(INFERRED)
        self.clock.tick()
        self.bad("chain.0", self.edit, "publish", base_version=v["version"])  # 還沒確認：進不了定稿
        v = self.edit("confirm", base_version=v["version"], index=0)
        self.assertTrue(v["links"][0]["confirmed"])
        self.assertEqual(v["unconfirmed"], 0)
        self.clock.tick()
        v = self.edit("publish", base_version=v["version"])
        self.assertEqual(v["status"], "final")
        self.assertEqual(self.store.page(self.theme)["final"]["body"]["chain"][0]["confirmed"], True)

    def test_changing_a_confirmed_link_asks_for_confirmation_again(self):
        v = self.add(INFERRED)
        self.clock.tick()
        v = self.edit("confirm", base_version=v["version"], index=0)
        self.clock.tick()
        v = self.edit("update", base_version=v["version"], index=0, link={**INFERRED, "relation": "改了"})
        self.assertEqual((v["links"][0]["confirmed"], v["unconfirmed"]), (False, 1))

    def test_confirm_cannot_be_smuggled_in_through_add_or_update(self):
        v = self.add({**INFERRED, "confirmed": True})
        self.assertEqual((v["links"][0]["confirmed"], v["unconfirmed"]), (False, 1))

    def test_confirm_needs_an_inferred_unconfirmed_link(self):
        v = self.add(SRC_LINK)
        self.clock.tick()
        self.bad("index", self.edit, "confirm", base_version=v["version"], index=0)

    def test_company_links_point_at_tracked_entities_with_names(self):
        v = self.add(self.company_link(revenue_share={"range": [8, 12], "source": SOURCE}, role="laggard"))
        link = v["links"][0]
        self.assertEqual((link["to"]["name"], link["to"]["type"]), ("範例封裝廠", "company"))
        self.assertEqual((link["revenue_share"]["range"], link["role"]), ([8, 12], "laggard"))
        self.bad("chain.1.to", self.add, {**self.company_link(), "to": {"entity_id": "E-" + "0" * 32}})

    def test_revenue_share_without_a_source_shows_unknown(self):
        v = self.add(self.company_link(revenue_share={"value": 40}))  # 沒有出處：AI 不能估，使用者也要附出處
        self.assertEqual(v["links"][0]["revenue_share"], "unknown")
        self.clock.tick()
        v = self.add(self.company_link())
        self.assertEqual(v["links"][1]["revenue_share"], "unknown")

    def test_stale_base_version_is_refused(self):
        v = self.add(SRC_LINK)
        self.clock.tick()
        self.bad("base_version", self.edit, "add", base_version=v["version"] - 1, link=SRC_LINK)
        self.bad("base_version", self.edit, "add", base_version=True, link=SRC_LINK)
        self.bad("base_version", self.edit, "add", link=SRC_LINK)

    def test_a_version_written_between_check_and_write_is_refused(self):
        v = self.add(SRC_LINK)
        self.clock.tick()
        real = self.store.add_theme_version

        def sneak(*a, **kw):  # 檢查之後、寫入之前，另一個分頁先存了一版
            real(self.theme, "draft", {"chain": [SRC_LINK, INFERRED]})
            return real(*a, **kw)
        with mock.patch.object(self.store, "add_theme_version", side_effect=sneak):
            self.bad("base_version", self.edit, "add", base_version=v["version"], link=SRC_LINK)
        self.assertEqual(len(self.head()["links"]), 2)  # 留下的是另一個分頁的版本，沒被蓋掉

    def test_role_op_keeps_confirmation(self):
        v = self.add(self.company_link(source=None))  # 沒有出處 = AI 推論
        self.clock.tick()
        v = self.edit("confirm", base_version=v["version"], index=0)
        self.clock.tick()
        v = self.edit("role", base_version=v["version"], index=0, role="leader")
        self.assertEqual((v["links"][0]["role"], v["links"][0]["confirmed"]), ("leader", True))
        self.bad("role", self.edit, "role", base_version=v["version"], index=0, role="boss")
        self.clock.tick()
        v = self.add(SRC_LINK)
        self.bad("index", self.edit, "role", base_version=v["version"], index=1, role="leader")  # 不是公司環節

    def test_item_source_for_revenue_share_survives(self):
        item = {"item_id": "item-example-1"}
        v = self.add(self.company_link(revenue_share={"value": 12, "source": item}))
        self.assertEqual(v["links"][0]["revenue_share"]["source"], item)
        self.clock.tick()
        v = self.edit("role", base_version=v["version"], index=0, role="laggard")
        self.assertEqual(v["links"][0]["revenue_share"], {"value": 12, "source": item})  # 採用建議不會清掉占比

    def test_bad_input_is_refused(self):
        for body in ({"op": "nope"}, {}, "x"):
            with self.subTest(body=body):
                with self.assertRaises(entities.EntityError):
                    chain.edit(APP, self.store, self.theme, body)
        self.bad("link", self.edit, "add", base_version=0, link="x")
        self.bad("op", self.edit, "publish", base_version=0)  # 沒有草稿
        v = self.add(SRC_LINK)
        for index in (-1, 1, "0", True, None):
            with self.subTest(index=index):
                self.bad("index", self.edit, "remove", base_version=v["version"], index=index)
        self.bad("chain.1.relation", self.add, {**SRC_LINK, "relation": "x" * 301})

    def test_chain_length_limit(self):
        with mock.patch.object(chain, "MAX_LINKS", 2), mock.patch.object(narratives, "MAX_LINKS", 2):
            self.add(SRC_LINK)
            self.clock.tick()
            self.add(SRC_LINK)
            self.clock.tick()
            self.bad("link", self.add, SRC_LINK)
            self.assertEqual(len(self.head()["links"]), 2)

    def test_unknown_theme_is_not_found(self):
        with self.assertRaises(entities.NotFound):
            chain.edit(APP, self.store, "E-" + "0" * 32, {"op": "add", "base_version": 0, "link": SRC_LINK})


class RoleTest(ChainCase):
    def setUp(self):
        super().setUp()
        self.company2 = self.ents.create({"type": "company", "name": "範例基板廠", "listings": [{"market": "TW", "symbol": "9903"}]})["id"]

    def two_companies(self):
        self.add(self.company_link())
        self.clock.tick()
        self.add({**self.company_link(), "to": {"entity_id": self.company2}})

    def test_suggestion_is_unknown_until_market_data_exists(self):
        self.two_companies()
        v = self.head()
        self.assertEqual([x["role_suggestion"] for x in v["links"]], ["unknown", "unknown"])
        self.assertFalse(v["market_data"])
        self.assertEqual([x["role"] for x in v["links"]], ["unknown", "unknown"])  # 沒有自動套用

    def test_suggestion_follows_relative_return_since_the_theme_started(self):
        self.two_companies()
        calls = []

        def returns(entity_id, since):
            calls.append(since)
            return {self.company: 0.30, self.company2: 0.05}[entity_id]
        v = chain.view(types.SimpleNamespace(market_returns=returns), self.store, self.theme)
        self.assertEqual([x["role_suggestion"] for x in v["links"]], ["leader", "laggard"])
        self.assertTrue(v["market_data"])
        self.assertEqual(len(set(calls)), 1)  # 起點是題材第一個版本的時間
        self.assertEqual([x["role"] for x in v["links"]], ["unknown", "unknown"])  # 建議不等於確認

    def test_my_confirmation_is_the_role_i_save(self):
        self.two_companies()
        v = self.head()
        self.clock.tick()
        v = self.edit("update", base_version=v["version"], index=0, link={**self.company_link(), "role": "leader"})
        self.assertEqual(v["links"][0]["role"], "leader")

    def test_pure_suggestion_rules(self):
        self.assertEqual(chain.suggest_roles({"a": 1.0}), {"a": "unknown"})  # 只有一家有資料：不比
        self.assertEqual(chain.suggest_roles({"a": 1.0, "b": None}), {"a": "unknown", "b": "unknown"})
        self.assertEqual(chain.suggest_roles({"a": 2, "b": 1, "c": 0}), {"a": "leader", "b": "leader", "c": "laggard"})
        self.assertEqual(chain.suggest_roles({"a": float("nan"), "b": True, "c": "x"}), {"a": "unknown", "b": "unknown", "c": "unknown"})

    def test_a_failing_market_source_degrades_to_unknown_and_logs_only_the_type(self):
        self.two_companies()

        def boom(entity_id, since):
            raise RuntimeError("secret-token-123")
        with self.assertLogs("easyread", "WARNING") as logs:
            v = chain.view(types.SimpleNamespace(market_returns=boom), self.store, self.theme)
        self.assertEqual([x["role_suggestion"] for x in v["links"]], ["unknown", "unknown"])
        self.assertNotIn("secret-token-123", "\n".join(logs.output))
        self.assertIn("RuntimeError", "\n".join(logs.output))

    def test_market_lookups_are_bounded_by_the_chain_limit(self):
        self.two_companies()
        seen = []
        with mock.patch.object(chain, "MAX_LINKS", 1):
            chain.view(types.SimpleNamespace(market_returns=lambda i, s: seen.append(i) or 0.1), self.store, self.theme)
        self.assertEqual(len(seen), 1)

    def test_market_lookups_stop_at_the_time_budget(self):
        self.two_companies()
        now = [0.0]
        seen = []

        def slow(entity_id, since):  # 每查一家花掉整個預算
            seen.append(entity_id)
            now[0] += chain.MARKET_BUDGET
            return 0.1
        out = chain._returns(types.SimpleNamespace(market_returns=slow), self.store, self.theme,
                             [self.company, self.company2], clock=lambda: now[0])
        self.assertEqual(len(seen), 1)
        self.assertEqual(list(out.values()), [0.1, None])


class ApiTest(ApiTestCase):
    def make_app(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "newsread.sqlite3"
        self.addCleanup(entities._STORES.pop, self.db, None)
        self.addCleanup(narratives._STORES.pop, self.db, None)
        self.addCleanup(ledger._SHARED.pop, self.db, None)
        return {"ledger_path": self.db}

    def test_chain_flow_over_http(self):
        self.assertEqual(self.request("GET", "/api/themes/E-" + "0" * 32 + "/chain")[0], 404)
        theme = self.request("POST", "/api/entities", {"type": "theme", "name": "範例題材"})[1]["id"]
        status, v = self.request("GET", f"/api/themes/{theme}/chain")
        self.assertEqual((status, v["links"]), (200, []))
        status, v = self.request("POST", f"/api/themes/{theme}/chain", {"op": "add", "base_version": 0, "link": INFERRED})
        self.assertEqual((status, v["links"][0]["inferred"]), (200, True))
        status, data = self.request("POST", f"/api/themes/{theme}/chain", {"op": "add", "base_version": 0, "link": INFERRED})
        self.assertEqual((status, data["field"]), (400, "base_version"))
        status, v = self.request("POST", f"/api/themes/{theme}/chain", {"op": "confirm", "base_version": 1, "index": 0})
        self.assertTrue(v["links"][0]["confirmed"])
        self.assertEqual(self.request("GET", f"/api/themes/{theme}")[1]["draft"]["body"]["chain"][0]["confirmed"], True)  # 題材頁 API 看得到同一版
        self.assertEqual(self.request("POST", f"/api/themes/{theme}/chain", {"op": "x"})[0], 400)
        self.assertEqual(self.request("POST", f"/api/themes/{theme}/chain", {"op": "add"}, token="bad")[0], 403)

    def test_theme_page_is_served(self):
        status, body = self.request("GET", "/theme/E-" + "0" * 32)
        self.assertEqual(status, 200)
        self.assertIn("/web/js/theme/chain.js", body)


if __name__ == "__main__":
    unittest.main()
