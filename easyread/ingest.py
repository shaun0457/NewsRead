"""貼新聞連結匯入（ticket 11）：網址正規化、抓頁面、抽出標題 / 媒體 / 發布時間 / 正文，建成一則沒有 PDF 的資料。

所有入口（匯入頁、右上角「＋ 貼網址」、Ctrl+V）都呼叫 POST /api/ingest，也就是這裡的 handle()。

- 同一篇只匯入一次：網址去掉追蹤參數和 AMP 版之後算 ID（textitem.item_id），已經有了就不再抓。
- 發布時間一定要帶時區才算數；頁面上的時間沒有時區、或根本找不到，就標「時間不明」（time_source = unknown），
  原文留在 published_raw，讓使用者自己確認。時間不明的資料不納入事件驗證（spec「時間點規則」）。
- 付費牆：頁面自己標了 isAccessibleForFree = false，或正文落在 paywall 區塊裡又只有幾段，就標「只有預覽」。
- 抓取失敗只回錯誤類別和固定訊息（fetch.FetchError.public()）；上游的原文不進回應、不進 log。
- 原文是中文的（和譯文同一種語言）不送翻譯：譯文欄直接放原文。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from . import config, fetch, langs, ledger, textitem
from .i18n import tr
from .log import log

SOURCE = "news"                      # 抓取規則的每小時上限用這個來源名
ACCEPT = ("text/html", "application/xhtml")
MAX_BODY = 2 * 1024 * 1024           # POST /api/ingest 的 body 上限（手動貼全文最多 40 萬字，UTF-8 約 1.2 MB）
MAX_FIELD = 300                      # 標題、媒體名稱、時間這些短欄位的上限（字元）
MAX_LD_SCRIPTS = 20                  # 最多看幾個 JSON-LD
MAX_LD_CHARS = 256 * 1024            # 每個 JSON-LD 最多幾個字
MAX_LD_NODES = 500                   # 走訪 JSON-LD 時最多看幾個物件
MAX_TAG_DEPTH = 400                  # HTML 巢狀超過這個深度就不再往下記
MAX_EVENTS = 200_000                 # 一頁最多處理幾個標籤；超過就停（惡意頁面拖不住請求）
MAX_TEXT_DEPTH = 4                   # JSON-LD 裡的名稱欄位最多往下找幾層
PREVIEW_PARAS = 5                    # 落在付費牆區塊、段數不超過這個數字時當成只有預覽
MIN_PARA_CHARS = 20                  # 挑正文區塊時，太短的段落（按鈕文字、圖說）不計分
CJK_RATIO = 0.3                      # 正文的字裡中日文字元超過這個比例，就當成中文原文

ERROR_KINDS = ("no_text", "busy", "bad_input", "internal")

_AMP_QUERY = {"amp", "outputtype", "amp_js_v", "usqp"}
_ARTICLE_TYPES = {"newsarticle", "article", "reportagenewsarticle", "blogposting", "analysisnewsarticle", "opinionnewsarticle"}
_BODY_HINT = re.compile(r"article[-_]?body|story[-_]?body|post[-_]?content|entry[-_]?content|article[-_]?content|news[-_]?content", re.I)
_PAYWALL_HINT = re.compile(r"paywall|subscriber[-_]?only|premium[-_]?content|meter[-_]?wall", re.I)
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "nav", "footer", "aside", "button", "select",
              "iframe", "figcaption", "header"}  # 不含 form：ASP.NET 網站用 <form> 包住整個 body
_CLOSES_P = {"address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figcaption", "figure",
             "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "main", "menu", "nav",
             "ol", "p", "pre", "section", "table", "ul"}  # HTML 規格裡會自動結束 <p> 的開頭標籤
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_TEXT_TAGS = {"p", "h2", "h3"}
_CONTAINERS = {"article", "main", "section", "div"}
_CJK = re.compile(r"[㐀-鿿豈-﫿]")  # i18n-ok 中日文字元範圍
_LETTER = re.compile(r"\w")
_KANA = re.compile(r"[぀-ヿ]")  # i18n-ok 平假名、片假名：有這些就是日文，不是中文
KANA_RATIO = 0.05                     # 中日文字元裡假名超過這個比例，就當成日文
_TIME_META = ("article:published_time", "og:article:published_time", "datepublished", "pubdate", "publishdate",
              "publish-date", "parsely-pub-date", "sailthru.date", "dc.date.issued", "date")


class IngestError(Exception):
    """匯入失敗：kind 是固定的類別，message 是固定訊息（不含上游原文、不含使用者輸入）。"""

    def __init__(self, kind: str, message: str):
        super().__init__(kind)
        self.kind = kind
        self.message = message

    def public(self) -> dict:
        return {"kind": self.kind, "message": self.message}


def _messages() -> dict:
    return {
        "no_text": tr("這一頁抽不到正文，可以改成手動貼全文。"),
        "busy": tr("這篇正在翻譯，等它結束再重新匯入。"),
        "bad_input": tr("要給網址，或是手動貼上的全文。"),
        "internal": tr("匯入時出了問題，請稍後再試。"),
    }


def message(kind: str) -> str:
    return _messages()[kind]


def _error(kind: str) -> IngestError:
    return IngestError(kind, message(kind))


def http_status(kind: str) -> int:
    """API 的狀態碼：輸入不對 400、正在翻譯 409、抽不到正文 422，其他（抓取失敗）502。"""
    return {"bad_input": 400, "invalid_url": 400, "busy": 409, "no_text": 422}.get(kind, 502)


# ---------- 網址 ----------
def normalize(url: str) -> str:
    """textitem.normalize_url 之外，再把 AMP 版換回一般版：amp. 開頭的主機、結尾的 /amp、.amp、?amp=1。"""
    try:
        clean = textitem.normalize_url(url)
    except textitem.TextError:
        raise IngestError("invalid_url", fetch.FetchError("invalid_url").message) from None
    parts = urlsplit(clean)
    host = parts.netloc
    if host.startswith("amp.") and host.count(".") >= 2:
        host = host[4:]
    path = re.sub(r"(/amp|\.amp)$", "", parts.path) or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _AMP_QUERY])
    return urlunsplit((parts.scheme, host, path, query, ""))


# ---------- 抽出內容 ----------
class _Page(HTMLParser):
    """一次走完 HTML：收 <title>、<meta>、canonical、JSON-LD、<time>，以及每個段落和它所在的區塊。

    每個事件的成本固定：跳過區塊、付費牆區塊、開著的標籤都用計數器記，不每次掃整個 stack。
    超過 MAX_TAG_DEPTH 的標籤不進 stack，只記層數（self.deep），裡面的字不收；超過 MAX_EVENTS 個標籤就停。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.serial = 0
        self.events = 0
        self.stopped = False
        self.deep = 0                      # 超過深度上限、還開著的標籤數
        self.open: dict[str, int] = {}     # 每種標籤目前開著幾個
        self.skip_n = 0                    # 開著的跳過區塊（nav、script…）數
        self.paywall_n = 0                 # 開著的付費牆區塊數
        self.containers: list[int] = []    # 開著的區塊（article / main / section / div）serial
        self.bodies: list[int] = []        # 開著的「文章本文」區塊 serial
        self.title = ""
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.ld: list[str] = []
        self.times: list[str] = []
        self.paras: list[dict] = []
        self._text: list[str] | None = None
        self._text_serial = 0
        self._title: list[str] | None = None
        self._ld: list[str] | None = None
        self._ld_size = 0

    def _skipping(self) -> bool:
        return self.skip_n > 0 or self.deep > 0

    def _count(self) -> bool:
        """每個標籤算一個事件；超過 MAX_EVENTS 就停止收集（回 False）。"""
        if self.stopped:
            return False
        self.events += 1
        if self.events > MAX_EVENTS:
            self.stopped = True
            log.warning("ingest html event cap reached")
            return False
        return True

    def _push(self, tag: str, a: dict) -> None:
        hint = " ".join((a.get("class", ""), a.get("id", ""), a.get("itemprop", "")))
        self.serial += 1
        e = {"tag": tag, "serial": self.serial, "skip": tag in _SKIP_TAGS,
             "body": tag == "article" or "articlebody" in hint.lower() or bool(_BODY_HINT.search(hint)),
             "paywall": bool(_PAYWALL_HINT.search(hint))}
        self.stack.append(e)
        self.open[tag] = self.open.get(tag, 0) + 1
        self.skip_n += e["skip"]
        self.paywall_n += e["paywall"]
        if tag in _CONTAINERS:
            self.containers.append(e["serial"])
        if e["body"]:
            self.bodies.append(e["serial"])

    def _pop(self) -> dict:
        e = self.stack.pop()
        self.open[e["tag"]] -= 1
        self.skip_n -= e["skip"]
        self.paywall_n -= e["paywall"]
        if self.containers and self.containers[-1] == e["serial"]:
            self.containers.pop()
        if self.bodies and self.bodies[-1] == e["serial"]:
            self.bodies.pop()
        if self._text is not None and e["serial"] == self._text_serial:
            self._finish(e["tag"])
        return e

    def _pop_through(self, tag: str) -> None:
        while self.stack and self._pop()["tag"] != tag:
            pass

    def handle_starttag(self, tag, attrs):
        if not self._count():
            return
        a = {k.lower(): (v or "") for k, v in attrs if k}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"][:MAX_FIELD * 4]
            return
        if tag == "link":
            if "canonical" in a.get("rel", "").lower().split() and not self.canonical:
                self.canonical = a.get("href", "")[:textitem.MAX_URL]
            return
        if tag == "br" and self._text is not None:
            self._text.append(" ")
        if tag in _VOID:
            return
        if tag == "time" and a.get("datetime") and len(self.times) < 10:
            self.times.append(a["datetime"][:MAX_FIELD])
        if tag == "title" and not self.title:
            self._title = []
        if tag == "script" and "ld+json" in a.get("type", "").lower() and len(self.ld) < MAX_LD_SCRIPTS:
            self._ld, self._ld_size = [], 0
        if self.deep or len(self.stack) >= MAX_TAG_DEPTH:
            self.deep += 1
            return
        if tag in _CLOSES_P and self.open.get("p"):
            self._pop_through("p")  # HTML 可以省略 </p>：下一個區塊開始就算上一段結束
        self._push(tag, a)
        if tag in _TEXT_TAGS and self._text is None and not self._skipping():
            self._text, self._text_serial = [], self.serial

    def handle_endtag(self, tag):
        if not self._count():
            return
        if tag == "title" and self._title is not None:
            self.title = re.sub(r"\s+", " ", "".join(self._title)).strip()[:MAX_FIELD]
            self._title = None
        if tag == "script" and self._ld is not None:
            self.ld.append("".join(self._ld))
            self._ld = None
        if self.deep:
            self.deep -= 1  # 深度上限以下的結尾標籤只抵掉層數，不去關上面的祖先
            return
        if self.open.get(tag):
            self._pop_through(tag)  # 沒有開頭的結尾標籤不理

    def close(self):
        super().close()
        while self.stack:  # 頁面結束時還開著的段落（沒寫 </p>）也收進來
            self._pop()

    def _finish(self, tag):
        text = re.sub(r"\s+", " ", "".join(self._text or [])).strip()
        self._text = None
        if not text or len(self.paras) >= textitem.MAX_PARAS * 2:
            return
        self.paras.append({"text": text, "tag": tag, "container": self.containers[-1] if self.containers else 0,
                           "body": self.bodies[0] if self.bodies else 0, "paywall": self.paywall_n > 0})

    def handle_data(self, data):
        if self.stopped:
            return
        if self._title is not None:
            self._title.append(data)
        if self._ld is not None:
            if self._ld_size < MAX_LD_CHARS:
                self._ld.append(data[:MAX_LD_CHARS - self._ld_size])
                self._ld_size += len(data)
            return
        if self._text is not None and not self._skipping():
            self._text.append(data)


