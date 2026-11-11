"""Obsidian Vault 的設定和安全寫檔，閱讀器的 Obsidian 匯出用（ticket 03 從研究模組抽出來）。

設定還是存在 prefs 的 research.vault / research.folders：鍵名不改，舊使用者的設定照樣能讀。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath

from . import config, prefs
from .i18n import tr


KINDS = {
    "paper": "Papers",
    "topic": "Topics",
    "concept": "Concepts",
    "question": "Questions",
    "hypothesis": "Hypotheses",
    "comparison": "05-跨論文比較",  # i18n-ok：Vault 裡的資料夾名稱，沿用舊名才找得到既有筆記
}

# New multi-file Obsidian export layout.  The legacy folders above remain
# readable for compatibility with existing Research OS notes.
EXPORT_FOLDERS = ("01-論文分析", "02-心智圖", "03-閱讀標註", "04-論文深度剖析", "05-跨論文比較", "06-論文摘要")  # i18n-ok：資料夾名稱


def settings() -> dict:
    return (prefs.load().get("research") or {}).copy()


def normalize_folders(value=None) -> list[str]:
    if value is None:
        value = ["Research", "Papers"]
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    if not isinstance(value, (list, tuple)):
        raise ValueError(tr("索引資料夾必須是 Vault 內的相對路徑清單。"))
    result = []
    for item in value:
        raw = str(item or "").strip().replace("\\", "/")
        if not raw:
            continue
        # Check before normalization: stripping a leading slash would otherwise
        # turn an absolute path into an apparently safe vault-relative path.
        raw_parts = raw.split("/")
        if raw.startswith("/") or any(part in (".", "..") or part.startswith(".") for part in raw_parts):
            raise ValueError(tr("索引資料夾必須位於 Vault 內，且不能包含隱藏資料夾。"))
        path = PurePosixPath(raw)
        if path.is_absolute() or PureWindowsPath(raw).drive:
            raise ValueError(tr("索引資料夾必須位於 Vault 內，且不能包含隱藏資料夾。"))
        normalized = path.as_posix()
        if normalized.casefold() not in {entry.casefold() for entry in result}:
            result.append(normalized)
    return result


def vault_path() -> Path | None:
    raw = settings().get("vault")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def set_vault(raw: str, folders=None) -> Path:
    if not raw.strip():
        raise ValueError(tr("請選擇 Obsidian Vault 資料夾。"))
    path = Path(raw).expanduser()
    selected_folders = normalize_folders(folders)
    path.mkdir(parents=True, exist_ok=True)
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError(tr("所選路徑不是資料夾。"))
    if path == config.HOME.resolve() or path == config.library_dir().resolve():
        raise ValueError(tr("請選擇 Obsidian Vault 資料夾，不可選 PaperRead 資料目錄。"))
    prefs.save({"research": {"vault": str(path), "folders": selected_folders}})
    for name in {*KINDS.values(), *EXPORT_FOLDERS}:
        (path / "Research" / name).mkdir(parents=True, exist_ok=True)
    return path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_replace(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
