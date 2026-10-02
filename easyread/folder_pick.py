"""浏览器版的“选文件夹”：网页拿不到本机路径，由后端弹出系统自带的选择窗口（桌面版用 Electron 自己的）。

返回选中的绝对路径；用户取消返回 ""；这台机器弹不出窗口（比如 Linux 没装 zenity）返回 None，页面改成让用户填路径。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from . import foreground

# Windows 用和“打开文件”同一种资源管理器窗口（IFileOpenDialog + FOS_PICKFOLDERS），不是老式的树状 FolderBrowserDialog。
# 只用 ASCII：PowerShell 5.1 会按 GBK 读脚本。标题、起始目录从环境变量传进去。
_PS = r"""
$code = @'
using System;
using System.Runtime.InteropServices;
public static class EasyReadPicker {
  [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialog {}
  [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileDialog {
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint c, IntPtr t); void SetFileTypeIndex(uint i); void GetFileTypeIndex(out uint i);
    void Advise(IntPtr e, out uint c); void Unadvise(uint c);
    void SetOptions(uint o); void GetOptions(out uint o);
    void SetDefaultFolder(IShellItem s); void SetFolder(IShellItem s);
    void GetFolder(out IShellItem s); void GetCurrentSelection(out IShellItem s);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string n); void GetFileName(out IntPtr n);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string t); void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void GetResult(out IShellItem s);
  }
  [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(IntPtr p, ref Guid b, ref Guid r, out IntPtr v); void GetParent(out IShellItem s);
    void GetDisplayName(uint t, [MarshalAs(UnmanagedType.LPWStr)] out string n);
  }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr bc, ref Guid riid, out IShellItem item);
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
  public static string Pick(string title, string start) {
    var d = (IFileDialog)new FileOpenDialog();
    uint o; d.GetOptions(out o); d.SetOptions(o | 0x20 | 0x40);  // FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM
    if (!string.IsNullOrEmpty(title)) d.SetTitle(title);
    if (!string.IsNullOrEmpty(start)) {
      try { var g = typeof(IShellItem).GUID; IShellItem s; SHCreateItemFromParsingName(start, IntPtr.Zero, ref g, out s); d.SetFolder(s); } catch {}
    }
    // Background process: without a topmost owner the dialog opens behind the browser.
    var owner = new System.Windows.Forms.Form();
    owner.TopMost = true; owner.ShowInTaskbar = false; owner.Opacity = 0;
    owner.FormBorderStyle = System.Windows.Forms.FormBorderStyle.None;
    owner.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen;
    owner.Size = new System.Drawing.Size(1, 1);
    owner.Show(); owner.Activate(); SetForegroundWindow(owner.Handle);
    try { if (d.Show(owner.Handle) != 0) return ""; } finally { owner.Close(); }
    IShellItem r; d.GetResult(out r); string p; r.GetDisplayName(0x80058000, out p);  // SIGDN_FILESYSPATH
    return p;
  }
}
'@
Add-Type -TypeDefinition $code -Language CSharp -ReferencedAssemblies System.Windows.Forms, System.Drawing
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::Out.Write([EasyReadPicker]::Pick($env:EASYREAD_PICK_TITLE, $env:EASYREAD_PICK_START))
"""


def pick(title: str, start: str = "") -> str | None:
    env = {**os.environ, "EASYREAD_PICK_TITLE": title, "EASYREAD_PICK_START": start or os.path.expanduser("~")}
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
    foreground.allow()
    try:
        r = subprocess.run(cmd, capture_output=True, env=env, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:  # 编译或 COM 出错：当成弹不出来，让页面改成填路径
        return "" if sys.platform != "win32" else None
    return r.stdout.decode("utf-8", "replace").strip().rstrip("/\\")
