import argparse
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pypdf import PdfWriter

from easyread import cli
from easyread.library import Library
from easyread.server import Handler
from easyread.store import write_json_atomic


class ImportRetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pdf = self.root / "test.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=60, height=80)
        writer.write(self.pdf)
        self.lib = Library(self.root / "lib")
        self.ws, _ = self.lib.create_from_pdf(self.pdf.read_bytes(), self.pdf.name)

    def test_reimport_after_cli_prepare_failure_retries(self):
        args = argparse.Namespace(source=str(self.pdf), no_translate=True)
        with patch.object(cli, "lib", return_value=self.lib), patch.object(cli, "out"), \
                patch("easyread.translate.prepare", side_effect=OSError("missing native library")):
            with self.assertRaises(OSError):
                cli.cmd_import(args)
        with patch.object(cli, "lib", return_value=self.lib), patch.object(cli, "out"), \
                patch("easyread.translate.prepare") as prepare:
            cli.cmd_import(args)
        prepare.assert_called_once()

    def test_api_retries_incomplete_entry_but_skips_active_and_prepared(self):
        handler = object.__new__(Handler)
        handler.app = types.SimpleNamespace(jobs=Mock())
        handler._json = lambda code, obj: obj
        for state, prepared, expected in [("error", False, True), ("cancelled", False, True),
                                          ("queued", False, False), ("running", False, False), ("done", True, False)]:
            with self.subTest(state=state):
                paper = self.ws.load("paper")
                paper["meta"]["pages"] = [{"n": 1}] if prepared else []
                write_json_atomic(self.ws.paper_path, paper)
                write_json_atomic(self.ws.root / "job.json", {"state": state})
                handler.app.jobs.reset_mock()
                result = handler._import_result(self.ws, False, False, "range:1-1")
                self.assertFalse(result["new"])
                self.assertEqual(result["queued"], expected)
                self.assertEqual(handler.app.jobs.enqueue.call_count, int(expected))
                if expected:
                    handler.app.jobs.enqueue.assert_called_with(self.ws, translate_after=False, scope="range:1-1")
