from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote

from .. import config
from ..i18n import tr
# Vault 設定和安全寫檔搬到 easyread/vault.py（ticket 03），這裡轉出去讓研究工作區照常運作。
from ..vault import (EXPORT_FOLDERS, KINDS, atomic_replace, normalize_folders,  # noqa: F401
                     set_vault, settings, sha256_text, vault_path)


def state_dir() -> Path:
    path = config.HOME / ".research-os"
    path.mkdir(parents=True, exist_ok=True)
    return path


def index_folders() -> list[str]:
    # An old or partially saved preference may contain an empty list. Keep the
    # Research OS usable in that case and stay within its standard folders.
    return normalize_folders(settings().get("folders")) or normalize_folders(None)


def validate_vault_path(path: Path) -> Path:
    root = vault_path()
    if root is None:
        raise ValueError(tr("請先設定 Obsidian Vault 資料夾。"))
    # Test doubles and temporary folders can contain symlinks (especially on
    # macOS), and an as-yet-uncreated child can retain a different spelling
    # from its parent after ``Path.resolve()``.  realpath/commonpath compares
    # the canonical directory boundary while still rejecting paths that leave
    # the Vault.
    root_path = Path(root).expanduser()
    candidate_path = root_path / path
    root_real = os.path.realpath(os.fspath(root_path))
    candidate_real = os.path.realpath(os.fspath(candidate_path))
    try:
        inside = os.path.normcase(os.path.commonpath([root_real, candidate_real])) == os.path.normcase(root_real)
    except ValueError:  # Different Windows drives cannot share a Vault root.
        inside = False
    if not inside and not path.is_absolute() and ".." not in path.parts:
        # Some macOS temp directories keep /var and /private/var as distinct
        # spellings even after realpath().  A plain relative path without a
        # parent component is lexically contained and cannot escape the root.
        root_abs = os.path.normcase(os.path.abspath(os.fspath(root_path)))
        candidate_abs = os.path.normcase(os.path.abspath(os.fspath(candidate_path)))
        try:
            inside = os.path.commonpath([root_abs, candidate_abs]) == root_abs
        except ValueError:
            inside = False
    resolved = Path(candidate_real)
    if not inside or resolved.suffix.lower() != ".md":
        raise ValueError(tr("筆記路徑必須是所選 Vault 內的 Markdown 檔案。"))
    return resolved


def open_easyread(sha256: str, block: str = "") -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        return ""
    query = f"sha256={sha256}"
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", block or ""):
        query += "&block=" + quote(block)
    return "easyread://open?" + query


def markdown_path(root: Path, kind: str, title: str, identity: str) -> Path:
    folder = KINDS.get(kind)
    if not folder:
        raise ValueError(tr("不支援的研究筆記類型。"))
    safe = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "-", title).strip(" .-")[:100] or kind.title()
    if safe.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        safe = "_" + safe
    candidate = root / "Research" / folder / f"{safe}.md"
    if candidate.exists():
        candidate = root / "Research" / folder / f"{safe} ({identity[:8]}).md"
    return candidate
