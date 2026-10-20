"""Only pages without PDF objects or annotations may be skipped automatically."""
from contextlib import closing

from .pdfwork import open_pdf


def find(ws, pages, cancel=None):
    occupied = {b.get("page") for b in ws.load("paper").get("blocks", [])}
    blank = []
    try:
        with open_pdf(ws.source_pdf) as doc:
            for n in pages:
                if cancel and cancel.is_set():
                    break
                if n in occupied or not 1 <= n <= len(doc):
                    continue
                with closing(doc[n - 1]) as page:
                    # Scans, white vector drawings and unrecognized objects stay.
                    # Being unable to extract text is never evidence of blankness.
                    from pypdfium2 import raw
                    if raw.FPDFPage_GetAnnotCount(page) != 0:
                        continue
                    if next(iter(page.get_objects()), None) is not None:
                        continue
                    with closing(page.get_textpage()) as text:
                        if text.count_chars() == 0:
                            blank.append(n)
    except Exception:
        return []  # A missing/unreadable source must not silently lose pages.
    return blank
