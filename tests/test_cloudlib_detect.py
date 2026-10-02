import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread import cloudlib, cloudlib_detect, config


class CloudLibraryDetectionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()  # 同 test_cloudlib：代码比较的是解析后的路径
        for context in (patch.object(config, "CONFIG_PATH", self.root / "config.json"),
                        patch.dict(os.environ, {"EASYREAD_LANG": "zh"}, clear=True),  # 断言中文报错；CI 系统语言是英文
                        patch("easyread.cloudlib_detect.Path.home", return_value=self.root)):
            context.start()
            self.addCleanup(context.stop)

    def test_windows_icloud_accepts_both_directory_spellings(self):
        for name in ("iCloudDrive", "iCloud Drive"):
            (self.root / name).mkdir()
        with patch("easyread.cloudlib_detect.sys.platform", "win32"):
            candidates = cloudlib_detect.detect()
        self.assertEqual({row["root_path"] for row in candidates},
                         {str(self.root / name) for name in ("iCloudDrive", "iCloud Drive")})

    def test_custom_empty_and_unrelated_folder_get_easyread_child(self):
        selected = self.root / "Nutstore"
        selected.mkdir()
        for contents in (None, "other files"):
            if contents:
                (selected / "notes.txt").write_text(contents)
            self.assertEqual(cloudlib_detect.target_path(selected), selected / "EasyRead")
            self.assertEqual(cloudlib.inspect(selected)["path"], str(selected / "EasyRead"))
        self.assertFalse((selected / "EasyRead").exists())

    def test_existing_library_and_explicit_easyread_folder_stay_as_selected(self):
        selected = self.root / "existing-library"
        paper = selected / "paper001"
        paper.mkdir(parents=True)
        (paper / "item.json").write_text("{}")
        self.assertEqual(cloudlib_detect.target_path(selected), selected)
        explicit = self.root / "new" / "EasyRead"
        self.assertEqual(cloudlib_detect.target_path(explicit), explicit)

    def test_partial_library_marker_is_not_hidden_in_an_extra_child(self):
        selected = self.root / "incomplete-library"
        selected.mkdir()
        (selected / cloudlib.MIGRATION_MARKER).write_text(json.dumps({"state": "publishing"}))
        self.assertEqual(cloudlib_detect.target_path(selected), selected)
        with self.assertRaisesRegex(ValueError, "未完成"):
            cloudlib.inspect(selected)

    def test_empty_current_library_location_uses_exact_path(self):
        current = self.root / "current-library"
        current.mkdir()
        self.assertEqual(cloudlib.inspect(current, exact=True)["path"], str(current))

    def test_normalizing_parent_or_current_path_cannot_bypass_nesting_guard(self):
        source = self.root / "custom-library"
        source.mkdir()
        for selected in (source, self.root, source / "nested"):
            with self.assertRaisesRegex(ValueError, "不能"):
                cloudlib.move(source, selected, "copy")

    def test_existing_file_is_not_treated_as_a_folder(self):
        selected = self.root / "file.txt"
        selected.write_text("keep")
        self.assertFalse(cloudlib.inspect(selected)["writable"])


if __name__ == "__main__":
    unittest.main()
