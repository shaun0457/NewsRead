"""Optional per-user Windows Task Scheduler integration for Wiki Lint."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from .. import config, prefs
from ..i18n import tr
from .store import settings


TASK_NAME = "PaperRead Wiki Lint"


def status() -> dict:
    value = settings().get("wiki_lint_schedule") or {}
    return {"enabled": bool(value.get("enabled")), "frequency": value.get("frequency", "weekly"),
            "time": value.get("time", "09:00"), "task_name": TASK_NAME,
            "available": os.name == "nt"}


def _ps(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def configure(enabled: bool, frequency: str = "weekly", at: str = "09:00") -> dict:
    if os.name != "nt":
        raise ValueError(tr("定期 Wiki Lint 目前只支援 Windows 工作排程器。"))
    if frequency not in ("weekly", "monthly"):
        raise ValueError(tr("請選擇每週或每月執行。"))
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", at or ""):
        raise ValueError(tr("請以 24 小時制輸入時間，例如 09:00。"))
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise ValueError(tr("找不到 Windows PowerShell，無法設定排程。"))
    if not enabled:
        script = (f"Unregister-ScheduledTask -TaskName {_ps(TASK_NAME)} -Confirm:$false "
                  "-ErrorAction SilentlyContinue; exit 0")
        completed = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                                   capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if completed.returncode:
            raise ValueError((completed.stderr or completed.stdout or tr("無法移除 Wiki Lint 排程。"))[-800:])
        prefs.save({"research": {"wiki_lint_schedule": {"enabled": False, "frequency": frequency, "time": at}}})
        return status()

    if getattr(sys, "frozen", False):
        executable, arguments, working = sys.executable, "wiki-lint --scheduled", str(config.HOME)
    else:
        executable, arguments, working = sys.executable, "-m easyread wiki-lint --scheduled", str(config.PACKAGE.parent)
    action = ("$action = New-ScheduledTaskAction -Execute " + _ps(executable) + " -Argument " + _ps(arguments) +
              " -WorkingDirectory " + _ps(working))
    if frequency == "weekly":
        trigger = "$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At " + _ps(at)
    else:
        trigger = "$trigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At " + _ps(at)
    user = "$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name"
    settings_command = ("$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable "
                        "-ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries "
                        "-DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew")
    register = ("$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited; "
                f"Register-ScheduledTask -TaskName {_ps(TASK_NAME)} -Action $action -Trigger $trigger "
                "-Settings $settings -Principal $principal -Description 'PaperRead local read-only Wiki Lint' "
                "-Force | Out-Null")
    script = "; ".join(("$ErrorActionPreference = 'Stop'", action, trigger, settings_command, user, register, "exit 0"))
    completed = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                               capture_output=True, text=True, timeout=45,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode:
        raise ValueError((completed.stderr or completed.stdout or tr("無法建立 Wiki Lint 排程。"))[-1000:])
    prefs.save({"research": {"wiki_lint_schedule": {"enabled": True, "frequency": frequency, "time": at}}})
    return status()
