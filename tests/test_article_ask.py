"""文章的問 AI（ticket 12）：範圍只有全文、回答拆三段、引述對過原文、逐句標記、帳本紀錄。

文章內容都是虛構的範例。
"""
import contextlib
import json
import sqlite3
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from easyread import article_ask, chat_markdown, chat_store, engines, ledger, server
from easyread.server import Handler
from easyread.store import Workspace, write_json_atomic

PARAS = [
    {"id": "p1", "type": "para", "page": 1, "en": "Example Corp said revenue rose 12% in the third quarter.",
     "zh": "範例公司表示第三季營收成長 12%。"},
    {"id": "p2", "type": "para", "page": 2, "en": "The company did not give guidance for next year.",
     "zh": "公司沒有給明年的財測。"},
]

ANSWER = """\
【文章怎麼說】
- 第三季營收成長 12%。〔¶1「revenue rose 12%」〕
- 公司沒有給明年財測。〔¶2「沒有給明年的財測」〕
- 毛利率創新高。〔¶1「gross margin hit a record」〕
- 營收很好，沒有附出處。
【一般解釋】
- 營收成長不一定代表獲利成長。
【文章沒寫的】
- 文章沒有提到股價。
"""


def article(root: Path, published_at="2026-11-01T00:00:00Z", paras=PARAS):
    ws = Workspace(root)
    meta = {"kind": "text", "title_en": "Example Corp Q3", "target": "zh-TW"}
    if published_at:
        meta["published_at"] = published_at
    write_json_atomic(ws.paper_path, {"meta": meta, "blocks": [dict(p) for p in paras]})
    return ws


