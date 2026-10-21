import tempfile
import unittest
from pathlib import Path

from easyread.store import Workspace


class ReaderOpsTest(unittest.TestCase):
    def test_ink_strokes_merge_by_id_and_reject_invalid_coordinates(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(Path(d))
            stroke = {"id": "i1", "group": "g1", "anchor": "p1", "textHash": "1234abcd", "ref": [200, 100],
                      "points": [[1, 2], [3.5, 8]], "color": "#d94b4b", "width": 2}
            ws.apply_reader_ops([{"op": "ink", "stroke": stroke, "at": "2026-10-01T00:01:00Z"}])
            ws.apply_reader_ops([{"op": "ink_del", "id": "i1", "at": "2026-10-01T00:02:00Z"}])
            ws.apply_reader_ops([{"op": "ink", "stroke": stroke, "at": "2026-10-01T00:01:00Z"}])
            self.assertTrue(ws.load("reader")["ink"]["i1"]["deleted"])
            with self.assertRaises(ValueError):
                ws.apply_reader_ops([{"op": "ink", "stroke": {**stroke, "id": "bad", "points": [[float("nan"), 1]]}}])

    def test_deletion_wins_over_delayed_creation_in_both_orders(self):
        note = {"op": "note", "note": {"id": "n1", "body": "旧笔记", "updated": "2026-10-01T00:01:00Z"}}
        delete = {"op": "note_del", "id": "n1", "at": "2026-10-01T00:02:00Z"}
        for ops in [[note, delete], [delete, note]]:
            with self.subTest(ops=ops), tempfile.TemporaryDirectory() as d:
                ws = Workspace(Path(d))
                for op in ops:
                    ws.apply_reader_ops([op])
                self.assertTrue(ws.load("reader")["notes"]["n1"]["deleted"])
                # Explicitly restoring with a newer edit is still possible.
                ws.apply_reader_ops([{**note, "note": {**note["note"], "updated": "2026-10-01T00:03:00Z"}}])
                self.assertFalse(ws.load("reader")["notes"]["n1"].get("deleted", False))

    def test_reading_position_keeps_block_offset_and_ratio(self):
        """回到上次读到的地方要用这三样：哪一块、线在块里的位置、全文比例。"""
        with tempfile.TemporaryDirectory() as d:
            ws = Workspace(Path(d))
            ws.apply_reader_ops([{"op": "progress", "block": "p2", "off": 0.32, "ratio": 0.43, "at": "2026-10-01T00:01:00Z"}])
            self.assertEqual(ws.load("reader")["progress"],
                             {"block": "p2", "off": 0.32, "ratio": 0.43, "at": "2026-10-01T00:01:00Z"})
            # 更早的位置晚到，不覆盖
            ws.apply_reader_ops([{"op": "progress", "block": "p1", "off": 0.9, "ratio": 0.1, "at": "2026-10-01T00:00:00Z"}])
            self.assertEqual(ws.load("reader")["progress"]["block"], "p2")
            # 1.4.2 及以前的操作只带 ratio，照旧能落盘
            ws.apply_reader_ops([{"op": "progress", "block": "p5", "ratio": 0.6, "at": "2026-10-01T00:02:00Z"}])
            self.assertEqual(ws.load("reader")["progress"]["ratio"], 0.6)
            self.assertNotIn("off", ws.load("reader")["progress"])
