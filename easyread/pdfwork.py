"""PDF 相关的机械活：渲染原页、抽文字和字符坐标、裁图、给译文段落定位原页区域。

这里不做任何翻译，也不调用模型。
"""
from __future__ import annotations

import json
import re
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from .store import write_json_atomic


@contextmanager
def open_pdf(pdf: Path):
    """用完一定要关：pypdfium2 不会在变量释放时关文件，Windows 上 source.pdf 会一直被占着，论文就移不进回收站。"""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        yield doc
    finally:
        doc.close()


def render_pages(pdf: Path, out_dir: Path, scale: float = 2.4, quality: int = 84) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    with open_pdf(pdf) as doc:
        for i in range(len(doc)):
            page = doc[i]
            w, h = page.get_size()
            img = page.render(scale=scale).to_pil().convert("RGB")
            name = f"page-{i + 1:03d}.webp"
            img.save(out_dir / name, "WEBP", quality=quality, method=5)
            pages.append({"n": i + 1, "w": round(w, 2), "h": round(h, 2), "img": f"pages/{name}"})
    return pages


def extract_text(pdf: Path, out_dir: Path) -> int:
    """每页一份 .txt（给 agent 读）和 .chars.json（给定位用，坐标按页宽高归一化）。"""
    import pdfplumber

    out_dir.mkdir(parents=True, exist_ok=True)
    with open_pdf(pdf) as doc:
        for i in range(len(doc)):
            tp = doc[i].get_textpage()
            (out_dir / f"page-{i + 1:03d}.txt").write_text(tp.get_text_range(), encoding="utf-8")
    with pdfplumber.open(str(pdf)) as plumb:
        for i, page in enumerate(plumb.pages):
            W, H = float(page.width), float(page.height)
            chars = [
                [c["text"], round(c["x0"] / W, 4), round(c["top"] / H, 4), round(c["x1"] / W, 4), round(c["bottom"] / H, 4)]
                for c in page.chars
            ]
            (out_dir / f"page-{i + 1:03d}.chars.json").write_text(json.dumps(chars, ensure_ascii=False), encoding="utf-8")
        return len(plumb.pages)


def crop(root: Path, page: int, box: list[float], out_name: str, scale: float = 3.0) -> str:
    """box 是按页宽高归一化的 [x0, y0, x1, y1]；输出到 figures/，返回相对路径。"""
    with open_pdf(root / "source.pdf") as doc:
        img = doc[page - 1].render(scale=scale).to_pil().convert("RGB")
    W, H = img.size
    x0, y0, x1, y1 = box
    part = img.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
    (root / "figures").mkdir(exist_ok=True)
    rel = f"figures/{out_name}.webp"
    part.save(root / rel, "WEBP", quality=90)
    return rel


# ---------- 定位：译文段落 -> 原页区域 ----------

_MATH = re.compile(r"\$[^$]*\$")
_ALNUM = re.compile(r"[a-z0-9]")
LOCATE_VERSION = "2"  # 定位规则改了就加一，旧论文打开时会重算 layout.json


def _norm(s: str) -> str:
    return "".join(_ALNUM.findall(unicodedata.normalize("NFKC", s).lower()))


def _page_stream(extract_dir: Path, n: int):
    path = extract_dir / f"page-{n:03d}.chars.json"
    if not path.exists():
        return None
    chars = json.loads(path.read_text(encoding="utf-8"))
    text, idx = [], []
    for k, c in enumerate(chars):
        for t in _norm(c[0]):  # 连字 ﬁ/ﬂ 会展开成两个字母，指向同一个字符框
            text.append(t)
            idx.append(k)
    return "".join(text), idx, chars


def _anchors(en: str) -> tuple[str, str]:
    plain_parts = [p for p in _MATH.split(en) if _norm(p)]
    if not plain_parts:
        return "", ""
    head = _norm(plain_parts[0])[:28]
    tail = _norm(plain_parts[-1])[-28:]
    return head, tail


def _box(chars, idx, a: int, b: int):
    sel = [chars[idx[k]] for k in range(a, min(b, len(idx) - 1) + 1)]
    return [min(c[1] for c in sel), min(c[2] for c in sel), max(c[3] for c in sel), max(c[4] for c in sel)]


def block_english(block: dict) -> str:
    if block.get("type") == "list":
        return " ".join(it.get("en", "") for it in block.get("items", []))
    if block.get("type") in ("table", "figure"):
        return block.get("caption_en", "")
    return block.get("en", "")


