"""Ticket 12：翻譯的每次 AI 呼叫都記進帳本的 AI 用量；記不進去不讓翻譯失敗，也不把錯誤原文寫進 log。"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from easyread import jobs, ledger, textitem
from easyread.jobs import Jobs
from easyread.library import Library
from tests.test_jobs import StopWorker
from tests.test_readmode import fill_engine


class LedgerMeterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "newsread.sqlite3"

    def test_every_call_is_one_usage_row(self):
        meter = jobs.LedgerMeter("claude", "claude-sonnet-5-5", self.path)
        meter.add(input=120, cached=20, output=30, limits={"five_hour": {"used": 0.4, "resets_at": 1}})
        meter.add(input=80, output=10, cost_usd=0.002, actual_model="gpt-x")
        rows = ledger.Index(self.path).usage()
        self.assertEqual([(r["task"], r["engine"], r["model"]) for r in rows],
                         [("translate", "claude", "claude-sonnet-5-5"), ("translate", "claude", "gpt-x")])
        self.assertEqual((rows[0]["input_tokens"], rows[0]["cached_tokens"], rows[0]["output_tokens"]), (120, 20, 30))
        self.assertEqual(rows[0]["cost"], "unknown")  # 訂閱不折算金額
        self.assertEqual(rows[0]["quota"], {"five_hour": {"used": 0.4, "resets_at": 1}})
        self.assertEqual(rows[1]["cost_usd"], 0.002)
        snap = meter.snapshot()  # 任務裡的累計照舊
        self.assertEqual((snap["calls"], snap["input"], snap["output"]), (2, 200, 40))

    def test_no_calls_no_database(self):
        jobs.LedgerMeter("claude", "", self.path).snapshot()
        self.assertFalse(self.path.exists())

    def test_ledger_failure_does_not_break_translation_or_leak_text(self):
        meter = jobs.LedgerMeter("claude", "m", self.path)
        boom = sqlite3.OperationalError("database is locked: secret-path-and-key")
        with mock.patch.object(ledger.Index, "record_usage", side_effect=boom), \
                self.assertLogs("easyread", level="WARNING") as logs:
            meter.add(input=5, output=1)
        self.assertEqual(meter.snapshot()["calls"], 1)
        self.assertIn("OperationalError", logs.output[0])
        self.assertNotIn("secret", logs.output[0])

    def test_engine_and_model_come_from_the_translation_config(self):
        meter = jobs.translation_meter({"engine": "codex", "codex": {"model": "gpt-5.5"}})
        self.assertEqual((meter.data["engine"], meter.model), ("codex", "gpt-5.5"))
        meter = jobs.translation_meter({"engine": "openai", "openai": "broken"})
        self.assertEqual((meter.data["engine"], meter.model), ("openai", ""))

    def test_local_ollama_is_recorded_as_ollama(self):
        meter = jobs.translation_meter({"engine": "openai", "openai": {"preset": "ollama", "model": "qwen3"}})
        self.assertEqual((meter.data["engine"], meter.model), ("ollama", "qwen3"))

    def test_first_calls_at_the_same_time_all_get_recorded(self):  # 資料庫檔還不存在時同時建
        meters = [jobs.LedgerMeter("claude", "m", self.path) for _ in range(12)]
        start = threading.Barrier(len(meters))

        def call(meter):
            start.wait(5)
            meter.add(input=1, output=1)
        threads = [threading.Thread(target=call, args=(m,)) for m in meters]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(len(ledger.Index(self.path).usage()), len(meters))

    def test_odd_numbers_from_an_engine_are_clamped(self):
        meter = jobs.LedgerMeter("", "x" * 500, self.path)
        meter.add(input=-3, output=2)
        row = ledger.Index(self.path).usage()[0]
        self.assertEqual((row["engine"], len(row["model"]), row["input_tokens"]), ("unknown", 200, 0))


class TranslationJobUsageTest(unittest.TestCase):
    """真的跑翻譯任務（假引擎），用量照呼叫次數記進帳本。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.lib = Library(root / "lib")
        self.db = root / "newsread.sqlite3"
        self.ws, _ = textitem.create(self.lib, "\n\n".join(f"Paragraph {n}." for n in range(1, 31)), title="Thirty")
        cfg = {"engine": "openai", "batch_pages": 1, "concurrency": 1, "target": "zh",
               "openai": {"vision": False, "model": "gpt-test"}}
        self.calls = calls = []
        inner = fill_engine(calls)

        def engine(cfg, prompt, cwd, images=None, cancel=None, meter=None, json_mode=False):
            meter.add(input=50, output=7)  # 真引擎回報用量的地方
            return inner(cfg, prompt, cwd, images, cancel, meter, json_mode)
        for p in (mock.patch("easyread.jobs.config.load", return_value=cfg),
                  mock.patch("easyread.engines.run", side_effect=engine),
                  mock.patch("easyread.translate.netcheck.problem", return_value=""),
                  mock.patch("easyread.translate.tex_problems", return_value=[]),
                  mock.patch.object(ledger, "default_path", return_value=self.db),
                  mock.patch("easyread.i18n.lang", return_value="zh")):
            p.start()
            self.addCleanup(p.stop)
        with mock.patch("easyread.jobs.threading.Thread.start"):
            self.jobs = Jobs(self.lib)

    def drain(self):
        get = self.jobs.bulk.get

        def next_job():
            if self.jobs.bulk.empty():
                raise StopWorker()
            return get()
        with mock.patch.object(self.jobs.bulk, "get", side_effect=next_job), self.assertRaises(StopWorker):
            self.jobs._bulk_loop()

    def test_each_call_writes_one_usage_row(self):
        self.jobs.enqueue(self.ws, scope="all")
        self.drain()
        self.assertEqual((self.ws.load("job") or {}).get("state"), "done", self.ws.load("job"))
        rows = ledger.Index(self.db).usage()
        self.assertGreater(len(self.calls), 1)  # 30 段分成好幾批
        self.assertEqual(len(rows), len(self.calls))  # 每次呼叫一筆
        self.assertTrue(all(r["task"] == "translate" and r["model"] == "gpt-test" for r in rows))
        self.assertEqual(sum(r["input_tokens"] for r in rows), 50 * len(self.calls))


if __name__ == "__main__":
    unittest.main()
