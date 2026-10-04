"""按原页渲染结果确认图形真的画在页面上。

PDF 里的白色背景矩形、被裁剪路径挡住的内容、嵌入图片自带的白边，在对象坐标里都有范围，
但页面上看不见；只按对象坐标取范围会把图框撑到正文或页眉。这里把每个候选框收到看得见的像素上。
"""
from __future__ import annotations

import math
from contextlib import closing
from pathlib import Path

SCALE = 2
_WHITE = 245  # 三个通道都不低于这个值就算页面底色


def visible_mask(pdf: Path, page_index: int, erase: list[list[float]]):
    """渲染一页，返回两张“非底色”像素的黑白图（255 为有内容）：(图形, 全部)。
    图形那张抹掉 erase 里的框（PDF 文字、页眉分隔线）：文字由题注、标签那套规则单独处理，
    不能让正文或页眉线把图形范围撑开。全部那张用来确认文字本身看得见（被裁掉的文字不算标签）。"""
    from PIL import ImageChops, ImageDraw, ImageFilter

    from .pdfwork import open_pdf
    with open_pdf(pdf) as doc, closing(doc[page_index]) as page, closing(page.render(scale=SCALE)) as bitmap:
        with bitmap.to_pil() as raw, raw.convert("RGB") as rgb:
            r, g, b = rgb.split()
    darkest = ImageChops.darker(ImageChops.darker(r, g), b)
    ink = darkest.point(lambda v: 255 if v < _WHITE else 0)
    mask = ink.copy()
    width, height = mask.size
    draw = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in erase:
        draw.rectangle([x0 * width - 1, y0 * height - 1, x1 * width + 1, y1 * height + 1], fill=0)
    # 去掉文字抗锯齿留下的孤立噪点；1 像素宽的细线在 3x3 邻域里有 3 个点，会保留。
    return mask.filter(ImageFilter.BoxBlur(1)).point(lambda v: 255 if v >= 70 else 0), ink


def trim(mask, box: list[float]) -> list[float] | None:
    """把框收到框内可见像素的范围；整块都是底色时返回 None。"""
    width, height = mask.size
    left, top = int(box[0] * width), int(box[1] * height)
    right = max(left + 1, math.ceil(box[2] * width))
    bottom = max(top + 1, math.ceil(box[3] * height))
    found = mask.crop((left, top, right, bottom)).getbbox()
    if not found:
        return None
    return [max(box[0], (left + found[0] - 1) / width), max(box[1], (top + found[1] - 1) / height),
            min(box[2], (left + found[2] + 1) / width), min(box[3], (top + found[3] + 1) / height)]


def inked(ink, box: list[float]) -> bool:
    """文字框里真的有字：可见像素横向铺满一半以上（只是边上压到别的字不算）。"""
    found = trim(ink, box)
    return bool(found) and found[2] - found[0] >= (box[2] - box[0]) * .5