def _ld_articles(scripts: list[str]) -> list[dict]:
    """JSON-LD 裡的新聞物件（NewsArticle、Article…），含 @graph 和陣列；最多看 MAX_LD_NODES 個物件。"""
    out, budget = [], [MAX_LD_NODES]

    def walk(node, depth=0):
        if budget[0] <= 0 or depth > 6:
            return
        if isinstance(node, list):
            for x in node:
                walk(x, depth + 1)
            return
        if not isinstance(node, dict):
            return
        budget[0] -= 1
        kinds = node.get("@type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if any(isinstance(k, str) and k.lower() in _ARTICLE_TYPES for k in kinds):
            out.append(node)
        for key in ("@graph", "mainEntity", "mainEntityOfPage"):
            if isinstance(node.get(key), (list, dict)):
                walk(node[key], depth + 1)

    for raw in scripts:
        if len(raw) >= MAX_LD_CHARS:
            continue  # 被截斷的 JSON 解不開，也不值得試
        try:
            walk(json.loads(raw))
        except (ValueError, RecursionError):  # 壞掉的、或巢狀深到解不開的 JSON
            continue
    return out


def _text_of(value, depth: int = 0) -> str:
    """字串、{"name": …}、或清單裡第一個有字的；最多往下 MAX_TEXT_DEPTH 層、每層看 20 個。"""
    if depth > MAX_TEXT_DEPTH:
        return ""
    if isinstance(value, dict):
        value = value.get("name") or ""
    if isinstance(value, list):
        for v in value[:20]:
            text = _text_of(v, depth + 1)
            if text:
                return text
        return ""
    return re.sub(r"\s+", " ", value).strip()[:MAX_FIELD] if isinstance(value, str) else ""


def parse_time(value: str) -> str | None:
    """ISO 8601 而且帶時區才回傳（統一成 isoformat）；沒有時區、格式不對都回 None。"""
    value = (value or "").strip()[:64]
    if not value:
        return None
    value = value[:-1] + "+00:00" if value.endswith("Z") else value
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)  # +0800 → +08:00：Python 3.10 的 fromisoformat 只認有冒號的時區
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.isoformat() if dt.tzinfo is not None else None


