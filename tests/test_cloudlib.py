import json
import os
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from easyread import cloudlib, cloudlib_detect, config
from easyread.cloudlib_lock import LibraryMarker
from easyread.library import Library
from easyread.library_api import LibraryLocation
from easyread.store import write_json_atomic


def paper(root, pid, pdf=None):
    folder = root / pid
    folder.mkdir(parents=True)
    write_json_atomic(folder / "item.json", {"tags": ["test"]})
    write_json_atomic(folder / "paper.json", {"meta": {}})
    write_json_atomic(folder / "reader.json", {"notes": {"note": "preserve me"}})
    (folder / "source.pdf").write_bytes(pdf or b"%PDF " + pid.encode())
    return folder


class CloudLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src, self.dst = self.root / "source", self.root / "target"
        self.src.mkdir()
        for key, value in (("CONFIG_PATH", self.root / "config.json"),):
            cm = patch.object(config, key, value)
            cm.start(); self.addCleanup(cm.stop)
        cm = patch.dict(os.environ, {})
        cm.start(); self.addCleanup(cm.stop)
        for name in ("EASYREAD_LIBRARY", "COREAD_LIBRARY", "OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            os.environ.pop(name, None)
        config.save({"library_dir": str(self.src)})
        self.app = SimpleNamespace(lib=Library(self.src), jobs=SimpleNamespace(busy=lambda: False), presence=None)
        self.location = LibraryLocation(self.app)

    def migrate(self, mode="copy", target=None):
        return self.location.move({"path": str(target or self.dst), "mode": mode})

    def test_copy_preserves_all_papers_notes_trash_and_old_library(self):
        for pid in ("paper001", "paper002", "paper003"):
            paper(self.src, pid)
        paper(self.src / ".trash", "deleted01")
        result = self.migrate()
        self.assertEqual(result["copied"], 3)
        self.assertEqual(config.load()["library_dir"], str(self.dst))
        self.assertEqual(self.location.status, "restart_required")
        for original in self.src.rglob("*"):
            if original.is_file():
                self.assertEqual(original.read_bytes(), (self.dst / original.relative_to(self.src)).read_bytes())

    def test_failed_copy_does_not_change_configuration_or_existing_files(self):
        paper(self.src, "paper001")
        self.dst.mkdir()
        (self.dst / "keep.txt").write_text("original")
        with patch("easyread.cloudlib.shutil.copy2", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.migrate()
        self.assertEqual(config.load()["library_dir"], str(self.src))
        self.assertEqual(self.location.status, "idle")
        self.assertEqual((self.dst / "keep.txt").read_text(), "original")
        self.assertFalse(list(self.dst.glob(".easyread-copy-*")))

    def test_mismatch_is_not_accepted(self):
        paper(self.src, "paper001")
        with patch("easyread.cloudlib.shutil.copy2", side_effect=lambda s, d: Path(d).write_bytes(b"bad")):
            with self.assertRaisesRegex(ValueError, "核对失败"):
                self.migrate()
        self.assertEqual(config.load()["library_dir"], str(self.src))

    def test_merge_full_pdf_sha_and_id_collision_keep_target(self):
        paper(self.src, "paper001", b"%PDF same")
        paper(self.src, "paper002")
        paper(self.src, "paper003")
        paper(self.dst, "differentid", b"%PDF same")
        target = paper(self.dst, "paper003", b"%PDF other")
        result = self.migrate("merge")
        self.assertEqual(result["copied"], 1)
        self.assertEqual(len(result["skipped"]), 2)
        self.assertEqual((target / "source.pdf").read_bytes(), b"%PDF other")
        self.assertTrue((self.dst / "paper002").is_dir())

    def test_use_does_not_copy_or_remove_source(self):
        paper(self.src, "paper001")
        paper(self.dst, "paper002")
        result = self.migrate("use")
        self.assertEqual(result["copied"], 0)
        self.assertFalse((self.dst / "paper001").exists())
        self.assertTrue((self.src / "paper001").exists())

    def test_nested_paths_and_temporary_library_rejected(self):
        for dst in (self.src, self.src / "nested", self.src.parent):
            with self.assertRaisesRegex(ValueError, "不能"):
                self.migrate(target=dst)
        with patch.dict(os.environ, {"EASYREAD_LIBRARY": str(self.src)}):
            with self.assertRaisesRegex(ValueError, "临时"):
                self.migrate()

    def test_unknown_target_with_same_id_never_overwritten(self):
        paper(self.src, "paper001")
        self.dst.mkdir()
        (self.dst / "paper001").write_text("unknown")
        with self.assertRaisesRegex(ValueError, "不会覆盖"):
            self.migrate()
        self.assertEqual((self.dst / "paper001").read_text(), "unknown")

    def test_busy_job_and_dequeued_job_transition_rejected(self):
        self.app.jobs.busy = lambda: True
        with self.assertRaisesRegex(ValueError, "任务"):
            self.migrate()
        self.app.jobs.busy = lambda: False
        folder = paper(self.src, "paper001")
        write_json_atomic(folder / "job.json", {"state": "queued"})
        with self.assertRaisesRegex(ValueError, "任务"):
            self.migrate()

    def test_requests_warm_and_other_pages_block_migration(self):
        with self.location.request("POST", "/api/p/paper001/chat"):
            with self.assertRaisesRegex(ValueError, "保存"):
                self.migrate()
        self.location.begin()
        with self.assertRaisesRegex(ValueError, "保存"):
            self.migrate()
        self.location.end()
        self.app.presence = SimpleNamespace(pages=2, lock=threading.Lock())
        with self.assertRaisesRegex(ValueError, "关闭其他"):
            self.migrate()

    def test_gate_freezes_writes_during_copy_and_until_restart(self):
        paper(self.src, "paper001")
        copy = cloudlib._copy_verified

        def guarded(src, dst):
            self.assertEqual(self.location.status, "moving")
            with self.assertRaises(ValueError), self.location.request("POST", "/api/p/paper001/ops"):
                pass
            with self.assertRaises(ValueError), self.location.request("GET", "/read/paper001"):
                pass
            return copy(src, dst)
        with patch("easyread.cloudlib._copy_verified", side_effect=guarded):
            self.migrate()
        with self.assertRaises(ValueError), self.location.request("POST", "/api/import"):
            pass
        with self.location.request("GET", "/api/p/paper001/state"):
            pass

    def test_links_and_junctions_cannot_escape_source(self):
        folder = paper(self.src, "paper001")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("never copy")
        link = folder / "escape"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, "链接|联接"):
                self.migrate()
            self.assertEqual(config.load()["library_dir"], str(self.src))
            self.assertEqual((outside / "secret.txt").read_text(), "never copy")
        finally:
            # 只移除链接本身；Windows rmdir 不递归，不删除链接目标。
            if os.name == "nt":
                link.rmdir()
            else:
                link.unlink()

    def test_detection_uses_existing_onedrive_and_subfolder(self):
        disk = self.root / "OneDrive"
        disk.mkdir()
        with patch.dict(os.environ, {"OneDrive": str(disk), "OneDriveCommercial": str(self.root / "missing")}), \
                patch("easyread.cloudlib_detect.Path.home", return_value=self.root):
            candidates = cloudlib_detect.detect()
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["path"], str(disk / "EasyRead"))
            self.assertEqual(cloudlib.inspect(disk)["path"], str(disk / "EasyRead"))
            self.assertFalse((disk / "EasyRead").exists())

    def test_marker_recent_other_host_and_owned_cleanup(self):
        marker = LibraryMarker(self.src)
        for minutes, expected in ((2, "other-pc"), (10, "")):
            write_json_atomic(marker.path, {"host": "other-pc", "pid": 123,
                "at": (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()})
            self.assertEqual(marker.other_device(), expected)
        marker.refresh()
        marker.close()
        self.assertFalse(marker.path.exists())
        write_json_atomic(marker.path, {"owner": "someone-else"})
        marker.close()
        self.assertTrue(marker.path.exists())

    def test_get_cannot_invoke_mutating_library_routes(self):
        from easyread.server import Handler
        self.app.location = self.location
        handler = Handler.__new__(Handler)
        handler.app = self.app
        handler._json = Mock()
        for path in ("/api/library/move", "/api/shutdown", "/api/library/reveal"):
            handler.path = path
            with patch("easyread.library_api.post") as post:
                handler._get()
                post.assert_not_called()
                self.assertEqual(handler._json.call_args.args[0], 404)


if __name__ == "__main__":
    unittest.main()
