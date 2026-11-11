"""Ticket 07：共用排程器。用假時鐘測補做、不重複、失敗重試的間隔、狀態檔和停止時限。"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from easyread import scheduler

HOUR = 3600.0


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "schedule.json"
        self.clock = FakeClock()
        self.calls: list[str] = []

    def make(self, **kw) -> scheduler.Scheduler:
        return scheduler.Scheduler(self.state, clock=self.clock, **kw)

    def job(self, name="fetch"):
        return lambda: self.calls.append(name)

    def write_state(self, data) -> None:
        self.state.write_text(json.dumps(data), encoding="utf-8")

    def test_new_job_runs_once_then_waits_for_its_interval(self):
        s = self.make()
        s.add("fetch", HOUR, self.job())
        self.assertEqual(s.run_pending(), ["fetch"])
        self.assertEqual(s.run_pending(), [])
        self.clock.advance(HOUR - 1)
        self.assertEqual(s.run_pending(), [])
        self.clock.advance(1)
        self.assertEqual(s.run_pending(), ["fetch"])
        self.assertEqual(self.calls, ["fetch", "fetch"])

    def test_missed_periods_are_caught_up_once_not_one_per_period(self):
        self.write_state({"version": 1, "jobs": {"fetch": {"last_success": self.clock.t - 10 * HOUR}}})
        s = self.make()
        s.add("fetch", HOUR, self.job())
        self.assertEqual(s.run_pending(), ["fetch"])
        self.assertEqual(s.run_pending(), [])
        self.clock.advance(HOUR - 1)  # 過了失敗重試的等待，還不到一個間隔
        self.assertEqual(s.run_pending(), [])
        self.assertEqual(self.calls, ["fetch"])

    def test_last_success_survives_a_restart_so_nothing_runs_twice(self):
        s = self.make()
        s.add("fetch", HOUR, self.job())
        s.run_pending()
        saved = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(saved["jobs"]["fetch"]["last_success"], self.clock.t)
        self.clock.advance(HOUR / 2)
        again = self.make()  # 重新啟動
        again.add("fetch", HOUR, self.job())
        self.assertEqual(again.run_pending(), [])
        self.clock.advance(HOUR / 2)
        self.assertEqual(again.run_pending(), ["fetch"])
        self.assertEqual(self.calls, ["fetch", "fetch"])

    def test_success_is_recorded_at_the_start_time(self):
        def slow():
            self.clock.advance(600)  # 跑了十分鐘
        s = self.make()
        job = s.add("slow", HOUR, slow)
        started = self.clock.t
        s.run_pending()
        self.assertEqual(job.last_success, started)

    def test_failure_is_not_recorded_and_retries_after_a_pause(self):
        attempts = []

        def flaky():
            attempts.append(self.clock.t)
            if len(attempts) == 1:
                raise RuntimeError("upstream said: secret-key-123")
        s = self.make(retry_after=300)
        job = s.add("flaky", HOUR, flaky)
        with self.assertLogs("easyread", level="WARNING") as logs:
            self.assertEqual(s.run_pending(), [])
        self.assertIsNone(job.last_success)
        self.assertNotIn("secret-key-123", "\n".join(logs.output))  # 只記錯誤類型
        self.assertIn("RuntimeError", "\n".join(logs.output))
        self.assertFalse(self.state.exists())
        self.clock.advance(299)
        self.assertEqual(s.run_pending(), [])
        self.clock.advance(1)
        self.assertEqual(s.run_pending(), ["flaky"])
        self.assertEqual(len(attempts), 2)

    def test_retry_pause_is_never_longer_than_the_interval(self):
        s = self.make(retry_after=300)
        attempts = []
        s.add("quick", 60, lambda: (attempts.append(1), 1 / 0))
        s.run_pending()
        self.clock.advance(60)
        s.run_pending()
        self.assertEqual(len(attempts), 2)

    def test_a_running_job_is_not_started_again(self):
        entered, release = threading.Event(), threading.Event()
        count = []

        def slow():
            count.append(1)
            entered.set()
            release.wait(5)
        s = self.make()
        s.add("slow", 1, slow)
        first = threading.Thread(target=s.run_pending)
        first.start()
        self.assertTrue(entered.wait(5))
        self.clock.advance(10)  # 早就超過間隔了，但它還在跑
        self.assertEqual(s.run_pending(), [])
        release.set()
        first.join(5)
        self.assertEqual(len(count), 1)

    def test_job_calling_sys_exit_is_a_failure_not_the_end_of_the_scheduler(self):
        s = self.make(retry_after=60)
        job = s.add("exits", HOUR, lambda: (self.calls.append("exits"), sys.exit(2)))
        with self.assertLogs("easyread", level="WARNING") as logs:
            self.assertEqual(s.run_pending(), [])
        self.assertIn("SystemExit", "\n".join(logs.output))
        self.assertFalse(job.running)
        self.assertIsNone(job.last_success)
        self.clock.advance(60)
        with self.assertLogs("easyread", level="WARNING"):
            s.run_pending()
        self.assertEqual(self.calls, ["exits", "exits"])

    def test_concurrent_saves_never_write_an_older_snapshot_last(self):
        s = self.make()
        s.add("a", HOUR, self.job("a"))
        s.add("b", HOUR, self.job("b"))
        writes = []
        real = scheduler.write_json_atomic
        first_in, release = threading.Event(), threading.Event()

        def slow_write(path, data):
            writes.append(sorted(data["jobs"]))
            if len(writes) == 1:  # 第一個存檔停在寫檔前，讓第二個有機會插隊
                first_in.set()
                release.wait(2)
            real(path, data)
        with mock.patch.object(scheduler, "write_json_atomic", side_effect=slow_write):
            s.jobs["a"].last_success = self.clock.t
            t = threading.Thread(target=s._save)
            t.start()
            self.assertTrue(first_in.wait(5))
            s.jobs["b"].last_success = self.clock.t
            second = threading.Thread(target=s._save)
            second.start()
            second.join(0.3)
            self.assertTrue(second.is_alive())  # 第二個在等第一個寫完
            release.set()
            t.join(5)
            second.join(5)
        saved = json.loads(self.state.read_text(encoding="utf-8"))["jobs"]
        self.assertEqual(sorted(saved), ["a", "b"])

    def test_one_broken_job_does_not_block_the_others(self):
        s = self.make()
        s.add("broken", HOUR, lambda: 1 / 0)
        s.add("fine", HOUR, self.job("fine"))
        with self.assertLogs("easyread", level="WARNING"):
            self.assertEqual(s.run_pending(), ["fine"])

    def test_record_far_in_the_future_is_treated_as_a_clock_error(self):
        self.write_state({"jobs": {"a": {"last_success": self.clock.t + 2 * HOUR},
                                   "b": {"last_success": self.clock.t + 10}}})
        s = self.make()
        s.add("a", HOUR, self.job("a"))
        s.add("b", HOUR, self.job("b"))  # 只是時鐘稍微往回調：不算錯
        self.assertEqual(s.run_pending(), ["a"])

    def test_bad_state_files_are_ignored(self):
        cases = ["{not json", json.dumps([1, 2]), json.dumps({"jobs": {"fetch": {"last_success": "yesterday"}}}),
                 json.dumps({"jobs": {"fetch": {"last_success": True}}}), json.dumps({"jobs": {"fetch": 5}})]
        for raw in cases:
            with self.subTest(raw=raw):
                self.state.write_text(raw, encoding="utf-8")
                s = self.make()
                s.add("fetch", HOUR, self.job())
                self.assertEqual(s.run_pending(), ["fetch"])

    def test_oversized_state_file_is_not_read(self):
        self.write_state({"jobs": {"fetch": {"last_success": self.clock.t}}, "pad": "x" * scheduler.STATE_MAX_BYTES})
        with self.assertLogs("easyread", level="WARNING"):
            s = self.make()
        s.add("fetch", HOUR, self.job())
        self.assertEqual(s.run_pending(), ["fetch"])

    def test_state_keeps_at_most_max_entries(self):
        many = {f"old{i}": {"last_success": 1.0} for i in range(scheduler.MAX_ENTRIES + 50)}
        self.write_state({"jobs": many})
        s = self.make()
        self.assertEqual(len(s._saved), scheduler.MAX_ENTRIES)
        s.add("fetch", HOUR, self.job())
        s.run_pending()
        saved = json.loads(self.state.read_text(encoding="utf-8"))["jobs"]
        self.assertLessEqual(len(saved), scheduler.MAX_ENTRIES)
        self.assertIn("fetch", saved)

    def test_records_of_jobs_not_added_this_time_are_kept(self):
        self.write_state({"jobs": {"later": {"last_success": 5.0}}})
        s = self.make()
        s.add("fetch", HOUR, self.job())
        s.run_pending()
        saved = json.loads(self.state.read_text(encoding="utf-8"))["jobs"]
        self.assertEqual(saved["later"], {"last_success": 5.0})

    def test_in_memory_scheduler_writes_nothing(self):
        s = scheduler.Scheduler(None, clock=self.clock)
        s.add("fetch", HOUR, self.job())
        self.assertEqual(s.run_pending(), ["fetch"])
        self.assertEqual(s.run_pending(), [])
        self.assertFalse(self.state.exists())

    def test_add_validates_its_arguments(self):
        s = self.make()
        s.add("fetch", HOUR, self.job())
        for name, interval in (("fetch", HOUR), ("", HOUR), ("x" * 101, HOUR), ("a", 0), ("a", -1),
                               ("a", float("nan")), ("a", float("inf")), ("a", True)):
            with self.subTest(name=name, interval=interval), self.assertRaises(ValueError):
                s.add(name, interval, self.job())

    def test_run_pending_stops_early_once_stopping(self):
        s = self.make()
        s.add("first", HOUR, lambda: (self.calls.append("first"), s.stopping.set()))
        s.add("second", HOUR, self.job("second"))
        self.assertEqual(s.run_pending(), ["first"])
        self.assertEqual(self.calls, ["first"])

    def test_default_clock_is_wall_time(self):
        self.assertAlmostEqual(scheduler.Clock().now(), time.time(), delta=5)


class SchedulerThreadTest(unittest.TestCase):
    def test_background_thread_runs_due_jobs_and_stops_in_time(self):
        ran = threading.Event()
        s = scheduler.Scheduler(None, tick=0.05)
        s.add("fetch", HOUR, ran.set)
        s.start()
        self.assertTrue(ran.wait(5))
        started = time.monotonic()
        self.assertTrue(s.stop(2))
        self.assertLess(time.monotonic() - started, 1)  # 不必等滿一個 tick
        self.assertFalse(s._thread.is_alive())

    def test_stop_gives_up_after_the_timeout_when_a_job_hangs(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        s = scheduler.Scheduler(None, tick=0.05)
        s.add("hang", HOUR, lambda: (entered.set(), release.wait(30)))
        s.start()
        self.assertTrue(entered.wait(5))
        started = time.monotonic()
        self.assertFalse(s.stop(0.3))
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(s._thread.daemon)  # 卡住的工作不會擋住程序結束

    def test_stop_without_start(self):
        self.assertTrue(scheduler.Scheduler(None).stop(0.1))

    def test_loop_survives_an_unexpected_error(self):
        s = scheduler.Scheduler(None, tick=0.05)
        calls = []
        original = s.run_pending

        def boom():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("x")
            return original()
        s.run_pending = boom
        with self.assertLogs("easyread", level="WARNING"):
            s.start()
            deadline = time.monotonic() + 5
            while len(calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
        self.assertTrue(s.stop(2))
        self.assertGreaterEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