def _body(paras: list[dict], locked: bool = False) -> tuple[list[str], bool]:
    """挑正文：有標成文章本文的段落（<article>、itemprop=articleBody、article-body 之類的 class）就用那些；
    沒有就挑總字數最多的那個區塊。回傳 (段落, 是不是落在付費牆區塊)。
    locked：頁面自己標了不是免費的；這時付費牆區塊裡的字是「訂閱才能看」的提示，不算正文。"""
    walled = any(p["paywall"] for p in paras)
    if locked:
        paras = [p for p in paras if not p["paywall"]]
    groups: dict[int, int] = {}  # 最外層的文章本文區塊 → 總字數；頁面上有好幾個 <article>（相關新聞卡片）時挑字最多的
    for p in paras:
        if p["body"]:
            groups[p["body"]] = groups.get(p["body"], 0) + len(p["text"])
    chosen = [p for p in paras if groups and p["body"] == max(groups, key=groups.get)]
    if not chosen:
        score: dict[int, int] = {}
        for p in paras:
            if len(p["text"]) >= MIN_PARA_CHARS:
                score[p["container"]] = score.get(p["container"], 0) + len(p["text"])
        if not score:
            return [], walled
        best = max(score, key=score.get)
        chosen = [p for p in paras if p["container"] == best]
    texts = [p["text"] for p in chosen if p["tag"] == "p" or len(p["text"]) <= MAX_FIELD]
    return texts, walled and (locked or any(p["paywall"] for p in chosen))


