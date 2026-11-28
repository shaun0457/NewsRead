"""沒有 PDF 的資料（純文字、網頁正文）：切段、穩定的段落 ID、版本。

- 一段就是一「頁」：塊的 page = 段落序號（從 1 開始），meta.pages 每段一筆、沒有原頁圖。
  既有的分批翻譯、續傳（translation.done_pages / en_pages）不用改，就是以段落為單位做。
- 原文放在塊的 en 欄位（沿用 PaperRead 的欄位名，意思是「原文」，不一定是英文）。
- 段落 ID 由內容算出來：同樣的內容重新匯入，ID 不變，劃線和筆記還掛得住。
- ID：網頁用正規化之後的網址（w 開頭），純文字用內容雜湊（t 開頭）；PDF 的 ID 是 12 位十六進位，不會撞。
- 同一個網址的內容變了：舊的 paper.json 存進 versions/，新版本沿用沒變的段落和它們的譯文。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .i18n import tr
from .store import SCHEMA, Workspace, dir_lock, empty_discussion, empty_reader, now_iso, read_json, write_json_atomic

KIND = "text"
MAX_CHARS = 400_000        # 一則資料的原文上限（字元）
MAX_PARAS = 2_000          # 段落數上限
MAX_PARA_CHARS = 6_000     # 單段太長就在句子結尾再切開，一批翻譯才不會太大
MAX_TITLE = 300
MAX_URL = 2_000
MAX_VERSIONS = 50          # versions/ 最多留幾份舊版；滿了刪最舊的，但第一版永遠留著
PARAS_PER_BATCH = 12       # 翻譯一批幾段

_TRACKING = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_cid|mc_eid|ref_src)$", re.I)
# 中文句尾標點後面直接切；英文的 . ! ? ; 後面要有空白才切（3.5%、U.S.、example.com 不切）
_SENTENCE_END = re.compile(r"(?<=[。！？；])\s*|(?<=[.!?;])\s+")  # i18n-ok 句尾標點
_CJK = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯]")  # i18n-ok 中日文字元範圍


class TextError(ValueError):
    """使用者給的內容不能建成一則資料（空的、太長、網址不對）。訊息是固定的說明。"""


def is_text(meta: dict | None) -> bool:
    return (meta or {}).get("kind") == KIND


def normalize_url(url: str) -> str:
    """同一篇文章的不同寫法算成同一個網址：小寫主機、去掉 #、預設埠、追蹤參數，查詢參數排序。"""
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_URL:
        raise TextError(tr("網址不對。"))
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise TextError(tr("網址不對。"))
    try:
        port = parts.port  # 埠號不是數字或超出範圍時 urllib 丟 ValueError，訊息裡有使用者的輸入
    except ValueError:
        raise TextError(tr("網址不對。")) from None
    host = parts.hostname.lower()
    if ":" in host:  # IPv6 位址要放回方括號裡，不然接上埠號之後解析不回來
        host = f"[{host}]"
    port = port if port and (scheme, port) not in (("http", 80), ("https", 443)) else None
    netloc = f"{host}:{port}" if port else host
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)))
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise TextError(tr("內容是空的。"))
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _join(lines: list[str]) -> str:
    """同一段裡的換行：中文和中文之間直接接起來，其他情況補一個空白。"""
    out = ""
    for line in (s.strip() for s in lines):
        if not line:
            continue
        if out and not (_CJK.match(out[-1]) and _CJK.match(line[0])):
            out += " "
        out += line
    return out


def _split_long(para: str) -> list[str]:
    if len(para) <= MAX_PARA_CHARS:
        return [para]
    out, cur = [], ""
    for sentence in (s for s in _SENTENCE_END.split(para) if s):
        while len(sentence) > MAX_PARA_CHARS:  # 一句就超過上限：硬切
            if cur:
                out.append(cur)
                cur = ""
            out.append(sentence[:MAX_PARA_CHARS])
            sentence = sentence[MAX_PARA_CHARS:]
        if cur and len(cur) + len(sentence) + 1 > MAX_PARA_CHARS:
            out.append(cur)
            cur = ""
        cur = _join([cur, sentence]) if cur else sentence
    if cur:
        out.append(cur)
    return out


