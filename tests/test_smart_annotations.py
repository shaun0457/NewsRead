import tempfile
import unittest
from pathlib import Path

from easyread import paperdata, smart_annotations
from easyread.store import Workspace, empty_reader, write_json_atomic


class SmartAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        write_json_atomic(root / "paper.json", {
            "meta": {"title_zh": "測試論文"},
            "blocks": [
                {"id": "h1", "type": "heading", "zh": "方法"},
                {"id": "p1", "type": "para", "page": 2, "zh": "我們提出一個新的方法。我們比較結果。", "en": "We propose a new method. We compare results.", "sents": [[24, 11], [44, 18]]},
            ],
        })
        write_json_atomic(root / "reader.json", empty_reader())
        self.ws = Workspace(root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_candidate_uses_exact_source_location_and_rejects_unknown_color(self):
        sources = smart_annotations._sources(self.ws.load("paper"))
        candidate = smart_annotations._candidate(self.ws.id, {
            "anchor": "p1", "quote": "新的方法", "type": "highlight", "color": "yellow",
            "note": "方法核心", "reason": "作者的主要方法主張", "confidence": 0.9,
        }, sources, "test-model", "", "2026-01-01")
        self.assertTrue(candidate["locatable"])
        self.assertEqual(candidate["page"], 2)
        self.assertEqual(candidate["quote"], "新的方法")
        self.assertEqual(candidate["source_en_hash"], smart_annotations.text_hash("We propose a new method. We compare results."))
        self.assertEqual(candidate["source_zh_hash"], smart_annotations.text_hash("我們提出一個新的方法。我們比較結果。"))
        self.assertIsNone(smart_annotations._candidate(self.ws.id, {
            "anchor": "p1", "quote": "新的方法", "type": "highlight", "color": "purple",
        }, sources, "test-model", "", "2026-01-01"))

    def test_prompt_uses_original_english_as_stable_quote(self):
        prompt = smart_annotations._prompt("測試論文", "auto", "", smart_annotations._sources(self.ws.load("paper")))
        self.assertIn("quote_en 必須逐字從 EN 原文複製", prompt)
        self.assertIn('"quote_zh"', prompt)

    def test_location_ignores_sentence_alignment_marker(self):
        source = [{"anchor": "p", "key": "p", "page": 1, "section": "", "zh": "", "en": "A first claim‖ and a second claim."}]
        located = smart_annotations._locate("A first claim and a second claim.", "p", source, "en")
        self.assertIsNotNone(located)
        self.assertEqual(located["side"], "en")

    def test_accept_creates_one_formal_note_and_repeat_is_idempotent(self):
        sources = smart_annotations._sources(self.ws.load("paper"))
        candidate = smart_annotations._candidate(self.ws.id, {
            "anchor": "p1", "quote": "新的方法", "type": "underline", "color": "red", "note": "重點",
        }, sources, "test-model", "", "2026-01-01")
        self.ws.apply_reader_ops([{"op": "ai_annotation", "annotation": candidate, "at": "2026-01-01T00:00:00+08:00"}])
        smart_annotations.apply_action(self.ws, {"action": "accept", "id": candidate["annotation_id"]})
        smart_annotations.apply_action(self.ws, {"action": "accept", "id": candidate["annotation_id"]})
        reader = self.ws.load("reader")
        self.assertEqual(len(reader["notes"]), 1)
        self.assertEqual(reader["notes"][next(iter(reader["notes"]))]["style"], "underline")
        self.assertEqual(reader["ai_annotations"][candidate["annotation_id"]]["status"], "accepted")

    def test_unlocatable_candidate_cannot_be_accepted(self):
        sources = smart_annotations._sources(self.ws.load("paper"))
        candidate = smart_annotations._candidate(self.ws.id, {
            "anchor": "p1", "quote": "模型捏造的句子", "type": "highlight", "color": "yellow",
        }, sources, "test-model", "", "2026-01-01")
        self.assertFalse(candidate["locatable"])
        self.ws.apply_reader_ops([{"op": "ai_annotation", "annotation": candidate, "at": "2026-01-01T00:00:00+08:00"}])
        with self.assertRaises(ValueError):
            smart_annotations.apply_action(self.ws, {"action": "accept", "id": candidate["annotation_id"]})

    def test_english_quote_survives_translation_and_updates_formal_note(self):
        sources = smart_annotations._sources(self.ws.load("paper"))
        candidate = smart_annotations._candidate(self.ws.id, {
            "anchor": "p1", "quote_en": "We propose a new method", "quote_zh": "我們提出一個新的方法。", "type": "highlight", "color": "green", "side": "en",
            "note": "方法核心",
        }, sources, "test-model", "", "2026-01-01")
        self.ws.apply_reader_ops([{"op": "ai_annotation", "annotation": candidate, "at": "2026-01-01T00:00:00+08:00"}])
        smart_annotations.apply_action(self.ws, {"action": "accept", "id": candidate["annotation_id"]})

        paperdata.set_block_text(self.ws, "p1", "這是重新翻譯後的第一句。這是重新翻譯後的第二句。", [[24, 12], [44, 24]])
        reader = self.ws.load("reader")
        refreshed = reader["ai_annotations"][candidate["annotation_id"]]
        self.assertTrue(refreshed["locatable"])
        self.assertEqual(refreshed["side"], "zh")
        self.assertEqual(refreshed["quote"], "這是重新翻譯後的第一句。")
        note = next(iter(reader["notes"].values()))
        self.assertFalse(note.get("stale", False))

    def test_legacy_english_annotation_is_migrated_to_translation(self):
        sources = smart_annotations._sources(self.ws.load("paper"))
        current = smart_annotations._candidate(self.ws.id, {
            "anchor": "p1", "quote_en": "We propose a new method", "quote_zh": "我們提出一個新的方法。",
            "type": "highlight", "color": "green", "note": "方法核心",
        }, sources, "test-model", "", "2026-01-01")
        # 模擬舊版資料：只保存英文 quote，沒有 source_quote_* 欄位。
        legacy = dict(current, side="en", quote="We propose a new method")
        legacy.pop("source_quote_en", None)
        legacy.pop("source_quote_zh", None)
        self.ws.apply_reader_ops([{"op": "ai_annotation", "annotation": legacy, "at": "2026-01-01T00:00:00+08:00"}])
        smart_annotations.apply_action(self.ws, {"action": "accept", "id": legacy["annotation_id"]})

        result = smart_annotations.refresh_after_translation(self.ws)
        self.assertGreaterEqual(result["updated"], 1)
        reader = self.ws.load("reader")
        refreshed = reader["ai_annotations"][legacy["annotation_id"]]
        self.assertEqual(refreshed["side"], "zh")
        self.assertEqual(refreshed["quote"], "我們提出一個新的方法。")
        note = next(iter(reader["notes"].values()))
        self.assertEqual(note["side"], "zh")
        self.assertEqual(note["quote"], "我們提出一個新的方法。")

    def test_old_translation_quote_is_marked_stale_after_retranslation(self):
        sources = smart_annotations._sources(self.ws.load("paper"))
        candidate = smart_annotations._candidate(self.ws.id, {
            "anchor": "p1", "quote": "新的方法", "type": "highlight", "color": "yellow", "side": "zh",
            "note": "舊譯文中的方法",
        }, sources, "test-model", "", "2026-01-01")
        self.ws.apply_reader_ops([{"op": "ai_annotation", "annotation": candidate, "at": "2026-01-01T00:00:00+08:00"}])
        paperdata.set_block_text(self.ws, "p1", "重新翻譯後的另一種說法。")
        refreshed = self.ws.load("reader")["ai_annotations"][candidate["annotation_id"]]
        self.assertFalse(refreshed["locatable"])
        self.assertEqual(refreshed["stale_reason"], "translation_changed")


if __name__ == "__main__":
    unittest.main()