class ParseTest(unittest.TestCase):
    paras = [{"n": p["page"], "id": p["id"], "en": p["en"], "zh": p["zh"]} for p in PARAS]

    def test_said_keeps_only_items_whose_quote_is_in_the_cited_paragraph(self):
        out = article_ask.parse(ANSWER, self.paras)
        self.assertEqual([s["kind"] for s in out["sections"]], ["said", "general", "missing"])
        said = out["sections"][0]["items"]
        self.assertEqual([i["text"] for i in said], ["第三季營收成長 12%。", "公司沒有給明年財測。"])
        self.assertEqual(said[0]["cites"], [{"n": 1, "id": "p1", "quote": "revenue rose 12%"}])
        self.assertEqual(said[1]["cites"][0]["id"], "p2")  # 引述譯文也算
        self.assertEqual(out["dropped"], 2)  # 引述對不上 + 沒附出處
        self.assertEqual(out["sections"][1]["items"], [{"text": "營收成長不一定代表獲利成長。", "cites": []}])
        self.assertFalse(out["truncated"])

    def test_quote_must_come_from_the_cited_paragraph_number(self):
        out = article_ask.parse("【文章怎麼說】\n- 營收成長。〔¶2「revenue rose 12%」〕\n- 不存在的段。〔¶9「revenue」〕", self.paras)
        self.assertEqual(out["sections"], [])
        self.assertEqual(out["dropped"], 2)

    def test_quote_matching_ignores_width_case_and_spaces(self):
        out = article_ask.parse("## 文章怎麼說\n- 營收。〔¶1「ＲＥＶＥＮＵＥ   rose １２%」〕", self.paras)
        self.assertEqual(out["dropped"], 0)
        self.assertEqual(len(out["sections"][0]["items"]), 1)

    def test_one_bad_cite_drops_the_whole_said_item(self):
        out = article_ask.parse("【文章怎麼說】\n- 營收。〔¶1「revenue rose」〕〔¶1「made up」〕", self.paras)
        self.assertEqual((out["sections"], out["dropped"]), ([], 1))

    def test_too_short_quote_is_not_evidence(self):
        out = article_ask.parse("【文章怎麼說】\n- 營收。〔¶1「r」〕\n- 營收。〔¶1〕", self.paras)
        self.assertEqual((out["sections"], out["dropped"]), ([], 2))

    def test_answer_without_section_titles_is_shown_as_is(self):
        self.assertIsNone(article_ask.parse("這篇文章沒有可以判斷股價的資訊。", self.paras))
        self.assertIsNone(article_ask.parse("", self.paras))

    def test_markdown_bold_and_heading_variants_are_titles(self):
        for head in ("**【文章怎麼說】**", "### 文章怎麼說：", "__文章怎么说__", "[文章怎麼說]"):
            with self.subTest(head=head):
                out = article_ask.parse(head + "\n- 營收。〔¶1「revenue rose」〕\n- 沒出處", self.paras)
                self.assertEqual((len(out["sections"][0]["items"]), out["dropped"]), (1, 1))
        self.assertIsNone(article_ask.parse("- 文章怎麼說", self.paras))  # 列點不是標題

    def test_long_whitespace_lines_parse_fast(self):
        text = "\n".join(["一般解釋" + " " * 20000 + "x", "【一般解釋】" + " " * 20000 + "：x", " " * 50000, "【一般解釋】", "- 點" + " " * 20000 + "x"])
        start = time.monotonic()
        out = article_ask.parse(text, self.paras)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertTrue(out["truncated"])
        self.assertLessEqual(len(out["sections"][0]["items"][0]["text"]), article_ask.MAX_ITEM_CHARS)

    def test_quotes_with_nested_quote_marks_still_match(self):
        paras = [{"n": 1, "id": "p1", "en": 'The CEO said "we expect growth" next year.', "zh": "執行長表示「我們預期成長」。"}]
        out = article_ask.parse("【文章怎麼說】\n- 執行長預期成長。〔¶1「執行長表示「我們預期成長」」〕\n"
                                '- 也有英文。〔¶1「said "we expect growth"」〕', paras)
        self.assertEqual((len(out["sections"][0]["items"]), out["dropped"]), (2, 0))
        self.assertEqual(out["sections"][0]["items"][0]["cites"][0]["quote"], "執行長表示「我們預期成長」")

    def test_quote_longer_than_the_limit_is_not_evidence(self):
        paras = [{"n": 1, "id": "p1", "en": "a" * 400, "zh": ""}]
        ok = article_ask.parse("【文章怎麼說】\n- 長。〔¶1「" + "a" * article_ask.MAX_QUOTE + "」〕", paras)
        too_long = article_ask.parse("【文章怎麼說】\n- 長。〔¶1「" + "a" * (article_ask.MAX_QUOTE + 1) + "」〕", paras)
        self.assertEqual(ok["dropped"], 0)
        self.assertEqual((too_long["sections"], too_long["dropped"]), ([], 1))

    def test_as_text_has_only_the_checked_content(self):
        out = article_ask.parse(ANSWER, self.paras)
        text = article_ask.as_text(out)
        self.assertIn("- 第三季營收成長 12%。〔¶1「revenue rose 12%」〕", text)
        self.assertIn("## 一般解釋（文中沒寫）", text)
        self.assertNotIn("毛利率", text)
        self.assertNotIn("沒有附出處", text)
        self.assertIn("有 2 句的引述對不上原文，已隱藏", text)
        self.assertEqual(article_ask.shown({"content": "原文", "answer": out}), text)
        self.assertEqual(article_ask.shown({"content": "原文"}), "原文")

    def test_lead_and_wrapped_lines(self):
        out = article_ask.parse("先說結論。\n【一般解釋】\n- 第一行\n  接著第二行\n- 第二點", self.paras)
        self.assertEqual(out["lead"], "先說結論。")
        self.assertEqual([i["text"] for i in out["sections"][0]["items"]], ["第一行 接著第二行", "第二點"])

    def test_bounds(self):
        many = "【一般解釋】\n" + "\n".join(f"- 第 {i} 點" for i in range(article_ask.MAX_SECTION_ITEMS + 5))
        out = article_ask.parse(many, self.paras)
        self.assertEqual(len(out["sections"][0]["items"]), article_ask.MAX_SECTION_ITEMS)
        self.assertTrue(out["truncated"])

        long_item = article_ask.parse("【一般解釋】\n- " + "長" * (article_ask.MAX_ITEM_CHARS + 50), self.paras)
        self.assertEqual(len(long_item["sections"][0]["items"][0]["text"]), article_ask.MAX_ITEM_CHARS)
        self.assertTrue(long_item["truncated"])

        cites = "".join("〔¶1「revenue」〕" for _ in range(article_ask.MAX_CITES + 1))
        out = article_ask.parse("【文章怎麼說】\n- 營收。" + cites, self.paras)
        self.assertEqual((out["sections"], out["dropped"]), ([], 1))  # 出處太多：不顯示

        lines = "【一般解釋】\n" + "\n".join("- 點" for _ in range(article_ask.MAX_LINES)) + "\n【文章沒寫的】\n- 看不到"
        out = article_ask.parse(lines, self.paras)
        self.assertEqual([s["kind"] for s in out["sections"]], ["general"])  # MAX_LINES 之後的行不看


