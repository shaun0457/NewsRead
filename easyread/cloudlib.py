"""文献库位置切换：只复制，核对完成才更新配置；旧库和目标已有文件都保留。"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

from . import config
from .cloudlib_detect import detect, target_path  # noqa: F401
from .i18n import tr


def _linked(path: Path) -> bool:
    info = path.lstat()
    # 云端占位文件也带 REPARSE_POINT，不能一律拒绝；只拒绝符号链接和目录联接。
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in (0xA0000003, 0xA000000C)


def _manifest(root: Path) -> dict[str, tuple[int, int]]:
    """逐级检查再遍历，不能让链接把范围带出论文目录。"""
    files = {}
    if _linked(root):
        raise ValueError(tr("文献库中有符号链接或目录联接，请改用普通文件夹：{path}", path=str(root)))
    if root.is_file():
        s = root.stat()
        return {".": (s.st_size, s.st_mtime_ns)}

    def walk(folder):
        if _linked(folder):
            raise ValueError(tr("文献库中有符号链接或目录联接，请改用普通文件夹：{path}", path=str(folder)))
        for p in folder.iterdir():
            if _linked(p):
                raise ValueError(tr("文献库中有符号链接或目录联接，请改用普通文件夹：{path}", path=str(p)))
            if p.is_dir():
                walk(p)
            elif p.is_file():
                s = p.stat()
                files[p.relative_to(root).as_posix()] = (s.st_size, s.st_mtime_ns)
            else:
                raise ValueError(tr("文献库中有无法复制的特殊文件：{path}", path=str(p)))
    walk(root)
    return files


def _papers(root: Path) -> list[Path]:
    if not root.exists():
        return []
    found = []
    for p in sorted(root.iterdir()):
        if p.name.startswith("."):
            continue
        if _linked(p):
            raise ValueError(tr("文献库中有符号链接或目录联接，请改用普通文件夹：{path}", path=str(p)))
        if p.is_dir() and (p / "item.json").is_file():
            found.append(p)
    return found


def inspect(path: str | Path) -> dict:
    root = target_path(path)
    if root.exists() and not root.is_dir():
        return {"path": str(root), "exists": True, "writable": False, "papers": 0, "bytes": 0}
    papers = _papers(root)
    size = sum(sum(n for n, _ in _manifest(p).values()) for p in papers)
    if (root / ".trash").exists():
        size += sum(n for n, _ in _manifest(root / ".trash").values())
    parent = root
    while not parent.exists():
        parent = parent.parent
    # 实际创建临时文件检测 ACL；不创建用户选择的目标目录。
    try:
        with tempfile.TemporaryFile(dir=parent):
            pass
        writable = True
    except OSError:
        writable = False
    return {"path": str(root), "exists": root.exists(), "writable": writable, "papers": len(papers), "bytes": size}


def _sha(paper: Path) -> str:
    pdf = paper / "source.pdf"
    if not pdf.exists():
        return ""
    if _linked(pdf):
        raise ValueError(tr("文献库中有符号链接或目录联接，请改用普通文件夹：{path}", path=str(pdf)))
    digest = hashlib.sha256()
    with pdf.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_verified(src: Path, dst: Path):
    if src.is_file():
        if _linked(src):
            raise ValueError(tr("文献库中有符号链接或目录联接，请改用普通文件夹：{path}", path=str(src)))
        before = src.stat()
        shutil.copy2(src, dst)
        after = src.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or dst.stat().st_size != before.st_size:
            raise ValueError(tr("复制核对失败，文献库位置没有更改"))
        return {".": (before.st_size, before.st_mtime_ns)}
    before = _manifest(src)
    # 先建目录、逐文件复制，禁止 copytree 默认跟随链接。
    dst.mkdir()
    for rel in before:
        source, target = src / rel, dst / rel
        if _linked(source) or not source.resolve().is_relative_to(src.resolve()):
            raise ValueError(tr("复制过程中源文件发生变化，请重试"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    after, copied = _manifest(src), _manifest(dst)
    if before != after or {p: n for p, (n, _) in before.items()} != {p: n for p, (n, _) in copied.items()}:
        raise ValueError(tr("复制核对失败，文献库位置没有更改"))
    return before


def move(src: str | Path, dst: str | Path, mode: str) -> dict:
    if config.temp_library():
        raise ValueError(tr("临时文献库不能更改位置"))
    src, dst = Path(src).resolve(), target_path(dst)
    if mode not in ("copy", "use", "merge"):
        raise ValueError(tr("请选择复制、使用或合并文献库"))
    if src == dst or src.is_relative_to(dst) or dst.is_relative_to(src):
        raise ValueError(tr("新旧文献库不能相同，也不能互相包含"))
    state = inspect(dst)
    if not state["writable"]:
        raise ValueError(tr("目标文件夹不可写"))
    if mode == "copy" and state["papers"]:
        raise ValueError(tr("目标已有论文，请选择使用或合并文献库"))
    if mode in ("use", "merge") and not state["papers"]:
        raise ValueError(tr("目标还没有论文，请选择复制文献库"))
    result = {"ok": True, "path": str(dst), "old_path": str(src), "copied": 0, "skipped": [],
              "restart_required": True, "message": tr("文献库位置已更改，需要重启 EasyRead 才能生效")}
    if mode == "use":
        config.save({"library_dir": str(dst)})
        return result
    papers = _papers(src)
    digests = {_sha(p) for p in _papers(dst)} - {""} if mode == "merge" else set()
    entries = []
    for p in papers:
        if (dst / p.name).exists():
            if mode == "copy":
                raise ValueError(tr("目标中已有同名文件或文件夹，不会覆盖：{name}", name=p.name))
            result["skipped"].append({"id": p.name, "reason": tr("目标已有同名文件夹，已保留目标内容")})
            continue
        digest = _sha(p) if mode == "merge" else ""
        if digest and digest in digests:
            result["skipped"].append({"id": p.name, "reason": tr("目标已有相同 PDF，已跳过")})
            continue
        if digest:
            digests.add(digest)
        entries.append((p, Path(p.name)))
    if (src / ".trash").exists():
        if _linked(src / ".trash"):
            raise ValueError(tr("文献库中有符号链接或目录联接，请改用普通文件夹：{path}", path=str(src / ".trash")))
        trash_entries = list((src / ".trash").iterdir()) if (dst / ".trash").exists() else [src / ".trash"]
        for p in trash_entries:
            target = Path(".trash") if p == src / ".trash" else Path(".trash") / p.name
            if (dst / target).exists():
                if mode == "copy":
                    raise ValueError(tr("目标中已有同名文件或文件夹，不会覆盖：{name}", name=str(target)))
                result["skipped"].append({"id": str(target), "reason": tr("目标已有同名文件夹，已保留目标内容")})
            else:
                entries.append((p, target))
    dst.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".easyread-copy-", dir=dst))
    try:
        snapshots = []
        for i, (source, _) in enumerate(entries):
            snapshots.append(_copy_verified(source, staging / str(i)))
        if any(_manifest(source) != snapshot for (source, _), snapshot in zip(entries, snapshots)):
            raise ValueError(tr("复制过程中源文件发生变化，请重试"))
        # 此时尚未改配置；目标同名项即使在复制期间出现，也不能覆盖。
        for i, (_, relative) in enumerate(entries):
            target = dst / relative
            if not target.parent.resolve().is_relative_to(dst):
                raise ValueError(tr("复制过程中目标文件夹发生变化，请重试"))
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                raise ValueError(tr("目标中已有同名文件或文件夹，不会覆盖：{name}", name=str(relative)))
            # mkdir 是跨平台排他占位；之后逐个移动，只写入自己刚建的目录。
            staged = staging / str(i)
            if staged.is_dir():
                target.mkdir(exist_ok=False)
                for child in staged.iterdir():
                    child.rename(target / child.name)
            else:
                with target.open("xb") as output, staged.open("rb") as source:
                    shutil.copyfileobj(source, output)
                if target.stat().st_size != staged.stat().st_size:
                    raise ValueError(tr("复制核对失败，文献库位置没有更改"))
            if relative.parts[0] != ".trash":
                result["copied"] += 1
        config.save({"library_dir": str(dst)})
        return result
    finally:
        # 只清理本次在目标下生成的随机 staging；绝不清理源库或目标已有目录。
        if staging.parent == dst and staging.resolve().parent == dst and staging.name.startswith(".easyread-copy-") and not _linked(staging):
            shutil.rmtree(staging)
