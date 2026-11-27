import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread import chat_store
from easyread.store import Workspace, write_json_atomic


class ChatStoreTest(unittest.TestCase):
    def test_empty_chat_can_be_created_renamed_and_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(Path(d))
            write_json_atomic(ws.root / "chat.json", {})
            chat_store.append(ws, "t1", {"content": "q"}, "a", "m", "M")
            chat_store.rename(ws, "t1", "renamed")
            self.assertEqual(chat_store.get(ws, "t1")["title"], "renamed")
            chat_store.delete(ws, "t1")
            self.assertEqual(chat_store.threads(ws), [])

    def test_note_reply_holds_only_the_checked_answer(self):
        """文章問 AI 回答頁邊筆記時，引述對不上原文、畫面上藏起來的句子不寫進頁邊（gate F1）。"""
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(Path(d))
            write_json_atomic(ws.paper_path, {"blocks": [{"id": "p1"}]})
            write_json_atomic(ws.root / "reader.json", {"notes": {"n1": {"id": "n1", "anchor": "p1", "body": "?"}}})
            raw = "- 營收成長〔¶1「營收成長」〕\n- 編造的說法〔¶9「沒有這句」〕"
            checked = {"lead": "", "dropped": 1, "sections": [
                {"kind": "said", "items": [{"text": "營收成長", "cites": [{"n": 1, "quote": "營收成長"}]}]}]}
            chat_store.append(ws, "t1", {"content": "?", "note": "n1"}, raw, "m", "M", extra={"answer": checked})
            body = ws.load("discussion")["entries"][0]["body"]
            self.assertIn("營收成長", body)
            self.assertNotIn("編造的說法", body)
            self.assertNotIn("沒有這句", body)

    def test_same_clock_tick_does_not_alias_threads_or_pinned_answers(self):
        with tempfile.TemporaryDirectory() as d, patch("time.time", return_value=1):
            ws = Workspace(Path(d))
            write_json_atomic(ws.paper_path, {"blocks": [{"id": "p1"}]})
            tids = [chat_store.new_id() for _ in range(10)]
            self.assertEqual(len(set(tids)), 10)
            user = {"content": "q", "anchor": "p1"}
            first = chat_store.append(ws, tids[0], user, "first answer", "m", "M")
            second = chat_store.append(ws, tids[0], user, "second answer", "m", "M")
            self.assertNotEqual(first["id"], second["id"])
            chat_store.pin(ws, tids[0], second["id"])
            self.assertEqual(ws.load("discussion")["entries"][0]["body"], "second answer")

    def test_pin_with_mismatched_thread_id_finds_answer_across_threads(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(Path(d))
            write_json_atomic(ws.paper_path, {"blocks": [{"id": "b1"}]})
            t1 = chat_store.new_id()
            t2 = chat_store.new_id()
            chat_store.append(ws, t1, {"content": "question in t1", "anchor": "b1"}, "answer in t1", "m", "M")
            ans2 = chat_store.append(ws, t2, {"content": "question in t2", "anchor": "b1"}, "answer in t2", "m", "M")
            # Passing wrong thread t1 or non-existent thread still locates ans2
            chat_store.pin(ws, t1, ans2["id"])
            entries = ws.load("discussion")["entries"]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["body"], "answer in t2")
            self.assertEqual(entries[0]["anchor"], "b1")

    def test_pin_with_nonexistent_message_id_raises_key_error(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(Path(d))
            write_json_atomic(ws.paper_path, {"blocks": [{"id": "b1"}]})
            t1 = chat_store.new_id()
            chat_store.append(ws, t1, {"content": "q", "anchor": "b1"}, "ans", "m", "M")
            with self.assertRaises(KeyError):
                chat_store.pin(ws, t1, "nonexistent_mid")
