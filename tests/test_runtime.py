"""Ticket 07：常駐服務。單一執行個體鎖、關掉頁面後仍在跑、停止時背景執行緒在時限內結束、Windows 開機自動啟動。"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from easyread import autostart, cli, config, instance, launch, presence, server
from tests.test_presence import _ws_connect

ROOT = Path(__file__).resolve().parents[1]
HOLD = """
import sys, time
sys.path.insert(0, sys.argv[2])
from easyread.instance import InstanceLock
lock = InstanceLock(sys.argv[1])
print("held" if lock.acquire() else "busy", flush=True)
time.sleep(60)
"""


class InstanceLockTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "home" / instance.LOCK_NAME

    def test_second_lock_on_the_same_file_is_refused_until_released(self):
        first, second = instance.InstanceLock(self.path), instance.InstanceLock(self.path)
        self.assertTrue(first.acquire())
        self.assertTrue(first.acquire())  # 自己再拿一次沒問題
        self.assertFalse(second.acquire())
        self.assertFalse(second.held)
        first.release()
        first.release()  # 放兩次沒問題
        self.assertTrue(second.acquire())
        second.release()

    def test_lock_held_by_another_process_and_released_when_it_dies(self):
        proc = subprocess.Popen([sys.executable, "-c", HOLD, str(self.path), str(ROOT)],
                                stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "held")
            with instance.InstanceLock(self.path) as lock:
                self.assertFalse(lock.acquire())
        finally:
            proc.kill()  # 不是正常結束：鎖由系統放開
            proc.wait(10)
            proc.stdout.close()
        with instance.InstanceLock(self.path) as lock:
            deadline = time.monotonic() + 3  # Windows 放開被強制結束的程序的鎖可能慢一點
            while not lock.acquire() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(lock.held)

    def test_lock_file_is_not_inherited_by_child_processes(self):
        with instance.InstanceLock(self.path) as lock:
            self.assertTrue(lock.acquire())
            self.assertFalse(os.get_inheritable(lock._fd))

    def spy_open(self):
        opened, real_open = [], os.open

        def spy(*a, **kw):
            fd = real_open(*a, **kw)
            opened.append(fd)
            return fd
        return opened, mock.patch.object(instance.os, "open", side_effect=spy)

    def test_failed_lock_closes_its_file(self):
        with instance.InstanceLock(self.path) as holder:
            holder.acquire()
            other = instance.InstanceLock(self.path)
            opened, spy = self.spy_open()
            with spy, mock.patch.object(instance.os, "close", wraps=os.close) as close:
                self.assertFalse(other.acquire())
            close.assert_any_call(opened[0])

    def test_other_lock_errors_are_raised_not_reported_as_running(self):  # 例如檔案系統不支援鎖
        import errno
        lock = instance.InstanceLock(self.path)
        opened, spy = self.spy_open()
        with spy, mock.patch.object(instance, "_lock", side_effect=OSError(errno.ENOLCK, "no locks")), \
                mock.patch.object(instance.os, "close", wraps=os.close) as close, self.assertRaises(OSError):
            lock.acquire()
        close.assert_any_call(opened[0])
        self.assertFalse(lock.held)

    def test_busy_error_codes(self):
        import errno
        for code in (errno.EACCES, errno.EAGAIN):
            with self.subTest(code=code), mock.patch.object(instance, "_lock", side_effect=OSError(code, "busy")):
                self.assertFalse(instance.InstanceLock(self.path).acquire())

    def test_server_url_validation(self):
        good = "http://127.0.0.1:8765"
        self.assertEqual(instance.server_url({"url": good}), good)
        for bad in ({"url": "file:///etc/passwd"}, {"url": "http://x/" + "a" * 300}, {"url": "http://x\x1b[2J"},
                    {"url": 5}, {}, [good], None):
            with self.subTest(bad=bad):
                self.assertEqual(instance.server_url(bad), "")


class ServeBase(unittest.TestCase):
    """真的跑 launch.serve()，資料目錄和文獻庫都在暫存目錄。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.home.mkdir()
        lib = Path(tmp.name) / "library"
        env = {k: v for k, v in os.environ.items() if k not in ("EASYREAD_LIBRARY", "COREAD_LIBRARY")}
        cfg = {**config.DEFAULTS, "library_dir": str(lib), "port": 0}
        self.apps = []
        real_app = launch.App

        def remember(cfg):
            app = real_app(cfg)
            self.apps.append(app)
            return app
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(config, "HOME", self.home),
                        mock.patch.object(config, "SERVER_INFO", self.home / ".server.json"),
                        mock.patch.object(config, "load", return_value=cfg),
                        mock.patch.object(launch, "setup_log"),
                        mock.patch.object(launch.detect, "warm"),
                        mock.patch.object(launch, "print", create=True),  # 啟動那一行不印到測試輸出
                        mock.patch.object(launch, "App", side_effect=remember),
                        mock.patch.object(server.Handler, "app", getattr(server.Handler, "app", None), create=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def start(self, wait_for=".server.json", **kw) -> threading.Thread:
        self.errors = []
        index = len(self.apps)  # 這個執行緒建的 App；cleanup 只停它，不會停到後來別的測試步驟建的

        def run():
            try:
                launch.serve(port=0, **kw)
            except BaseException as e:  # noqa: BLE001
                self.errors.append(e)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(self.stop, thread, index)
        deadline = time.monotonic() + 10
        while thread.is_alive() and time.monotonic() < deadline and not self.ready(wait_for):
            time.sleep(0.02)
        self.assertTrue(thread.is_alive(), self.errors)
        self.app = self.apps[index]
        return thread

    def ready(self, wait_for: str) -> bool:
        if wait_for == ".server.json":
            return (self.home / ".server.json").exists()
        return bool(self.apps and getattr(self.apps[-1], "scheduler", None) and self.apps[-1].scheduler._thread)

    def stop(self, thread: threading.Thread, index: int) -> None:
        shutdown = getattr(self.apps[index], "shutdown", None) if len(self.apps) > index else None
        if thread.is_alive() and shutdown:
            shutdown()
            thread.join(10)

    @property
    def url(self) -> str:
        return launch.running_url()

    def alive(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/api/version", timeout=2) as r:
                return r.status == 200
        except OSError:
            return False

    def close_a_page(self) -> None:
        port = int(self.url.rsplit(":", 1)[1])
        sock, resp = _ws_connect(port, self.url)
        self.assertIn(b"101", resp.split(b"\r\n", 1)[0])
        time.sleep(0.2)
        sock.close()


FAST_PRESENCE = partial(presence.Presence, grace=0.2, first_wait=0.2, tick=0.05)


def _watching_presence(busy, stop, enabled):
    """監看執行緒打開，但一直「有工作在跑」不會自己退出：測停止時它也會結束。"""
    return presence.Presence(lambda: True, stop, True, tick=0.05)


class ServeTest(ServeBase):
    def test_server_keeps_running_after_every_page_is_closed(self):
        with mock.patch.object(launch, "Presence", FAST_PRESENCE):
            self.start()
        self.close_a_page()
        time.sleep(1)
        self.assertTrue(self.alive())

    def test_exit_on_close_still_exits_when_asked(self):  # 對照組：證明上一個測試等的時間夠讓它退出
        with mock.patch.object(launch, "Presence", FAST_PRESENCE):
            thread = self.start(exit_on_close=True)
        self.close_a_page()
        thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_second_server_is_refused_and_points_at_the_first(self):
        self.start()
        url = self.url
        with mock.patch.object(launch, "_Server", side_effect=AssertionError("must not bind")) as bind:
            with self.assertRaises(instance.AlreadyRunning) as caught:
                launch.serve(port=0)
        bind.assert_not_called()
        self.assertEqual(caught.exception.url, url)
        self.assertEqual(len(self.apps), 1)  # 第二個沒建 App，不會去碰文獻庫和背景工作
        self.assertTrue(self.alive())

    def test_cli_reports_the_running_server_and_exits(self):
        self.start()
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(cli, "running_server", return_value=None), \
                mock.patch.object(launch, "_Server", side_effect=AssertionError("must not bind")), \
                self.assertRaises(SystemExit) as code:  # 沒擋下時會丟 AssertionError，不會在這裡一直跑下去
            cli.cmd_serve(SimpleNamespace(port=None, open=False, exit_on_close=False, host=None))
        self.assertEqual(code.exception.code, 3)
        self.assertIn("已經在執行", buf.getvalue())
        self.assertIn(self.url, buf.getvalue())

    def test_second_click_while_the_first_is_starting_opens_the_browser(self):
        self.start()
        answers = iter([None, None, None, self.url])  # 前幾次還沒回應：剛開始啟動
        with redirect_stdout(io.StringIO()), mock.patch.object(cli, "running_server", side_effect=lambda: next(answers)), \
                mock.patch.object(launch, "_Server", side_effect=AssertionError("must not bind")), \
                mock.patch("webbrowser.open") as browser:
            cli.cmd_serve(SimpleNamespace(port=None, open=True, exit_on_close=False, host=None))
        browser.assert_called_once_with(self.url)

    def test_second_click_gives_up_after_the_wait(self):
        self.start()
        exits = []

        def second_click():
            try:
                cli.cmd_serve(SimpleNamespace(port=None, open=True, exit_on_close=False, host=None))
            except SystemExit as e:
                exits.append(e.code)
        with redirect_stdout(io.StringIO()), mock.patch.object(cli, "running_server", return_value=None) as probe, \
                mock.patch.object(launch, "_Server", side_effect=AssertionError("must not bind")), \
                mock.patch.object(cli, "START_WAIT", 1.0), mock.patch("webbrowser.open") as browser:
            click = threading.Thread(target=second_click, daemon=True)
            click.start()
            click.join(4)  # 等的時間有上限：沒有上限時這裡會逾時、測試失敗，不會一直卡著
            self.assertFalse(click.is_alive())
        self.assertEqual(exits, [3])
        browser.assert_not_called()
        self.assertLessEqual(probe.call_count, 1 + 4)  # cmd_serve 先問一次，之後每 0.5 秒一次

    def test_stop_ends_background_threads_within_the_time_limit(self):
        entered, release = threading.Event(), threading.Event()
        with mock.patch.object(launch, "STOP_TIMEOUT", 0.5), \
                mock.patch.object(launch, "Presence", _watching_presence), \
                mock.patch.object(launch, "Scheduler", partial(launch.Scheduler, tick=0.05)):
            thread = self.start()
            app = self.app
            self.addCleanup(lambda: (release.set(), app.scheduler._thread.join(5)))  # 暫存目錄刪掉前讓它收工
            app.scheduler.add("hang", 3600, lambda: (entered.set(), release.wait(30)))
            self.assertTrue(entered.wait(5))  # 卡住的工作
            started = time.monotonic()
            app.shutdown()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - started, 4)  # 排程最多等 0.5 秒，presence 和標記各自有上限
        self.assertTrue(app.scheduler.stopping.is_set())
        self.assertFalse(app.presence.thread.is_alive())
        self.assertFalse(app.location.marker.thread.is_alive())
        self.assertFalse((self.home / ".server.json").exists())
        with instance.InstanceLock(self.home / instance.LOCK_NAME) as lock:
            self.assertTrue(lock.acquire())  # 鎖放開了，可以再啟動

    def test_startup_failure_releases_everything(self):
        with mock.patch.object(launch, "Presence", _watching_presence), \
                mock.patch.object(launch, "write_json_atomic", side_effect=OSError("disk full")), \
                self.assertRaises(OSError):
            launch.serve(port=0)
        app = self.apps[-1]
        self.assertFalse(app.scheduler._thread.is_alive())
        app.presence.thread.join(2)
        self.assertFalse(app.presence.thread.is_alive())
        with instance.InstanceLock(self.home / instance.LOCK_NAME) as lock:
            self.assertTrue(lock.acquire())

    def test_scheduler_state_lives_in_the_data_directory(self):
        self.start()
        self.assertEqual(self.app.scheduler.state_path, self.home / launch.SCHEDULE_NAME)

    def test_server_schedules_ai_triage(self):
        """排程器裡有 AI 分類這個工作，跑它就是對這個 app 跑 triage.run_pending（gate F1：自動分類只靠這一行）。"""
        from easyread import triage
        self.start()
        job = self.app.scheduler.jobs.get("triage")
        self.assertIsNotNone(job, sorted(self.app.scheduler.jobs))
        self.assertEqual(job.interval, triage.INTERVAL)
        with mock.patch.object(triage, "run_pending") as run_pending:
            job.run()
        run_pending.assert_called_once_with(self.app)

    def test_server_catches_up_waiting_translations_through_the_quota_guard(self):
        """匯入後自動翻譯等額度時，排程每一輪補翻；送出前問的是 ai_engines 的額度保護。"""
        from easyread import ai_engines, launch
        self.start()
        job = self.app.scheduler.jobs.get("translate_catchup")
        self.assertIsNotNone(job, sorted(self.app.scheduler.jobs))
        self.assertEqual(job.interval, launch.TRANSLATE_CATCHUP_INTERVAL)
        with mock.patch.object(self.app.jobs, "resume_waiting") as resume:
            job.run()
        resume.assert_called_once_with()
        fake = mock.Mock()
        fake.translation_gate.return_value = {"reason": "quota", "until": None}
        with mock.patch.object(ai_engines, "for_app", return_value=fake) as for_app:
            self.assertEqual(self.app.jobs.translate_gate({"engine": "claude"}), {"reason": "quota", "until": None})
        for_app.assert_called_once_with(self.app)

    def test_temporary_library_takes_no_lock(self):
        with mock.patch.dict(os.environ, {"EASYREAD_LIBRARY": str(self.home / "tmp-lib")}), \
                instance.InstanceLock(self.home / instance.LOCK_NAME) as other:
            self.assertTrue(other.acquire())  # 就算鎖被佔著，暫用文獻庫照樣能啟動
            thread = self.start(wait_for="scheduler")
            self.assertIsNone(self.app.scheduler.state_path)
            self.app.shutdown()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.errors, [])


