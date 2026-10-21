"""读 Zotero 的数据库：先复制一份再读，不碰 Zotero 自己的文件，Zotero 开着也能读。

读出来的是一条条“条目”（论文、书、报告……，或者没有父条目、单独放着的 PDF），每条带：
元数据、所在分类的路径、手动加的标签、要导入的 PDF 文件。回收站里的不算。
分类路径用“/”连起来（和 EasyRead 的分类层级一样）；群组文献库的分类放在群组名下面。"""
from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr
from . import locate

SKIP_TYPES = ("attachment", "note", "annotation")
VENUE_FIELDS = ("publicationTitle", "proceedingsTitle", "conferenceName", "bookTitle", "repository", "university", "institution", "publisher", "websiteTitle")
ARXIV = re.compile(r"(?:arxiv[:/ ]\s*|abs/|pdf/)(\d{4}\.\d{4,5})(v\d+)?", re.I)


@dataclass
class Entry:
    key: str
    meta: dict
    added: str = ""                                          # Zotero 里加进来的时间（ISO）
    cats: list[str] = field(default_factory=list)            # 分类路径
    tags: list[str] = field(default_factory=list)            # 手动标签
    pdf: Path | None = None
    missing: str = ""                                        # 没有 PDF 的原因：“无 PDF 附件”或找不到的文件路径


@dataclass
class Snapshot:
    entries: list[Entry]
    collections: list[str]                                   # 全部分类路径（含空分类），按 Zotero 里的树序
    from_backup: bool = False                                # 数据库被占用，读的是 Zotero 的自动备份


def _copy(data_dir: Path, tmp: Path) -> tuple[Path, bool]:
    """复制数据库到临时目录。复制失败或副本打不开（Zotero 正在写）就退到 zotero.sqlite.bak。"""
    for name, backup in ((locate.DB, False), (locate.DB + ".bak", True)):
        src = data_dir / name
        if not src.is_file():
            continue
        dst = tmp / name
        try:
            shutil.copyfile(src, dst)
            con = sqlite3.connect(f"file:{dst.as_posix()}?mode=ro", uri=True)
            con.execute("SELECT count(*) FROM items").fetchone()
            con.close()
            return dst, backup
        except (OSError, sqlite3.Error):
            continue
    raise ValueError(tr("读不了 Zotero 的数据库。请先关掉 Zotero 再试。"))


