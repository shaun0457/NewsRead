"""每段第一批的前文参考、全文译完后的术语一致性检查。不调真模型。  python -m unittest tests.test_consistency"""
import json
import shutil
import threading
import unittest
from unittest import mock

from easyread import consistency, engines, front_context, prompts, translate
from tests.test_translate import make_ws


def page_of(prompt: str) -> int:
    return int(prompt.split("这次只处理第 ")[1].split(" ")[0].split(",")[0])


class FrontContextTest(unittest.TestCase):
    def setUp(self):
        self.ws = make_ws(6)
        self.addCleanup(shutil.rmtree, self.ws.root, True)
        ex = self.ws.root / "extract"
        (ex / "page-001.txt").write_text("A Great Paper\nAbstract\nWe study DPO, short for direct preference optimization.", encoding="utf-8")
        (ex / "page-003.txt").write_text("2 Method\nWe define the policy as follows and then we keep", encoding="utf-8")
        (ex / "page-004.txt").write_text("writing the sentence on the next page.", encoding="utf-8")

    def test_reference_has_opening_outline_and_full_previous_page(self):
        text = front_context.build(self.ws.root, 4)
        self.assertIn("DPO, short for direct preference optimization", text)  # 前面定义的缩写
        self.assertIn("2 Method（第 3 页）", text)
        self.assertIn("then we keep", text)  # 页首半句话前面的那整句
        self.assertIn("不要翻译", text)
        self.assertEqual(front_context.build(self.ws.root, 1), "")
        self.assertNotIn("【论文开头】", front_context.build(self.ws.root, 2))  # 上一页就是第 1 页，不重复

    def test_only_first_batch_of_each_later_segment_gets_it(self):
        cfg = {"engine": "openai", "batch_pages": 1, "concurrency": 2, "openai": {"vision": False}}
        seen = {}

        def engine(cfg, prompt, cwd, images=None, cancel=None, meter=None):
            if "这次只处理第" not in prompt:  # 最后的一致性检查
                return '{"fixes": []}'
            page = page_of(prompt)
            seen[page] = "前文参考" in prompt
            return json.dumps({"blocks": [{"id": f"p{page}-1", "type": "para", "page": page, "en": "x", "zh": "译"}]})

        with mock.patch.object(engines, "run", engine), mock.patch.object(translate.pdfwork, "locate", lambda r: None), \
                mock.patch.object(translate, "tex_problems", lambda t: []):
            translate.translate_pages(self.ws, cfg, [1, 2, 3, 4, 5, 6], threading.Event(), lambda *a: None)
        firsts = [p for p, has in seen.items() if has]
        self.assertEqual(len(firsts), 1)  # 两段：只有第二段的第一批
        self.assertGreater(firsts[0], 1)
        self.assertFalse(seen[1])

    def test_prompt_places_reference_before_pages(self):
        p = prompts.translate(self.ws, [4], "text", "", front=front_context.build(self.ws.root, 4))
        self.assertLess(p.index("前文参考"), p.index("===== 第 4 页"))


def paper(blocks, glossary):
    return {"meta": {"target": "zh"}, "glossary": glossary, "blocks": blocks}