class LauncherTest(unittest.TestCase):
    def test_launchers_start_an_always_on_server(self):
        for rel in ("start.cmd", "start.sh"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("-m easyread serve --open", text, rel)
            self.assertNotIn("--exit-on-close", text, rel)


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_QUERY_VALUE, KEY_SET_VALUE = 1, 2
    REG_SZ, REG_EXPAND_SZ, REG_DWORD = 1, 2, 4

    def __init__(self):
        self.values: dict[tuple, tuple] = {}
        self.keys: set[str] = set()

    class _Key:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, reserved=0, access=0):
        if path not in self.keys:
            raise FileNotFoundError(path)
        return self._Key(path)

    def CreateKeyEx(self, root, path, reserved=0, access=0):
        self.keys.add(path)
        return self._Key(path)

    def QueryValueEx(self, key, name):
        if (key.path, name) not in self.values:
            raise FileNotFoundError(name)
        return self.values[(key.path, name)]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[(key.path, name)] = (value, kind)

    def DeleteValue(self, key, name):
        if (key.path, name) not in self.values:
            raise FileNotFoundError(name)
        del self.values[(key.path, name)]


class AutostartTest(unittest.TestCase):
    def setUp(self):
        self.reg = FakeWinreg()
        for patcher in (mock.patch.object(autostart, "_winreg", return_value=self.reg),
                        mock.patch.object(autostart, "is_windows", return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_enable_writes_the_current_user_run_key(self):
        self.assertEqual(autostart.status(), {"supported": True, "enabled": False, "current": False})
        cmd = autostart.enable()
        self.assertEqual(self.reg.values[(autostart.RUN_KEY, "NewsRead")], (cmd, FakeWinreg.REG_SZ))
        self.assertEqual(autostart.RUN_KEY, r"Software\Microsoft\Windows\CurrentVersion\Run")
        self.assertEqual(autostart.status(), {"supported": True, "enabled": True, "current": True})
        self.assertTrue(autostart.disable())
        self.assertFalse(autostart.disable())
        self.assertEqual(autostart.status()["enabled"], False)

    def test_entry_from_another_copy_is_reported_as_stale(self):
        self.reg.keys.add(autostart.RUN_KEY)
        self.reg.values[(autostart.RUN_KEY, "NewsRead")] = ('"C:/old/pythonw.exe" -m easyread serve', FakeWinreg.REG_SZ)
        self.assertEqual(autostart.status(), {"supported": True, "enabled": True, "current": False})

    def test_non_string_value_is_ignored(self):
        self.reg.keys.add(autostart.RUN_KEY)
        self.reg.values[(autostart.RUN_KEY, "NewsRead")] = (1, FakeWinreg.REG_DWORD)
        self.assertIsNone(autostart.registered())

    def test_source_command_runs_serve_from_this_checkout_without_a_console(self):
        cmd = autostart.command()
        self.assertIn(autostart.ROOT.as_posix(), cmd)
        self.assertIn("main(['serve'])", cmd)
        self.assertNotIn("--open", cmd)
        self.assertNotIn("--exit-on-close", cmd)
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            self.assertTrue(cmd.startswith(f'"{pythonw}"'))

    def test_source_command_actually_imports_this_checkout(self):  # 登入時的工作目錄不固定
        cmd = autostart.command()
        self.assertIn('" -I -c "', cmd)  # 隔離模式：工作目錄裡的同名模組不會被載入
        code = cmd.split(" -I -c ", 1)[1].strip('"').replace("main(['serve'])", "print('ok')")
        with tempfile.TemporaryDirectory() as cwd:
            (Path(cwd) / "json.py").write_text("raise SystemExit('planted module ran')", encoding="utf-8")
            out = subprocess.run([sys.executable, "-I", "-c", code], cwd=cwd, capture_output=True,
                                 text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "ok", out.stderr[-500:])

    def test_frozen_backend_runs_serve(self):
        with mock.patch.object(autostart.sys, "frozen", True, create=True), \
                mock.patch.object(autostart.sys, "executable", r"C:\Apps\NewsRead\backend.exe"):
            self.assertEqual(autostart.command(), '"C:\\Apps\\NewsRead\\backend.exe" serve')

    def test_paths_with_quotes_or_percent_are_refused(self):
        for root in ("/tmp/it's here", "/tmp/%TEMP%x"):
            with self.subTest(root=root), mock.patch.object(autostart, "ROOT", Path(root)), \
                    self.assertRaises(ValueError):
                autostart.command()

    def test_not_windows(self):
        with mock.patch.object(autostart, "is_windows", return_value=False):
            self.assertEqual(autostart.status(), {"supported": False, "enabled": False, "current": False})
            self.assertIsNone(autostart.registered())
            with self.assertRaises(autostart.Unsupported):
                autostart.enable()
            with self.assertRaises(autostart.Unsupported):
                autostart.disable()

    def test_cli(self):
        def run(*argv):
            buf = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")  # cli.main 會 reconfigure stdout
            with redirect_stdout(buf):
                cli.main(["autostart", *argv])
            buf.seek(0)
            return buf.read()
        self.assertIn("關", run("status"))
        self.assertIn("已設定", run("on"))
        self.assertIn("開", run())
        self.assertIn("已取消", run("off"))
        self.assertIn("本來就沒有", run("off"))
        with mock.patch.object(autostart, "is_windows", return_value=False), self.assertRaises(SystemExit) as code:
            run("on")
        self.assertEqual(code.exception.code, 2)


class StopCommandTest(unittest.TestCase):
    def test_nothing_running(self):
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(cli, "running_server", return_value=None):
            cli.cmd_stop(SimpleNamespace())
        self.assertIn("沒有在跑", buf.getvalue())

    def refused(self, status: int) -> str:
        err = urllib.error.HTTPError("http://127.0.0.1:1/api/shutdown", status, "no", {}, io.BytesIO(b"{}"))
        responses = [io.BytesIO(b'{"token": "t"}'), err]

        def fake(req, timeout=None):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(cli, "running_server", return_value="http://127.0.0.1:1"), \
                mock.patch.object(cli.urllib.request, "urlopen", side_effect=fake), self.assertRaises(SystemExit):
            cli.cmd_stop(SimpleNamespace())
        return buf.getvalue()

    def test_refused_while_busy(self):
        self.assertIn("還有工作沒做完", self.refused(400))

    def test_other_refusals_show_the_status(self):
        out = self.refused(403)
        self.assertIn("HTTP 403", out)
        self.assertNotIn("還有工作沒做完", out)

    def test_running_server_ignores_a_bad_server_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = Path(tmp) / ".server.json"
            info.write_text('{"url": "file:///etc/passwd"}', encoding="utf-8")
            with mock.patch.object(config, "SERVER_INFO", info), \
                    mock.patch.object(cli.urllib.request, "urlopen", side_effect=AssertionError("network")):
                self.assertIsNone(cli.running_server())
                info.write_text("[1, 2]", encoding="utf-8")
                self.assertIsNone(cli.running_server())


class StopCommandLiveTest(ServeBase):
    def test_stop_command_shuts_the_server_down(self):
        thread = self.start()
        url = self.url
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(cli, "running_server", return_value=url):
            cli.cmd_stop(SimpleNamespace())
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertIn("已請服務停止", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