def split_paragraphs(text: str) -> list[str]:
    """空行分段；太長的段在句子結尾切開。超過上限或沒有內容時丟 TextError。"""
    text = normalize_text(text)
    if not text:
        raise TextError(tr("內容是空的。"))
    if len(text) > MAX_CHARS:
        raise TextError(tr("內容太長了（上限 {n} 字）。", n=MAX_CHARS))
    paras = []
    for chunk in re.split(r"\n\s*\n", text):
        para = _join(chunk.split("\n"))
        if para:
            paras.extend(_split_long(para))
    if len(paras) > MAX_PARAS:
        raise TextError(tr("段落太多了（上限 {n} 段）。", n=MAX_PARAS))
    return paras


def _fold(para: str) -> str:
    return re.sub(r"\s+", " ", para).strip()


def para_ids(paras: list[str]) -> list[str]:
    """段落 ID = 內容雜湊；同樣的段落出現兩次，第二次加 -2，依出現順序。"""
    seen: dict[str, int] = {}
    out = []
    for para in paras:
        base = "p" + hashlib.sha256(_fold(para).encode("utf-8")).hexdigest()[:10]
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return out


def item_id(text: str, url: str | None = None) -> str:
    if url:
        return "w" + hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:11]
    return "t" + hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:11]


def content_hash(paras: list[str]) -> str:
    return hashlib.sha256("\n\n".join(paras).encode("utf-8")).hexdigest()


def _blocks(paras: list[str], old: dict[str, dict] | None = None) -> list[dict]:
    """每段一個 para 塊；old 裡同一個 ID 的譯文和句子對齊沿用（同 ID = 同內容）。"""
    blocks = []
    for page, (bid, para) in enumerate(zip(para_ids(paras), paras), start=1):
        block = {"id": bid, "type": "para", "page": page, "en": para}
        prev = (old or {}).get(bid) or {}
        for field in ("zh", "sents"):
            if field in prev:
                block[field] = prev[field]
        blocks.append(block)
    return blocks


def _translation(blocks: list[dict], previous: dict | None = None) -> dict:
    """每段都已經「整理好」（done）；還沒有譯文的段留在 en_pages，翻譯時用補譯文的流程。"""
    translation = dict(previous or {})
    pages = [b["page"] for b in blocks]
    translation["done_pages"] = pages
    translation["en_pages"] = [b["page"] for b in blocks if not b.get("zh")]
    translation["scope"] = translation.get("scope") or "未开始"  # i18n-ok 存進 paper.json，沿用 PaperRead 的值
    translation.pop("page_revisions", None)  # 段落序號換過，舊的頁修訂次數對不上
    translation["gaps_checked"] = 1  # 每段都有塊，不用做 PDF 漏頁檢查（page_check.repair_done）
    return translation


def _meta(paras: list[str], title: str, url: str | None, extra: dict | None) -> dict:
    meta = {k: v for k, v in (extra or {}).items() if k not in ("kind", "pages", "page_count", "content_sha256", "pdf", "source_sha256")}
    meta.update(kind=KIND, title_en=title, title_zh=meta.get("title_zh", ""), authors=meta.get("authors", ""),
                source=url or title, pages=[{"n": n} for n in range(1, len(paras) + 1)], page_count=len(paras),
                content_sha256=content_hash(paras))
    if url:
        meta["source_url"] = url
        meta["url"] = url
    return meta


def _title(title, paras: list[str]) -> str:
    title = _fold(title) if isinstance(title, str) else ""
    return (title or paras[0])[:MAX_TITLE]


def _saved(folder) -> list:
    """versions/ 裡的舊版 [(編號, 路徑)]，由舊到新（照數字排，不照字典序）；檔名不合格式的跳過。"""
    out = []
    for path in folder.glob("paper-*.json"):
        number = path.stem.split("-", 1)[1]
        if number.isascii() and number.isdigit():
            out.append((int(number), path))
    return sorted(out, key=lambda pair: pair[0])


