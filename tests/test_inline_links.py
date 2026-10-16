import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from easyread.store import Workspace, write_json_atomic
from easyread import links, pdfwork
from easyread.prompts import _page_texts


class InlineLinksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ws = Workspace(self.root)
        writer = PdfWriter()
        page = writer.add_blank_page(width=400, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Courier')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 40 150 Td (Read docs here and details.) Tj 0 -30 Td (Use einx here for examples.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
        writer.add_annotation(0, Link(rect=(111, 148, 142, 161), url='https://example.com/docs'))
        writer.add_annotation(0, Link(rect=(104, 118, 134, 131), url='https://example.com/einx'))
        writer.add_annotation(0, Link(rect=(40, 148, 68, 161), url='javascript:alert(1)'))
        with (self.root / 'source.pdf').open('wb') as out:
            writer.write(out)
        write_json_atomic(self.root / 'paper.json', {'blocks': []})

    def test_real_pdf_annotations_survive_extraction_and_prompt_construction(self):
        pdfwork.extract_text(self.root / 'source.pdf', self.root / 'extract')
        records = links.ensure(self.ws)['1']
        self.assertEqual([record['quote'] for record in records], ['here', 'here'])
        prompt = _page_texts(self.ws, [1])
        self.assertIn('[here](https://example.com/docs)', prompt)
        self.assertIn('[here](https://example.com/einx)', prompt)
        self.assertNotIn('javascript:', prompt)
        self.assertEqual(links.insert(prompt, records), prompt)

    def test_old_original_is_backfilled_without_changing_translation_or_notes(self):
        en = 'Read docs here and details. Use einx here for examples.'
        zh = '已有译文保持不变'
        write_json_atomic(self.root / 'paper.json', {'blocks': [{'id': 'p1', 'type': 'para', 'page': 1, 'en': en, 'zh': zh, 'sents': [[26, 4], [len(en), len(zh)]]}]})
        write_json_atomic(self.root / 'reader.json', {'notes': {'n1': {'quote': 'here', 'body': 'Keep'}}})
        before = (self.root / 'reader.json').read_bytes()
        links.refresh(self.ws)
        block = self.ws.load('paper')['blocks'][0]
        self.assertIn('[here](https://example.com/docs)', block['en'])
        self.assertEqual(block['zh'], zh)
        self.assertEqual(block['sents'][-1], [len(block['en']), len(zh)])
        self.assertEqual((self.root / 'reader.json').read_bytes(), before)
        links.refresh(self.ws)
        self.assertEqual(self.ws.load('paper')['blocks'][0]['en'], block['en'])

    def test_ambiguous_or_unsafe_links_are_not_guessed(self):
        self.assertEqual(links.insert('here and here', [{'quote': 'here', 'url': 'https://example.com'}]), 'here and here')
        for uri in ['javascript:alert(1)', 'file:///private/file', 'data:text/html,evil', 'https://example.com\nscript']:
            self.assertEqual(links.safe_url(uri), '')


if __name__ == '__main__':
    unittest.main()
