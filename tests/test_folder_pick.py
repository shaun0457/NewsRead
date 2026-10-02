import subprocess
import unittest
from unittest.mock import patch

from easyread import folder_pick


class FolderPickTest(unittest.TestCase):
    def run_with(self, returncode, stdout):
        done = subprocess.CompletedProcess([], returncode, stdout=stdout.encode("utf-8"), stderr=b"")
        with patch("easyread.folder_pick.subprocess.run", return_value=done) as run:
            return folder_pick.pick("选文件夹"), run

    def test_returns_chosen_path_without_trailing_separator(self):
        path, run = self.run_with(0, "D:\\坚果云\\论文\\\n")
        self.assertEqual(path, "D:\\坚果云\\论文")
        self.assertEqual(run.call_args.kwargs["env"]["EASYREAD_PICK_TITLE"], "选文件夹")

    def test_cancel_returns_empty(self):
        self.assertEqual(self.run_with(0, "")[0], "")

    def test_windows_dialog_failure_falls_back_to_typing(self):
        with patch("easyread.folder_pick.sys.platform", "win32"):
            self.assertIsNone(self.run_with(1, "")[0])

    def test_unavailable_dialog_returns_none(self):
        with patch("easyread.folder_pick.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(folder_pick.pick("x"))
        with patch("easyread.folder_pick.sys.platform", "linux"), patch("easyread.folder_pick.shutil.which", return_value=None):
            self.assertIsNone(folder_pick.pick("x"))

    def test_powershell_script_is_ascii_and_uses_the_explorer_style_dialog(self):  # PowerShell 5.1 按 GBK 读脚本
        folder_pick._PS.encode("ascii")
        self.assertIn("FOS_PICKFOLDERS", folder_pick._PS)
        self.assertNotIn("FolderBrowserDialog", folder_pick._PS)


if __name__ == "__main__":
    unittest.main()