def _save_version(ws: Workspace, paper: dict) -> None:
    folder = ws.root / "versions"
    folder.mkdir(exist_ok=True)
    saved = _saved(folder)
    n = saved[-1][0] + 1 if saved else 1
    while len(saved) >= MAX_VERSIONS:  # 第一版（最早發布的內容）永遠留著，刪第二舊的
        _, victim = saved.pop(1 if len(saved) > 1 else 0)
        victim.unlink()
    write_json_atomic(folder / f"paper-{n:04d}.json", paper)


def create(library, text: str, *, title: str = "", url: str | None = None, meta: dict | None = None,
           defaults: dict | None = None, prepare=None) -> tuple[Workspace, str]:
    """建立或更新一則沒有 PDF 的資料。回傳 (目錄, 狀態)：created / unchanged / updated。

    下面兩個都在寫入鎖裡面處理，和其他寫入（排翻譯任務、同時匯入同一篇）不會互相插隊：
    - defaults：只有新建時用的 meta 預設值（meta 有給的蓋過它）。
    - prepare(ws, old_meta)：已經有這則資料時、寫任何東西之前呼叫。丟例外就不寫（例如正在翻譯）；
      回傳 dict 就併進 meta，內容沒變（unchanged）也照樣寫進去（例如補上原本不明的發布時間）。

    url 有給時用網址當 ID：同一個網址再匯入、內容變了，就存一個新版本（舊版留在 versions/）。
    沒有網址時用內容雜湊當 ID：內容不一樣就是另一則資料。"""
    paras = split_paragraphs(text)
    clean_url = normalize_url(url) if url else None
    pid = item_id(text, clean_url)
    ws = Workspace(library.root / pid)
    ws.root.mkdir(parents=True, exist_ok=True)
    with dir_lock(ws.root):
        if not ws.paper_path.exists():
            blocks = _blocks(paras)
            first = {**(defaults or {}), **(meta or {})}
            write_json_atomic(ws.paper_path, {
                "schema": SCHEMA, "meta": {**_meta(paras, _title(title, paras), clean_url, first), "version": 1, "fetched_at": now_iso()},
                "translation": _translation(blocks), "glossary": [], "references": [], "blocks": blocks,
            })
            write_json_atomic(ws.discussion_path, empty_discussion())
            write_json_atomic(ws.reader_path, empty_reader())
            write_json_atomic(ws.item_path, {"added": now_iso(), "tags": [], "status": "unread", "starred": False})
            return ws, "created"
        paper = read_json(ws.paper_path, {}) or {}
        old_meta = paper.get("meta") or {}
        extra = (prepare(ws, old_meta) if prepare is not None else None) or {}
        if old_meta.get("content_sha256") == content_hash(paras):
            if any(old_meta.get(k) != v for k, v in extra.items()):
                paper["meta"] = {**old_meta, **extra}
                write_json_atomic(ws.paper_path, paper)
            return ws, "unchanged"
        _save_version(ws, paper)
        blocks = _blocks(paras, {b.get("id"): b for b in paper.get("blocks") or [] if isinstance(b, dict)})
        keep = {k: v for k, v in old_meta.items() if k in ("title_zh", "title_zh_auto", "short_zh", "target", "date", "authors", "published_at", "time_source",
                                                       "publisher", "published_raw", "canonical_url")}
        new_meta = _meta(paras, _title(title or old_meta.get("title_en", ""), paras), clean_url, {**keep, **(meta or {}), **extra})
        new_meta.update(version=int(old_meta.get("version") or 1) + 1, fetched_at=now_iso())
        paper.update(meta=new_meta, blocks=blocks, translation=_translation(blocks, paper.get("translation")))
        write_json_atomic(ws.paper_path, paper)
        return ws, "updated"


def versions(ws: Workspace) -> list[dict]:
    """舊版本清單（新到舊）：版本號、抓取時間、段落數。"""
    out = []
    for _, path in reversed(_saved(ws.root / "versions")):
        meta = (read_json(path, {}) or {}).get("meta") or {}
        out.append({"file": path.name, "version": meta.get("version", 1), "fetched_at": meta.get("fetched_at", ""),
                    "paragraphs": meta.get("page_count", 0)})
    return out
