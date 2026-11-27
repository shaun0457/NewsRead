"""Ticket 14：AI 分類寫進帳本。用假的 AI adapter（不呼叫真的 CLI），資料都是虛構的範例。"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from easyread import ai_engines as ai
from easyread import entities, ingest, ledger, narratives, triage
from easyread.library import Library
from tests.doubles import ApiTestCase
from tests.test_ai_engines import FOUND_ALL, FakeAdapter, ok

PARAS = ["範例科技（範例）公告第三季營收年增 30%，主因 AI 伺服器出貨。",
         "公司表示 CoWoS 產能明年將再擴充一倍。",
         "分析師認為股價已經反映大部分利多。"]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class FakeJobs:
    def enqueue(self, *a, **kw):
        raise ValueError("busy")  # 匯入照樣成功，不翻譯


class Adapter:
    """假的 Claude Code。step 可以是結果、AIError，或拿 prompt 算出結果的函式（追蹤對象的代號要從 prompt 查）。"""

    def __init__(self):
        self.steps: list = []
        self.prompts: list[tuple[str, bool]] = []
        self.specs: list[dict] = []

    def call(self, spec, prompt, cancel=None, json_mode=False):
        self.prompts.append((prompt, json_mode))
        self.specs.append(dict(spec))
        if not self.steps:
            raise AssertionError("unexpected call")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step(prompt) if callable(step) else step

    def check(self, spec):
        pass


def refs(prompt: str) -> dict[str, str]:
    """prompt 清單裡的代號：追蹤對象用名稱查，論點用 T1、T2…（依出現順序）。"""
    out, n = {}, 0
    for line in prompt.splitlines():
        head = line.split("｜")
        if len(head) > 1 and head[0][:1] in "et" and head[0][1:].isdigit():
            if head[0][0] == "e":
                out[head[1]] = head[0]
            else:
                n += 1
                out[f"T{n}"] = head[0]
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.app = types.SimpleNamespace(lib=Library(root / "lib"), ledger_path=root / "newsread.sqlite3", jobs=FakeJobs())
        self.addCleanup(triage._STORES.pop, self.app.ledger_path, None)
        patcher = mock.patch.object(ingest.config, "load", lambda: {"auto_translate": False})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = triage.store(self.app)
        self.index = self.store.index
        self.ents = entities.Store(self.index)
        self.narr = narratives.Store(self.index)
        self.company = self.ents.create({"type": "company", "name": "範例科技", "listings": [{"market": "TW", "symbol": "9999"}],
                                         "aliases": ["範例"]})["id"]
        self.archived = self.ents.create({"type": "company", "name": "封存範例"})["id"]
        self.ents.set_archived(self.archived, True)
        self.theme = self.ents.create({"type": "theme", "name": "AI 伺服器（範例）"})["id"]
        final = {"claim": "AI 伺服器需求兩年向上（範例）", "direction_implication": {"direction": "bull", "targets": [self.company]},
                 "timing": "now", "edge": "analysis", "horizon": "2 年", "refute_if": "雲端資本支出連兩季下修"}
        self.thesis = self.narr.add_thesis(self.theme, "final", final)["id"]
        self.draft = self.narr.add_thesis(self.theme, "draft", {"claim": "草稿論點不送（範例）"})["id"]
        self.adapter = Adapter()
        self.adapters = {e: FakeAdapter() for e in ai.ENGINES}
        self.adapters["claude"] = self.adapter
        self.settings = ai.Settings(root / "ai.json")
        # 這些測試用假的 Claude Code 跑背景分類：打開「背景工作也可以用訂閱」（預設關，見 ticket 68 的條款查證）
        self.settings.update(lambda d: d["guard"].__setitem__("background_subscription", True))
        self.found = json.loads(json.dumps(FOUND_ALL))

    def engine(self):
        return ai.Engines(self.settings, self.index, adapters=self.adapters, detector=lambda fresh=False: self.found,
                          wait=lambda s, c: None, has_sdk=lambda: True, quota=lambda: None)

    def add(self, published: datetime | None = None, text: str | None = None, title: str = "範例新聞", url: str = "") -> str:
        body = {"text": text or "\n\n".join(PARAS), "title": title, "url": url}
        if published is not None:
            body["published_at"] = iso(published)
        return ingest.from_text(self.app, body)["id"]

    def answer(self, **over):
        """AI 的回答。ref 寫成 @名稱 或 @T1，送出時換成 prompt 裡的代號。"""
        out = {"entities": [{"ref": "@範例科技", "importance": "high", "noise_kind": None, "relation": "bull", "confidence": "mid",
                             "reason": "營收年增 30%"}],
               "theses": [{"ref": "@T1", "relation": "strengthens", "grade": "A", "importance": "high", "noise_kind": None,
                           "confidence": "high", "reason": "公司公告營收成長"}],
               "points": [{"text": "營收年增 30%", "cites": [{"p": 1, "quote": "第三季營收年增 30%"}]},
                          {"text": "產能擴充", "cites": [{"p": 2, "quote": "這句不在原文裡"}]},
                          {"text": "市場可能已經反映", "cites": []}]}
        out.update(over)

        def step(prompt):
            table = refs(prompt)
            data = json.loads(json.dumps(out))
            for key in ("entities", "theses"):
                for entry in data.get(key) or []:
                    if isinstance(entry, dict) and str(entry.get("ref", "")).startswith("@"):
                        entry["ref"] = table.get(entry["ref"][1:], "e999")
            return ok("```json\n" + json.dumps(data, ensure_ascii=False) + "\n```")
        return step

    def triage_round(self, *steps, limit=triage.MAX_PER_ROUND):
        self.adapter.steps.extend(steps)
        return triage.run_pending(self.app, limit=limit, engine=self.engine())

    def rows(self, sql, *args):
        with self.index.read() as db:
            return [dict(r) for r in db.execute(sql, args)]


class TriageTest(Base):
    def recent(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(hours=1)

    def test_triage_writes_links_evidence_judgments_and_usage(self):
        item = self.add(self.recent())
        self.assertEqual(self.store.view(item)["state"], "pending")
        counts = self.triage_round(self.answer(entities=[
            {"ref": "@範例科技", "importance": "high", "noise_kind": None, "relation": "bull", "confidence": "mid", "reason": "營收年增 30%"},
            {"ref": "@封存範例", "importance": "noise", "noise_kind": "short_term", "relation": "noise", "confidence": "low",
             "reason": "對它只是短期波動"}]))
        self.assertEqual(counts["done"], 1)
        prompt, json_mode = self.adapter.prompts[0]
        self.assertTrue(json_mode)
        self.assertIn("AI 伺服器需求兩年向上", prompt)
        self.assertNotIn("草稿論點不送", prompt)  # 只送定稿
        self.assertIn("封存範例", prompt)  # 已封存的也送
        view = self.store.view(item)
        self.assertEqual(view["state"], "done")
        result = view["result"]
        self.assertEqual(result["importance"], "high")
        self.assertEqual([e["id"] for e in result["entities"]], [self.company, self.archived])
        self.assertEqual(result["entities"][1]["noise_kind"], "short_term")  # 雜訊相對於這個追蹤對象
        self.assertEqual(result["theses"][0]["id"], self.thesis)
        self.assertEqual([p["text"] for p in result["points"]], ["營收年增 30%", "市場可能已經反映"])
        self.assertEqual(result["points"][0]["cites"][0]["n"], 1)
        self.assertTrue(result["points"][1]["inferred"])  # 沒出處 = AI 推論
        self.assertEqual(result["dropped"]["points"], 1)  # 引述不在原文裡：不顯示
        mentions = self.rows("SELECT entity_id, source FROM mentions WHERE item_id=? ORDER BY entity_id", item)
        self.assertEqual({m["entity_id"] for m in mentions}, {self.company, self.archived})
        self.assertTrue(all(m["source"] == "ai" for m in mentions))
        ev = self.rows("SELECT * FROM evidence WHERE item_id=?", item)
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["relation"], ev[0]["grade"], ev[0]["thesis_id"]), ("strengthens", "A", self.thesis))
        self.assertTrue(ev[0]["by"].startswith("ai:") and ev[0]["context_manifest"])
        judgments = self.index.records("judgment")
        self.assertEqual(len(judgments), 1)  # 有論點時每個論點一筆，不再替追蹤對象寫
        j = judgments[0]
        p = j["payload"]
        self.assertEqual(p["target"], {"type": "thesis", "id": self.thesis})
        self.assertEqual((p["relation"], p["signal"], p["confidence"], p["importance"]), ("strengthens", True, "high", "high"))
        self.assertFalse(p["retrospective"])
        self.assertEqual(p["baseline"][0]["entity"], self.company)
        self.assertEqual(p["baseline"][0]["benchmark"], entities.DEFAULT_BENCHMARK["TW"])
        self.assertTrue(p["prompt_version"].startswith(triage.PROMPT_VERSION + "@claude/"))
        self.assertTrue(j["who"].endswith("@" + p["prompt_version"]))
        self.assertEqual(p["story"], self.index.story_of(item))
        manifest = self.index.manifest(j["context_manifest"])
        self.assertEqual(manifest["items"][0]["id"], item)
        self.assertEqual([t["id"] for t in manifest["theses"]], [self.thesis])
        self.assertEqual(manifest["prompt_version"], p["prompt_version"])
        usage = self.index.usage()
        self.assertEqual([(u["task"], u["source"], u["engine"]) for u in usage], [("triage", "triage", "claude")])
        self.assertTrue(self.index.verify()["ok"])

    def test_without_theses_each_entity_gets_a_judgment(self):
        item = self.add(self.recent())
        self.triage_round(self.answer(theses=[]))
        judgments = self.index.records("judgment")
        self.assertEqual(len(judgments), 1)
        self.assertEqual(judgments[0]["payload"]["target"]["type"], "entity")
        self.assertEqual(judgments[0]["payload"]["relation"], "bull")
        self.assertEqual(self.store.view(item)["state"], "done")

    def test_unknown_refs_and_bad_entries_are_dropped(self):
        item = self.add(self.recent())
        bad = [{"ref": "e999", "importance": "high", "noise_kind": None, "relation": "bull", "confidence": "mid", "reason": "x"},
               {"ref": "@範例科技", "importance": "noise", "noise_kind": None, "relation": "noise", "confidence": "mid", "reason": "x"},
               {"ref": "E-" + "0" * 32, "importance": "high", "noise_kind": None, "relation": "bull", "confidence": "mid", "reason": "x"},
               "not an object"]
        self.triage_round(self.answer(entities=bad, theses=[{"ref": "t99", "relation": "weakens", "grade": "A", "importance": "high",
                                                       "noise_kind": None, "confidence": "low", "reason": "x"}]))
        result = self.store.view(item)["result"]
        self.assertEqual(result["entities"], [])
        self.assertEqual(result["dropped"]["entities"], 4)
        self.assertEqual(result["dropped"]["theses"], 1)
        self.assertEqual(self.index.records("judgment"), [])

    def test_output_limits(self):
        item = self.add(self.recent())
        many = [{"text": f"第 {i} 點", "cites": []} for i in range(triage.MAX_POINTS + 5)]
        self.triage_round(self.answer(points=many))
        result = self.store.view(item)["result"]
        self.assertEqual(len(result["points"]), triage.MAX_POINTS)
        self.assertEqual(result["dropped"]["points"], 5)
        with self.assertRaises(triage.TriageError):  # 超過 MAX_OUTPUT 的部分不看：JSON 被截斷就是格式不對
            triage.parse("{" + " " * triage.MAX_OUTPUT + "}", [], {}, {})

    def test_retrospective_and_unknown_time(self):
        old = self.add(datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc), title="舊聞範例")
        self.triage_round(self.answer())
        self.assertTrue(self.index.records("judgment")[0]["payload"]["retrospective"])
        unknown = self.add(None, text="時間不明的範例新聞。\n\n" + PARAS[0], title="時間不明範例")
        self.triage_round(self.answer())
        p = self.index.records("judgment")[-1]["payload"]
        self.assertEqual(p["item"], unknown)
        self.assertTrue(p["time_unknown"])
        self.assertFalse(p["retrospective"])  # 時間不明不納入事件驗證，也不標事後補判
        self.assertNotEqual(old, unknown)

    def test_retrospective_counts_weekdays_in_taipei(self):
        r = triage.retrospective
        self.assertFalse(r("2026-11-09T09:00+08:00", "2026-11-11T09:00+08:00"))  # 週一 → 週三：2 個交易日
        self.assertTrue(r("2026-11-09T09:00+08:00", "2026-11-12T09:00+08:00"))   # 週四：3 個
        self.assertFalse(r("2026-11-13T09:00+08:00", "2026-11-17T09:00+08:00"))  # 週五 → 下週二：週末不算
        self.assertFalse(r("2026-11-11T09:00+08:00", "2026-11-11T08:00+08:00"))
        self.assertTrue(r("2024-01-01T00:00+00:00", "2026-11-11T00:00+00:00"))   # 很久以前的直接算

    def test_failures_retry_with_backoff_and_leave_no_partial_records(self):
        item = self.add(self.recent())
        self.triage_round(ai.AIError("UPSTREAM_ERROR", "上游原文 sk-secret-範例"))
        v = self.store.view(item)
        self.assertEqual((v["state"], v["attempts"], v["error"]), ("pending", 1, "UPSTREAM_ERROR"))
        self.assertNotIn("sk-secret", json.dumps(v, ensure_ascii=False))
        self.assertIsNotNone(v["next_at"])
        self.assertEqual(triage.run_pending(self.app, engine=self.engine()),
                         {k: 0 for k in ("done", "paused", "pending", "failed", "deferred", "stale", "skipped")})
        with self.index.write() as db:  # 時間到了
            db.execute("UPDATE triage_state SET next_at=NULL")
        self.triage_round(ok("不是 JSON"))
        self.assertEqual(self.store.view(item)["error"], "BAD_OUTPUT")
        with self.index.write() as db:
            db.execute("UPDATE triage_state SET next_at=NULL")
        self.triage_round(ok("[1, 2]"))
        v = self.store.view(item)
        self.assertEqual((v["state"], v["attempts"]), ("failed", triage.MAX_ATTEMPTS))
        self.assertEqual(self.index.records("judgment"), [])
        self.assertEqual(self.rows("SELECT * FROM evidence WHERE item_id=?", item), [])
        self.assertEqual(self.rows("SELECT * FROM mentions WHERE item_id=?", item), [])
        self.assertEqual(self.store.retry(item)["state"], "pending")
        self.triage_round(self.answer())
        self.assertEqual(self.store.view(item)["state"], "done")
        with self.assertRaises(entities.EntityError):
            self.store.retry(item)  # 完成的不重做

    def test_backoff_doubles(self):
        item = self.add(self.recent())
        self.triage_round(ai.AIError("TIMEOUT"))
        first = ledger.parse_time(self.store.view(item)["next_at"])
        with self.index.write() as db:
            db.execute("UPDATE triage_state SET next_at=NULL")
        self.triage_round(ai.AIError("TIMEOUT"))
        second = ledger.parse_time(self.store.view(item)["next_at"])
        now = datetime.now(timezone.utc)
        self.assertAlmostEqual((first - now).total_seconds(), triage.RETRY_BASE, delta=30)
        self.assertAlmostEqual((second - now).total_seconds(), triage.RETRY_BASE * 2, delta=30)

    def test_no_ai_keeps_it_pending_without_counting(self):
        item = self.add(self.recent())
        self.found = json.loads(json.dumps({k: {"found": False} for k in ("claude", "codex", "antigravity")}))
        self.found["ollama"] = {"running": False, "models": []}
        counts = triage.run_pending(self.app, engine=self.engine())
        self.assertEqual(counts["paused"], 1)
        v = self.store.view(item)
        self.assertEqual((v["state"], v["attempts"], v["error"]), ("pending", 0, None))

    def test_engine_gets_no_tools(self):
        self.add(self.recent())
        self.triage_round(self.answer())
        self.assertIs(self.adapter.specs[0].get("tools"), False)

    def test_only_codex_keeps_it_pending(self):
        item = self.add(self.recent())
        self.found = {"claude": {"found": False}, "codex": {"found": True}, "antigravity": {"found": True},
                      "ollama": {"running": False, "models": []}}
        engine = self.engine()
        self.assertFalse(engine.available("triage"))
        p = engine.plan("triage", self.settings.load(), self.found)
        self.assertEqual((p["state"], p["reason"]), ("no_ai", "no_tools"))
        counts = triage.run_pending(self.app, engine=engine)
        self.assertEqual(counts["paused"], 1)
        v = self.store.view(item)
        self.assertEqual((v["state"], v["attempts"], v["error"]), ("pending", 0, None))
        self.assertEqual((self.adapters["codex"].calls, self.adapters["antigravity"].calls), ([], []))
        self.assertTrue(engine.available("translate"))  # 別的工作照樣能用 Codex

    def test_codex_primary_is_skipped_for_triage(self):
        self.add(self.recent())
        codex = {"engine": "codex", "model": "", "entry": ""}
        self.settings.update(lambda d: d["tasks"]["triage"].update(primary=codex))
        self.assertEqual(triage.run_pending(self.app, engine=self.engine())["paused"], 1)  # 指定 Codex、沒備用：不分類
        claude = {"engine": "claude", "model": "", "entry": ""}
        self.settings.update(lambda d: d["tasks"]["triage"].update(fallback=claude))
        counts = self.triage_round(self.answer())
        self.assertEqual(counts["done"], 1)  # 有備用就改用 Claude Code
        self.assertEqual(self.adapters["codex"].calls, [])
        self.assertIs(self.adapter.specs[0].get("tools"), False)

    def test_auth_invalid_never_falls_back_to_codex(self):
        item = self.add(self.recent())
        counts = self.triage_round(ai.AIError("AUTH_INVALID"))  # FOUND_ALL 有 Codex；自動模式也不能換過去
        self.assertEqual(counts["paused"], 1)
        self.assertEqual((self.adapters["codex"].calls, self.adapters["antigravity"].calls), ([], []))
        self.assertEqual(self.store.view(item)["attempts"], 0)

    def test_cli_adapter_refuses_tools_off_for_codex_and_antigravity(self):
        for name in ("codex", "antigravity"):
            with self.subTest(name), mock.patch.object(ai.config, "load", lambda: {name: {}}), \
                    mock.patch.object(ai.engines, f"{name}_path", lambda c: name), \
                    mock.patch.object(ai.engines, f"run_{name}", side_effect=AssertionError("must not run")):
                with self.assertRaises(ai.AIError) as cm:
                    ai.CliAdapter(name).call({"engine": name, "model": "", "tools": False}, "p")
                self.assertEqual(cm.exception.code, "ENGINE_MISSING")

    def test_rate_limit_counts_once_and_stops_the_round(self):
        first = self.add(self.recent(), text="第一則範例新聞內容。", title="範例一")
        second = self.add(self.recent(), text="第二則範例新聞內容。", title="範例二")
        counts = self.triage_round(*[ai.AIError("RATE_LIMITED")] * ai.MAX_ATTEMPTS)
        self.assertEqual(counts["paused"], 1)
        self.assertEqual(self.store.view(first)["attempts"] + self.store.view(second)["attempts"], 1)
        self.assertEqual(len(self.adapter.prompts), ai.MAX_ATTEMPTS)  # 只有第一則試了（含退避重試）

    def test_a_failure_does_not_stop_the_round(self):
        first = self.add(self.recent(), text="第一則範例新聞內容。", title="範例一")
        second = self.add(self.recent(), text="第二則範例新聞內容。", title="範例二")
        counts = self.triage_round(ai.AIError("UPSTREAM_ERROR"), self.answer(theses=[]))
        self.assertEqual((counts["pending"], counts["done"]), (1, 1))
        self.assertEqual(self.store.view(first)["error"], "UPSTREAM_ERROR")
        self.assertEqual(self.store.view(second)["state"], "done")

    def test_unexpected_error_counts_as_internal_failure(self):
        first = self.add(self.recent(), text="第一則範例新聞內容。", title="範例一")
        second = self.add(self.recent(), text="第二則範例新聞內容。", title="範例二")
        real = self.store.triage

        def flaky(lib, item_id, *a, **kw):
            if item_id == first:
                raise RuntimeError("內部原文 sk-secret-範例")
            return real(lib, item_id, *a, **kw)
        with mock.patch.object(self.store, "triage", side_effect=flaky), self.assertLogs("easyread", "WARNING") as logs:
            counts = self.triage_round(self.answer(theses=[]))
        self.assertEqual((counts["pending"], counts["done"]), (1, 1))
        v = self.store.view(first)
        self.assertEqual((v["state"], v["attempts"], v["error"]), ("pending", 1, "INTERNAL"))
        self.assertNotIn("sk-secret", "\n".join(logs.output))
        self.assertIn("RuntimeError", "\n".join(logs.output))
        self.assertEqual(self.store.view(second)["state"], "done")

    def test_deeply_nested_json_is_bad_output(self):
        deep = "{\"a\": " + "[" * 100_000 + "]" * 100_000 + "}"
        with self.assertRaises(triage.TriageError) as cm:
            triage.parse(deep, [], {}, {})
        self.assertEqual(cm.exception.code, "BAD_OUTPUT")

    def test_publish_time_slightly_ahead_is_deferred(self):
        ahead = datetime.now(timezone.utc) + timedelta(hours=2)
        item = self.add(ahead)
        counts = triage.run_pending(self.app, engine=self.engine())
        self.assertEqual(counts["deferred"], 1)
        v = self.store.view(item)
        self.assertEqual((v["state"], v["attempts"], v["error"]), ("pending", 0, None))
        self.assertAlmostEqual(ledger.parse_time(v["next_at"]).timestamp(), ahead.replace(microsecond=0).timestamp(), delta=1)
        self.assertEqual(self.adapter.prompts, [])
        self.assertEqual(self.store.due(5), [])  # 時間到之前不會再排

    def test_publish_time_far_ahead_is_bad_time(self):
        item = self.add(datetime.now(timezone.utc) + triage.FUTURE_GRACE + timedelta(hours=1))
        triage.run_pending(self.app, engine=self.engine())
        v = self.store.view(item)
        self.assertEqual((v["state"], v["attempts"], v["error"]), ("pending", 1, "BAD_TIME"))
        self.assertEqual(self.adapter.prompts, [])

    def test_no_time_at_all_is_no_time(self):
        item = self.add(None, text="時間不明的範例新聞。\n\n" + PARAS[0], title="時間不明範例")
        self.app.lib.ws(item).update("item", lambda it: it.pop("added", None))
        triage.run_pending(self.app, engine=self.engine())
        v = self.store.view(item)
        self.assertEqual((v["error"], v["attempts"]), ("NO_TIME", 1))
        self.assertTrue(v["error_message"])
        self.assertEqual(self.adapter.prompts, [])

    def test_write_failure_rolls_back_everything(self):
        item = self.add(self.recent())
        real = self.index.append_in
        def boom(db, kind, *a, **kw):
            if kind == "judgment":
                raise ValueError("boom")
            return real(db, kind, *a, **kw)
        with mock.patch.object(self.index, "append_in", side_effect=boom):
            self.triage_round(self.answer())
        v = self.store.view(item)
        self.assertEqual((v["state"], v["error"]), ("pending", "WRITE_FAILED"))
        self.assertIsNone(v["result"])
        self.assertEqual(self.rows("SELECT * FROM evidence WHERE item_id=?", item), [])
        self.assertEqual(self.rows("SELECT * FROM mentions WHERE item_id=?", item), [])
        self.assertEqual(self.rows("SELECT * FROM triage_results"), [])

    def test_changed_content_makes_the_old_run_stale(self):
        when = self.recent()
        url = "https://example.com/news/1"
        item = self.add(when, url=url)
        old_hash = self.store.due(1)[0]["content_hash"]
        again = self.add(when, text="\n\n".join(PARAS + ["補上的一段範例。"]), url=url)
        self.assertEqual(again, item)
        self.assertEqual(self.store.due(5)[0]["item_id"], item)
        self.assertEqual(self.store.triage(self.app.lib, item, old_hash, 0, self.engine()), "stale")
        self.triage_round(self.answer())
        self.assertEqual(self.store.view(item)["state"], "done")
        self.assertNotEqual(self.store.view(item)["result"]["stale"], True)

    def test_done_content_is_not_requeued_but_new_content_is(self):
        item = self.add(self.recent())
        self.triage_round(self.answer())
        content = self.rows("SELECT content_hash FROM triage_state")[0]["content_hash"]
        self.assertFalse(self.store.enqueue(item, content))
        self.assertTrue(self.store.enqueue(item, "other-hash"))

    def test_ai_does_not_relink_a_manually_removed_mention(self):
        item = self.add(self.recent())
        self.ents.unlink(item, self.company)
        self.ents.link(item, self.company)
        self.ents.unlink(item, self.company)
        self.triage_round(self.answer())
        self.assertEqual(self.rows("SELECT removed FROM mentions WHERE item_id=? AND entity_id=?", item, self.company), [{"removed": 1}])
        self.assertEqual(self.store.view(item)["result"]["linked"], [])

    def test_round_limit(self):
        items = [self.add(self.recent(), text=f"第 {i} 則範例新聞內容。", title=f"範例 {i}") for i in range(triage.MAX_PER_ROUND + 2)]
        self.adapter.steps.extend(self.answer(theses=[], entities=[]) for _ in items)
        counts = triage.run_pending(self.app, engine=self.engine())
        self.assertEqual(counts["done"], triage.MAX_PER_ROUND)
        self.assertEqual(len(self.store.due(100)), 2)

    def test_non_article_is_skipped(self):
        self.store.enqueue("missing-item", "h")
        counts = triage.run_pending(self.app, engine=self.engine())
        self.assertEqual(counts["skipped"], 1)
        self.assertEqual(self.store.view("missing-item")["state"], "failed")
        self.assertEqual(self.adapter.prompts, [])

    def test_stop_event_ends_the_round(self):
        self.add(self.recent())
        stop = types.SimpleNamespace(is_set=lambda: True)
        counts = triage.run_pending(self.app, engine=self.engine(), cancel=stop)
        self.assertEqual(sum(counts.values()), 0)

    def test_no_pending_does_not_touch_engines(self):
        with mock.patch.object(triage.ai_engines, "for_app", side_effect=AssertionError("should not build engines")):
            self.assertEqual(triage.run_pending(self.app)["done"], 0)

    def test_rules_are_pinned(self):
        self.assertEqual(triage.RULES_SHA256, "f1606adeb2572ca00e8a6e0656c77ba40cafe71b6d34ad1af47e9db327a9ea4a")  # 改了 RULES 要換 PROMPT_VERSION

    def test_results_are_append_only(self):
        self.add(self.recent())
        self.triage_round(self.answer())
        with self.assertRaises(sqlite3.IntegrityError):
            with self.index.write() as db:
                db.execute("UPDATE triage_results SET body='{}'")


class TriageApiTest(ApiTestCase):
    def make_app(self):
        self.base_case = Base("setUp")
        self.base_case.setUp()
        self.addCleanup(self.base_case.doCleanups)
        return {"lib": self.base_case.app.lib, "ledger_path": self.base_case.app.ledger_path}

    def test_get_and_retry(self):
        b = self.base_case
        item = b.add(datetime.now(timezone.utc) - timedelta(hours=1))
        status, data = self.get(f"/api/triage/{item}")
        self.assertEqual((status, data["state"]), (200, "pending"))
        b.triage_round(ai.AIError("UPSTREAM_ERROR"))
        with b.index.write() as db:
            db.execute("UPDATE triage_state SET state='failed'")
        status, data = self.post(f"/api/triage/{item}/retry")
        self.assertEqual((status, data["state"], data["attempts"]), (200, "pending", 0))
        self.assertEqual(self.post(f"/api/triage/{item}/retry", token="wrong")[0], 403)
        self.assertEqual(self.get("/api/triage/unknown-item")[0], 404)
        self.assertEqual(self.get("/api/triage/bad%20id")[0], 400)
        self.assertEqual(self.request("POST", f"/api/triage/{item}/retry", b"x" * 2048)[0], 413)
        b.triage_round(b.answer())
        status, data = self.post(f"/api/triage/{item}/retry")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
