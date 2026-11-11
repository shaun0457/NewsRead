"""Ticket 04：研究工作區、文獻搜尋、Zotero 遷移、批次匯入都移除了；使用者資料夾裡的舊資料不刪。"""
from __future__ import annotations

import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from easyread import planning_store
from easyread.library import Library

from tests.doubles import ApiTestCase

REPO = Path(__file__).resolve().parents[1]


class RemovedRoutesTest(ApiTestCase):
    def make_app(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        return {"lib": Library(self.root)}

    def test_research_zotero_and_bulk_routes_are_gone(self):
        for path in ("/research", "/api/research/v1/monitor", "/api/research/v2/reading-path/tasks/current",
                     "/api/zotero/detect", "/api/migrate/status"):
            self.assertEqual(self.request("GET", path)[0], 404, path)
        for path in ("/api/research/v1/setup", "/api/research/v2/paper/p1/deep-analysis",
                     "/api/research/v2/attach-pdf", "/api/migrate/start", "/api/migrate/scan",
                     "/api/migrate/stop"):
            self.assertEqual(self.request("POST", path, {})[0], 404, path)

    def test_old_research_data_is_kept_but_no_longer_read(self):
        """舊版留下的摘要回收站不再出現在回收站，清空回收站也不會刪到它。"""
        planning_store.statuses(self.root)  # 建出資料庫檔
        db_path = self.root / ".paperread-planning.sqlite3"
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("CREATE TABLE paper_summary_trash (trash_id TEXT PRIMARY KEY, paper_key TEXT, metadata_json TEXT,"
                       " summary_markdown TEXT, summary_model TEXT, created TEXT, updated TEXT, deleted_at TEXT)")
            db.execute("INSERT INTO paper_summary_trash VALUES ('t1','openalex:W1','{}','舊摘要','','x','x','x')")
            db.commit()
        status, listed = self.request("GET", "/api/trash")
        self.assertEqual(status, 200)
        self.assertEqual([item for item in listed["items"] if item.get("type") != "paper"], [])
        self.assertEqual(self.request("POST", "/api/trash", {"action": "empty"})[0], 200)
        self.assertEqual(self.request("POST", "/api/trash", {"action": "restore", "type": "summary", "name": "t1"})[0], 400)
        with closing(sqlite3.connect(db_path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM paper_summary_trash").fetchone()[0], 1)

    def test_trash_rejects_malformed_names_as_bad_requests(self):
        for name in (123, ["x"], None, "0123456789ab-20261111000000\n", "../0123456789ab-20261111000000"):
            status, _ = self.request("POST", "/api/trash", {"action": "purge", "name": name})
            self.assertEqual(status, 400, repr(name))


class OldDatabaseTest(unittest.TestCase):
    def test_new_code_opens_an_old_research_database_without_touching_its_tables(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        db_path = root / ".paperread-planning.sqlite3"
        with closing(sqlite3.connect(db_path)) as db:
            db.executescript("""
              CREATE TABLE statuses (id TEXT PRIMARY KEY, label TEXT NOT NULL, color TEXT NOT NULL,
                position INTEGER NOT NULL, builtin INTEGER NOT NULL DEFAULT 0);
              INSERT INTO statuses VALUES ('unread','待閱讀','#8b8b8b',0,1), ('mine','我的狀態','#123456',9,0);
              CREATE TABLE saved_papers (paper_key TEXT PRIMARY KEY, metadata_json TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL);
              INSERT INTO saved_papers VALUES ('openalex:W1','{}','x','x');
              CREATE TABLE keyword_links (id TEXT PRIMARY KEY, keyword_id TEXT NOT NULL, paper_id TEXT NOT NULL);
              INSERT INTO keyword_links VALUES ('k1','kw','p1');
              CREATE TABLE cache (cache_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated TEXT NOT NULL);
              INSERT INTO cache VALUES ('reading-path:latest','{"steps":[1]}','x');
            """)
            db.commit()

        def snapshot():
            with closing(sqlite3.connect(db_path)) as db:
                tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                return {t: db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}

        before = snapshot()
        self.assertEqual([s["id"] for s in planning_store.statuses(root)], ["unread", "mine"])
        self.assertEqual(planning_store.cache_get(root, "reading-path:latest")[0], {"steps": [1]})
        planning_store.cache_put(root, "mindmap:x", {"mermaid": "mindmap"})
        after = snapshot()
        self.assertEqual(after, {**before, "cache": before["cache"] + 1})
        with closing(sqlite3.connect(db_path)) as db:
            self.assertEqual(db.execute("SELECT payload_json FROM cache WHERE cache_key='reading-path:latest'").fetchone()[0],
                             '{"steps":[1]}')


class StartupImportsTest(unittest.TestCase):
    def test_server_and_launch_do_not_load_research_modules(self):
        code = ("import sys; import easyread.launch, easyread.server, easyread.jobs; "
                "print(sorted(m for m in sys.modules if m.startswith(('easyread.research', 'easyread.bulk', 'easyread.zotero'))))")
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(out.stdout.strip(), "[]")
        for name in ("research", "bulk", "zotero"):
            self.assertFalse((REPO / "easyread" / name).exists(), name)
        self.assertFalse((REPO / "easyread" / "research_v2.py").exists())


if __name__ == "__main__":
    unittest.main()
