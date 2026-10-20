from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from easyread import planning_store, research_v2
from easyread.research import api, tasks


class ResearchTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        planning_store.init(self.root)
        self.app = SimpleNamespace(lib=SimpleNamespace(root=self.root, all=lambda: []))

    def tearDown(self):
        self.temp.cleanup()

    def _wait_for(self, predicate, timeout=2):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            value = predicate()
            if value:
                return value
            time.sleep(.01)
        self.fail("background research task did not reach the expected state")

    def test_task_scope_isolation_deduplication_and_acknowledgement(self):
        scope = tasks.scope_id(self.root)
        other_scope = tasks.scope_id(self.root / "other")
        release = threading.Event()
        started = threading.Event()

        def runner(cancel, report):
            started.set()
            release.wait(1)
            return {"ok": True}

        first = tasks.submit("comparison", runner, scope=scope)
        self.assertTrue(started.wait(1))
        duplicate = tasks.submit("comparison", runner, scope=scope)
        other = tasks.submit("comparison", lambda cancel, report: {"ok": True}, scope=other_scope)
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual([item["id"] for item in tasks.list_tasks(scope=scope)], [first["id"]])
        self.assertIsNone(tasks.get(other["id"], scope=scope))
        self.assertIsNone(tasks.cancel(other["id"], scope=scope))
        release.set()
        done = self._wait_for(lambda: (lambda task: task if task and task["state"] == "completed" else None)(
            tasks.get(first["id"], scope=scope)))
        self.assertTrue(tasks.acknowledge(done["id"], scope=scope)["acknowledged"])

    def test_reading_path_task_endpoint_persists_and_recovers_completion(self):
        original_post = research_v2.post

        def mocked_path(app, endpoint, body, *, _cancel=None, _report=None):
            _report("planning", 3, 5, "AI 正在規劃閱讀順序。")
            return {"results": [{"paper_key": "openalex:W1"}], "path_id": "path-1", "revision": 1,
                    "warning": "部分搜尋資料使用快取。"}

        with mock.patch("easyread.research_v2.post", side_effect=mocked_path):
            submitted = original_post(self.app, "/reading-path/tasks", {
                "topic": "vision", "candidate_papers": [], "search_results": [],
            })["task"]
            self.assertIn(submitted["state"], ("queued", "running", "completed"))
            completed = self._wait_for(lambda: (lambda task: task if task and task["id"] == submitted["id"]
                and task["state"] == "completed" else None)(research_v2.get(
                    self.app, research_v2.PREFIX + "/reading-path/tasks/current")["task"]))

        self.assertEqual(completed["result"]["path_id"], "path-1")
        self.assertEqual(completed["result"]["warning"], "部分搜尋資料使用快取。")
        acked = original_post(self.app, f"/reading-path/tasks/{submitted['id']}/ack", {})["task"]
        self.assertTrue(acked["acknowledged"])

    def test_reading_path_current_marks_lost_active_task_interrupted_and_retains_retry_input(self):
        from easyread.research.tasks import scope_id
        request = {"topic": "vision", "candidate_papers": []}
        interrupted = {"id": "lost-task", "kind": "reading-path", "scope": scope_id(self.root),
                       "state": "running", "phase": "planning", "message": "running"}
        research_v2._persist_reading_path_task(self.root, request, interrupted)
        current = research_v2.get(self.app, research_v2.PREFIX + "/reading-path/tasks/current")["task"]
        self.assertEqual(current["state"], "interrupted")
        self.assertEqual(current["request"], request)

    def test_research_monitor_only_lists_tasks_for_current_library(self):
        scope = tasks.scope_id(self.root)
        release = threading.Event()
        current = tasks.submit("comparison", lambda cancel, report: release.wait(.4), scope=scope)
        other = tasks.submit("comparison", lambda cancel, report: release.wait(.4), scope=tasks.scope_id(self.root / "other"))
        monitor = api.get(self.app, "/api/research/v1/monitor")
        self.assertEqual(monitor["scope_id"], scope)
        self.assertEqual([item["id"] for item in monitor["tasks"]], [current["id"]])
        release.set()

    def test_reading_path_endpoint_rejects_non_list_candidate_data(self):
        with self.assertRaises(ValueError):
            research_v2.post(self.app, "/reading-path/tasks", {"topic": "vision", "candidate_papers": 123})

    def test_balanced_candidate_selection_deduplicates_and_keeps_each_source_represented(self):
        seed = {"id": "https://openalex.org/W100", "title": "Seed"}
        candidates = [{"doi": "10.1/shared", "title": "Shared", "openalex_id": "https://openalex.org/W101"}]
        references = [{"id": "https://openalex.org/W101", "doi": "https://doi.org/10.1/shared", "title": "Shared source record"},
                      {"id": "https://openalex.org/W102", "title": "Reference"}]
        related = [{"id": "https://openalex.org/W103", "title": "Related"}]
        searched = [{"id": "https://openalex.org/W104", "title": "Search result"}]
        selected = research_v2._balanced_candidates(seed, candidates, references, related, searched, limit=5)
        self.assertEqual([item["title"] for item in selected], ["Seed", "Shared source record", "Reference", "Related", "Search result"])
        self.assertEqual(len({research_v2._key(item) for item in selected}), 5)

    def test_identifier_lookup_uses_fresh_cache_without_repeating_openalex_call(self):
        work = {"id": "https://openalex.org/W100", "title": "Cached paper"}
        with mock.patch.object(research_v2, "_openalex", return_value=work) as openalex:
            first = research_v2._identifier_search(self.root, "https://openalex.org/W100")
            second = research_v2._identifier_search(self.root, "W100")
        self.assertEqual(openalex.call_count, 1)
        self.assertTrue(second["cached"])
        self.assertEqual(first["results"][0]["title"], second["results"][0]["title"])


if __name__ == "__main__":
    unittest.main()
