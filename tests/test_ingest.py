"""Ticket 11：貼新聞連結匯入。抽出內容（3 種以上版型的 fixture）、網址正規化、去重、錯誤類別、時間不明、手動貼全文、API。"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import types
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from easyread import fetch, ingest, ledger, textitem
from easyread.library import Library
from tests.doubles import FIXTURES, ApiTestCase, FakeResponse, FakeTransport, fixture

URL = "https://news.example.com/2026/11/chips"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeJobs:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, ws, **kw):
        self.enqueued.append((ws.id, kw))


def make_app(root: Path, *steps):
    return types.SimpleNamespace(
        lib=Library(root / "lib"), ledger_path=root / "newsread.sqlite3", jobs=FakeJobs(),
        fetch_options={"transport": FakeTransport(*steps), "budget": fetch.Budget(), "sleep": lambda s: None})


def story_time(app, item_id):
    with closing(sqlite3.connect(app.ledger_path)) as db:
        row = db.execute("SELECT s.first_published_at FROM stories s JOIN item_story i ON i.story_id = s.id WHERE i.item_id = ?",
                         (item_id,)).fetchone()
    return row[0] if row else None


class ExtractTest(unittest.TestCase):
    def test_json_ld_page_with_article_body(self):
        info = ingest.extract(read("news-jsonld.html"), URL)
        self.assertEqual(info["title"], "（範例）先進封裝擴產：設備交期縮短至 6 個月")
        self.assertEqual(info["publisher"], "範例財經新聞")
        self.assertEqual(info["published_at"], "2026-11-11T10:20:00+08:00")
        self.assertEqual(info["canonical"], "https://news.example.com/news/2026/11/cowos-example")
        self.assertEqual(len(info["paragraphs"]), 5)
        joined = "\n".join(info["paragraphs"])
        for junk in ("導覽列", "圖說", "延伸閱讀", "版權所有", "window.ads"):
            self.assertNotIn(junk, joined)
        self.assertFalse(info["preview_only"])

    def test_open_graph_page_with_article_tag(self):
        info = ingest.extract(read("news-og-en.html"), URL)
        self.assertEqual(info["title"], "(Example) Cloud providers raise next year's capex guidance")
        self.assertEqual(info["publisher"], "Example Wire")
        self.assertEqual(info["published_at"], "2026-11-10T13:05:00+00:00")
        self.assertEqual(len(info["paragraphs"]), 3)
        self.assertIn("expected & could", info["paragraphs"][1])
        self.assertNotIn("cookies", "\n".join(info["paragraphs"]))

    def test_plain_div_page_without_a_timezone(self):
        info = ingest.extract(read("news-div-notime.html"), URL)
        self.assertEqual(info["title"], "（範例）範例記憶體廠十月營收創新高")
        self.assertEqual(info["publisher"], "範例日報")
        self.assertIsNone(info["published_at"])  # 沒有時區：時間不明
        self.assertEqual(info["published_raw"], "2026-11-10 13:30")
        self.assertEqual(len(info["paragraphs"]), 3)
        self.assertNotIn("熱門", "\n".join(info["paragraphs"]))

    def test_paywalled_page_is_a_preview(self):
        info = ingest.extract(read("news-paywall.html"), URL)
        self.assertTrue(info["preview_only"])
        self.assertEqual(len(info["paragraphs"]), 2)
        self.assertNotIn("Subscribe", "\n".join(info["paragraphs"]))

    def test_page_without_text(self):
        info = ingest.extract("<html><head><title>x</title></head><body><nav><p>menu</p></nav></body></html>", URL)
        self.assertEqual(info["paragraphs"], [])

    def test_json_ld_limits(self):
        article = '<script type="application/ld+json">{"@type": "NewsArticle", "headline": "From LD"}</script>'
        filler = '<script type="application/ld+json">{"@type": "WebSite"}</script>'
        html = "<html><head>" + filler + article + "</head><body><article><p>Body text here.</p></article></body></html>"
        self.assertEqual(ingest.extract(html, URL)["title"], "From LD")
        with mock.patch.object(ingest, "MAX_LD_SCRIPTS", 1):  # 只看第一個 JSON-LD
            self.assertEqual(ingest.extract(html, URL)["title"], "")
        with mock.patch.object(ingest, "MAX_LD_CHARS", 20):  # 太長的 JSON-LD 不解
            self.assertEqual(ingest.extract(html, URL)["title"], "")
        many = [{"@type": "Thing"}] * 30 + [{"@type": "NewsArticle", "headline": "Late"}]
        with mock.patch.object(ingest, "MAX_LD_NODES", 10):
            self.assertEqual(ingest._ld_articles([json.dumps(many)]), [])

    def test_deep_nesting_is_bounded(self):
        with mock.patch.object(ingest, "MAX_TAG_DEPTH", 50):
            page = ingest._Page()
            page.feed("<div>" * 500 + "</div>" * 500 + "<article><p>After the deep part.</p></article>")
            self.assertLessEqual(len(page.stack), 50)
        self.assertEqual([p["text"] for p in page.paras], ["After the deep part."])

    def test_paragraphs_without_closing_tags(self):
        html = ("<article><p>First paragraph of the example story." "<p>Second paragraph of the example story.</article>"
                "<div><p>Footer text that is not part of the story.</p></div>")
        self.assertEqual(ingest.extract(html, URL)["paragraphs"],
                         ["First paragraph of the example story.", "Second paragraph of the example story."])
        page = ingest._Page()
        page.feed("<div><p>First block of example text.</div><div><p>Second block of example text.</p></div>")
        page.close()
        self.assertEqual([p["text"] for p in page.paras], ["First block of example text.", "Second block of example text."])
        self.assertEqual(ingest.extract("<article><p>Only one paragraph, never closed", URL)["paragraphs"],
                         ["Only one paragraph, never closed"])

    def test_related_article_cards_are_not_body(self):
        html = ("<article><p>Main story paragraph one, which is long enough.</p><p>Main story paragraph two.</p></article>"
                "<article><p>Related story teaser.</p></article>")
        self.assertEqual(ingest.extract(html, URL)["paragraphs"],
                         ["Main story paragraph one, which is long enough.", "Main story paragraph two."])

    def test_page_wrapped_in_a_form(self):
        html = '<body><form id="aspnetForm"><article><p>Example text inside an ASP.NET page.</p></article></form></body>'
        self.assertEqual(ingest.extract(html, URL)["paragraphs"], ["Example text inside an ASP.NET page."])

    def test_tags_past_the_depth_limit_do_not_close_ancestors(self):
        with mock.patch.object(ingest, "MAX_TAG_DEPTH", 5):
            html = ("<article>" + "<div>" * 4 + "<article>deep</article>" + "</div>" * 4 + "<p>Kept as body text.</p></article>"
                    "<p>Visible " + "<span>" * 10 + "<nav>hidden menu</nav>" + "</span>" * 10 + "text.</p>")
            page = ingest._Page()
            page.feed(html)
            page.close()
        self.assertEqual(page.paras[0]["text"], "Kept as body text.")
        self.assertTrue(page.paras[0]["body"])
        self.assertNotIn("hidden menu", " ".join(p["text"] for p in page.paras))

    def test_event_cap(self):
        with mock.patch.object(ingest, "MAX_EVENTS", 100):
            page = ingest._Page()
            page.feed("<article>" + "<p>Example paragraph.</p>" * 200 + "</article>")
            page.close()
        self.assertTrue(page.stopped)
        self.assertLessEqual(len(page.paras), 50)

    def test_hostile_json_ld(self):
        deep = '<script type="application/ld+json">' + "[" * 5000 + "]" * 5000 + "</script>"
        info = ingest.extract("<html><head>" + deep + "</head><body><article><p>Body text here.</p></article></body></html>", URL)
        self.assertEqual(info["paragraphs"], ["Body text here."])
        nested = "Example Wire"
        for _ in range(40):  # 每層兩個一樣的子清單：沒有深度上限時是指數時間
            nested = [[], nested]
        self.assertEqual(ingest._text_of(nested), "")
        self.assertEqual(ingest._text_of([[], [[], "Example Wire"]]), "Example Wire")

    def test_long_pages_are_truncated_to_what_an_item_holds(self):
        html = "<article>" + "".join(f"<p>Example paragraph number {i}.</p>" for i in range(30)) + "</article>"
        with mock.patch.object(textitem, "MAX_PARAS", 10):
            info = ingest.extract(html, URL)
        self.assertEqual(len(info["paragraphs"]), 10)
        self.assertTrue(info["truncated"])
        self.assertFalse(ingest.extract(read("news-og-en.html"), URL)["truncated"])
        long_title = "<title>" + "T" * 1000 + "</title><article><p>Body text here.</p></article>"
        self.assertEqual(len(ingest.extract(long_title, URL)["title"]), ingest.MAX_FIELD)

    def test_split_title_keeps_lowercase_tails(self):
        self.assertEqual(ingest.split_title("Fed holds rates - again"), ("Fed holds rates - again", ""))
        self.assertEqual(ingest.split_title("Fed holds rates - Example Wire"), ("Fed holds rates", "Example Wire"))

    def test_charset_from_meta_tag(self):
        html = '<html><head><meta charset="big5"></head><body><article><p>範例晶圓廠</p></article></body></html>'
        got = types.SimpleNamespace(headers={"content-type": "text/html"}, body=html.encode("big5"), text=lambda: "")
        self.assertIn("範例晶圓廠", ingest.decode(got))

    def test_parse_time_needs_a_timezone(self):
        self.assertEqual(ingest.parse_time("2026-11-10T13:05:00Z"), "2026-11-10T13:05:00+00:00")
        self.assertEqual(ingest.parse_time("2026-11-10T13:05:00+0800"), "2026-11-10T13:05:00+08:00")
        for bad in ("2026-11-10 13:30", "yesterday", "", "9" * 200):
            self.assertIsNone(ingest.parse_time(bad), bad)

    def test_amp_and_tracking_urls_normalize_to_one(self):
        base = ingest.normalize(URL)
        for variant in (URL + "/amp", URL + ".amp", URL + "?amp=1&utm_source=x", "https://amp.news.example.com/2026/11/chips",
                        URL + "?outputType=amp#comments", "HTTPS://News.Example.com/2026/11/chips/"):
            self.assertEqual(ingest.normalize(variant), base, variant)
        with self.assertRaises(ingest.IngestError) as e:
            ingest.normalize("ftp://news.example.com/x")
        self.assertEqual(e.exception.kind, "invalid_url")

    def test_language(self):
        self.assertTrue(ingest.is_chinese(["範例晶圓廠今天表示，產能會擴充。"]))
        self.assertFalse(ingest.is_chinese(["Chip stocks rallied on Tuesday."]))
        self.assertFalse(ingest.is_chinese([""]))
        # 日文：漢字多，但有假名，不是中文
        self.assertFalse(ingest.is_chinese(["日本銀行は本日、政策金利を据え置くと発表した。市場では追加利上げの観測が強まっている。"]))


class IngestFlowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = mock.patch.object(ingest.config, "load", lambda: {"auto_translate": True})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_english_article_is_created_with_a_story_and_queued_for_translation(self):
        app = make_app(self.root, fixture("news-og-en.html"))
        r = ingest.handle(app, {"url": URL + "?utm_source=newsletter"})
        self.assertEqual(r["status"], "created")
        self.assertEqual((r["publisher"], r["time_source"], r["paragraphs"]), ("Example Wire", "metadata", 3))
        self.assertTrue(r["translate"])
        self.assertEqual([i for i, _ in app.jobs.enqueued], [r["id"]])
        self.assertIs(app.jobs.enqueued[0][1]["background"], True)  # 匯入後自動翻譯受額度保護
        meta = app.lib.ws(r["id"]).load("paper")["meta"]
        self.assertEqual(meta["source_url"], URL)
        self.assertEqual(meta["published_at"], "2026-11-10T13:05:00+00:00")
        self.assertTrue(meta["fetched_at"])
        self.assertEqual(len(meta["content_sha256"]), 64)
        self.assertEqual(story_time(app, r["id"]), "2026-11-10T13:05:00+00:00")

    def test_same_article_is_not_fetched_again(self):
        app = make_app(self.root, fixture("news-og-en.html"))
        first = ingest.handle(app, {"url": URL})
        again = ingest.handle(app, {"url": URL + "/amp?utm_campaign=x"})  # FakeTransport 沒有下一個回應：再抓就會失敗
        self.assertEqual((again["status"], again["id"]), ("exists", first["id"]))
        self.assertEqual(len(app.fetch_options["transport"].requests), 1)
        self.assertTrue(again["added"])

    def test_chinese_article_is_not_translated(self):
        app = make_app(self.root, fixture("news-jsonld.html"))
        r = ingest.handle(app, {"url": URL})
        self.assertTrue(r["same_language"])
        self.assertFalse(r["translate"])
        self.assertEqual(app.jobs.enqueued, [])
        paper = app.lib.ws(r["id"]).load("paper")
        self.assertEqual(paper["translation"]["en_pages"], [])
        self.assertTrue(all(b["zh"] == b["en"] for b in paper["blocks"]))

    def test_simplified_original_is_shown_in_traditional_without_ai(self):
        """譯文語言是台灣繁體、原文是簡體：匯入時用 OpenCC 轉成繁體放譯文欄，不叫 AI，原文保留（#98）。"""
        app = make_app(self.root, fixture("news-jsonld.html"))
        ws_text = "台积电表示，先进封装的产能会继续扩充。" + chr(10) * 2 + "分析师认为软件与网络服务的需求也会增加。"
        with mock.patch.object(ingest.config, "load", lambda: {"auto_translate": True, "target": "zh-TW"}):
            r = ingest.handle(app, {"text": ws_text, "title": "台积电扩充产能"})
        self.assertTrue(r["same_language"] and r["hant_converted"])
        self.assertEqual(app.jobs.enqueued, [])  # 不送 AI 翻譯
        paper = app.lib.ws(r["id"]).load("paper")
        en = [b["en"] for b in paper["blocks"]]
        zh = [b["zh"] for b in paper["blocks"]]
        self.assertEqual(en[0], "台积电表示，先进封装的产能会继续扩充。")  # 原文不動
        self.assertEqual(zh[0], "台積電表示，先進封裝的產能會繼續擴充。")  # 「台」不轉成「臺」
        self.assertIn("軟體", zh[1])  # s2twp：台灣用語
        meta = paper["meta"]
        self.assertEqual((meta["title_en"], meta["title_zh"]), ("台积电扩充产能", "台積電擴充產能"))
        self.assertEqual((meta["target"], meta["paperread_traditional_v"]), ("zh-TW", 1))  # 打開閱讀頁時不再轉一次
        from easyread import traditional
        self.assertFalse(traditional.migrate(app.lib.ws(r["id"])))

    def test_traditional_original_stays_as_it_is(self):
        app = make_app(self.root, fixture("news-jsonld.html"))
        with mock.patch.object(ingest.config, "load", lambda: {"auto_translate": True, "target": "zh-TW"}):
            r = ingest.handle(app, {"text": "台積電表示，先進封裝的產能會繼續擴充。", "title": "台積電擴充產能"})
        paper = app.lib.ws(r["id"]).load("paper")
        self.assertTrue(all(b["zh"] == b["en"] for b in paper["blocks"]))
        self.assertEqual(paper["meta"]["title_zh"], "")  # 繁體原文：不另外存標題，照舊顯示原標題
        self.assertNotIn("hant_converted", paper["meta"])

    def test_simplified_detection(self):
        from easyread import traditional
        self.assertTrue(traditional.looks_simplified(["台积电表示，先进封装的产能会继续扩充。"]))
        self.assertFalse(traditional.looks_simplified(["台積電表示，先進封裝的產能會繼續擴充。"]))
        self.assertFalse(traditional.looks_simplified(["台北"]))  # 只有簡繁共用的字：不轉
        self.assertEqual(traditional.to_taiwan("台北股市上涨，软件股领涨"), "台北股市上漲，軟體股領漲")

    def test_simplified_target_keeps_the_original_copy(self):
        app = make_app(self.root, fixture("news-jsonld.html"))
        with mock.patch.object(ingest.config, "load", lambda: {"auto_translate": True, "target": "zh"}):
            r = ingest.handle(app, {"text": "台积电表示，先进封装的产能会继续扩充。", "title": "台积电扩充产能"})
        paper = app.lib.ws(r["id"]).load("paper")
        self.assertTrue(all(b["zh"] == b["en"] for b in paper["blocks"]))
        self.assertNotIn("paperread_traditional_v", paper["meta"])

    def test_without_opencc_the_original_is_copied(self):
        app = make_app(self.root, fixture("news-jsonld.html"))
        with mock.patch.object(ingest.config, "load", lambda: {"auto_translate": True, "target": "zh-TW"}),                 mock.patch("easyread.i18n._tw_converter", return_value=False):
            r = ingest.handle(app, {"text": "台积电表示，先进封装的产能会继续扩充。", "title": "台积电扩充产能"})
        paper = app.lib.ws(r["id"]).load("paper")
        self.assertTrue(all(b["zh"] == b["en"] for b in paper["blocks"]))

    def test_chinese_article_is_translated_when_target_is_not_chinese(self):
        app = make_app(self.root, fixture("news-jsonld.html"))
        with mock.patch.object(ingest.config, "load", lambda: {"auto_translate": True, "target": "ja"}):
            r = ingest.handle(app, {"url": URL})
        self.assertFalse(r["same_language"])
        self.assertTrue(r["translate"])
        self.assertEqual([i for i, _ in app.jobs.enqueued], [r["id"]])

    def test_unknown_time_story_has_no_time(self):
        app = make_app(self.root, fixture("news-div-notime.html"))
        r = ingest.handle(app, {"url": URL})
        self.assertEqual((r["time_source"], r["published_at"], r["published_raw"]), ("unknown", "", "2026-11-10 13:30"))
        self.assertEqual(story_time(app, r["id"]), "")  # 不拿抓取時間冒充發布時間

    def test_paywall_preview_is_imported_and_marked(self):
        app = make_app(self.root, fixture("news-paywall.html"))
        r = ingest.handle(app, {"url": URL})
        self.assertTrue(r["preview_only"])
        self.assertEqual(r["paragraphs"], 2)

    def test_fetch_errors_are_categories_with_fixed_messages(self):
        cases = [(FakeResponse(status=403, body=b"secret=abc123 denied"), "blocked"), (FakeResponse(status=402), "paywall"),
                 (FakeResponse(status=404), "not_found"),
                 (FakeResponse(body=b"%PDF-1.7", headers={"Content-Type": "application/pdf"}), "unsupported")]
        for response, kind in cases:
            with self.subTest(kind):
                app = make_app(self.root / kind, response)
                with self.assertRaises(ingest.IngestError) as e:
                    ingest.handle(app, {"url": URL})
                self.assertEqual(e.exception.kind, kind)
                self.assertEqual(e.exception.message, fetch.FetchError(kind).message)
                self.assertNotIn("abc123", json.dumps(e.exception.public()))

    def test_internal_addresses_are_refused_without_a_request(self):
        for url in ("http://127.0.0.1/admin", "http://192.168.1.1/", "http://[::1]:8080/x"):
            with self.subTest(url):
                app = make_app(self.root / str(abs(hash(url))))
                with self.assertRaises(ingest.IngestError) as e:
                    ingest.handle(app, {"url": url})
                self.assertEqual(e.exception.kind, "invalid_url")
                self.assertEqual(app.fetch_options["transport"].requests, [])

    def test_page_without_text_suggests_manual_paste(self):
        app = make_app(self.root, FakeResponse(body=b"<html><body><nav><p>menu</p></nav></body></html>",
                                               headers={"Content-Type": "text/html"}))
        with self.assertRaises(ingest.IngestError) as e:
            ingest.handle(app, {"url": URL})
        self.assertEqual(e.exception.kind, "no_text")

    def test_manual_paste(self):
        app = make_app(self.root)
        r = ingest.handle(app, {"text": "First paragraph of the example.\n\nSecond paragraph.", "title": "Manual example",
                                "publisher": "Example Desk", "published_at": "2026-11-10T09:00+08:00", "url": ""})
        self.assertEqual((r["status"], r["time_source"], r["title"]), ("created", "user", "Manual example"))
        self.assertTrue(r["id"].startswith("t"))
        self.assertEqual(story_time(app, r["id"]), "2026-11-10T09:00:00+08:00")
        unknown = ingest.handle(app, {"text": "Another example text without a time."})
        self.assertEqual(unknown["time_source"], "unknown")
        with self.assertRaises(ingest.IngestError) as e:
            ingest.handle(app, {"text": "x", "published_at": "2026-11-10 09:00"})
        self.assertEqual(e.exception.kind, "bad_input")
        for body in ({}, {"text": "  "}, {"url": 5}, [], "x"):
            with self.assertRaises(ingest.IngestError):
                ingest.handle(app, body)

    def test_manual_paste_over_a_preview_saves_a_new_version(self):
        app = make_app(self.root, fixture("news-paywall.html"))
        preview = ingest.handle(app, {"url": URL})
        full = ingest.handle(app, {"url": URL, "text": "(Example) The full text.\n\nSecond paragraph of the full text."})
        self.assertEqual((full["id"], full["status"]), (preview["id"], "updated"))
        self.assertEqual(len(textitem.versions(app.lib.ws(full["id"]))), 1)

    def test_manual_paste_keeps_what_was_fetched(self):
        app = make_app(self.root, fixture("news-og-en.html"))
        fetched = ingest.handle(app, {"url": URL})
        full = ingest.handle(app, {"url": URL, "text": "(Example) The full text.\n\nSecond paragraph of the full text."})
        self.assertEqual(full["status"], "updated")
        for key in ("publisher", "published_at", "time_source"):
            self.assertEqual(full[key], fetched[key], key)
        with self.assertRaises(ingest.IngestError) as e:  # 發布時間記了就不改
            ingest.handle(app, {"url": URL, "text": "(Example) Changed again.", "published_at": "2026-11-09T09:00+08:00"})
        self.assertEqual(e.exception.kind, "bad_input")
        same = ingest.handle(app, {"url": URL, "text": "(Example) Changed again.", "published_at": fetched["published_at"]})
        self.assertEqual(same["status"], "updated")

    def test_manual_time_fills_an_unknown_story_time(self):
        app = make_app(self.root, fixture("news-div-notime.html"))
        first = ingest.handle(app, {"url": URL})
        self.assertEqual((first["time_source"], story_time(app, first["id"])), ("unknown", ""))
        full = ingest.handle(app, {"url": URL, "text": "(Example) Full text.", "published_at": "2026-11-10T09:00+08:00"})
        self.assertEqual((full["time_source"], full["published_at"]), ("user", "2026-11-10T09:00:00+08:00"))
        self.assertEqual(story_time(app, first["id"]), "2026-11-10T09:00:00+08:00")
        self.assertEqual(full["published_raw"], "")

    def test_same_text_with_a_time_fills_meta_and_story_together(self):
        app = make_app(self.root)
        first = ingest.handle(app, {"text": "Example text without a link or a time."})
        self.assertEqual((first["time_source"], story_time(app, first["id"])), ("unknown", ""))
        again = ingest.handle(app, {"text": "Example text without a link or a time.", "published_at": "2026-11-10T09:00+08:00"})
        self.assertEqual((again["id"], again["status"]), (first["id"], "unchanged"))
        self.assertEqual((again["time_source"], again["published_at"]), ("user", "2026-11-10T09:00:00+08:00"))
        self.assertEqual(story_time(app, first["id"]), again["published_at"])  # meta 和 Story 一致
        self.assertEqual(textitem.versions(app.lib.ws(first["id"])), [])

    def test_a_broken_old_time_counts_as_unknown(self):
        app = make_app(self.root)
        r = ingest.handle(app, {"text": "Example text with an old time.", "url": URL})
        app.lib.ws(r["id"]).update("paper", lambda p: p["meta"].update(published_at="2026-11-10 09:00", time_source="metadata"))
        fixed = ingest.handle(app, {"text": "Example text with an old time.", "url": URL, "published_at": "2026-11-10T09:00+08:00"})
        self.assertEqual((fixed["time_source"], fixed["published_at"]), ("user", "2026-11-10T09:00:00+08:00"))
        self.assertEqual(story_time(app, r["id"]), fixed["published_at"])

    def test_reimport_while_translating_is_refused(self):
        app = make_app(self.root)
        r = ingest.handle(app, {"text": "Example text.", "url": URL})
        app.lib.ws(r["id"]).update("job", lambda j: j.update(state="running"))
        with self.assertRaises(ingest.IngestError) as e:
            ingest.handle(app, {"text": "Changed example text.", "url": URL})
        self.assertEqual(e.exception.kind, "busy")
        paper = app.lib.ws(r["id"]).load("paper")
        self.assertEqual(paper["blocks"][0]["en"], "Example text.")  # 沒有寫入
        self.assertEqual(textitem.versions(app.lib.ws(r["id"])), [])

    def test_auto_translate_off(self):
        app = make_app(self.root, fixture("news-og-en.html"))
        with mock.patch.object(ingest.config, "load", lambda: {"auto_translate": False}):
            r = ingest.handle(app, {"url": URL})
        self.assertFalse(r["translate"])
        self.assertEqual(app.jobs.enqueued, [])


