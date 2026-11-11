"""同一個資料目錄只跑一個 NewsRead 服務（ticket 07）。

用作業系統的檔案鎖，鎖住服務整個生命週期。程序結束（包括當掉、被強制結束）時系統會自動放開，
不會留下過期的鎖；鎖檔本身留在磁碟上、不刪，避免「刪檔的同時另一個剛好開檔」的競爭。
os.open 開的檔案不會被子程序繼承，所以服務叫起來的 CLI（claude、codex）不會在服務結束後還佔著鎖。
"""
from __future__ import annotations

import errno
import os
from pathlib import Path

LOCK_NAME = ".server.lock"
URL_MAX = 200
# 「鎖被別人佔著」的錯誤碼；其他錯誤（檔案系統不支援鎖之類）照樣丟出，不誤報成已經在跑
_BUSY = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}


def server_url(info) -> str:
    """.server.json 記下的位址；不是 http://、太長或含控制字元就當作沒有。"""
    url = info.get("url") if isinstance(info, dict) else None
    ok = isinstance(url, str) and url.startswith("http://") and len(url) <= URL_MAX and url.isprintable()
    return url if ok else ""


class AlreadyRunning(Exception):
    """已經有一個服務在跑。url 是它記下的位址（讀不到就是空字串）。"""

    def __init__(self, url: str = ""):
        super().__init__(url)
        self.url = url


if os.name == "nt":
    import msvcrt

    def _lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # 鎖不到立刻丟 OSError，不等

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class InstanceLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """拿到鎖回 True；已經被別的服務拿走回 False。開不了鎖檔、檔案系統不支援鎖，照樣丟 OSError。"""
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock(fd)
        except BaseException as e:
            os.close(fd)
            if isinstance(e, OSError) and e.errno in _BUSY:
                return False
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock(fd)
        except OSError:
            pass  # 關檔時系統一樣會放開
        finally:
            os.close(fd)

    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()