def _fit(paragraphs: list[str]) -> tuple[list[str], bool]:
    """截到 textitem 收得下的量（段數、總字數）；回傳 (段落, 有沒有截掉)。長段之後會再切，所以按切完最多幾段估。"""
    out, paras, chars = [], 0, 0
    for text in paragraphs:
        pieces = 1 + 2 * (len(text) // textitem.MAX_PARA_CHARS)
        if paras + pieces > textitem.MAX_PARAS or chars + len(text) + 2 > textitem.MAX_CHARS:
            return out, True
        out.append(text)
        paras, chars = paras + pieces, chars + len(text) + 2
    return out, False


_TITLE_SEP = re.compile(r"\s+[|\-–—]\s+|\s*｜\s*")  # i18n-ok 標題分隔符號


def split_title(title: str) -> tuple[str, str]:
    """<title> 常寫成「標題 - 媒體」：最後一段不長（≤ 30 字）、前面還夠長，就拆成 (標題, 媒體)。"""
    parts = _TITLE_SEP.split(title)
    if len(parts) >= 2 and 0 < len(parts[-1].strip()) <= 30 and not parts[-1].strip()[0].islower():  # 「- again」是標題的一部分
        main = title[: title.rfind(parts[-1])].rstrip(" |-–—｜")  # i18n-ok 標題分隔符號
        if len(main.strip()) >= 4:
            return main.strip(), parts[-1].strip()
    return title, ""


def extract(html: str, url: str) -> dict:
    """從 HTML 抽出標題、媒體、發布時間、正文段落。抽不到正文時 paragraphs 是空的。"""
    page = _Page()
    try:
        page.feed(html)
        page.close()
    except Exception as e:  # 很壞的 HTML：用已經收到的部分；只記例外類型
        log.warning("ingest html parse stopped early: %s", type(e).__name__)
    articles = _ld_articles(page.ld)
    ld = articles[0] if articles else {}
    m = page.meta
    plain_title, site = split_title(page.title)
    title = _text_of(m.get("og:title")) or _text_of(m.get("twitter:title")) or _text_of(ld.get("headline")) or plain_title
    publisher = _text_of(m.get("og:site_name")) or _text_of(ld.get("publisher")) or site or urlsplit(url).hostname or ""
    raw_times = [m.get(k, "") for k in _TIME_META] + [_text_of(ld.get("datePublished"))] + page.times
    raw = next((t for t in raw_times if t), "")
    published = next((parse_time(t) for t in raw_times if parse_time(t)), None)
    free = ld.get("isAccessibleForFree")
    locked = free is False or (isinstance(free, str) and free.strip().lower() == "false")
    paragraphs, in_paywall = _body(page.paras, locked)
    paragraphs, truncated = _fit(paragraphs)
    canonical = urljoin(url, page.canonical) if page.canonical else ""
    return {"title": title, "publisher": publisher, "published_at": published, "published_raw": "" if published else raw[:MAX_FIELD],
            "paragraphs": paragraphs, "preview_only": bool(paragraphs) and (locked or (in_paywall and len(paragraphs) <= PREVIEW_PARAS)),
            "canonical": canonical, "truncated": truncated}


_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([A-Za-z0-9_\-]{1,40})""", re.I)


def decode(got) -> str:
    """HTTP 標頭有寫編碼就照標頭；沒寫就看頁面前 4 KB 的 <meta charset>（Big5 的舊新聞網站常這樣），都沒有就當 UTF-8。"""
    if re.search(r"charset=", (got.headers or {}).get("content-type", ""), re.I):
        return got.text()
    m = _META_CHARSET.search(got.body[:4096])
    charset = m.group(1).decode("ascii") if m else "utf-8"
    try:
        return got.body.decode(charset, "replace")
    except LookupError:
        return got.body.decode("utf-8", "replace")


def is_chinese(paragraphs: list[str]) -> bool:
    sample = "".join(paragraphs)[:20_000]
    letters = len(_LETTER.findall(sample))
    cjk = len(_CJK.findall(sample))
    kana = len(_KANA.findall(sample))
    return letters > 0 and cjk / letters >= CJK_RATIO and kana / (cjk + kana) < KANA_RATIO


def _hant_converter(paragraphs: list[str]):
    """譯文語言是台灣繁體、原文是簡體時，回傳轉成台灣繁體的函式（traditional.to_taiwan）；
    原文已經是繁體、別的譯文語言、或沒裝 OpenCC 回 None（譯文欄照舊放原文）。"""
    if langs.valid(config.load().get("target")) != "zh-TW":
        return None
    from . import traditional
    from .i18n import _tw_converter
    if not _tw_converter() or not traditional.looks_simplified(paragraphs):
        return None
    return traditional.to_taiwan


def _same_language(paragraphs: list[str]) -> bool:
    """原文是中文、而且設定的譯文語言也是中文，才不送翻譯。"""
    return langs.valid(config.load().get("target")).startswith("zh") and is_chinese(paragraphs)


# ---------- 建立資料 ----------
def _index(app):
    path = Path(getattr(app, "ledger_path", None) or ledger.default_path())
    return ledger.shared(path, create=True)


def _busy(ws) -> bool:
    return (ws.load("job") or {}).get("state") in ("queued", "running")


def _summary(ws, status: str, translate: bool) -> dict:
    paper = ws.load("paper") or {}
    meta = paper.get("meta") or {}
    blocks = paper.get("blocks") or []
    return {"status": status, "id": ws.id, "title": meta.get("title_en", ""), "publisher": meta.get("publisher", ""),
            "published_at": meta.get("published_at") or "", "time_source": meta.get("time_source", "unknown"),
            "published_raw": meta.get("published_raw", ""), "fetched_at": meta.get("fetched_at", ""),
            "url": meta.get("source_url", ""), "paragraphs": len(blocks), "chars": sum(len(b.get("en") or "") for b in blocks),
            "preview_only": bool(meta.get("preview_only")), "same_language": bool(meta.get("same_language")),
            "hant_converted": bool(meta.get("hant_converted")),
            "added": (ws.load("item") or {}).get("added", ""), "translate": translate}


_NEW_META = {"publisher": "", "published_at": "", "time_source": "unknown", "published_raw": ""}


def _time_fields(published: str | None, source: str) -> dict | None:
    """一組發布時間欄位（published_at 是 parse_time 的結果）；沒有時間就是 None。"""
    return {"published_at": published, "time_source": source, "published_raw": ""} if published else None


def _store(app, text: str, *, title: str, url: str | None, meta: dict, time: dict | None) -> dict:
    """建立或更新。meta 只放這次知道的欄位：更新時沒給的欄位沿用舊值（textitem.create 的 keep）。

    發布時間（time）記了就不改：已經有合格的時間、又給了不同的，就拒絕；原本不明（或是壞掉的舊值）就補上。
    這些判斷都在 textitem.create 的鎖裡面做，Story 的時間一律照存好的 meta 走，兩邊不會各說各話。"""
    def prepare(ws, old: dict):
        if _busy(ws):
            raise _error("busy")
        if not time:
            return None
        known = parse_time(old.get("published_at") or "")
        if known is None:
            return time
        if datetime.fromisoformat(known) != datetime.fromisoformat(time["published_at"]):
            raise IngestError("bad_input", tr("這篇已經記了發布時間，不能改成別的時間。"))
        return None

    try:
        ws, status = textitem.create(app.lib, text, title=title, url=url, meta=meta,
                                     defaults={**_NEW_META, **(time or {})}, prepare=prepare)
    except textitem.TextError as e:
        raise IngestError("bad_input", str(e)) from None
    paras = [b.get("en") or "" for b in (ws.load("paper") or {}).get("blocks", [])]
    same = _same_language(paras)
    if same and status != "unchanged":
        hant = _hant_converter(paras)

        def fill(paper):  # 原文已經是中文：譯文欄放原文，不送翻譯
            meta = paper.setdefault("meta", {})
            for b in paper.get("blocks", []):
                if not b.get("zh"):
                    # 譯文語言是台灣繁體：用 OpenCC 轉成繁體放譯文欄（不叫 AI）；原文欄照舊，切回原文看得到（#98）
                    b["zh"] = hant(b.get("en", "")) if hant else b.get("en", "")
            if hant:
                title = meta.get("title_en") or ""
                if title and (not meta.get("title_zh") or meta.get("title_zh_auto")):
                    meta["title_zh"], meta["title_zh_auto"] = hant(title), True
                # 已經是繁體了：閱讀頁打開時的 traditional.migrate 不用再轉一次
                meta.update(target="zh-TW", paperread_traditional_v=1, hant_converted="opencc")
            paper.setdefault("translation", {})["en_pages"] = []
            meta["same_language"] = True
        ws.update("paper", fill)
    stored = parse_time(((ws.load("paper") or {}).get("meta") or {}).get("published_at") or "")
    index = _index(app)
    index.ensure_story(ws.id, stored)
    if stored:
        index.fill_story_time(ws.id, stored)  # 原本不明、這次補上的
    if status in ("created", "updated"):  # 新的或換了內容：排進 AI 分類（ticket 14）
        from . import triage
        content = ((ws.load("paper") or {}).get("meta") or {}).get("content_sha256")
        if content:
            triage.enqueue(app, ws.id, content)
    translate = False
    if status in ("created", "updated") and not same and config.load().get("auto_translate", True):
        try:
            app.jobs.enqueue(ws, translate_after=True, scope="all", background=True)  # 匯入後自動翻：受額度保護
            translate = True
        except ValueError:
            translate = False  # 剛好有任務在跑：匯入照樣成功，之後再翻
    return _summary(ws, status, translate)


def from_url(app, url: str) -> dict:
    """抓網址並匯入。已經匯入過的不再抓（status = exists）。
    app.fetch_options（測試用）會原樣交給 fetch.fetch：transport、budget、sleep…；平常沒有，用真的網路和共用上限。"""
    clean = normalize(url)
    existing = app.lib.ws(textitem.item_id("", clean))
    if existing is not None:
        return _summary(existing, "exists", False)
    try:
        got = fetch.fetch(clean, source=SOURCE, accept=ACCEPT, **dict(getattr(app, "fetch_options", None) or {}))
    except fetch.FetchError as e:
        log.warning("ingest %s", e.log_line())
        raise IngestError(e.kind, e.message) from None
    info = extract(decode(got), got.url or clean)
    if not info["paragraphs"]:
        raise _error("no_text")
    meta = {"publisher": info["publisher"], "preview_only": info["preview_only"],
            "canonical_url": info["canonical"][:textitem.MAX_URL], "truncated": info["truncated"]}
    if info["published_raw"]:
        meta["published_raw"] = info["published_raw"]
    return _store(app, "\n\n".join(info["paragraphs"]), title=info["title"], url=clean, meta=meta,
                  time=_time_fields(info["published_at"], "metadata"))


def from_text(app, body: dict) -> dict:
    """手動貼全文：標題、媒體、發布時間（使用者填的；空著就是時間不明）、原始連結都可以不填。"""
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _error("bad_input")
    fields = {k: body.get(k) if isinstance(body.get(k), str) else "" for k in ("title", "publisher", "published_at", "url")}
    published = parse_time(fields["published_at"]) if fields["published_at"] else None
    if fields["published_at"] and not published:
        raise IngestError("bad_input", tr("發布時間要寫成 2026-11-10T13:30+08:00 這種格式（要有時區）。"))
    url = normalize(fields["url"]) if fields["url"].strip() else None
    meta = {"preview_only": False, "truncated": False, "manual": True}  # 沒填的欄位不放：補貼全文時沿用原本抓到的
    if fields["publisher"].strip():
        meta["publisher"] = fields["publisher"].strip()[:MAX_FIELD]
    return _store(app, text, title=fields["title"].strip()[:MAX_FIELD], url=url, meta=meta,
                  time=_time_fields(published, "user"))


def handle(app, body) -> dict:
    """POST /api/ingest：{"url": …} 抓網址；{"text": …, "title", "publisher", "published_at", "url"} 手動貼全文。"""
    if not isinstance(body, dict):
        raise _error("bad_input")
    if isinstance(body.get("text"), str) and body["text"].strip():
        return from_text(app, body)
    if isinstance(body.get("url"), str) and body["url"].strip():
        return from_url(app, body["url"])
    raise _error("bad_input")
