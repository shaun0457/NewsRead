"""让后端打开的窗口（资源管理器、选文件夹）弹到最前面，而不是只在任务栏闪。

Windows 只允许“刚收到用户输入的进程”把窗口提到前台；后端是后台进程，打开的窗口会被拦下来只闪任务栏。
模拟按一下 Alt 让本进程拿到前台权限，再用 AllowSetForegroundWindow 把权限交给别的进程（PowerShell 选文件夹）；
资源管理器的窗口由已在运行的 explorer 打开，权限交不过去，只能等窗口出现后由本进程亲手提到前面。
"""
from __future__ import annotations

import os
import sys
import time


def _user32():
    import ctypes
    return ctypes.windll.user32


def allow() -> None:
    if sys.platform != "win32":
        return
    try:
        u = _user32()
        u.keybd_event(0x12, 0, 0, 0)  # VK_MENU 按下
        u.keybd_event(0x12, 0, 2, 0)  # KEYEVENTF_KEYUP
        u.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:  # noqa: BLE001  拿不到权限就退回老样子，窗口照样会打开
        pass


def _explorer_windows() -> dict[int, str]:
    import ctypes
    from ctypes import wintypes
    u, found = _user32(), {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if cls.value == "CabinetWClass" and u.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, title, 512)
            found[hwnd] = title.value
        return True

    u.EnumWindows(each, 0)
    return found


def open_folder(path: str) -> None:
    """用资源管理器打开文件夹，并把那个窗口提到最前面。"""
    try:
        before = _explorer_windows()
    except Exception:  # noqa: BLE001
        before = {}
    allow()
    os.startfile(path)  # noqa: S606
    name = os.path.basename(path.rstrip("\\/")) or path
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        time.sleep(0.15)
        try:
            now = _explorer_windows()
        except Exception:  # noqa: BLE001
            return
        hwnd = next((h for h in now if h not in before), None)
        if not hwnd and time.monotonic() > deadline - 2:  # 没有新窗口：资源管理器可能复用了已开着的同名窗口
            hwnd = next((h for h, t in now.items() if t == name), None)
        if hwnd:
            u = _user32()
            allow()
            if u.IsIconic(hwnd):
                u.ShowWindow(hwnd, 9)  # SW_RESTORE
            u.SetForegroundWindow(hwnd)
            return
