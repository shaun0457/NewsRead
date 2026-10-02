"""All PDFium operations, including closing native handles, share one lock."""
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pypdfium2
from PIL import Image
from pypdf import PdfWriter

from easyread import pdfwork


class PDFConcurrencyTest(unittest.TestCase):
    def test_render_extract_crop_and_model_images_cannot_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            writer = PdfWriter()
            writer.add_blank_page(width=60, height=80)
            writer.write(root / "source.pdf")
            active = set()
            closed = []
            guard = threading.Lock()
            real_document = pypdfium2.PdfDocument

            def tracked_document(path):
                owner = threading.get_ident()
                with guard:
                    if active:
                        raise AssertionError("PDFium documents overlapped across threads")
                    active.add(owner)
                time.sleep(0.01)  # Make the old unguarded implementation fail deterministically.
                doc = real_document(path)
                close = doc.close

                def tracked_close():
                    if doc.raw:
                        close()
                        with guard:
                            active.remove(owner)
                            closed.append(owner)
                doc.close = tracked_close
                return doc

            tasks = [lambda: pdfwork.engine_image(root, 1),
                     lambda: pdfwork.render_pages(root / "source.pdf", root / "pages", scale=1),
                     lambda: pdfwork.extract_text(root / "source.pdf", root / "extract"),
                     lambda: pdfwork.crop(root, 1, [0, 0, 1, 1], "test", scale=1)]
            with patch.object(pypdfium2, "PdfDocument", side_effect=tracked_document), ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda task: task(), tasks))
            self.assertEqual(len(closed), 4)
            self.assertFalse(active)
            for path in [root / "extract/page-001.jpg", root / "pages/page-001.webp", root / "figures/test.webp"]:
                with Image.open(path) as image:
                    image.verify()

    def test_pdf_handles_close_after_save_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            writer = PdfWriter()
            writer.add_blank_page(width=60, height=80)
            writer.write(root / "source.pdf")
            real_document = pypdfium2.PdfDocument
            docs = []

            def opened(path):
                doc = real_document(path)
                docs.append(doc)
                return doc
            with patch.object(pypdfium2, "PdfDocument", side_effect=opened), \
                    patch("PIL.Image.Image.save", side_effect=OSError("disk full")), self.assertRaises(OSError):
                pdfwork.engine_image(root, 1)
            self.assertTrue(docs)
            self.assertIsNone(docs[0].raw)
            self.assertTrue(pdfwork.engine_image(root, 1).exists())
