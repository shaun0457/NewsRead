"""圖片只保留原文版面佔位，不偵測、翻譯或裁切圖內文字。"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from pypdf import PdfWriter

from easyread import engines, figures, prompts_en, translate
from easyread.store import Workspace, write_json_atomic


class FigureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(self.root / "source.pdf")

    @staticmethod
    def figure():
        return {
            "id": "fig1", "type": "figure", "page": 1,
            "box": [.1, .1, .4, .4], "src": "figures/old.webp",
            "image_en": "Accuracy", "image_zh": "準確率", "caption_en": "Figure 1",
        }

    def test_normalize_figure_keeps_only_placeholder_fields(self):
        block = self.figure()
        figures.normalize_figure(block)
        self.assertEqual(block["src"], "")
        self.assertNotIn("box", block)
        for key in ("image_en", "image_zh", "image_text_en", "image_text_zh"):
            self.assertNotIn(key, block)

    def test_prepare_figures_never_crops_or_keeps_image_text(self):
        blocks = [self.figure()]
        with mock.patch.object(figures, "crop") as crop:
            figures.prepare_figures(self.root, blocks, 1)
        crop.assert_not_called()
        self.assertEqual(blocks[0]["src"], "")
        self.assertNotIn("box", blocks[0])
        self.assertNotIn("image_en", blocks[0])
        self.assertNotIn("image_zh", blocks[0])

    def test_invalid_coordinates_are_still_rejected_by_compatibility_helper(self):
        for box in ([0, 0, float("nan"), 1], [0, 0, float("inf"), 1], [.8, 0, .2, 1]):
            self.assertIsNone(figures.figure_box(box))

    def test_read_drops_figure_text_and_does_not_create_crop(self):
        ws = Workspace(self.root)
        (self.root / "extract").mkdir()
        write_json_atomic(self.root / "paper.json", {"meta": {"page_count": 1}, "blocks": [], "translation": {}})
        original_reader = {"edits": {"fig1#image": {"zh": "my edit"}}}
        write_json_atomic(self.root / "reader.json", original_reader)
        cfg = {"engine": "openai", "openai": {"vision": False}}
        with mock.patch.object(engines, "run", return_value=json.dumps({"blocks": [self.figure()]})), \
             mock.patch.object(translate, "_problems", return_value=[]), \
             mock.patch.object(translate.pdfwork, "locate"):
            translate._one_batch(ws, cfg, [1], 1, threading.Event(), lambda *a: None, read=True)
        block = ws.load("paper")["blocks"][0]
        self.assertEqual(block["src"], "")
        self.assertNotIn("image_en", block)
        self.assertNotIn("image_zh", block)
        self.assertNotIn("fig1#image", prompts_en.todo([block]))
        self.assertEqual(ws.load("reader"), original_reader)

    def test_duplicate_figure_id_still_gets_deduplicated_without_cropping(self):
        ws = Workspace(self.root)
        (self.root / "extract").mkdir()
        old = self.figure()
        old["src"] = "figures/kept.webp"
        write_json_atomic(self.root / "paper.json", {"meta": {"page_count": 1}, "blocks": [old], "translation": {}})
        cfg = {"engine": "openai", "openai": {"vision": False}}
        with mock.patch.object(engines, "run", return_value=json.dumps({"blocks": [self.figure()]})), \
             mock.patch.object(translate, "_problems", return_value=[]), \
             mock.patch.object(translate.pdfwork, "locate"):
            translate._one_batch(ws, cfg, [1], 1, threading.Event(), lambda *a: None)
        blocks = {b["id"]: b for b in ws.load("paper")["blocks"]}
        self.assertEqual(blocks["fig1"]["src"], "")
        self.assertTrue(all(b.get("src", "") == "" for b in blocks.values()))
        self.assertTrue(all("box" not in b for b in blocks.values()))

    def test_legacy_pending_crops_are_noop(self):
        ws = Workspace(self.root)
        block = self.figure()
        write_json_atomic(self.root / "paper.json", {"meta": {"page_count": 1}, "blocks": [block]})
        write_json_atomic(self.root / "layout.json", {"fig1": {"page": 1, "box": [.1, .1, .8, .8]}})
        with mock.patch.object(figures, "crop") as crop:
            self.assertEqual(figures.missing(ws), [])
            self.assertEqual(figures.fill(ws), 0)
        crop.assert_not_called()
        self.assertEqual(ws.load("paper")["blocks"][0]["src"], "figures/old.webp")


if __name__ == "__main__":
    unittest.main()
