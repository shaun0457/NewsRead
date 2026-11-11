"""Ticket 06：產品名稱改成 NewsRead；打包版不從 PaperRead 的發佈頁下載更新。資料目錄、深層連結先不動（另見 ticket 74）。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from easyread import updates

ROOT = Path(__file__).resolve().parents[1]


class RenameTest(unittest.TestCase):
    def test_desktop_package_is_newsread_without_an_update_feed(self):
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        build = pkg["build"]
        self.assertEqual(build["productName"], "NewsRead")
        self.assertNotIn("easyread", build["appId"])  # 安裝程式不會蓋掉 PaperRead；資料目錄和深層連結還共用，見 ticket 74
        self.assertIsNone(build["publish"])
        self.assertTrue(build["win"]["target"] and build["nsis"]["artifactName"].startswith("NewsRead-"))
        self.assertNotIn("PaperRead", pkg["repository"]["url"])

    def test_no_update_source_points_at_paperread(self):
        for rel in ("electron/main.cjs", "easyread/updates.py"):
            self.assertNotIn("YuriyLin/PaperRead", (ROOT / rel).read_text(encoding="utf-8"), rel)
        env = {k: v for k, v in os.environ.items() if k != "EASYREAD_UPDATE_REPOSITORY"}
        out = subprocess.run([sys.executable, "-c", "from easyread import updates; print(repr(updates.REPO))"],
                             cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(out.stdout.strip(), "''")
        env["EASYREAD_UPDATE_REPOSITORY"] = " owner/repo \t"
        out = subprocess.run([sys.executable, "-c", "from easyread import updates; print(repr(updates.REPO))"],
                             cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(out.stdout.strip(), "'owner/repo'")

    def test_without_a_repository_nothing_goes_to_the_network(self):
        with mock.patch.object(updates, "REPO", ""),                 mock.patch.object(updates.http, "urlopen", side_effect=AssertionError("network")) as urlopen:
            out = updates.check(force=True)
        urlopen.assert_not_called()
        self.assertFalse(out["enabled"])
        self.assertFalse(out["newer"])

    def test_window_titles(self):
        for page in ("library.html", "reader.html", "tabs.html"):
            html = (ROOT / "easyread/web" / page).read_text(encoding="utf-8")
            self.assertIn("<title>NewsRead</title>", html, page)

    def test_desktop_shell_recognises_the_backend_ready_line(self):
        launch = (ROOT / "easyread/launch.py").read_text(encoding="utf-8")
        line = re.search(r'print\(f"(NewsRead 已啟動)：', launch)
        self.assertIsNotNone(line)
        main = (ROOT / "electron/main.cjs").read_text(encoding="utf-8")
        pattern = re.search(r"output\.match\(/(.+?)/\);", main).group(1)
        self.assertRegex("NewsRead 已啟動：http://127.0.0.1:8765", pattern.replace(r"\/", "/"))


if __name__ == "__main__":
    unittest.main()
