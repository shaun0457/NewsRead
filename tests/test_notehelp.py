"""筆記 AI 助手的語言與輸出規則。"""
import shutil
import unittest

from easyread import notehelp
from tests.test_translate import make_ws


class NoteHelpPromptTest(unittest.TestCase):
    def setUp(self):
        self.ws = make_ws(1)
        self.ws.update("paper", lambda paper: paper.setdefault("meta", {}).update({"target": "zh-TW"}))

    def tearDown(self):
        shutil.rmtree(self.ws.root, ignore_errors=True)

    def test_traditional_prompt_is_explicit_for_review_and_draft(self):
        for mode in ("review", "revise", "draft"):
            with self.subTest(mode=mode):
                prompt = notehelp.prompt(self.ws, mode, "我的筆記", "openai")
                self.assertIn("繁體中文（臺灣用語）", prompt)
                self.assertIn("不可使用簡體字", prompt)
                self.assertNotIn("请点评", prompt)
                self.assertNotIn("请帮读者", prompt)


if __name__ == "__main__":
    unittest.main()
