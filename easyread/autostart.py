"""Windows 登入後自動啟動常駐服務（ticket 07）。

在目前使用者的 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 寫一筆 NewsRead，
登入後在背景啟動 `easyread serve`（不開瀏覽器、關掉頁面也不退出）。只動目前使用者自己的設定，不需要系統管理員權限。
安裝版的視窗、系統匣和它自己的開機啟動在 ticket 66。
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "NewsRead"
ROOT = Path(__file__).resolve().parents[1]  # 原始碼模式：easyread 套件所在的目錄


class Unsupported(Exception):
    pass


def is_windows() -> bool:
    return sys.platform == "win32"


def _winreg():
    import winreg
    return winreg


def command() -> str:
    """寫進登錄的指令。登入時的工作目錄不固定，所以原始碼模式要自己把套件目錄放進 sys.path；
    用 -I（隔離模式）啟動，工作目錄和使用者 site 裡放的同名模組不會被載入。"""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):  # 打包的後端（scripts/backend_entry.py）
        return f'"{exe}" serve'
    pythonw = exe.with_name("pythonw.exe")  # 不跳出主控台視窗
    runner = pythonw if pythonw.is_file() else exe
    root = ROOT.as_posix()  # 只用正斜線：不必處理反斜線和引號的跳脫規則
    # 引號會弄壞指令；% 會被 Windows 當成環境變數展開成別的路徑
    if any(c in root for c in "'\"%") or any(c in str(runner) for c in "\"%"):
        raise ValueError("NewsRead folder path contains quotes or %; cannot register autostart")
    code = f"import sys; sys.path.insert(0, '{root}'); from easyread.cli import main; main(['serve'])"
    return f'"{runner}" -I -c "{code}"'


def registered() -> str | None:
    """目前登錄裡的指令；沒有登記就是 None。"""
    if not is_windows():
        return None
    w = _winreg()
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_QUERY_VALUE) as key:
            value, kind = w.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None
    return value if kind in (w.REG_SZ, w.REG_EXPAND_SZ) and isinstance(value, str) else None


def status() -> dict:
    if not is_windows():
        return {"supported": False, "enabled": False, "current": False}
    value = registered()
    try:
        current = value is not None and value == command()
    except ValueError:
        current = False
    return {"supported": True, "enabled": value is not None, "current": current}


def enable() -> str:
    if not is_windows():
        raise Unsupported("autostart is only supported on Windows")
    cmd = command()
    w = _winreg()
    with w.CreateKeyEx(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_SET_VALUE) as key:
        w.SetValueEx(key, VALUE_NAME, 0, w.REG_SZ, cmd)
    return cmd


def disable() -> bool:
    """移除登記；本來就沒有回 False。"""
    if not is_windows():
        raise Unsupported("autostart is only supported on Windows")
    w = _winreg()
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_SET_VALUE) as key:
            w.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True
