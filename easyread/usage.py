"""翻译花了多少：token 数，Claude Code 订阅还能看到 5 小时 / 7 天额度用了百分之几。

每次调用模型后，各引擎把返回里的用量交给 Meter；整篇翻译时 Meter 的累计写进 job.json 给页面显示。
input 是全部输入 token（含命中缓存的部分），cached 是其中命中缓存的，output 是输出。
"""
from __future__ import annotations

import threading


class Meter:
    """一次翻译任务的累计用量。并发翻译时多个线程一起往里加。"""

    def __init__(self, engine: str = ""):
        self._lock = threading.Lock()
        self.data: dict = {"engine": engine, "calls": 0, "input": 0, "cached": 0, "output": 0}

    def add(self, input: int = 0, cached: int = 0, output: int = 0, cost_usd: float | None = None, limits: dict | None = None):
        with self._lock:
            d = self.data
            d["calls"] += 1
            d["input"] += int(input or 0)
            d["cached"] += int(cached or 0)
            d["output"] += int(output or 0)
            if cost_usd is not None:
                d["cost_usd"] = round(d.get("cost_usd", 0) + float(cost_usd), 4)
            if limits:
                d["limits"] = limits  # 额度只看最新一次

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.data)


def merge(total: dict | None, run: dict) -> dict:
    """把这次的用量加进这篇论文的累计（job.json 的 usage_total）。"""
    out = dict(total or {})
    for k in ("calls", "input", "cached", "output"):
        out[k] = int(out.get(k, 0)) + int(run.get(k, 0))
    if "cost_usd" in run:
        out["cost_usd"] = round(out.get("cost_usd", 0) + run["cost_usd"], 4)
    for k in ("engine", "limits"):
        if run.get(k):
            out[k] = run[k]
    return out


# ---------- 各引擎返回的用量 ----------
def from_claude(result: dict, rate_event: dict | None) -> dict:
    """claude -p --output-format stream-json 的 result 行，和其中的 rate_limit_event。"""
    u = result.get("usage") or {}
    cached = int(u.get("cache_read_input_tokens") or 0)
    rec = {"input": int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) + cached,
           "cached": cached, "output": int(u.get("output_tokens") or 0)}
    windows = ((rate_event or {}).get("rate_limit_info") or {}).get("unifiedWindows") or {}
    if windows:  # 有额度信息就是订阅；订阅时 total_cost_usd 只是按官方价折算，不是真花的钱，不记
        rec["limits"] = {k: {"used": w.get("utilization"), "resets_at": w.get("resetsAt")}
                         for k, w in windows.items() if isinstance(w, dict)}
    elif result.get("total_cost_usd") is not None:
        rec["cost_usd"] = float(result["total_cost_usd"])
    return rec


def from_codex(event: dict) -> dict:
    """codex exec --json 的 turn.completed 事件。"""
    u = event.get("usage") or {}
    return {"input": int(u.get("input_tokens") or 0), "cached": int(u.get("cached_input_tokens") or 0),
            "output": int(u.get("output_tokens") or 0)}


def from_openai(res: dict) -> dict:
    """Chat Completions 或 Responses 返回的 usage（DeepSeek 的缓存命中数字段名不一样）。"""
    u = (res or {}).get("usage") or {}
    if "prompt_tokens" in u:  # Chat Completions
        details = u.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens") or u.get("prompt_cache_hit_tokens") or 0
        return {"input": int(u.get("prompt_tokens") or 0), "cached": int(cached), "output": int(u.get("completion_tokens") or 0)}
    details = u.get("input_tokens_details") or {}
    return {"input": int(u.get("input_tokens") or 0), "cached": int(details.get("cached_tokens") or 0),
            "output": int(u.get("output_tokens") or 0)}