def locate(root: Path) -> dict:
    paper = json.loads((root / "paper.json").read_text(encoding="utf-8"))
    extract_dir = root / "extract"
    streams: dict[int, tuple] = {}
    layout: dict[str, dict] = {}
    cursor: dict[int, int] = {}
    for block in paper.get("blocks", []):
        bid, page = block.get("id"), block.get("page")
        if not bid or not page:
            continue
        if block.get("box"):
            layout[bid] = {"page": page, "box": block["box"], "src": "manual"}
            continue
        head, tail = _anchors(block_english(block))
        if not head:
            continue
        heads = [head]
        if block.get("type") == "heading" and block.get("num"):  # 带上编号，免得撞上图里同名的标签
            heads.insert(0, _anchors(f"{block['num']} {block.get('en', '')}")[0])
        for pn in (page, page + 1):
            if pn not in streams:
                streams[pn] = _page_stream(extract_dir, pn)
            st = streams[pn]
            if not st:
                continue
            text, idx, chars = st
            a = -1
            for h in heads:
                a = text.find(h, cursor.get(pn, 0) if pn == page else 0)
                if a < 0:
                    a = text.find(h)
                if a >= 0:
                    break
            if a < 0:
                continue
            b = text.find(tail, a) if tail else -1
            end = b + len(tail) - 1 if b >= 0 else min(a + len(_norm(block_english(block))), len(idx) - 1)
            layout[bid] = {"page": pn, "box": _box(chars, idx, a, end), "src": "text" if b >= 0 else "head"}
            cursor[pn] = end
            break
    _extend_captioned(paper.get("blocks", []), layout)
    _clamp_overlaps(layout)
    _fill_gaps(paper.get("blocks", []), layout)
    write_json_atomic(root / "layout.json", layout)
    (extract_dir / "locate.version").write_text(LOCATE_VERSION, encoding="utf-8")
    return layout


def refresh_layout(root: Path) -> None:
    """定位规则改过后，旧论文的 layout.json 是旧规则算的；打开时按新规则重算一次。"""
    marker = root / "extract" / "locate.version"
    if not (root / "layout.json").exists() or not (root / "paper.json").exists():
        return
    if not any((root / "extract").glob("page-*.chars.json")):  # 没有逐字坐标就算不出来，别把原来的框清空
        return
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == LOCATE_VERSION:
        return
    locate(root)


def _overlap_x(a: list, x0: float, x1: float) -> bool:
    return max(a[0], x0) < min(a[2], x1) - 0.01


def _column(locs: list[dict], box: list) -> tuple[float, float] | None:
    """双栏页上 box 所在那一栏的左右边界；单栏页或 box 本身横跨两栏时返回 None。"""
    left = [l["box"] for l in locs if l["box"][2] <= 0.55]
    right = [l["box"] for l in locs if l["box"][0] >= 0.45]
    if len(left) < 2 or len(right) < 2 or box[2] - box[0] > 0.5:
        return None
    col = right if (box[0] + box[2]) / 2 >= 0.5 else left
    return min(b[0] for b in col), max(b[2] for b in col)


def _page_locs(layout: dict, page: int) -> list[dict]:
    return [l for l in layout.values() if l["page"] == page]


def _extend_captioned(blocks: list[dict], layout: dict):
    """表格/图只匹配到了题注，把框往上撑到同一栏里上方最近一块的下沿（题注在上方的往下撑）。"""
    for block in blocks:
        loc = layout.get(block.get("id"))
        if block.get("type") not in ("table", "figure") or not loc or loc.get("src") == "manual":
            continue
        x0, y0, x1, y1 = loc["box"]
        others = [l for l in _page_locs(layout, loc["page"]) if l is not loc]
        col = _column(others, loc["box"])
        if col:
            x0, x1 = col
        elif x1 - x0 < 0.45 and abs((x0 + x1) / 2 - 0.5) > 0.1:  # 窄题注偏在一侧：正文绕排的小表/小图
            x0, x1 = max(0.05, x0 - 0.02), min(0.95, x1 + 0.02)
        else:
            x0, x1 = min(x0, 0.15), max(x1, 0.85)
        same_col = [l["box"] for l in others if _overlap_x(l["box"], x0, x1)]
        if block.get("caption_pos", "below") == "below":
            above = [b[3] for b in same_col if b[3] < y0]
            y0 = max(above) + 0.005 if above else 0.08
        else:
            below = [b[1] for b in same_col if b[1] > y1]
            y1 = min(below) - 0.005 if below else 0.92
        loc["box"] = [x0, round(y0, 4), x1, round(y1, 4)]
        loc["src"] = "caption"  # 撑过的框旁边常有绕排正文，后面截重叠时不能再截它


