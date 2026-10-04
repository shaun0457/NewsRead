import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs

from easyread import open_link
from easyread.library import Library, sha256_bytes

PDF = b"%PDF-1.4\n%open-link test\n"


class OpenLinkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Library(Path(self.tmp.name))
        self.ws, _ = self.lib.create_from_pdf(PDF, "a.pdf", {"title_en": "A"})
        self.sha = sha256_bytes(PDF)

    def tearDown(self):
        self.tmp.cleanup()

    def target(self, query: str) -> str:
        return open_link.target(self.lib, parse_qs(query))

    def test_opens_paper_by_fingerprint_with_block_anchor(self):
        self.assertEqual(self.target(f"sha256={self.sha.upper()}&block=p3-2"), f"/read/{self.ws.root.name}#p3-2")

    def test_opens_paper_by_id(self):
        self.assertEqual(self.target(f"id={self.ws.root.name}"), f"/read/{self.ws.root.name}")

    def test_unknown_or_malformed_links_fall_back_to_library(self):
        self.assertEqual(self.target("sha256=" + "b" * 64), "/")
        self.assertEqual(self.target("sha256=xyz"), "/")
        self.assertEqual(self.target("id=../x"), "/")

    def test_unsafe_block_is_dropped(self):
        self.assertEqual(self.target(f"sha256={self.sha}&block=<x>"), f"/read/{self.ws.root.name}")

    def test_version_reports_api_level(self):
        self.assertEqual(open_link.version()["api"], 1)


if __name__ == "__main__":
    unittest.main()
