"""浏览器版的“选文件夹”：网页拿不到本机路径，由后端弹出系统自带的选择窗口（桌面版用 Electron 自己的）。

返回选中的绝对路径；用户取消返回 ""；这台机器弹不出窗口（比如 Linux 没装 zenity）返回 None，页面改成让用户填路径。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

# 只用 ASCII：PowerShell 5.1 会按 GBK 读脚本。标题文字从环境变量传进去。
_PS = r"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = $env:EASYREAD_PICK_TITLE
$d.ShowNewFolderButton = $true
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($d.SelectedPath) }
"""


def pick(title: str) -> str | None:
    env = {**os.environ, "EASYREAD_PICK_TITLE": title}
    if sys.platform == "win32":
        cmd = ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", _PS]
    elif sys.platform == "darwin":
        cmd = ["osascript", "-e", 'POSIX path of (choose folder with prompt (system attribute "EASYREAD_PICK_TITLE"))']
    elif shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", "--title", title]
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--getexistingdirectory", os.path.expanduser("~"), "--title", title]
    else:
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, env=env, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.decode("utf-8", "replace").strip().rstrip("/\\") if r.returncode == 0 else ""