def _date(raw: str) -> tuple[str, str]:
    """Zotero 存成“2021-06-00 June 2021”：前半是规范日期（不知道的部分是 00）。返回 (日期, 年份)。"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw or "")
    if not m:
        y = re.search(r"(1[89]|20)\d{2}", raw or "")
        return (raw or "").strip(), y.group(0) if y else ""
    y, mo, d = m.groups()
    date = y if mo == "00" else f"{y}-{mo}" if d == "00" else f"{y}-{mo}-{d}"
    return ("" if y == "0000" else date), ("" if y == "0000" else y)


def _author(first: str, last: str, mode: int) -> str:
    return (last or "").strip() if mode == 1 or not first else f"{first.strip()} {last.strip()}".strip()


def _meta(fields: dict, authors: list[str], type_name: str) -> dict:
    date, year = _date(fields.get("date", ""))
    m = ARXIV.search(" ".join(fields.get(k, "") for k in ("archiveID", "url", "extra", "number")))
    meta = {
        "title_en": fields.get("title", "").strip(),
        "authors": ", ".join(a for a in authors if a),
        "date": date, "year": year,
        "venue": next((fields[k].strip() for k in VENUE_FIELDS if fields.get(k, "").strip()), ""),
        "doi": re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", fields.get("DOI", "").strip(), flags=re.I),
        "url": fields.get("url", "").strip(),
        "abstract_en": fields.get("abstractNote", "").strip(),
        "arxiv": f"arXiv:{m.group(1)}" if m else "",
        "zotero_type": type_name,
    }
    return {k: v for k, v in meta.items() if v}


def _iso(stamp: str) -> str:
    """Zotero 的 dateAdded 是 UTC 的“2023-01-02 03:04:05”。"""
    return stamp.replace(" ", "T") + "+00:00" if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", stamp or "") else ""


def _pdf_path(data_dir: Path, base: str, att_key: str, link_mode: int, path: str) -> Path | None:
    if not path:
        return None
    if path.startswith("storage:"):  # 导入到 Zotero 里的文件
        return data_dir / "storage" / att_key / path[len("storage:"):]
    if path.startswith("attachments:"):  # 链接的文件，相对“链接附件根目录”
        return Path(base) / path[len("attachments:"):] if base else None
    return Path(path) if link_mode == 2 else None


def read(data_dir: str | Path, base: str = "") -> Snapshot:
    data_dir = locate.resolve(str(data_dir))
    with tempfile.TemporaryDirectory(prefix="easyread-zotero-") as tmp:
        db, backup = _copy(data_dir, Path(tmp))
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            return _read(con, data_dir, base, backup)
        finally:
            con.close()


def _has(con, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _read(con: sqlite3.Connection, data_dir: Path, base: str, backup: bool) -> Snapshot:
    q = lambda sql, *a: con.execute(sql, a).fetchall()  # noqa: E731
    deleted = {r[0] for r in q("SELECT itemID FROM deletedItems")} if _has(con, "deletedItems") else set()
    dead_cols = {r[0] for r in q("SELECT collectionID FROM deletedCollections")} if _has(con, "deletedCollections") else set()
    fields_table = "fieldsCombined" if _has(con, "fieldsCombined") else "fields"
    groups = {lib: name for lib, name in q("SELECT libraryID, name FROM groups")} if _has(con, "groups") else {}

    # 分类：拼出完整路径；群组库的放在群组名下面。名字里的“/”换成全角，免得被当成层级
    cols = {cid: (name, parent, lib) for cid, name, parent, lib in q("SELECT collectionID, collectionName, parentCollectionID, libraryID FROM collections")}
    paths: dict[int, str] = {}

    def col_path(cid: int) -> str:
        if cid not in paths:
            name, parent, lib = cols[cid]
            name = (name or "").strip().replace("/", "／") or "?"
            head = col_path(parent) if parent in cols else groups.get(lib, "").replace("/", "／")
            paths[cid] = f"{head}/{name}" if head else name
        return paths[cid]

    def alive(cid: int) -> bool:
        while cid in cols:
            if cid in dead_cols:
                return False
            cid = cols[cid][1]
        return True
    live = sorted((c for c in cols if alive(c)), key=lambda c: col_path(c).lower())
    in_col: dict[int, list[str]] = {}
    for cid, iid in q("SELECT collectionID, itemID FROM collectionItems"):
        if cid in live:
            in_col.setdefault(iid, []).append(col_path(cid))

    tags: dict[int, list[str]] = {}
    for iid, name, kind in q("SELECT it.itemID, t.name, it.type FROM itemTags it JOIN tags t USING(tagID)"):
        if kind == 0 and (name or "").strip():  # 只要手动标签；自动标签（type 1）多半是数据库抓来的关键词
            tags.setdefault(iid, []).append(name.strip())

    values: dict[int, dict] = {}
    for iid, fname, value in q(f"SELECT d.itemID, f.fieldName, v.value FROM itemData d JOIN {fields_table} f USING(fieldID) JOIN itemDataValues v USING(valueID)"):
        values.setdefault(iid, {})[fname] = str(value)
    creators: dict[int, list[tuple[str, str]]] = {}
    for iid, first, last, mode, ctype in q("SELECT ic.itemID, c.firstName, c.lastName, c.fieldMode, ct.creatorType FROM itemCreators ic "
                                           "JOIN creators c USING(creatorID) JOIN creatorTypes ct USING(creatorTypeID) ORDER BY ic.itemID, ic.orderIndex"):
        creators.setdefault(iid, []).append((ctype, _author(first, last, mode)))

    # 每个条目的第一个 PDF（按加入时间）；没有父条目的 PDF 自己算一条
    pdfs: dict[int, tuple] = {}
    lone = []
    for iid, parent, mode, path, key, added in q("SELECT ia.itemID, ia.parentItemID, ia.linkMode, ia.path, i.key, i.dateAdded FROM itemAttachments ia "
                                                 "JOIN items i USING(itemID) WHERE ia.contentType = 'application/pdf' ORDER BY i.dateAdded"):
        if iid in deleted:
            continue
        att = (_pdf_path(data_dir, base, key, mode, path or ""), path or "")
        if parent is None:
            lone.append((iid, key, added, att))
        elif parent not in pdfs:
            pdfs[parent] = att

    def entry(iid: int, key: str, added: str, type_name: str, att) -> Entry:
        ppl = creators.get(iid, [])
        authors = [n for t, n in ppl if t == "author"] or [n for _, n in ppl]
        e = Entry(key=key, meta=_meta(values.get(iid, {}), authors, type_name), added=_iso(added),
                  cats=sorted(set(in_col.get(iid, []))), tags=sorted(set(tags.get(iid, []))))
        if not att:
            e.missing = tr("没有 PDF 附件")
        elif att[0] and att[0].is_file():
            e.pdf = att[0]
        else:
            e.missing = str(att[0] or att[1])
        return e

    entries = []
    for iid, key, added, type_name in q("SELECT i.itemID, i.key, i.dateAdded, t.typeName FROM items i JOIN itemTypes t USING(itemTypeID) ORDER BY i.dateAdded"):
        if iid in deleted or type_name in SKIP_TYPES:
            continue
        entries.append(entry(iid, key, added, type_name, pdfs.get(iid)))
    for iid, key, added, att in lone:
        e = entry(iid, key, added, "attachment", att)
        if e.pdf and not e.meta.get("title_en"):
            e.meta["title_en"] = e.pdf.stem
        entries.append(e)
    return Snapshot(entries=entries, collections=[col_path(c) for c in live], from_backup=backup)
