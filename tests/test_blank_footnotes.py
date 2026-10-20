import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, ArrayObject, FloatObject, NumberObject

from easyread.store import Workspace, write_json_atomic
from easyread import blank_pages
from easyread import translate


def pdf(path):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    streams = [
        b"",
        b"BT /F1 12 Tf 40 600 Td (Normal body paragraph with enough words to set the font size.) Tj ET\n"
        b"BT /F1 12 Tf 40 550 Td (Body) Tj /F1 7 Tf 28 4 Td (13) Tj ET\n"
        b"BT /F1 7 Tf 40 104 Td (13) Tj /F1 10 Tf 9 -4 Td (This is a footnote.) Tj ET",
        b"0 0 0 rg 20 20 100 100 re f",  # diagram without extractable text
        b"BT /F1 12 Tf 40 600 Td (A genuine reference [13].) Tj ET",
    ]
    for data in streams:
        page = writer.add_blank_page(width=600, height=800)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        if data:
            stream = DecodedStreamObject()
            stream.set_data(data)
            page[NameObject("/Contents")] = writer._add_object(stream)
    # Annotation-only page must not disappear either.
    page = writer.add_blank_page(width=600, height=800)
    page[NameObject("/Annots")] = ArrayObject([writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Text"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in [20, 20, 40, 40]]),
    }))])
    image = DecodedStreamObject()
    image.set_data(b"\x00\x00\x00")
    image.update({NameObject(k): v for k, v in {
        "/Type": NameObject("/XObject"), "/Subtype": NameObject("/Image"),
        "/Width": NumberObject(1), "/Height": NumberObject(1),
        "/ColorSpace": NameObject("/DeviceRGB"), "/BitsPerComponent": NumberObject(8),
    }.items()})
    page = writer.add_blank_page(width=600, height=800)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Scan"): writer._add_object(image)})
    })
    stream = DecodedStreamObject()
    stream.set_data(b"q 600 0 0 800 0 0 cm /Scan Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as out:
        writer.write(out)


class SourceSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.pdf"
        pdf(self.source)
        write_json_atomic(self.root / "paper.json", {
            "meta": {"source_pdf_path": str(self.source), "page_count": 6},
            "blocks": [], "translation": {},
        })
        self.ws = Workspace(self.root)

    def test_only_empty_page_skipped_without_model_call(self):
        self.assertEqual(blank_pages.find(self.ws, [1, 2, 3, 4, 5, 6]), [1])
        progress = []
        with patch.object(translate.engines, "run", side_effect=AssertionError("model called")):
            self.assertEqual(translate.translate_pages(
                self.ws, {}, [1], threading.Event(), lambda *args: progress.append(args)), {})
        self.assertEqual(self.ws.load("paper")["translation"]["done_pages"], [1])
        self.assertEqual(progress[-1][:2], (1, 1))

    def test_existing_content_and_missing_source_are_not_skipped(self):
        self.ws.update("paper", lambda p: p.update(blocks=[{"page": 1, "type": "para", "en": "Keep me"}]))
        self.assertEqual(blank_pages.find(self.ws, [1]), [])
        self.source.unlink()
        self.assertEqual(blank_pages.find(self.ws, [1, 2]), [])



if __name__ == "__main__":
    unittest.main()
