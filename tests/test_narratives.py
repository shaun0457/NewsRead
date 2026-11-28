"""Ticket 57：題材頁、論點、因果鏈、證據的資料模型和 API。題材、公司都是虛構的範例。"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from easyread import entities, ledger, narratives

from tests.doubles import ApiTestCase

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
SOURCE = {"url": "https://example.com/news/1"}
THESIS = {"claim": "範例 AI 晶片需求兩年內持續向上", "direction_implication": {"direction": "bull", "targets": []},
          "timing": "now", "edge": "先進封裝產能吃緊帶來漲價", "horizon": "2y", "refute_if": "雲端業者連兩季下修資本支出"}


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def tick(self, minutes=1):
        self.t += timedelta(minutes=minutes)
        return ledger.iso(self.t)


class StoreCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.index = ledger.Index(Path(tmp.name) / "newsread.sqlite3", clock=self.clock)
        self.ents = entities.Store(self.index)
        self.store = narratives.Store(self.index)
        self.theme = self.ents.create({"type": "theme", "name": "範例先進封裝"})["id"]
        self.company = self.ents.create({"type": "company", "name": "範例封裝廠", "listings": [{"market": "TW", "symbol": "9902"}]})["id"]
        self.thesis = self.store.add_thesis(self.theme, "final", {**THESIS, "direction_implication": {"direction": "bull", "targets": [self.company]}})["id"]

    def bad(self, field, fn, *a, **kw):
        with self.assertRaises(entities.EntityError) as e:
            fn(*a, **kw)
        self.assertEqual(e.exception.field, field)

    def thesis_view(self, at=None):
        return next(t for t in self.store.page(self.theme, at)["theses"] if t["id"] == self.thesis)

    def manifest(self, version="v1"):
        self.clock.tick()
        return self.index.add_manifest(task="draft", prompt_version=version, items=[])

    def evidence(self, relation="strengthens", grade="B", by=narratives.ME, item="item-1", **kw):
        self.clock.tick()
        return self.store.add_evidence(self.thesis, {"item_id": item, "relation": relation, "grade": grade, "reason": "範例理由",
                                                     "source": SOURCE}, by=by, **kw)["id"]


class VersionTest(StoreCase):
    def test_draft_never_replaces_the_final(self):
        self.store.add_theme_version(self.theme, "final", {"one_liner": "定稿的故事"})
        self.clock.tick()
        self.store.add_theme_version(self.theme, "draft", {"one_liner": "新草稿"})
        page = self.store.page(self.theme)
        self.assertEqual((page["final"]["body"]["one_liner"], page["draft"]["body"]["one_liner"]), ("定稿的故事", "新草稿"))
        self.clock.tick()
        self.store.add_theme_version(self.theme, "final", {"one_liner": "第二版定稿"})
        page = self.store.page(self.theme)
        self.assertEqual(page["final"]["version"], 3)
        self.assertIsNone(page["draft"])  # 比定稿舊的草稿不再顯示

    def test_point_in_time_query_returns_the_versions_of_that_moment(self):
        self.store.add_theme_version(self.theme, "final", {"one_liner": "第一版"})
        between = self.clock.tick()
        self.clock.tick()
        self.store.add_theme_version(self.theme, "final", {"one_liner": "第二版"})
        self.store.add_thesis_version(self.thesis, "final", {**THESIS, "claim": "改過的論點",
                                                             "direction_implication": {"direction": "bull", "targets": [self.company]}})
        old = self.store.page(self.theme, between)
        self.assertEqual(old["final"]["body"]["one_liner"], "第一版")
        self.assertEqual(old["theses"][0]["final"]["body"]["claim"], THESIS["claim"])
        self.assertEqual(self.store.page(self.theme)["theses"][0]["final"]["body"]["claim"], "改過的論點")
        self.assertEqual(self.store.page(self.theme, ledger.iso(T0 - timedelta(days=1)))["theses"], [])

    def test_final_needs_the_full_story_but_a_draft_can_be_partial(self):
        self.store.add_theme_version(self.theme, "final", {"analogy": "只有類比"})  # 題材的一句話故事可以之後再寫
        self.store.add_theme_version(self.theme, "draft", {"analogy": "只有類比"})
        for field in ("timing", "edge", "horizon", "refute_if"):
            with self.subTest(field=field):
                body = {**THESIS, "direction_implication": {"direction": "bull", "targets": [self.company]}, field: None}
                self.bad(field, self.store.add_thesis, self.theme, "final", body)
        self.bad("direction_implication.targets", self.store.add_thesis, self.theme, "final", THESIS)
        self.store.add_thesis(self.theme, "draft", {"claim": "只有一句話的草稿"})
        self.bad("claim", self.store.add_thesis, self.theme, "draft", {"edge": "沒有論點"})

    def test_only_theme_entities_have_theme_pages(self):
        self.bad("theme_id", self.store.add_theme_version, self.company, "draft", {})
        with self.assertRaises(entities.NotFound):
            self.store.page("E-" + "0" * 32)

    def test_ai_drafts_need_a_manifest_and_are_ledgered_together(self):
        who = "ai:opus@v1"
        self.bad("status", self.store.add_theme_version, self.theme, "final", {"one_liner": "x"}, by=who, context_manifest=self.manifest())
        self.bad("context_manifest", self.store.add_theme_version, self.theme, "draft", {}, by=who)
        bad_manifest = self.manifest("v2")  # prompt 版本對不上：帳本擋下，版本也不能留下
        self.bad("context_manifest", self.store.add_theme_version, self.theme, "draft", {"one_liner": "x"}, by=who, context_manifest=bad_manifest)
        self.assertIsNone(self.store.page(self.theme)["draft"])
        mid = self.manifest()
        self.clock.tick()
        row = self.store.add_theme_version(self.theme, "draft", {"one_liner": "AI 草稿"}, by=who, context_manifest=mid)
        draft = self.index.records(kind="draft")
        self.assertEqual([(r["who"], r["context_manifest"], r["payload"]["version_id"]) for r in draft], [(who, mid, row["id"])])
        self.assertEqual(self.store.page(self.theme)["draft"]["context_manifest"], mid)

    def test_new_tables_are_append_only(self):
        self.store.add_theme_version(self.theme, "draft", {})
        self.evidence()
        db = sqlite3.connect(self.index.path)
        self.addCleanup(db.close)
        db.execute("PRAGMA recursive_triggers=ON")
        for table in narratives.APPEND_ONLY:
            for sql in (f"UPDATE {table} SET rowid=rowid", f"DELETE FROM {table}"):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                    db.execute(sql)

    def test_version_and_thesis_limits(self):
        with mock.patch.object(narratives, "MAX_VERSIONS", 2):
            self.store.add_theme_version(self.theme, "draft", {})
            self.store.add_theme_version(self.theme, "draft", {})
            self.bad("status", self.store.add_theme_version, self.theme, "draft", {})
        with mock.patch.object(narratives, "MAX_THESES", 2):
            self.store.add_thesis(self.theme, "draft", {"claim": "第二個"})
            self.bad("theme_id", self.store.add_thesis, self.theme, "draft", {"claim": "第三個"})


class ProvenanceTest(StoreCase):
    """Ticket 106：每個欄位記是誰寫的，AI 寫的在定稿前要看過。"""
    AI = "ai:opus@v1"
    BODY = {"one_liner": "故事", "analogy": "類比", "second_order": ["外溢一", "外溢二"],
            "chain": [{"from": {"label": "A"}, "to": {"label": "B"}, "relation": "r", "source": SOURCE}]}

    def ai_draft(self, body=None):
        mid = self.manifest()
        self.clock.tick()
        self.store.add_theme_version(self.theme, "draft", body or self.BODY, by=self.AI, context_manifest=mid)
        return self.store.page(self.theme)["draft"]

    def test_every_field_of_a_version_records_its_writer(self):
        prov = self.ai_draft()["body"]["provenance"]
        ai = {"by": self.AI, "reviewed": False}
        self.assertEqual(prov, {"one_liner": ai, "analogy": ai, "origin": ai, "stage": ai, "second_order": [ai, ai], "chain": [ai]})
        self.clock.tick()
        self.store.add_theme_version(self.theme, "draft", self.BODY)
        me = {"by": "me", "reviewed": False}
        self.assertEqual(self.store.page(self.theme)["draft"]["body"]["provenance"]["second_order"], [me, me])

    def test_provenance_in_the_body_is_ignored(self):
        ai = {"by": self.AI, "reviewed": True}
        self.store.add_theme_version(self.theme, "draft", {**self.BODY, "provenance": {"one_liner": ai}})
        self.assertEqual(self.store.page(self.theme)["draft"]["body"]["provenance"]["one_liner"], {"by": "me", "reviewed": False})

    def test_unreviewed_ai_fields_cannot_go_into_a_final(self):
        prov = narratives.provenance_of(self.ai_draft())
        body = {k: self.BODY[k] for k in self.BODY}
        self.bad("provenance", self.store.add_theme_version, self.theme, "final", body, provenance=prov)
        prov["one_liner"]["reviewed"] = True
        prov["analogy"]["reviewed"] = prov["origin"]["reviewed"] = prov["stage"]["reviewed"] = True
        prov["second_order"] = [narratives.mark(self.AI, True), narratives.mark("me")]
        prov["chain"] = [narratives.mark(self.AI, True)]
        self.clock.tick()
        self.store.add_theme_version(self.theme, "final", body, provenance=prov)
        final = self.store.page(self.theme)["final"]
        self.assertEqual(final["by"], "me")
        self.assertEqual(final["body"]["provenance"]["second_order"], [{"by": self.AI, "reviewed": True}, {"by": "me", "reviewed": False}])

    def test_bad_provenance_is_refused(self):
        good = narratives.provenance_of(None)
        good["second_order"] = [narratives.mark("me")] * 2
        good["chain"] = [narratives.mark("me")]
        cases = [("provenance", "x"), ("provenance.second_order", {**good, "second_order": []}),
                 ("provenance.one_liner", {**good, "one_liner": {"by": "someone"}}),
                 ("provenance.one_liner", {**good, "one_liner": {"by": "me", "reviewed": "yes"}}),
                 ("provenance.chain.0", {**good, "chain": [{"by": "me", "extra": 1}]})]
        for field, prov in cases:
            with self.subTest(field=field):
                self.bad(field, self.store.add_theme_version, self.theme, "draft", self.BODY, provenance=prov)
        self.store.add_theme_version(self.theme, "draft", self.BODY, provenance=good)

    def test_versions_without_stored_provenance_belong_to_their_writer(self):
        old = {"by": self.AI, "status": "draft", "body": {"one_liner": "x", "second_order": ["一"], "chain": []}}
        prov = narratives.provenance_of(old)
        self.assertEqual((prov["one_liner"], prov["second_order"], prov["chain"]), ({"by": self.AI, "reviewed": False}, [{"by": self.AI, "reviewed": False}], []))
        broken = {"by": "me", "body": {"second_order": ["一"], "provenance": {"second_order": []}}}  # 存的對不上內容
        self.assertEqual(narratives.provenance_of(broken)["second_order"], [{"by": "me", "reviewed": False}])
        self.assertEqual(narratives.provenance_of(None)["chain"], [])


class ChainTest(StoreCase):
    def link(self, **kw):
        return {"from": {"label": "CoWoS 產能"}, "to": {"entity_id": self.company}, "relation": "產能吃緊帶動接單", **kw}

    def test_links_without_a_source_are_ai_inference_and_stay_out_of_the_final(self):
        draft = self.store.add_theme_version(self.theme, "draft", {"chain": [self.link()]})
        self.assertTrue(draft["version"])
        link = self.store.page(self.theme)["draft"]["body"]["chain"][0]
        self.assertEqual((link["inferred"], link["confirmed"], link["revenue_share"], link["role"]), (True, False, "unknown", "unknown"))
        self.bad("chain.0", self.store.add_theme_version, self.theme, "final", {"one_liner": "x", "chain": [self.link()]})
        self.store.add_theme_version(self.theme, "final", {"one_liner": "x", "chain": [self.link(confirmed=True)]})
        self.assertTrue(self.store.page(self.theme)["final"]["body"]["chain"][0]["confirmed"])
        mid = self.manifest()
        self.store.add_theme_version(self.theme, "draft", {"chain": [self.link(confirmed=True)]}, by="ai:opus@v1", context_manifest=mid)
        self.assertFalse(self.store.page(self.theme)["draft"]["body"]["chain"][0]["confirmed"])  # AI 不能自己確認

    def test_revenue_share_without_a_source_is_unknown(self):
        body = {"one_liner": "x", "chain": [
            self.link(source=SOURCE, revenue_share={"value": 35}, role="leader"),
            self.link(source=SOURCE, revenue_share={"range": [10, 20], "source": {"item_id": "item-9"}}),
            self.link(source=SOURCE, revenue_share={"value": 50, "source": SOURCE}, role="laggard")]}
        self.store.add_theme_version(self.theme, "final", body)
        chain = self.store.page(self.theme)["final"]["body"]["chain"]
        self.assertEqual(chain[0]["revenue_share"], "unknown")
        self.assertEqual(chain[0]["role"], "leader")
        self.assertEqual(chain[1]["revenue_share"], {"range": [10, 20], "source": {"item_id": "item-9"}})
        self.assertEqual(chain[2]["revenue_share"], {"value": 50, "source": SOURCE})
        self.assertFalse(chain[0]["inferred"])

    def test_bad_links_are_rejected(self):
        to_label = {"from": {"label": "需求"}, "to": {"label": "瓶頸"}, "relation": "r", "source": SOURCE}
        for link, field in ((dict(to_label, revenue_share={"value": 5, "source": SOURCE}), "chain.0"),
                            (dict(to_label, role="leader"), "chain.0"),
                            (self.link(source=SOURCE, revenue_share={"value": 120, "source": SOURCE}), "chain.0.revenue_share.value"),
                            (self.link(source=SOURCE, revenue_share={"range": [30, 10], "source": SOURCE}), "chain.0.revenue_share.range"),
                            (self.link(source={"url": "javascript:alert(1)"}), "chain.0.source"),
                            (self.link(to={"entity_id": "E-" + "1" * 32}), "chain.0.to"),
                            (self.link(role="king"), "chain.0.role")):
            with self.subTest(field=field, link=str(link)[:60]):
                self.bad(field, self.store.add_theme_version, self.theme, "draft", {"chain": [link]})
        with mock.patch.object(narratives, "MAX_LINKS", 2):
            self.bad("chain", self.store.add_theme_version, self.theme, "draft", {"chain": [self.link()] * 3})


class StatusTest(StoreCase):
    def test_status_changes_need_matching_evidence(self):
        self.bad("evidence", self.store.set_status, self.thesis, "strengthening", [])
        weak = self.evidence("weakens")
        self.bad("evidence", self.store.set_status, self.thesis, "strengthening", [weak])
        self.bad("reason", self.store.set_status, self.thesis, "retired", [])
        other = self.store.add_thesis(self.theme, "draft", {"claim": "另一個論點"})["id"]
        self.bad("evidence", self.store.set_status, other, "weakening", [weak])  # 別的論點的證據
        self.assertEqual(self.thesis_view()["status"], "open")
        self.store.set_status(self.thesis, "weakening", [weak])
        self.store.set_status(self.thesis, "refuted", [weak])
        self.store.set_status(self.thesis, "retired", reason="題材結束")
        self.assertEqual(self.thesis_view()["status"], "retired")
        history = self.store.history(self.thesis)
        self.assertEqual([(r["payload"]["from"], r["payload"]["to"]) for r in history],
                         [("open", "weakening"), ("weakening", "refuted"), ("refuted", "retired")])
        self.assertTrue(all(r["kind"] == "thesis_status" and r["who"] == "me" for r in history))
        self.bad("to", self.store.set_status, self.thesis, "retired", reason="再一次")

    def test_ai_can_only_propose_and_the_status_waits_for_me(self):
        mid = self.manifest()
        ev = self.evidence(by="ai:opus@v1", context_manifest=mid)
        proposal = self.store.propose_status(self.thesis, "strengthening", [ev], "法說會上調", "ai:opus@v1", mid)
        view = self.thesis_view()
        self.assertEqual(view["status"], "open")
        self.assertEqual([p["id"] for p in view["proposals"]], [proposal["id"]])
        self.bad("to", self.store.set_status, self.thesis, "weakening", confirms=proposal["id"])
        self.store.set_status(self.thesis, "strengthening", confirms=proposal["id"])
        view = self.thesis_view()
        self.assertEqual((view["status"], view["proposals"]), ("strengthening", []))
        self.assertEqual(self.store.history(self.thesis)[-1]["payload"]["evidence"], [ev])
        self.bad("confirms", self.store.set_status, self.thesis, "strengthening", confirms=proposal["id"])
        self.bad("by", self.store.propose_status, self.thesis, "weakening", [ev], "x", "me", mid)

    def test_rejected_proposals_leave_the_status_alone(self):
        mid = self.manifest()
        ev = self.evidence("weakens", by="ai:opus@v1", context_manifest=mid)
        proposal = self.store.propose_status(self.thesis, "refuted", [ev], "被推翻了", "ai:opus@v1", mid)
        self.store.reject_proposal(self.thesis, proposal["id"], "證據太弱")
        view = self.thesis_view()
        self.assertEqual((view["status"], view["proposals"]), ("open", []))
        self.bad("confirms", self.store.set_status, self.thesis, "refuted", confirms=proposal["id"])

    def test_status_at_a_past_time(self):
        ev = self.evidence()
        before = self.clock.tick()
        self.clock.tick()
        self.store.set_status(self.thesis, "strengthening", [ev])
        self.assertEqual(self.thesis_view(before)["status"], "open")
        self.assertEqual(self.thesis_view()["status"], "strengthening")


class VisibleEvidenceTest(StoreCase):
    def test_unseen_ai_evidence_does_not_leak(self):
        mid = self.manifest()
        hidden = self.evidence(grade="A", by="ai:opus@v1", context_manifest=mid, item="item-new")
        self.evidence(grade="C", item="item-mine")
        view = self.thesis_view()
        self.assertEqual([e["item_id"] for e in view["evidence"]], ["item-mine"])
        self.assertTrue(view["missing_first_hand"])  # 看得到的只有 C 級
        self.index.record_exposure("item-new", "theme")
        view = self.thesis_view()
        self.assertEqual([e["id"] for e in view["evidence"]][0], hidden)  # A、B 級排前面
        self.assertFalse(view["missing_first_hand"])

    def test_my_judgment_or_a_confirmed_status_makes_evidence_visible(self):
        mid = self.manifest()
        judged = self.evidence(grade="D", by="ai:opus@v1", context_manifest=mid, item="item-j")
        cited = self.evidence(grade="D", by="ai:opus@v1", context_manifest=mid, item="item-c")
        self.assertEqual(self.thesis_view()["evidence"], [])
        self.assertFalse(self.thesis_view()["missing_first_hand"])  # 沒有證據不算「缺第一手」
        self.index.append("judgment", "me", {"item": "item-j", "target": self.thesis, "relation": "strengthens"})
        self.assertEqual([e["id"] for e in self.thesis_view()["evidence"]], [judged])
        self.store.set_status(self.thesis, "strengthening", [cited])
        self.assertEqual({e["id"] for e in self.thesis_view()["evidence"]}, {judged, cited})
        self.assertTrue(self.thesis_view()["missing_first_hand"])

    def test_story_evidence_is_visible_through_any_of_its_items(self):
        story = self.index.ensure_story("item-s1", None)
        mid = self.manifest()
        self.clock.tick()
        self.store.add_evidence(self.thesis, {"story_id": story, "relation": "strengthens", "grade": "B", "reason": "r"},
                                by="ai:opus@v1", context_manifest=mid)
        self.assertEqual(self.thesis_view()["evidence"], [])
        self.index.record_exposure("item-s1", "today")
        self.assertEqual(self.thesis_view()["evidence"][0]["story_id"], story)

    def test_evidence_input_and_limits(self):
        self.bad("item_id", self.store.add_evidence, self.thesis, {"relation": "strengthens", "grade": "A", "reason": "r"})
        self.bad("story_id", self.store.add_evidence, self.thesis, {"story_id": "S-" + "0" * 32, "relation": "strengthens",
                                                                    "grade": "A", "reason": "r"})
        self.bad("grade", self.store.add_evidence, self.thesis, {"item_id": "i", "relation": "strengthens", "grade": "E", "reason": "r"})
        self.bad("context_manifest", self.store.add_evidence, self.thesis,
                 {"item_id": "i", "relation": "strengthens", "grade": "A", "reason": "r"}, by="ai:opus@v1")
        with mock.patch.object(narratives, "MAX_EVIDENCE", 2):
            self.evidence()
            self.evidence()
            self.bad("thesis_id", self.evidence)
        with mock.patch.object(narratives, "MAX_LIST_EVIDENCE", 1):
            self.assertEqual(len(self.thesis_view()["evidence"]), 1)

    def test_page_stays_fast_with_many_items_judgments_and_hidden_evidence(self):
        import time
        mid = self.manifest()
        n_items, n_judged = 3000, 800
        with self.index.write() as db:
            now = self.index.now()
            db.executemany("INSERT INTO stories VALUES (?,?,?,?)", [(f"S-{i:032x}", f"it{i}", "", now) for i in range(n_items)])
            db.executemany("INSERT INTO item_story VALUES (?,?,?)", [(f"it{i}", f"S-{i:032x}", now) for i in range(n_items)])
            db.executemany("INSERT INTO exposures (item_id, place, at) VALUES (?,?,?)", [(f"it{i}", "today", now) for i in range(0, n_items, 2)])
            for i in range(n_judged):
                self.index.append_in(db, "judgment", "me", {"item": f"it{i}", "target": self.thesis, "relation": "strengthens"})
            rows = [(f"EV-{i:032x}", self.thesis, f"new{i}" if i % 2 else None, None if i % 2 else f"S-{i:032x}", "strengthens",
                     "A" if i % 3 else "C", "r", None, "ai:opus@v1", now, mid) for i in range(narratives.MAX_EVIDENCE)]
            db.executemany("INSERT INTO evidence (id, thesis_id, item_id, story_id, relation, grade, reason, source, by, created_at, "
                           "context_manifest) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        start = time.monotonic()
        view = self.thesis_view()
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(len(view["evidence"]), narratives.MAX_LIST_EVIDENCE)
        # Story 證據 S-i（i 是偶數）：成員 it{i} 有揭露 → 看得到；item 證據 new{i} 都沒揭露 → 看不到
        self.assertTrue(all(e["story_id"] for e in view["evidence"]))
        self.assertTrue(all(e["grade"] == "A" for e in view["evidence"]))

    def test_proposals_list_what_showing_them_would_expose(self):
        mid = self.manifest()
        ev = self.evidence(by="ai:opus@v1", context_manifest=mid, item="item-unseen")
        self.store.propose_status(self.thesis, "strengthening", [ev], "r", "ai:opus@v1", mid)
        self.assertEqual(self.thesis_view()["proposals"][0]["exposes"], ["item-unseen"])
        self.index.record_exposure("item-unseen", "theme")
        self.assertEqual(self.thesis_view()["proposals"][0]["exposes"], [])

    def test_ai_manifest_rules_apply_to_drafts_evidence_and_proposals(self):
        wrong = self.manifest("v2")
        self.bad("context_manifest", self.store.add_theme_version, self.theme, "draft", {}, by="ai:opus@v1",
                 context_manifest="M-" + "0" * 32)  # 不存在：不能變成資料庫錯誤
        self.bad("context_manifest", self.evidence, by="ai:opus@v1", context_manifest=wrong)
        ev = self.evidence()
        self.bad("context_manifest", self.store.propose_status, self.thesis, "strengthening", [ev], "r", "ai:opus@v1", wrong)

    def test_bad_cited_and_confirms_values_are_input_errors(self):
        for bad in ([[1]], [{}], ["EV-x"]):
            with self.subTest(bad=bad):
                self.bad("evidence", self.store.set_status, self.thesis, "strengthening", bad)
        for bad in (0, [], {}, False, 5):
            with self.subTest(confirms=bad):
                self.bad("confirms", self.store.set_status, self.thesis, "retired", reason="r", confirms=bad)
        self.assertEqual(self.thesis_view()["status"], "open")

    def test_append_in_refuses_to_run_outside_a_write_transaction(self):
        with self.index.read() as db, self.assertRaises(RuntimeError):
            self.index.append_in(db, "judgment", "me", {"item": "i"})
        self.assertEqual(self.index.records(kind="judgment"), [])

    def test_more_limits(self):
        self.bad("second_order", self.store.add_theme_version, self.theme, "draft",
                 {"second_order": ["x"] * (narratives.MAX_SECOND_ORDER + 1)})
        self.bad("direction_implication.targets", self.store.add_thesis, self.theme, "draft",
                 {"claim": "c", "direction_implication": {"direction": "bull", "targets": [self.company] * (narratives.MAX_TARGETS + 1)}})
        with mock.patch.object(narratives, "MAX_THESES", 1):
            self.assertEqual(len(self.store.page(self.theme)["theses"]), 1)
        ev = self.evidence("weakens")
        self.store.set_status(self.thesis, "weakening", [ev])
        self.store.set_status(self.thesis, "retired", reason="r")
        self.assertEqual(len(self.store.history(self.thesis, limit=1)), 1)

    def test_proposal_list_is_bounded(self):
        mid = self.manifest()
        ev = self.evidence(by="ai:opus@v1", context_manifest=mid)
        for _ in range(3):
            self.store.propose_status(self.thesis, "strengthening", [ev], "r", "ai:opus@v1", mid)
        with mock.patch.object(narratives, "MAX_PROPOSALS", 2):
            self.assertEqual(len(self.thesis_view()["proposals"]), 2)
        with mock.patch.object(narratives, "MAX_CITED", 1):
            self.bad("evidence", self.store.set_status, self.thesis, "strengthening", [ev, self.evidence()])


class StringsTest(unittest.TestCase):
    def test_traditional_strings_survive_the_zh_tw_conversion(self):
        # 字串本來就是繁體；s2twp 可能把用語換掉（例如「對象」→「物件」），zh-TW.json 要把它們固定住
        import re
        from easyread import i18n
        if not i18n._tw_converter():
            self.skipTest("opencc not installed")
        keys = re.findall(r'tr\("((?:[^"\\]|\\.)*)"', Path(narratives.__file__).read_text(encoding="utf-8"))
        self.assertGreater(len(keys), 20)
        for key in keys:
            self.assertEqual(i18n._tw_text(key), key, key)


class ApiTest(ApiTestCase):
    def make_app(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "newsread.sqlite3"
        self.addCleanup(entities._STORES.pop, self.db, None)
        self.addCleanup(narratives._STORES.pop, self.db, None)
        self.addCleanup(ledger._SHARED.pop, self.db, None)
        return {"ledger_path": self.db}

    def ok(self, method, path, body=None):
        status, data = self.request(method, path, body)
        self.assertEqual(status, 200, data)
        return data

    def test_theme_page_flow_over_http(self):
        self.assertEqual(self.request("GET", "/api/themes/E-" + "0" * 32)[0], 404)  # 資料庫還沒建：不建檔
        self.assertFalse(self.db.exists())
        theme = self.ok("POST", "/api/entities", {"type": "theme", "name": "範例題材"})["id"]
        page = self.ok("POST", f"/api/themes/{theme}/versions", {"status": "final", "body": {"one_liner": "一句話"}})
        self.assertEqual(page["final"]["by"], "me")
        ai = {"by": "ai:opus@v1", "reviewed": True}  # 從 HTTP 寫的整份都是我寫的，body 裡的 provenance 不看
        page = self.ok("POST", f"/api/themes/{theme}/versions", {"status": "draft", "body": {"one_liner": "x", "provenance": {"one_liner": ai}}})
        self.assertEqual(page["draft"]["body"]["provenance"]["one_liner"], {"by": "me", "reviewed": False})
        page = self.ok("POST", f"/api/themes/{theme}/theses", {"status": "draft", "body": {"claim": "論點"}})
        thesis = page["theses"][0]["id"]
        page = self.ok("POST", f"/api/theses/{thesis}/evidence", {"item_id": "item-1", "relation": "weakens", "grade": "A", "reason": "r"})
        ev = page["theses"][0]["evidence"][0]["id"]
        status, data = self.request("POST", f"/api/theses/{thesis}/status", {"to": "weakening"})
        self.assertEqual((status, data["field"]), (400, "evidence"))
        page = self.ok("POST", f"/api/theses/{thesis}/status", {"to": "weakening", "evidence": [ev]})
        self.assertEqual(page["theses"][0]["status"], "weakening")
        self.assertEqual(len(self.ok("GET", f"/api/theses/{thesis}/history")["records"]), 1)
        at = page["theses"][0]["created_at"]
        self.assertEqual(self.ok("GET", f"/api/themes/{theme}?at={quote(at)}")["at"], at)
        self.assertEqual(self.request("GET", f"/api/themes/{theme}?at=yesterday")[0], 400)
        self.assertEqual(self.request("POST", "/api/theses/T-bad/status", {"to": "open"})[0], 404)
        self.assertEqual(self.request("POST", f"/api/theses/{thesis}/nope", {})[0], 404)

    def test_body_size_is_capped(self):
        with mock.patch.object(narratives, "MAX_BODY", 100):
            status, _ = self.request("POST", "/api/themes/E-" + "0" * 32 + "/versions", {"body": {"analogy": "x" * 200}})
        self.assertEqual(status, 413)

    def test_writes_need_the_token(self):
        status, _ = self.request("POST", "/api/themes/E-" + "0" * 32 + "/versions", {}, token="wrong")
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
