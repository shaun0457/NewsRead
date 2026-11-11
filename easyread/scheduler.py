"""所有定時工作共用的排程器（ticket 07）。

每個工作有固定間隔，記錄上次成功的時間（存在 schedule.json，重新啟動後接著用）。
電腦關機、休眠錯過的週期不逐一補跑：啟動後只要距離上次成功超過一個間隔，就補做一次。
同一個工作同時只會跑一份；失敗不記成成功，但也不每一輪都重試，至少隔 RETRY_AFTER 秒。
時鐘可以替換（測試用假時鐘，直接呼叫 run_pending）。
"""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .log import log
from .store import read_json, write_json_atomic

TICK = 30.0           # 背景執行緒多久檢查一次有沒有到期的工作
RETRY_AFTER = 300.0   # 失敗後最快多久再試（間隔比這短的照間隔）
STATE_MAX_BYTES = 256 * 1024  # 狀態檔超過這個大小就當作壞掉、不讀
MAX_ENTRIES = 200     # 狀態檔裡最多保留幾個工作的紀錄（含這次沒登記、之前留下的）
MAX_NAME = 100


class Clock:
    """真的時鐘：秒數（epoch）。測試換成可以手動往前撥的假時鐘。"""

    def now(self) -> float:
        return time.time()


@dataclass
class Job:
    name: str
    interval: float
    run: Callable[[], object]
    last_success: float | None = None
    last_attempt: float | None = None  # 這次啟動以來最近一次開始跑的時間（失敗後等 RETRY_AFTER 用）
    running: bool = False


def _valid_time(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class Scheduler:
    def __init__(self, state_path: Path | None, clock: Clock | None = None, tick: float = TICK,
                 retry_after: float = RETRY_AFTER):
        self.state_path = Path(state_path) if state_path else None  # None：只記在記憶體（暫用文獻庫、測試）
        self.clock = clock or Clock()
        self.tick, self.retry_after = tick, retry_after
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self._save_lock = threading.Lock()  # 拍快照到寫完檔整段一起：舊的快照不會蓋掉新的
        self.stopping = threading.Event()  # 跑很久的工作可以看它，提早收工
        self._thread: threading.Thread | None = None
        self._saved = self._load()

    # ---------- 狀態檔 ----------
    def _load(self) -> dict[str, float]:
        if not self.state_path:
            return {}
        try:
            if self.state_path.stat().st_size > STATE_MAX_BYTES:
                log.warning("排程狀態檔太大，不讀")
                return {}
            data = read_json(self.state_path, {})
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, RecursionError) as e:
            log.warning("讀不了排程狀態檔：%s", type(e).__name__)
            return {}
        entries = data.get("jobs") if isinstance(data, dict) else None
        out: dict[str, float] = {}
        for name, entry in (entries.items() if isinstance(entries, dict) else ()):
            if len(out) >= MAX_ENTRIES:
                break
            value = entry.get("last_success") if isinstance(entry, dict) else None
            if isinstance(name, str) and 0 < len(name) <= MAX_NAME and _valid_time(value):
                out[name] = float(value)
        return out

    def _save(self) -> None:
        if not self.state_path:
            return
        with self._save_lock:
            with self.lock:
                merged = dict(self._saved)
                merged.update({j.name: j.last_success for j in self.jobs.values() if j.last_success is not None})
                self._saved = merged
                entries = {name: {"last_success": t} for name, t in list(merged.items())[-MAX_ENTRIES:]}
            try:
                write_json_atomic(self.state_path, {"version": 1, "jobs": entries})
            except OSError as e:  # 存不了：這次啟動內照樣不會重複跑，下次啟動可能多補一次
                log.warning("存不了排程狀態檔：%s", type(e).__name__)

    # ---------- 工作 ----------
    def add(self, name: str, interval: float, run: Callable[[], object]) -> Job:
        if not isinstance(name, str) or not 0 < len(name) <= MAX_NAME:
            raise ValueError("job name must be 1-100 characters")
        if not _valid_time(interval) or interval <= 0:
            raise ValueError("job interval must be a positive number of seconds")
        with self.lock:
            if name in self.jobs:
                raise ValueError(f"job already added: {name}")
            job = Job(name, float(interval), run, last_success=self._saved.get(name))
            self.jobs[name] = job
        return job

    def _due(self, job: Job, now: float) -> bool:
        if job.running:
            return False
        if job.last_attempt is not None and (job.last_success is None or job.last_attempt > job.last_success):
            if now - job.last_attempt < min(self.retry_after, job.interval):  # 剛失敗：先別再試
                return False
        if job.last_success is None:
            return True
        elapsed = now - job.last_success
        return elapsed >= job.interval or elapsed < -job.interval  # 記錄的時間比現在晚一整個間隔以上：時鐘曾經錯過，重新開始

    def due(self) -> list[str]:
        now = self.clock.now()
        with self.lock:
            return [j.name for j in self.jobs.values() if self._due(j, now)]

    def run_pending(self) -> list[str]:
        """把現在到期的工作各跑一次（依登記順序），回傳成功的工作名稱。"""
        done: list[str] = []
        for name in self.due():
            if self.stopping.is_set():
                break
            with self.lock:
                job = self.jobs[name]
                started = self.clock.now()
                if not self._due(job, started):  # 另一個執行緒剛搶先跑了
                    continue
                job.running = True
                job.last_attempt = started
            ok = False
            try:
                job.run()
                ok = True
            except (Exception, SystemExit) as e:  # noqa: BLE001 — 一個工作壞掉（含誤叫 sys.exit）不能拖垮其他工作
                log.warning("排程工作失敗 %s：%s", name, type(e).__name__)
            finally:
                with self.lock:
                    job.running = False
                    if ok:
                        job.last_success = started  # 用開始時間：間隔不會因為跑得久而一直往後漂
            if ok:
                done.append(name)
                self._save()
        return done

    # ---------- 背景執行緒 ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self.stopping.is_set():
            try:
                self.run_pending()
            except (Exception, SystemExit) as e:  # noqa: BLE001 — 執行緒不能無聲地死掉
                log.warning("排程器出錯：%s", type(e).__name__)
            self.stopping.wait(self.tick)

    def stop(self, timeout: float) -> bool:
        """請背景執行緒停下，最多等 timeout 秒。回傳是否真的停了（工作卡住時是 False，執行緒是 daemon，不會擋住程序結束）。"""
        self.stopping.set()
        thread = self._thread
        if thread is None:
            return True
        thread.join(max(0.0, timeout))
        return not thread.is_alive()
