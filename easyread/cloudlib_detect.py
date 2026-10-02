"""只检测有官方依据且确实存在的同步目录，不扫描磁盘猜测网盘位置。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def detect() -> list[dict]:
    found, seen = [], set()

    def add(kind, label, path):
        if not path:
            return
        p = Path(path).expanduser()
        try:
            p = p.resolve()
            if not p.is_dir() or str(p).casefold() in seen:
                return
        except OSError:
            return
        seen.add(str(p).casefold())
        found.append({"id": kind, "label": label, "root_path": str(p), "path": str(p / "EasyRead")})

    # OneDrive 给出的环境变量可以覆盖用户自选的位置；未设置时不猜用户目录。
    for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        add("onedrive", "OneDrive", os.environ.get(name))
    home = Path.home()
    if sys.platform == "darwin":
        cloud = home / "Library" / "CloudStorage"
        if cloud.is_dir():
            for p in sorted(cloud.glob("OneDrive*")):
                if p.name.startswith(("OneDrive-", "OneDrive - ")):
                    add("onedrive", "OneDrive", p)
    if sys.platform == "win32":
        # Apple: support.apple.com/guide/icloud-windows/icw0144825a5/icloud
        for name in ("iCloudDrive", "iCloud Drive"):
            add("icloud", "iCloud Drive", home / name)

    # Dropbox 官方支持 info.json，包含 personal/business 两种账户。
    # help.dropbox.com/installs/locate-dropbox-folder
    infos = [home / ".dropbox" / "info.json"]
    if sys.platform == "win32":
        infos = [Path(os.environ[n]) / "Dropbox" / "info.json"
                 for n in ("APPDATA", "LOCALAPPDATA") if os.environ.get(n)]
    for info in infos:
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
            for account in ("personal", "business"):
                entry = data.get(account, {})
                if isinstance(entry, dict):
                    add("dropbox", "Dropbox", entry.get("path"))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return found


def target_path(value: str | Path) -> Path:
    """已有库按原路径使用，普通同步文件夹只在 EasyRead 子目录里放论文。"""
    from .i18n import tr
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(tr("请选择文献库文件夹"))
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(tr("请输入完整的文件夹路径"))
    path = path.resolve()
    if path.name.casefold() == "easyread" or (path.exists() and not path.is_dir()):
        return path
    if path.is_dir():
        # 未完成迁移也必须交给 inspect 原地检查，不能套一层目录后绕过事务标记。
        marker = path / ".easyread-migration.json"
        if marker.exists() or marker.is_symlink():
            return path
        if any(not child.name.startswith(".") and (child / "item.json").is_file()
               for child in path.iterdir()):
            return path
    return path / "EasyRead"