class IngestApiTest(ApiTestCase):
    def make_app(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = mock.patch.object(ingest.config, "load", lambda: {"auto_translate": False})
        patcher.start()
        self.addCleanup(patcher.stop)
        app = make_app(self.root, fixture("news-og-en.html"), FakeResponse(status=403))
        return vars(app)

    def test_ingest_endpoint(self):
        status, data = self.request("POST", "/api/ingest", {"url": URL})
        self.assertEqual((status, data["status"]), (200, "created"))
        status, data = self.request("POST", "/api/ingest", {"url": "https://other.example.com/x"})
        self.assertEqual((status, data["kind"]), (502, "blocked"))
        self.assertEqual(data["error"], fetch.FetchError("blocked").message)
        status, data = self.request("POST", "/api/ingest", {"url": "http://127.0.0.1/"})
        self.assertEqual((status, data["kind"]), (400, "invalid_url"))
        status, data = self.request("POST", "/api/ingest", b"not json")
        self.assertEqual((status, data["kind"]), (400, "bad_input"))
        status, data = self.request("POST", "/api/ingest", b"[" * 100_000 + b"]" * 100_000)
        self.assertEqual((status, data["kind"]), (400, "bad_input"))
        status, _ = self.request("POST", "/api/ingest", {"url": URL}, token="wrong")
        self.assertEqual(status, 403)

    def test_unexpected_errors_get_a_fixed_message(self):
        with mock.patch.object(ingest, "handle", side_effect=OSError(r"C:\Users\someone\secret\paper.json")):
            status, data = self.request("POST", "/api/ingest", {"url": URL})
        self.assertEqual((status, data["kind"]), (500, "internal"))
        self.assertEqual(data["error"], ingest.message("internal"))
        self.assertNotIn("secret", json.dumps(data))

    def test_body_limit(self):
        with mock.patch.object(ingest, "MAX_BODY", 64):
            status, data = self.request("POST", "/api/ingest", {"text": "x" * 200})
        self.assertEqual((status, data["kind"]), (413, "too_large"))


class LedgerUnknownTimeTest(unittest.TestCase):
    def test_story_with_unknown_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            ix = ledger.Index(Path(tmp) / "x.sqlite3")
            story = ix.ensure_story("item-unknown", None)
            self.assertEqual(ix.story_of("item-unknown"), story)
            with self.assertRaises(ValueError):
                ix.ensure_story("item-bad", "2026-11-10 09:00")  # 給了時間就要合格
            self.assertTrue(ix.fill_story_time("item-unknown", "2026-11-10T09:00:00+08:00"))
            self.assertFalse(ix.fill_story_time("item-unknown", "2026-11-11T09:00:00+08:00"))  # 已經有時間就不改
            ix.ensure_story("item-known", "2026-11-01T00:00:00+00:00")
            self.assertFalse(ix.fill_story_time("item-known", "2026-11-02T00:00:00+00:00"))


if __name__ == "__main__":
    unittest.main()