class LiveTest(unittest.TestCase):
    """ticket 101：串流中只給已經定案、對過引述的部分。"""
    paras = ParseTest.paras

    def feed_all(self, text, size=1):
        live = article_ask.Live(self.paras)
        return [out for i in range(0, len(text), size) if (out := live.feed(text[i:i + size])) is not None]

    def test_streamed_answer_never_shows_unverified_points_and_only_grows(self):
        final = article_ask.parse(ANSWER, self.paras)
        shown = self.feed_all(ANSWER)
        self.assertTrue(shown)
        dropped = 0
        for out in shown:
            text = json.dumps(out, ensure_ascii=False)
            self.assertNotIn("毛利率", text)  # 引述對不上的那句
            self.assertNotIn("沒有附出處", text)
            kinds = {s["kind"]: s["items"] for s in final["sections"]}
            for section in out["sections"]:
                done = kinds[section["kind"]]
                self.assertEqual(section["items"], done[:len(section["items"])])  # 中途給的點，答完時一樣在
            self.assertGreaterEqual(out["dropped"], dropped)
            self.assertLessEqual(out["dropped"], final["dropped"])
            dropped = out["dropped"]
        self.assertEqual(shown[-1]["dropped"], 2)  # 對不上的照現在的規則算進 dropped
        self.assertNotIn("missing", [s["kind"] for s in shown[-1]["sections"]])  # 最後一點可能還會接下一行：答完才給

    def test_point_still_being_written_waits_for_the_next_point(self):
        live = article_ask.Live(self.paras)
        self.assertIsNone(live.feed("【文章怎麼說】\n- 營收成長。〔¶1「revenue rose 12%」〕\n"))
        self.assertIsNone(live.feed("  而且毛利率創新高〔¶1「gross margin hit a record」〕\n"))  # 同一點接下一行，引述對不上
        out = live.feed("- 公司沒有給財測。〔¶2「沒有給明年的財測」〕\n")
        self.assertEqual((out["sections"], out["dropped"]), ([], 1))  # 先顯示第一行的話，這裡就得藏起來
        self.assertIsNone(live.feed("還沒換行的半句"))

    def test_repeated_section_title_starts_a_new_point(self):
        text = "【文章怎麼說】\n- 營收成長。〔¶1「revenue rose 12%」〕\n【一般解釋】\n- 補充\n【文章怎麼說】\n接著說〔¶1「nope」〕\n"
        out = article_ask.parse(text, self.paras)
        self.assertEqual([i["text"] for i in out["sections"][0]["items"]], ["營收成長。"])  # 沒接到前面已經顯示的那點
        self.assertEqual(out["dropped"], 1)

    def test_lead_shows_before_the_first_title(self):
        live = article_ask.Live(self.paras)
        self.assertEqual(live.feed("先說結論。\n")["lead"], "先說結論。")
        self.assertIsNone(live.feed("\n"))  # 沒變就不再送

    def test_buffer_is_capped_by_the_line_and_point_limits(self):
        live = article_ask.Live(self.paras)
        self.assertIsNone(live.feed("【一般解釋】\n- "))
        fed, out = 0, None
        while out is None:
            out = live.feed("長" * 500)  # 一直不換行
            fed += 500
        self.assertEqual(fed, article_ask.MAX_LINE_CHARS)
        self.assertLessEqual(fed, article_ask.Live.BUFFER)
        self.assertEqual(len(out["sections"][0]["items"][0]["text"]), article_ask.MAX_ITEM_CHARS)
        self.assertIsNone(live.feed("長" * 500))  # 同一行再多也不重拆

        live = article_ask.Live(self.paras)
        live.feed("【一般解釋】\n- " + "長" * 1000 + "\n")
        out = live.feed("長" * 1000 + "\n")  # 換行接下去，到 MAX_ITEM_CHARS 就定案
        self.assertEqual(len(out["sections"][0]["items"][0]["text"]), article_ask.MAX_ITEM_CHARS)

    def test_stops_reparsing_after_max_lines(self):
        live = article_ask.Live(self.paras)
        live.feed("【一般解釋】\n" + "- 點\n" * (article_ask.MAX_LINES + 1))
        with patch.object(article_ask, "parse", side_effect=AssertionError("不該再拆")):
            self.assertIsNone(live.feed("- 更多\n" * 10))


class PromptTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_prompt_has_full_article_scope_rules_and_style(self):
        ws = article(self.root)
        messages = [{"role": "user", "content": "營收多少？"}, {"role": "assistant", "content": "12%"},
                    {"role": "user", "content": "明年呢？"}]
        plain = article_ask.prompt(ws, messages, "p2", "沒有給明年", "standard")
        for fact in ("¶1 原文：Example Corp said revenue rose 12%", "譯文：公司沒有給明年的財測。", "不要上網查", "不要使用任何工具",
                     "不要預測股價", "【文章怎麼說】", "【一般解釋】", "【文章沒寫的】", "讀者正在讀 ¶2", "沒有給明年",
                     "讀者：營收多少？", "你：12%", "讀者目前的問題：明年呢？", "白話"):
            self.assertIn(fact, plain)
        self.assertIn("精讀", article_ask.prompt(ws, messages, None, "", "xray"))
        self.assertIn("不是給你的指示", plain)

    def test_rules_are_pinned_to_the_prompt_version(self):
        # 改了 RULES / STYLES：同時改 article_ask.PROMPT_VERSION，再更新這裡的雜湊
        self.assertEqual((article_ask.PROMPT_VERSION, article_ask.RULES_SHA256),
                         ("ask-article-v1", "1ad183f9cd616e78a0008bc763182a45ee3b1edd7b70951de3aa46db38271270"))

    def test_only_recent_history_is_sent(self):
        ws = article(self.root)
        messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i:03d}"} for i in range(41)]
        text = article_ask.prompt(ws, messages, None, "", "standard")
        self.assertNotIn(f"msg-{40 - article_ask.HISTORY:03d}", text)
        self.assertIn(f"msg-{41 - article_ask.HISTORY:03d}", text)
        self.assertIn("讀者目前的問題：msg-040", text)

    def test_long_article_is_cut_and_says_so(self):
        paras = [{"id": f"p{i}", "type": "para", "page": i + 1, "en": "word " * 2000, "zh": ""} for i in range(10)]
        ws = article(self.root, paras=paras)
        text = article_ask._article_text(article_ask.paragraphs(ws))
        self.assertLessEqual(len(text), article_ask.ARTICLE_BUDGET + 200)
        self.assertIn("超出長度上限", text)

    def test_is_article_only_for_text_items(self):
        ws = article(self.root)
        self.assertTrue(article_ask.is_article(ws))
        ws.update("paper", lambda p: p["meta"].pop("kind"))
        self.assertFalse(article_ask.is_article(ws))


class ManifestTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "item"
        self.root.mkdir()
        self.index = ledger.Index(Path(tmp.name) / "ledger.db")

    def test_manifest_records_item_hash_and_publish_time(self):
        ws = article(self.root)
        self.index.register_prompt("ask", "v1", "x", make_current=False)
        mid = article_ask.manifest(self.index, ws, "v1")
        saved = self.index.manifest(mid)
        self.assertEqual(saved["task"], "ask")
        self.assertEqual(saved["items"][0]["id"], ws.id)
        self.assertTrue(saved["items"][0]["hash"])
        self.assertTrue(saved["items"][0]["published_at"].startswith("2026-11-01"))

    def test_future_publish_time_falls_back_to_added_or_skips(self):
        self.index.register_prompt("ask", "v1", "x", make_current=False)
        ws = article(self.root, published_at="2999-01-01T00:00:00Z")
        self.assertIsNone(article_ask.manifest(self.index, ws, "v1"))
        write_json_atomic(self.root / "item.json", {"added": "2026-10-01T00:00:00Z"})
        mid = article_ask.manifest(self.index, ws, "v1")
        self.assertTrue(self.index.manifest(mid)["items"][0]["published_at"].startswith("2026-10-01"))


class ServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        (base / "item").mkdir()
        self.ws = article(base / "item")
        self.ledger_path = base / "ledger.db"
        ws, ledger_path = self.ws, self.ledger_path

        class TestHandler(Handler):
            app = types.SimpleNamespace(token="test-token", lib=types.SimpleNamespace(ws=lambda pid: ws), ledger_path=ledger_path,
                                        location=types.SimpleNamespace(status="idle", request=lambda *a: contextlib.nullcontext()))

            def log_message(self, *args):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.base = f"http://127.0.0.1:{srv.server_port}/api/p/test/chat"

    def request(self, url, body):
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", "X-Token": "test-token"})
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.read().decode()

    def ask(self, body, answer=ANSWER, stream=None):
        prompts, self.stream_kw = [], []

        def fake_stream(ecfg, prompt_text, root, cancel, seen, meter, **kw):
            prompts.append(prompt_text)
            self.stream_kw.append(kw)
            meter.add(input=100, output=20)
            yield answer
        model = {"id": "m", "name": "Model", "engine": "claude", "model": "opus"}
        with patch("easyread.server.config.load", return_value={}), \
                patch("easyread.server.chat_models.engine_cfg", return_value=({"engine": "claude"}, model)), \
                patch("easyread.server.chat.stream", side_effect=stream or fake_stream):
            events = [json.loads(line) for line in self.request(self.base, body).splitlines()]
        return events, prompts

    def test_article_ask_turns_off_claude_tools(self):
        self.ask({"text": "營收多少？"})
        self.assertEqual(self.stream_kw, [{"tools": False}])

    def test_answer_is_capped_and_the_engine_is_stopped(self):
        cancelled = []

        def endless(ecfg, prompt_text, root, cancel, seen, meter, **kw):
            try:
                for _ in range(10_000):
                    yield "長" * 100
            finally:
                cancelled.append(cancel.is_set())
        with patch.object(server, "MAX_ANSWER_CHARS", 1050):
            events, _ = self.ask({"text": "寫長一點"}, stream=endless)
        saved = chat_store.get(self.ws, events[0]["thread"])["messages"][-1]["content"]
        self.assertTrue(saved.startswith("長" * 1050))
        self.assertIn("回答太長，已截斷", saved)
        self.assertEqual(saved.split("\n\n")[0], "長" * 1050)
        self.assertEqual(cancelled, [True])

    def test_no_exposure_when_the_engine_fails_before_answering(self):
        def failing(*a, **kw):
            raise engines.EngineError("NO_AI")
            yield  # noqa: unreachable — 讓它是 generator
        events, _ = self.ask({"text": "營收多少？"}, stream=failing)
        self.assertIn("error", events[-1])
        index = ledger.shared(self.ledger_path)
        self.assertEqual(index.exposures(self.ws.id), [])

    def test_stopped_answer_keeps_the_parsed_sections(self):
        def stopped(ecfg, prompt_text, root, cancel, seen, meter, **kw):
            yield ANSWER
            raise ConnectionResetError()
        events, _ = self.ask({"text": "營收多少？"}, stream=stopped)
        saved = chat_store.get(self.ws, events[0]["thread"])["messages"][-1]
        self.assertIn("已停止", saved["content"])
        self.assertEqual(saved["answer"]["dropped"], 2)
        self.assertTrue(saved["prompt_version"].startswith("ask-article-v1@"))

    def test_pin_and_export_use_only_the_checked_content(self):
        events, _ = self.ask({"text": "營收多少？", "anchor": "p1"})
        tid, mid = events[0]["thread"], events[-1]["id"]
        chat_store.pin(self.ws, tid, mid)
        body = self.ws.load("discussion")["entries"][-1]["body"]
        exported = chat_markdown.export(self.ws, {"thread": tid, "id": mid})["markdown"]
        for text in (body, exported):
            self.assertIn("第三季營收成長 12%", text)
            self.assertNotIn("毛利率", text)
            self.assertNotIn("沒有附出處", text)

    def test_article_answer_is_parsed_saved_and_recorded_in_the_ledger(self):
        events, prompts = self.ask({"text": "營收多少？", "anchor": "p1"})
        self.assertIn("不要上網查", prompts[0])
        done = events[-1]
        self.assertTrue(done["done"])
        self.assertEqual(done["answer"]["dropped"], 2)
        self.assertEqual(done["prompt_version"], "ask-article-v1@claude/opus")
        saved = chat_store.get(self.ws, events[0]["thread"])["messages"][-1]
        self.assertEqual(saved["answer"], done["answer"])
        self.assertEqual(saved["content"], ANSWER)  # 原文照樣留著

        index = ledger.shared(self.ledger_path)
        rows = index.usage()
        self.assertEqual([(r["task"], r["input_tokens"]) for r in rows], [("ask", 100)])
        self.assertEqual(rows[0]["context_manifest"], saved["manifest"])
        self.assertEqual(index.manifest(saved["manifest"])["prompt_version"], done["prompt_version"])
        self.assertEqual([e["place"] for e in index.exposures(self.ws.id)], ["ask_ai"])

        self.ask({"thread": events[0]["thread"], "text": "再說一次"})
        self.assertEqual(len(index.exposures(self.ws.id)), 1)  # 每個地點只記第一次
        self.assertEqual(len(index.usage()), 2)

    def test_article_stream_sends_only_checked_parts(self):
        def chunks(ecfg, prompt_text, root, cancel, seen, meter, **kw):
            for i in range(0, len(ANSWER), 3):
                yield ANSWER[i:i + 3]
        events, _ = self.ask({"text": "營收多少？"}, stream=chunks)
        self.assertFalse([e for e in events if "t" in e])  # 原文片段不送
        partial = [e["partial"] for e in events if "partial" in e]
        self.assertTrue(partial)
        for out in partial:
            self.assertNotIn("毛利率", json.dumps(out, ensure_ascii=False))
        self.assertEqual(events[-1]["answer"]["dropped"], 2)
        self.assertNotIn("content", events[-1])  # 拆好的回答不用再帶原文

    def test_plain_answer_has_no_sections(self):
        events, _ = self.ask({"text": "股價會漲嗎？"}, answer="這篇文章沒有可以判斷股價的資訊。")
        self.assertIsNone(events[-1]["answer"])
        self.assertEqual(events[-1]["content"], "這篇文章沒有可以判斷股價的資訊。")  # 沒照格式：答完照原文顯示
        self.assertNotIn("answer", chat_store.get(self.ws, events[0]["thread"])["messages"][-1])

    def test_ledger_failure_does_not_block_the_answer(self):
        with patch("easyread.server.ledger.shared", side_effect=sqlite3.OperationalError("disk")), \
                patch("easyread.jobs.ledger.shared", side_effect=sqlite3.OperationalError("disk")):
            events, _ = self.ask({"text": "營收多少？"})
        self.assertTrue(events[-1]["done"])
        self.assertNotIn("manifest", chat_store.get(self.ws, events[0]["thread"])["messages"][-1])

    def test_pdf_papers_keep_the_paper_prompt(self):
        self.ws.update("paper", lambda p: p["meta"].pop("kind"))
        events, prompts = self.ask({"text": "Explain"})
        self.assertNotIn("不要上網查", prompts[0])
        self.assertIsNone(events[-1]["answer"])
        self.assertTrue([e for e in events if "t" in e])  # 論文照舊送原文片段
        self.assertNotIn("content", events[-1])
        self.assertFalse(self.ledger_path.exists())  # 論文的問 AI 不寫帳本

    def test_rate_sets_clears_and_rejects_bad_input(self):
        events, _ = self.ask({"text": "營收多少？"})
        tid, mid = events[0]["thread"], events[-1]["id"]
        rate = self.base + "/rate"
        out = json.loads(self.request(rate, {"thread": tid, "id": mid, "key": "0.1", "verdict": "fabricated"}))
        self.assertEqual(out["ratings"]["0.1"]["verdict"], "fabricated")
        self.assertEqual(chat_store.get(self.ws, tid)["messages"][-1]["ratings"]["0.1"]["verdict"], "fabricated")
        out = json.loads(self.request(rate, {"thread": tid, "id": mid, "key": "0.1", "verdict": None}))
        self.assertEqual(out["ratings"], {})
        for bad in ({"key": "5.0", "verdict": "wrong"}, {"key": "x", "verdict": "wrong"}, {"key": "0.0", "verdict": "maybe"},
                    {"key": "0.0", "verdict": "wrong", "id": "nope"}):
            with self.subTest(bad=bad):
                with self.assertRaises(urllib.error.HTTPError) as err:
                    self.request(rate, {"thread": tid, "id": mid, **bad})
                self.assertEqual(err.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