def _clamp_overlaps(layout: dict):
    """只匹配到开头的块按长度估了结尾，可能压到同一栏的下一块；截到它的上沿。"""
    by_page: dict[int, list] = {}
    for loc in layout.values():
        by_page.setdefault(loc["page"], []).append(loc)
    for locs in by_page.values():
        locs.sort(key=lambda l: l["box"][1])
        for i, cur in enumerate(locs):
            if cur["src"] not in ("head", "text"):
                continue
            nxt = next((l for l in locs[i + 1:] if _overlap_x(l["box"], cur["box"][0], cur["box"][2])
                        and l["box"][1] > cur["box"][1]), None)
            if nxt and cur["box"][3] > nxt["box"][1]:
                cur["box"][3] = round(nxt["box"][1] - 0.002, 4)


def _fill_gaps(blocks: list[dict], layout: dict):
    """公式这类没有英文可匹配的块：放在同一栏里下一块之上、上方最近一块之下。"""
    for i, block in enumerate(blocks):
        bid = block.get("id")
        if not bid or bid in layout or not block.get("page"):
            continue
        page = block["page"]
        locs = _page_locs(layout, page)
        prev = next((layout[b["id"]] for b in reversed(blocks[:i]) if layout.get(b.get("id"), {}).get("page") == page), None)
        nxt = next((layout[b["id"]] for b in blocks[i + 1:] if layout.get(b.get("id"), {}).get("page") == page), None)
        ref = prev or nxt
        col = _column(locs, ref["box"]) if ref else None
        x0, x1 = col if col else (0.12, 0.88)
        if nxt and not _overlap_x(nxt["box"], x0, x1):
            nxt = None  # 下一块在另一栏，不能拿它当下沿
        bottom = nxt["box"][1] if nxt else 0.92
        above = [l["box"][3] for l in locs if _overlap_x(l["box"], x0, x1) and l["box"][3] <= bottom + 0.001]
        top = max(above) if above else 0.08
        if bottom - top < 0.01:
            bottom = top + 0.04
        layout[bid] = {"page": page, "box": [x0, round(top, 4), x1, round(bottom, 4)], "src": "between"}


def engine_image(root: Path, n: int) -> Path:
    """给翻译模型看的原页图（JPEG，模型工具普遍支持），按需生成。"""
    out = root / "extract" / f"page-{n:03d}.jpg"
    if not out.exists():
        with open_pdf(root / "source.pdf") as doc:
            doc[n - 1].render(scale=2.0).to_pil().convert("RGB").save(out, "JPEG", quality=82)
    return out


def page_variant(root: Path, rel: str, width: int) -> Path | None:
    """原页图的缩小版（原图 2.4 倍渲染、约 1500 像素宽，右侧面板用不着那么大）。生成一次缓存在 pages/w{宽}/。"""
    width = max(400, min(2000, width // 100 * 100))
    src = (root / rel).resolve()
    if not src.is_relative_to((root / "pages").resolve()) or not src.is_file():
        return None
    out = root / "pages" / f"w{width}" / src.name
    if not out.exists():
        from PIL import Image
        out.parent.mkdir(exist_ok=True)
        with Image.open(src) as im:
            if im.width <= width:
                return src
            im.resize((width, round(im.height * width / im.width)), Image.LANCZOS).save(out, "WEBP", quality=80, method=4)
    return out


PANEL_WIDTH = 1000  # 原页面板默认要的宽度（阅读页按面板宽度只会要 1000 或 1600）


def warm_variants(root: Path, width: int = PANEL_WIDTH) -> None:
    """后台把整篇的面板图都先生成好，打开原页面板时不用等。"""
    pages_dir = root / "pages"
    if not pages_dir.exists():
        return
    for src in sorted(pages_dir.glob("page-*.webp")):
        if not (root / "pages" / f"w{width}" / src.name).exists():
            page_variant(root, f"pages/{src.name}", width)


def prepare(root: Path) -> list[dict]:
    """渲染原页 + 抽文字，返回 meta.pages。"""
    pages = render_pages(root / "source.pdf", root / "pages")
    extract_text(root / "source.pdf", root / "extract")
    return pages
