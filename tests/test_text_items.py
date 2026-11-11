"""沒有 PDF 的資料（ticket 08）：切段、穩定的段落 ID、版本、以段落分批翻譯和續傳。"""
import json
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from easyread import engines, textitem, translate
from easyread.library import Library
from tests.test_readmode import fill_engine

ARTICLE = """Chip stocks rallied on Tuesday.

Analysts said demand for
accelerators stays strong.

Memory prices rose for a third month."""


class TextItemTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = Library(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def paper(self, ws):
        return ws.load("paper")

    def test_create_without_pdf(self):
        ws, status = textitem.create(self.lib, ARTICLE, title="Chips")
        self.assertEqual(status, "created")
        self.assertTrue(ws.id.startswith("t"))
        self.assertFalse(re.fullmatch(r"[0-9a-f]{12}", ws.id))  # PDF 的 ID 是 12 位十六進位
        self.assertIsNotNone(self.lib.ws(ws.id))
        self.assertFalse((ws.root / "source.pdf").exists())
        paper = self.paper(ws)
        self.assertEqual(paper["meta"]["kind"], "text")
        self.assertEqual(paper["meta"]["page_count"], 3)
        self.assertEqual([b["page"] for b in paper["blocks"]], [1, 2, 3])
        self.assertEqual(paper["blocks"][1]["en"], "Analysts said demand for accelerators stays strong.")
        self.assertEqual(paper["translation"]["en_pages"], [1, 2, 3])
        self.assertEqual(self.lib.summary(ws)["kind"], "text")

    def test_reimport_keeps_ids(self):
        ws, _ = textitem.create(self.lib, ARTICLE)
        ids = [b["id"] for b in self.paper(ws)["blocks"]]
        again, status = textitem.create(self.lib, ARTICLE.replace("\n", "\r\n") + "\n\n\n")
        self.assertEqual(status, "unchanged")
        self.assertEqual(again.id, ws.id)
        self.assertEqual([b["id"] for b in self.paper(again)["blocks"]], ids)

    def test_duplicate_paragraphs_get_suffix(self):
        ids = textitem.para_ids(["Same.", "Other.", "Same."])
        self.assertEqual(ids[2], ids[0] + "-2")
        self.assertEqual(len(set(ids)), 3)

    def test_url_normalization(self):
        a = textitem.item_id("", "https://News.Example.com/a/?utm_source=x&b=2&a=1#top")
        b = textitem.item_id("", "https://news.example.com:443/a?a=1&b=2&fbclid=z")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("w"))
        for bad in ("ftp://x.com/a", "not a url", "https://", "https://x.com/" + "a" * textitem.MAX_URL):
            with self.assertRaises(textitem.TextError):
                textitem.normalize_url(bad)

    def test_changed_source_saves_version_and_keeps_translations(self):
        url = "https://news.example.com/chips"
        ws, _ = textitem.create(self.lib, ARTICLE, url=url)
        ws.update("paper", lambda p: p["blocks"][0].update(zh="晶片股週二上漲。"))
        old_ids = [b["id"] for b in self.paper(ws)["blocks"]]
        changed = ARTICLE.replace("third month", "fourth month")
        same, status = textitem.create(self.lib, changed, url=url + "?utm_medium=mail")
        self.assertEqual((same.id, status), (ws.id, "updated"))
        paper = self.paper(ws)
        self.assertEqual(paper["meta"]["version"], 2)
        self.assertEqual([b["id"] for b in paper["blocks"]][:2], old_ids[:2])
        self.assertNotEqual(paper["blocks"][2]["id"], old_ids[2])
        self.assertEqual(paper["blocks"][0]["zh"], "晶片股週二上漲。")
        self.assertEqual(paper["translation"]["en_pages"], [2, 3])
        saved = textitem.versions(ws)
        self.assertEqual(len(saved), 1)
        old = json.loads((ws.root / "versions" / saved[0]["file"]).read_text(encoding="utf-8"))
        self.assertIn("third month", old["blocks"][2]["en"])

    def test_version_cap_keeps_first(self):
        url = "https://news.example.com/live"
        with mock.patch.object(textitem, "MAX_VERSIONS", 3):
            for n in range(6):
                textitem.create(self.lib, f"Update number {n}.", url=url)
        ws = self.lib.ws(textitem.item_id("", url))
        files = sorted(p.name for p in (ws.root / "versions").glob("paper-*.json"))
        self.assertEqual(len(files), 3)
        self.assertEqual(files[0], "paper-0001.json")  # 第一版留著
        first = json.loads((ws.root / "versions" / files[0]).read_text(encoding="utf-8"))
        self.assertEqual(first["blocks"][0]["en"], "Update number 0.")
        self.assertEqual(self.paper(ws)["meta"]["version"], 6)

    def test_bounds(self):
        with self.assertRaises(textitem.TextError):
            textitem.split_paragraphs("  \n\n ")
        with mock.patch.object(textitem, "MAX_CHARS", 20), self.assertRaises(textitem.TextError):
            textitem.split_paragraphs("x" * 21)
        with mock.patch.object(textitem, "MAX_PARAS", 2), self.assertRaises(textitem.TextError):
            textitem.split_paragraphs("a\n\nb\n\nc")
        with mock.patch.object(textitem, "MAX_PARA_CHARS", 25):
            parts = textitem.split_paragraphs("First sentence here. Second sentence here. " + "z" * 45)
        self.assertTrue(all(len(p) <= 25 for p in parts))
        self.assertEqual(parts[0], "First sentence here.")
        self.assertEqual("".join(parts[2:]), "z" * 45)

    def test_long_paragraph_split_keeps_the_text(self):
        text = "Prices rose 3.5% in the U.S. market today. See example.com for details! Really? Yes. 台積電上漲。真的！？好。"
        with mock.patch.object(textitem, "MAX_PARA_CHARS", 40):
            parts = textitem.split_paragraphs(text)
        self.assertTrue(all(len(p) <= 40 for p in parts))
        self.assertEqual("".join(parts).replace(" ", ""), text.replace(" ", ""))  # 只在句子交界切，字一個都沒改
        self.assertTrue(any("3.5%" in p for p in parts))
        self.assertTrue(any("example.com" in p for p in parts))
        self.assertTrue(any("U.S." in p for p in parts))

    def test_bad_ports_and_ipv6(self):
        for bad in ("https://x.com:abc/", "https://x.com:99999/"):
            with self.assertRaises(textitem.TextError):
                textitem.normalize_url(bad)
        self.assertEqual(textitem.normalize_url("http://[::1]:8080/a"), "http://[::1]:8080/a")

    def test_version_numbers_past_9999(self):
        url = "https://news.example.com/long-live"
        ws, _ = textitem.create(self.lib, "First.", url=url)
        folder = ws.root / "versions"
        folder.mkdir()
        for n in (1, 9998, 9999, 10000):
            (folder / f"paper-{n:04d}.json").write_text(json.dumps({"meta": {"version": n}}), encoding="utf-8")
        (folder / "paper-x.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(textitem, "MAX_VERSIONS", 4):
            textitem.create(self.lib, "Second.", url=url)
        names = sorted(p.name for p in folder.glob("paper-*.json"))
        self.assertEqual(names, ["paper-0001.json", "paper-10000.json", "paper-10001.json", "paper-9999.json", "paper-x.json"])
        self.assertEqual([v["file"] for v in textitem.versions(ws)][:2], ["paper-10001.json", "paper-10000.json"])

    def test_chinese_lines_join_without_space(self):
        self.assertEqual(textitem.split_paragraphs("台積電今天\n上漲。\nAI demand\nstays."), ["台積電今天上漲。 AI demand stays."])


class TextTranslateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lib = Library(self.tmp)
        text = "\n\n".join(f"Paragraph number {n}." for n in range(1, 31))
        self.ws, _ = textitem.create(self.lib, text, title="Thirty")
        self.cfg = {"engine": "openai", "batch_pages": 1, "concurrency": 1, "openai": {"vision": False}}
        self.patches = [mock.patch.object(translate, "tex_problems", lambda tex: []),
                        mock.patch.object(translate.blank_pages, "find", side_effect=AssertionError("no PDF"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_pages(self, engine, pages=None):
        pages = pages or list(range(1, 31))
        with mock.patch.object(engines, "run", engine):
            return translate.translate_pages(self.ws, self.cfg, pages, threading.Event(), lambda *a: None)

    def test_batches_by_paragraph(self):
        calls, prompts = [], []
        inner = fill_engine(calls)

        def engine(cfg, prompt, *a, **kw):
            prompts.append(prompt)
            return inner(cfg, prompt, *a, **kw)
        self.assertEqual(self.run_pages(engine), {})
        self.assertEqual([len(c) for c in calls], [12, 12, 6])  # 每批 PARAS_PER_BATCH 段，不看 batch_pages
        self.assertTrue(any(m in prompts[0] for m in ("第 1, 2, 3", "第 1、2、3")))
        self.assertTrue(all(("段" in p and "学术论文" not in p and "學術論文" not in p) for p in prompts))
        paper = self.ws.load("paper")
        self.assertEqual(paper["translation"]["en_pages"], [])
        self.assertTrue(all(b["zh"] == "中文 " + b["id"] for b in paper["blocks"]))

    def test_resume_after_interruption(self):
        blocks = self.ws.load("paper")["blocks"]
        lost = {b["id"] for b in blocks if b["page"] in (14, 15)}
        failed = self.run_pages(fill_engine([], skip=lost))
        self.assertLessEqual({14, 15}, set(failed))  # 這批回報失敗，但譯好的段已經存進去
        self.assertEqual(self.ws.load("paper")["translation"]["en_pages"], [14, 15])
        calls = []
        self.assertEqual(self.run_pages(fill_engine(calls), [14, 15]), {})
        self.assertEqual(calls, [sorted(lost)])  # 續傳只譯沒譯好的兩段
        self.assertEqual(self.ws.load("paper")["translation"]["en_pages"], [])

    def test_already_translated_paragraphs_are_not_resent(self):
        self.run_pages(fill_engine([]))
        calls = []
        self.assertEqual(self.run_pages(fill_engine(calls), [1, 2]), {})
        self.assertEqual(calls, [])

    def test_read_mode_is_a_no_op(self):
        with mock.patch.object(engines, "run", side_effect=AssertionError("no model call")):
            self.assertEqual(translate.translate_pages(self.ws, self.cfg, [1, 2], threading.Event(), lambda *a: None, read=True), {})


if __name__ == "__main__":
    unittest.main()