class ConsistencyTest(unittest.TestCase):
    GL = [{"en": "standard error", "zh": "标准误差"}, {"en": "policy", "zh": "策略（policy）"}]

    def test_suspects_only_where_term_appears_but_translation_missing(self):
        blocks = [
            {"id": "a", "type": "para", "page": 2, "en": "The standard errors are large.", "zh": "标准误很大。"},
            {"id": "b", "type": "para", "page": 2, "en": "The standard error is small.", "zh": "标准误差很小。"},
            {"id": "c", "type": "para", "page": 3, "en": "No term here.", "zh": "这里没有。"},
            {"id": "d", "type": "list", "page": 3, "items": [{"en": "a policy", "zh": "一个方针"}]},
            {"id": "e", "type": "table", "page": 3, "caption_en": "Table 1: standard error", "caption_zh": "表 1：标准差"},
            {"id": "f", "type": "para", "page": 3, "en": "standard error again", "zh": "又是标准误"},
        ]
        items, agree = consistency.suspects(paper(blocks, self.GL), {"f"})
        got = {s["key"]: [t["want"] for t in s["terms"]] for s in items}
        self.assertEqual(got, {"a": ["标准误差"], "d#0": ["策略"], "e#caption": ["标准误差"]})  # f 用户改过，不查
        self.assertEqual(agree, {"standard error": 1})
        self.assertEqual(consistency.suspects(paper(blocks, self.GL), set(), {2}), consistency.suspects(paper(blocks[:2], self.GL), set()))

    def test_accept_only_term_sized_edits(self):
        old = "设 $x$ 的标准误很大 [3]。"
        self.assertTrue(consistency.accept(old, "设 $x$ 的标准误差很大 [3]。", ["标准误差"]))
        self.assertFalse(consistency.accept(old, "设 $y$ 的标准误差很大 [3]。", ["标准误差"]))   # 改了公式
        self.assertFalse(consistency.accept(old, "设 $x$ 的标准误差很大。", ["标准误差"]))       # 丢了引用号
        self.assertFalse(consistency.accept(old, "设 $x$ 的误差偏大 [3]。", ["标准误差"]))       # 没用上定下的译法
        self.assertFalse(consistency.accept(old, old, ["标准误差"]))
        self.assertFalse(consistency.accept("短", "完全不同的", ["完全"]))
        long = "我们发现这个方法在各种设置下都很稳健，" * 4 + "标准误很大 [3]。"
        self.assertFalse(consistency.accept(long, "标准误差很大 [3]。", ["标准误差"]))  # 删了一大半
        self.assertFalse(consistency.accept("甲‖乙的标准误", "甲乙的标准误差", ["标准误差"]))  # 句子分界不能丢

    def make(self, blocks):
        ws = make_ws(3)
        self.addCleanup(shutil.rmtree, ws.root, True)
        ws.update("paper", lambda p: p.update(glossary=[dict(g) for g in self.GL], blocks=blocks))
        return ws

    def run_check(self, ws, reply, pages=(2,)):
        calls, lines = [], []

        def engine(cfg, prompt, cwd, images=None, cancel=None, meter=None):
            calls.append(prompt)
            return json.dumps(reply)

        with mock.patch.object(engines, "run", engine):
            n = consistency.check(ws, {}, list(pages), None, None, lambda w, s: lines.append(s), threading.Lock())
        return n, calls, lines

    def test_check_applies_accepted_fixes_and_logs(self):
        ws = self.make([{"id": "a", "type": "para", "page": 2, "en": "The standard error.", "zh": "标准误。"},
                        {"id": "b", "type": "para", "page": 2, "en": "A standard error of $x$.", "zh": "$x$ 的标准误。"}])
        n, calls, lines = self.run_check(ws, {"use": {"standard error": "标准误差"},
                                              "fixes": [{"key": "a", "zh": "标准误差。"}, {"key": "b", "zh": "$y$ 的标准误差。"}, {"key": "zzz", "zh": "x"}]})
        self.assertEqual(n, 1)
        zh = {b["id"]: b["zh"] for b in ws.load("paper")["blocks"]}
        self.assertEqual(zh, {"a": "标准误差。", "b": "$x$ 的标准误。"})  # b 改了公式，不采用
        self.assertTrue(any("统一了 标准误差" in s for s in lines))
        self.assertEqual(len(calls), 1)
        self.assertIn("用了术语表译法的段数", calls[0])

    def test_majority_rendering_replaces_glossary_and_rewrites_agreeing_passages(self):
        ws = self.make([{"id": "a", "type": "para", "page": 2, "en": "The standard error and covariance.", "zh": "标准误差和协方差。"},
                        {"id": "b", "type": "para", "page": 2, "en": "Each standard error.", "zh": "每个标准误。"},
                        {"id": "c", "type": "para", "page": 2, "en": "One standard error.", "zh": "一个标准误。"}])
        ws.update("paper", lambda p: p["glossary"].append({"en": "covariance", "zh": "协方差"}))
        n, _, lines = self.run_check(ws, {"use": {"standard error": "标准误"}, "fixes": []})
        paper_ = ws.load("paper")
        self.assertEqual({b["id"]: b["zh"] for b in paper_["blocks"]}, {"a": "标准误和协方差。", "b": "每个标准误。", "c": "一个标准误。"})
        self.assertEqual(next(g["zh"] for g in paper_["glossary"] if g["en"] == "standard error"), "标准误")
        self.assertEqual(n, 1)
        self.assertTrue(any("全文改用“标准误”" in s for s in lines))

    def test_user_edit_during_check_is_not_overwritten(self):
        ws = self.make([{"id": "a", "type": "para", "page": 2, "en": "The standard error.", "zh": "标准误。"}])

        def engine(cfg, prompt, cwd, images=None, cancel=None, meter=None):
            ws.update("reader", lambda r: r.setdefault("edits", {}).__setitem__("a", {"zh": "用户的译文"}))
            return json.dumps({"use": {"standard error": "标准误差"}, "fixes": [{"key": "a", "zh": "标准误差。"}]})

        with mock.patch.object(engines, "run", engine):
            self.assertEqual(consistency.check(ws, {}, [2], None, None, lambda w, s: None, threading.Lock()), 0)
        self.assertEqual(ws.load("paper")["blocks"][0]["zh"], "标准误。")

    def test_no_call_when_nothing_suspicious(self):
        ws = self.make([{"id": "a", "type": "para", "page": 1, "en": "The standard error.", "zh": "标准误差。"}])
        with mock.patch.object(engines, "run", side_effect=AssertionError("不该调模型")):
            self.assertEqual(consistency.check(ws, {}, [1], None, None, lambda w, s: None, threading.Lock()), 0)

    def test_cancel_during_check_keeps_finished_job(self):
        ws = make_ws(4)
        self.addCleanup(shutil.rmtree, ws.root, True)
        cfg = {"engine": "openai", "batch_pages": 1, "concurrency": 2, "openai": {"vision": False}}
        cancel = threading.Event()

        def engine(cfg, prompt, cwd, images=None, cancel_=None, meter=None):
            if "这次只处理第" not in prompt:
                cancel.set()
                raise engines.Cancelled()
            page = page_of(prompt)
            return json.dumps({"glossary": [{"en": "standard error", "zh": "标准误差"}],
                               "blocks": [{"id": f"p{page}-1", "type": "para", "page": page, "en": "standard error", "zh": "标准误"}]})

        with mock.patch.object(engines, "run", engine), mock.patch.object(translate.pdfwork, "locate", lambda r: None),                 mock.patch.object(translate, "tex_problems", lambda t: []):
            failed = translate.translate_pages(ws, cfg, [1, 2, 3, 4], cancel, lambda *a: None)
        self.assertEqual(failed, {})
        self.assertEqual(ws.load("paper")["translation"]["done_pages"], [1, 2, 3, 4])
        self.assertIn("术语一致性检查已取消", (ws.root / "job.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
