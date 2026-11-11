"""帳本與索引核心（ticket 10）：只能新增、內容雜湊、修正、Story、AI 用量、prompt 版本、ContextManifest、備份、唯讀 API。"""
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path

from easyread import ledger

from tests.doubles import ApiTestCase, FakeClock


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Windows 上 SQLite 檔可能還被防毒或 WAL 暫時鎖住
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "data" / ledger.DB_NAME
        self.clock = FakeClock()
        self.ix = ledger.Index(self.path, clock=self.clock)

    def raw(self):
        db = sqlite3.connect(self.path, isolation_level=None)  # 自動提交：失敗的語句不會留下沒結束的交易卡住寫入鎖
        self.addCleanup(db.close)
        return db

    def manifest(self, published_at="2026-11-10T08:00:00+00:00", decided_at="2026-11-11T00:00:00Z", prompt_version="triage@1"):
        return self.ix.add_manifest(task="triage", prompt_version=prompt_version, decided_at=decided_at,
                                    items=[{"id": "item-1", "hash": "h1", "published_at": published_at}],
                                    theses=[{"id": "thesis-1", "version": "3"}], concepts=[{"id": "c-1", "hash": "hc"}],
                                    market_context_date="2026-11-10")


class StorageTest(LedgerCase):
    def test_index_lives_at_given_data_path_in_wal_mode(self):
        self.assertTrue(self.path.exists())
        self.assertEqual(self.raw().execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_update_delete_and_replace_are_blocked_by_triggers(self):
        self.ix.append("judgment", "me", {"relation": "bull"})
        self.manifest()
        self.ix.record_usage(source="paste", task="triage", engine="claude", model="m")
        self.ix.register_prompt("triage", "1", "prompt text")
        db = self.raw()
        db.execute("PRAGMA recursive_triggers=ON")
        for table in ledger.APPEND_ONLY:
            for sql in (f"UPDATE {table} SET rowid = rowid", f"DELETE FROM {table}"):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                    db.execute(sql)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            db.execute("INSERT OR REPLACE INTO prompt_versions VALUES ('triage','1','other','2026-11-11T00:00:00Z')")
        self.assertEqual(self.ix.records()[0]["payload"], {"relation": "bull"})
        self.assertEqual(len(self.ix.usage()), 1)
        self.assertEqual(self.ix.current_prompt("triage"), "1")

    def test_index_connections_turn_on_recursive_triggers(self):
        self.ix.register_prompt("triage", "1", "prompt text")
        with self.ix._connect() as db, self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            db.execute("INSERT OR REPLACE INTO prompt_versions VALUES ('triage','1','other','2026-11-11T00:00:00Z')")

    def test_writer_waits_for_lock_up_to_busy_timeout_then_fails_and_recovers(self):
        quick = ledger.Index(self.path, busy_ms=200)
        holder = self.raw()
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
            quick.append("judgment", "me", {"n": 1})
        self.assertLess(time.monotonic() - started, 5)
        holder.execute("ROLLBACK")
        quick.append("judgment", "me", {"n": 2})  # 失敗那次的連線有釋放，之後照常寫得進去
        self.assertEqual([r["payload"]["n"] for r in self.ix.records()], [2])


class HashTest(LedgerCase):
    def test_tampered_payload_is_detected(self):
        a = self.ix.append("judgment", "me", {"relation": "bull"})
        self.ix.append("judgment", "me", {"relation": "bear"})
        self.assertTrue(self.ix.verify()["ok"])
        db = self.raw()
        db.execute("DROP TRIGGER ledger_no_update")  # 有人繞過 trigger 直接改檔
        db.execute("UPDATE ledger SET payload=? WHERE id=?", ('{"relation":"bear"}', a["id"]))
        result = self.ix.verify()
        self.assertFalse(result["ok"])
        self.assertIn(a["id"], result["broken"])

    def test_deleted_middle_record_breaks_the_chain(self):
        self.ix.append("judgment", "me", {"n": 1})
        b = self.ix.append("judgment", "me", {"n": 2})
        c = self.ix.append("judgment", "me", {"n": 3})
        db = self.raw()
        db.execute("DROP TRIGGER ledger_no_delete")
        db.execute("DELETE FROM ledger WHERE id=?", (b["id"],))
        self.assertEqual(self.ix.verify()["broken"], [c["id"]])

    def test_tail_truncation_is_caught_by_comparing_the_saved_head(self):
        self.ix.append("judgment", "me", {"n": 1})
        last = self.ix.append("judgment", "me", {"n": 2})
        saved = self.ix.verify()
        self.assertEqual((saved["head_seq"], saved["head_hash"]), (last["seq"], last["content_hash"]))
        db = self.raw()
        db.execute("DROP TRIGGER ledger_no_delete")
        db.execute("DELETE FROM ledger WHERE id=?", (last["id"],))
        now = self.ix.verify()
        self.assertTrue(now["ok"])  # 剩下的鏈本身仍完整（模組說明寫明的限制）
        self.assertNotEqual(now["head_hash"], saved["head_hash"])  # 跟存下的 head 比就看得出來

    def test_tampered_manifest_is_detected(self):
        m = self.manifest()
        db = self.raw()
        db.execute("DROP TRIGGER context_manifests_no_update")
        db.execute("UPDATE context_manifests SET created_at='2020-01-01T00:00:00Z' WHERE id=?", (m,))
        self.assertIn(m, self.ix.verify()["broken"])

    def test_broken_list_is_capped(self):
        for n in range(ledger.MAX_BROKEN + 5):
            self.ix.append("judgment", "me", {"n": n})
        db = self.raw()
        db.execute("DROP TRIGGER ledger_no_update")
        db.execute("UPDATE ledger SET payload='{}'")
        result = self.ix.verify()
        self.assertEqual(len(result["broken"]), ledger.MAX_BROKEN)
        self.assertTrue(result["truncated"])
        self.assertFalse(result["ok"])


class CorrectionTest(LedgerCase):
    def test_correction_appends_new_record_and_keeps_original(self):
        old = self.ix.append("judgment", "me", {"relation": "bull"})
        new = self.ix.append("judgment", "me", {"relation": "bear"}, supersedes=old["id"])
        everything = self.ix.records()
        self.assertEqual([r["id"] for r in everything], [old["id"], new["id"]])
        self.assertEqual(everything[0]["payload"], {"relation": "bull"})
        self.assertEqual(new["supersedes"], old["id"])
        self.assertEqual([r["id"] for r in self.ix.records(current_only=True)], [new["id"]])
        self.assertTrue(self.ix.verify()["ok"])

    def test_correction_rules(self):
        old = self.ix.append("judgment", "me", {"relation": "bull"})
        with self.assertRaisesRegex(ValueError, "not found"):
            self.ix.append("judgment", "me", {}, supersedes="L-missing")
        with self.assertRaisesRegex(ValueError, "same kind"):
            self.ix.append("prediction", "me", {}, supersedes=old["id"])
        self.ix.append("judgment", "me", {"relation": "bear"}, supersedes=old["id"])
        with self.assertRaisesRegex(ValueError, "already corrected"):
            self.ix.append("judgment", "me", {"relation": "neutral"}, supersedes=old["id"])

    def test_unknown_kind_missing_fields_and_oversized_payload_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown ledger kind"):
            self.ix.append("note", "me", {})
        with self.assertRaisesRegex(ValueError, "who"):
            self.ix.append("judgment", "  ", {})
        with self.assertRaisesRegex(ValueError, "too large"):
            self.ix.append("judgment", "me", {"text": "x" * ledger.MAX_PAYLOAD_BYTES})
        self.ix.append("judgment", "me", {"text": "x" * (ledger.MAX_PAYLOAD_BYTES - 20)})
        self.assertEqual(len(self.ix.records()), 1)


class StoryTest(LedgerCase):
    def test_each_item_gets_its_own_story_by_default(self):
        s1 = self.ix.ensure_story("item-1", "2026-11-10T08:00:00+08:00")
        s2 = self.ix.ensure_story("item-2", "2026-11-10T09:00:00+08:00")
        self.assertNotEqual(s1, s2)
        self.assertEqual(self.ix.ensure_story("item-1", "2026-11-10T08:00:00+08:00"), s1)
        self.assertEqual(self.ix.story_of("item-2"), s2)
        self.assertIsNone(self.ix.story_of("item-3"))
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.ix.ensure_story("item-3", "2026-11-10T08:00:00")


class ManifestTest(LedgerCase):
    def test_ai_records_must_point_to_an_existing_manifest(self):
        for who in ("ai:claude@triage@1", "AI:claude@triage@1", " ai:claude@triage@1"):
            with self.subTest(who=who), self.assertRaisesRegex(ValueError, "context manifest"):
                self.ix.append("judgment", who, {"relation": "strengthens"})
        with self.assertRaisesRegex(ValueError, "not found"):
            self.ix.append("judgment", "ai:claude@triage@1", {}, context_manifest="M-missing")
        m = self.manifest()
        rec = self.ix.append("judgment", "ai:claude@triage@1", {"relation": "strengthens"}, context_manifest=m)
        self.assertEqual(rec["context_manifest"], m)
        stored = self.ix.manifest(m)
        self.assertEqual(stored["items"], [{"id": "item-1", "hash": "h1", "published_at": "2026-11-10T08:00:00+00:00"}])
        self.assertEqual(stored["theses"], [{"id": "thesis-1", "version": "3"}])
        self.assertEqual(stored["market_context_date"], "2026-11-10")
        self.assertEqual(stored["prompt_version"], "triage@1")

    def test_ai_record_prompt_version_must_match_the_manifest(self):
        m = self.manifest(prompt_version="triage@9")
        with self.assertRaisesRegex(ValueError, "prompt version"):
            self.ix.append("judgment", "ai:claude@triage@1", {}, context_manifest=m)
        self.ix.append("judgment", "ai:claude@triage@9", {}, context_manifest=m)

    def test_manifest_items_must_be_earlier_than_the_decision(self):
        for published in ("2026-11-11T00:00:00Z", "2026-11-12T00:00:00+00:00", "2026-11-11T08:30:00+08:00"):
            with self.subTest(published=published), self.assertRaisesRegex(ValueError, "not earlier"):
                self.manifest(published_at=published)
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.manifest(published_at="2026-11-10T08:00:00")
        with self.assertRaisesRegex(ValueError, "id and hash"):
            self.ix.add_manifest(task="triage", prompt_version="v1", decided_at="2026-11-11T00:00:00Z", items=[{"id": "x"}])
        self.assertTrue(self.manifest(published_at="2026-11-11T07:59:59+08:00"))

    def test_decision_time_defaults_to_now_and_cannot_be_in_the_future(self):
        with self.assertRaisesRegex(ValueError, "future"):
            self.manifest(published_at="2098-01-01T00:00:00Z", decided_at="2099-01-01T00:00:00Z")
        m = self.ix.add_manifest(task="triage", prompt_version="v1", items=[{"id": "i", "hash": "h", "published_at": "2026-11-10T00:00:00Z"}])
        self.assertEqual(self.ix.manifest(m)["decided_at"], "2026-11-11T01:00:02.000000+00:00")
        with self.assertRaisesRegex(ValueError, "not earlier"):
            self.ix.add_manifest(task="triage", prompt_version="v1", items=[{"id": "i", "hash": "h", "published_at": "2026-11-12T00:00:00Z"}])

    def test_record_cannot_point_to_a_manifest_dated_after_it(self):
        m = self.manifest(decided_at=None)  # 判斷時間 = 現在
        self.clock.t -= timedelta(hours=1)    # 寫入帳本的時鐘比 manifest 早
        with self.assertRaisesRegex(ValueError, "dated after"):
            self.ix.append("judgment", "ai:claude@triage@1", {}, context_manifest=m)

    def test_manifest_stores_ids_and_hashes_not_full_text(self):
        m = self.ix.add_manifest(task="triage", prompt_version="v1", decided_at="2026-11-11T00:00:00Z",
                                 items=[{"id": "i", "hash": "h", "published_at": "2026-11-10T00:00:00Z", "text": "全文內容"}])
        body = self.raw().execute("SELECT body FROM context_manifests WHERE id=?", (m,)).fetchone()[0]
        self.assertNotIn("全文內容", body)


class UsageTest(LedgerCase):
    def test_usage_records_each_call_with_unknown_cost_for_subscriptions(self):
        m = self.manifest()
        self.ix.record_usage(source="paste", task="triage", engine="claude", model="claude-sonnet", input_tokens=1200,
                             cached_tokens=800, output_tokens=300, quota={"five_hour": 0.42, "resets_at": "2026-11-11T05:00:00Z"},
                             context_manifest=m)
        self.ix.record_usage(source="rss", task="translate", engine="openai", model="gpt", input_tokens=10, output_tokens=5, cost_usd=0.0012)
        sub, api = self.ix.usage()
        self.assertEqual((sub["source"], sub["task"], sub["engine"], sub["model"]), ("paste", "triage", "claude", "claude-sonnet"))
        self.assertEqual((sub["input_tokens"], sub["cached_tokens"], sub["output_tokens"]), (1200, 800, 300))
        self.assertEqual(sub["cost"], "unknown")
        self.assertEqual(sub["quota"]["five_hour"], 0.42)
        self.assertEqual(sub["context_manifest"], m)
        self.assertEqual(api["cost"], 0.0012)
        self.assertEqual(sub["at"], "2026-11-11T01:00:02.000000+00:00")  # 用注入的時鐘
        with self.assertRaisesRegex(ValueError, "negative"):
            self.ix.record_usage(source="paste", task="triage", engine="claude", model="m", input_tokens=-1)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.ix.record_usage(source="paste", task="triage", engine="claude", model="m", context_manifest="M-missing")


class PromptTest(LedgerCase):
    def test_prompt_versions_have_a_current_version_per_task(self):
        self.assertIsNone(self.ix.current_prompt("triage"))
        self.ix.register_prompt("triage", "1", "分類 prompt v1")
        self.ix.register_prompt("translate", "1", "翻譯 prompt")
        self.ix.register_prompt("triage", "2", "分類 prompt v2")
        self.assertEqual(self.ix.current_prompt("triage"), "2")
        self.assertEqual(self.ix.current_prompt("translate"), "1")
        self.ix.register_prompt("triage", "1", "分類 prompt v1")  # 改回舊版
        self.assertEqual(self.ix.current_prompt("triage"), "1")
        self.ix.register_prompt("triage", "3", "試行", make_current=False)
        self.assertEqual(self.ix.current_prompt("triage"), "1")
        with self.assertRaisesRegex(ValueError, "bump the version"):
            self.ix.register_prompt("triage", "1", "偷偷改了內容")


class ListingTest(LedgerCase):
    def test_listing_is_capped_and_pages_with_after(self):
        for n in range(ledger.MAX_LIST + 3):
            self.ix.append("judgment", "me", {"n": n})
        first = self.ix.records(limit=10_000)
        self.assertEqual(len(first), ledger.MAX_LIST)
        rest = self.ix.records(after=first[-1]["seq"], limit=10_000)
        self.assertEqual([r["payload"]["n"] for r in rest], [ledger.MAX_LIST, ledger.MAX_LIST + 1, ledger.MAX_LIST + 2])
        self.assertEqual(len(self.ix.records(limit=0)), 1)

    def test_listing_stops_at_the_byte_budget(self):
        for n in range(5):
            self.ix.append("judgment", "me", {"text": "x" * 1000, "n": n})
        page = self.ix.records(max_bytes=2500)
        self.assertEqual([r["payload"]["n"] for r in page], [0, 1])
        self.assertEqual(len(self.ix.records(max_bytes=10)), 1)  # 至少回一筆，翻頁才不會卡住


class BackupTest(LedgerCase):
    def test_backup_while_writing_is_consistent(self):
        stop = threading.Event()
        errors = []

        def writer():
            ix = ledger.Index(self.path)
            n = 0
            while not stop.is_set() and n < 2000:
                try:
                    ix.append("judgment", "me", {"n": n})
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
                    return
                n += 1

        t = threading.Thread(target=writer)
        t.start()
        try:
            for i in range(5):
                dest = self.ix.backup(Path(self.tmp.name) / "backup" / f"b{i}.sqlite3")
                result = ledger.Index(dest).verify()
                self.assertTrue(result["ok"], result)
                check = sqlite3.connect(dest)
                self.assertEqual(check.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                check.close()
        finally:
            stop.set()
            t.join(timeout=30)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(self.ix.verify()["ok"])
        self.assertEqual(sorted(p.name for p in (Path(self.tmp.name) / "backup").iterdir()
                                if not p.name.endswith(("-wal", "-shm"))), [f"b{i}.sqlite3" for i in range(5)])

    def test_backup_refuses_existing_destination_and_the_live_database(self):
        dest = Path(self.tmp.name) / "old-backup.sqlite3"
        dest.write_bytes(b"keep me")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.ix.backup(dest)
        self.assertEqual(dest.read_bytes(), b"keep me")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.ix.backup(self.path)

    def test_concurrent_appends_keep_one_unbroken_chain(self):
        def work(k):
            ix = ledger.Index(self.path)
            for n in range(40):
                ix.append("judgment", "me", {"w": k, "n": n})

        threads = [threading.Thread(target=work, args=(k,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        result = self.ix.verify()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["checked"], 160)


class LedgerApiTest(ApiTestCase):
    def make_app(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)  # Windows 上 SQLite 檔可能還被防毒或 WAL 暫時鎖住
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / ledger.DB_NAME
        return {"ledger_path": self.path}

    def test_missing_database_is_not_created_by_a_read(self):
        status, out = self.get("/api/ledger?verify=1")
        self.assertEqual(status, 200)
        self.assertEqual(out["records"], [])
        self.assertTrue(out["verify"]["ok"])
        self.assertFalse(self.path.exists())

    def test_lists_records_read_only(self):
        ix = ledger.Index(self.path)
        a = ix.append("judgment", "me", {"relation": "bull"})
        ix.append("prediction", "me", {"edge": "analysis"})
        ix.append("judgment", "me", {"relation": "bear"}, supersedes=a["id"])
        status, out = self.get("/api/ledger")
        self.assertEqual(status, 200)
        self.assertEqual([r["kind"] for r in out["records"]], ["judgment", "prediction", "judgment"])
        self.assertEqual(out["records"][0]["payload"], {"relation": "bull"})
        self.assertEqual(out["next_after"], 3)
        self.assertEqual(len(self.get("/api/ledger?kind=judgment&current=1")[1]["records"]), 1)
        page = self.get("/api/ledger?after=1&limit=1")[1]
        self.assertEqual((page["records"][0]["seq"], page["next_after"]), (2, 2))
        verify = self.get("/api/ledger?verify=1")[1]["verify"]
        self.assertEqual((verify["ok"], verify["checked"], verify["head_seq"]), (True, 3, 3))

    def test_bad_query_is_a_400_with_a_fixed_message(self):
        for q in ("after=x", "limit=abc", "after=-1", "after=999999999999999999999999999999"):
            with self.subTest(q=q):
                self.assertEqual(self.get("/api/ledger?" + q), (400, {"error": "bad ledger query"}))

    def test_post_is_not_a_write_path(self):
        ledger.Index(self.path)
        status, _ = self.post("/api/ledger", {"kind": "judgment", "who": "me", "payload": {}})
        self.assertNotEqual(status, 200)
        self.assertEqual(self.get("/api/ledger")[1]["records"], [])
        self.assertEqual(self.post("/api/ledger", {}, token="wrong")[0], 403)


if __name__ == "__main__":
    unittest.main()
