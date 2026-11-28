import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.jobs import Jobs
from easyread.library import Library
from easyread.store import Workspace, write_json_atomic


class StopWorker(Exception):
    pass


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = Library(Path(self.tmp.name))
        root = self.lib.root / "paper0001"
        root.mkdir()
        self.ws = Workspace(root)
        write_json_atomic(self.ws.paper_path, {"meta": {"pages": [{"n": 1}], "page_count": 1}})
        with patch("easyread.jobs.threading.Thread.start"):
            self.jobs = Jobs(self.lib)

    def drain(self, small=False):
        queue = self.jobs.small if small else self.jobs.bulk
        get = queue.get

        def next_job():
            if queue.empty():
                raise StopWorker()
            return get()
        with patch.object(queue, "get", side_effect=next_job), self.assertRaises(StopWorker):
            (self.jobs._small_loop if small else self.jobs._bulk_loop)()

    def test_duplicate_enqueue_preserves_queued_and_running_task(self):
        self.jobs.enqueue(self.ws, pages=[1])
        for state in ("queued", "running"):
            self.jobs._write(self.ws, state=state, message="original")
            before = self.ws.load("job")
            with self.assertRaisesRegex(ValueError, "已有任务"):
                self.jobs.enqueue(self.ws, pages=[2])
            self.assertEqual(self.ws.load("job"), before)
            self.assertEqual(self.jobs.bulk.qsize(), 1)

    def test_worker_marks_running_before_starting_work(self):
        self.jobs.enqueue(self.ws, pages=[1])

        def run(ws, job, cancel):
            self.assertEqual(ws.load("job")["state"], "running")
            with self.assertRaises(ValueError):
                self.jobs.enqueue(ws, pages=[2])
            self.jobs._write(ws, state="done")
        with patch.object(self.jobs, "_run_bulk", side_effect=run):
            self.drain()
        self.assertEqual(self.ws.load("job")["state"], "done")
        self.assertNotIn(self.ws.id, self.jobs.cancels)

    # ---------- 匯入後自動翻譯的額度保護（ticket 68） ----------
    CLAUDE = {"engine": "claude", "claude": {}}

    def run_background(self, gate, background=True):
        self.jobs.translate_gate = gate
        self.jobs.enqueue(self.ws, background=background)
        with patch("easyread.jobs.config.load", return_value=self.CLAUDE), \
                patch("easyread.jobs.translate.translate_pages", return_value={}) as tp:
            self.drain()
        return tp

    def test_background_translation_waits_when_the_gate_says_so(self):
        tp = self.run_background(lambda cfg: {"reason": "subscription", "until": None})
        job = self.ws.load("job")
        self.assertEqual(job["state"], "waiting")
        self.assertEqual(job["wait"], {"reason": "subscription", "until": None})
        self.assertEqual(job["total"], 1)
        tp.assert_not_called()

    def test_manual_translation_ignores_the_gate(self):
        calls = []
        tp = self.run_background(lambda cfg: calls.append(cfg) or {"reason": "quota", "until": 1}, background=False)
        tp.assert_called_once()
        self.assertEqual(calls, [])
        self.assertEqual(self.ws.load("job")["state"], "done")

    def test_an_unreadable_gate_waits_instead_of_spending(self):
        def broken(cfg):
            raise OSError("locked")
        tp = self.run_background(broken)
        tp.assert_not_called()
        self.assertEqual(self.ws.load("job")["wait"]["reason"], "quota")

    def test_an_unknown_gate_answer_also_waits(self):
        tp = self.run_background(lambda cfg: {"reason": "something-new"})
        tp.assert_not_called()
        self.assertEqual(self.ws.load("job")["wait"]["reason"], "quota")

    def test_waiting_translation_is_queued_again_once_the_gate_clears(self):
        blocked = {"on": True}
        self.run_background(lambda cfg: {"reason": "quota", "until": 1} if blocked["on"] else None)
        with patch("easyread.jobs.config.load", return_value=self.CLAUDE):
            self.assertEqual(self.jobs.resume_waiting(), 0)
            self.assertEqual(self.ws.load("job")["state"], "waiting")
            blocked["on"] = False
            self.assertEqual(self.jobs.resume_waiting(), 1)
        job = self.ws.load("job")
        self.assertEqual((job["state"], job["wait"], job["background"]), ("queued", None, True))
        self.assertEqual(self.jobs.bulk.qsize(), 1)

    def test_catch_up_queues_at_most_the_round_limit_in_arrival_order(self):
        names = []
        for i in range(4):
            root = self.lib.root / f"paper{i + 10:04d}"
            root.mkdir()
            ws = Workspace(root)
            write_json_atomic(ws.paper_path, {"meta": {"pages": [{"n": 1}], "page_count": 1}})
            write_json_atomic(root / "job.json", {"state": "waiting", "translate": True, "background": True,
                                                  "updated": f"2026-11-28T0{4 - i}:00:00"})
            names.append(ws.id)
        self.jobs.translate_gate = lambda cfg: None
        with patch("easyread.jobs.config.load", return_value=self.CLAUDE):
            self.assertEqual(self.jobs.resume_waiting(limit=2), 2)
        queued = [self.jobs.bulk.get_nowait() for _ in range(self.jobs.bulk.qsize())]
        self.assertEqual(queued, [names[3], names[2]])  # 最早開始等的先補

    def test_waiting_translation_can_be_cancelled_or_started_by_hand(self):
        self.run_background(lambda cfg: {"reason": "subscription", "until": None})
        self.jobs.cancel(self.ws.id)
        self.assertEqual(self.ws.load("job")["state"], "done")
        self.run_background(lambda cfg: {"reason": "subscription", "until": None})
        self.jobs.enqueue(self.ws)  # 使用者按了翻譯：手動，不再問額度保護
        job = self.ws.load("job")
        self.assertEqual((job["state"], job["background"], "wait" in job), ("queued", False, False))

    def test_stop_all_model_work_also_clears_waiting_translations(self):
        self.run_background(lambda cfg: {"reason": "api_cap", "until": None})
        self.assertEqual(self.jobs.stop_model_work(), 1)
        self.assertEqual(self.ws.load("job")["state"], "done")

    def test_waiting_translation_is_not_resumed_on_restart(self):
        self.run_background(lambda cfg: {"reason": "quota", "until": 1})
        with patch("easyread.jobs.threading.Thread.start"):
            again = Jobs(self.lib)
        self.assertEqual(again.bulk.qsize(), 0)
        self.assertEqual(self.ws.load("job")["state"], "waiting")

    def test_catch_up_without_a_gate_does_nothing(self):
        self.assertEqual(self.jobs.resume_waiting(), 0)

    def test_cancel_during_preparation_is_not_reported_done(self):
        write_json_atomic(self.ws.paper_path, {"meta": {}})
        self.jobs.enqueue(self.ws, translate_after=False)
        with patch("easyread.jobs.config.load", return_value={"engine": "none"}), \
                patch("easyread.jobs.translate.prepare", side_effect=lambda ws: self.jobs.cancel(ws.id)):
            self.drain()
        self.assertEqual(self.ws.load("job")["state"], "cancelled")

    def test_cancelled_queue_entry_is_skipped_and_can_be_retried(self):
        self.jobs.enqueue(self.ws, translate_after=False)
        self.jobs.cancel(self.ws.id)
        with patch.object(self.jobs, "_run_bulk") as run:
            self.drain()
        run.assert_not_called()
        self.jobs.enqueue(self.ws, translate_after=False)
        with patch.object(self.jobs, "_run_bulk", side_effect=lambda ws, job, ev: self.jobs._write(ws, state="done")) as run:
            self.drain()
        run.assert_called_once()

    def test_resume_finishes_before_workers_start(self):
        write_json_atomic(self.ws.root / "job.json", {"state": "running", "pages": [1]})
        states = []
        with patch("easyread.jobs.threading.Thread.start", side_effect=lambda: states.append(self.ws.load("job")["state"])):
            resumed = Jobs(self.lib)
        self.assertEqual(states, ["queued", "queued"])
        self.assertEqual(resumed.bulk.qsize(), 1)

    def test_small_job_ids_are_unique_with_frozen_clock(self):
        with patch("time.time", return_value=1):
            ids = {self.jobs.submit_small("answer", self.ws.id, note="n1")["id"] for _ in range(10)}
        self.assertEqual(len(ids), 10)

    def test_removed_paper_does_not_leave_small_job_queued_forever(self):
        job = self.jobs.submit_small("answer", self.ws.id, note="n1")
        self.lib.trash(self.ws.id)
        self.drain(small=True)
        self.assertEqual(self.jobs.small_status()[0]["state"], "error")
        self.assertIn("已移除", job["message"])
