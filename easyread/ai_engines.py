"""Engines & Usage：NewsRead 其他模組呼叫 AI 的唯一入口（ticket 67）。

- 偵測：本機訂閱（Claude Code、Codex CLI、Antigravity CLI）和本地模型（Ollama），沿用 detect.py 的背景偵測和快取。
- 自帶 key（BYOK）：Anthropic（官方 anthropic SDK）和 OpenAI 相容服務（填 base URL）。key 只存在本機的 ai.json，
  API 回應只露末四碼，log 不寫 key。
- 每種工作（TASKS）各自指定主要和備用的引擎與模型；實際用的引擎和模型記進 prompt 版本。
- 每次呼叫都記用量到帳本（ai_usage）：API 記費用，訂閱不折算金額，Claude Code 有回報時記額度和重置時間。
- 錯誤只帶錯誤代碼和固定訊息（AIError）；上游原文過 fetch.scrub 才留在例外上，不寫進 log。
- 額度保護（ticket 68，quota_guard.py）：呼叫端一定要標 trigger（background / manual）。背景工作預設不用訂閱 CLI、
  Claude Code 5 小時額度超過門檻時暫停或改用 API key、API 每月上限到了就停；手動的照跑，回傳 quota_notice 提醒。
"""
from __future__ import annotations

import importlib.util
import math
import re
import secrets
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import config, detect, engines, fetch, ledger, quota_guard, usage
from .i18n import tr
from .log import log
from .store import read_json, write_json_atomic

PREFIX = "/api/ai"
FILE_NAME = "ai.json"
TASKS = ("triage", "translate", "draft", "thesis_change", "ask")
CLI = ("claude", "codex", "antigravity")
NO_TOOLS_UNSUPPORTED = ("codex", "antigravity")  # 關不掉工具的 CLI：prompt 有外部內容的工作不用它們
NO_TOOLS_TASKS = frozenset({"triage"})  # prompt 一定有外部內容（文章全文）的工作：引擎不能有工具
ENGINES = CLI + ("ollama", "anthropic", "openai")
KIND = {"claude": "subscription", "codex": "subscription", "antigravity": "subscription", "ollama": "local",
        "anthropic": "api", "openai": "api"}
ENGINE_LABELS = {"claude": "Claude Code", "codex": "Codex CLI", "antigravity": "Antigravity CLI", "ollama": "Ollama",
                 "anthropic": "Anthropic API", "openai": "OpenAI 相容"}  # i18n-ok 產品名，畫面另外翻
CLAUDE_MODELS = {"claude-haiku-5-5": "Haiku", "claude-sonnet-5-5": "Sonnet", "claude-opus-5-5": "Opus"}
DEFAULT_MODEL = {"triage": "claude-haiku-5-5", "translate": "claude-sonnet-5-5", "draft": "claude-opus-5-5",
                 "thesis_change": "claude-sonnet-5-5", "ask": "claude-sonnet-5-5"}
AUTO_ORDER = ("claude", "codex", "antigravity", "anthropic", "openai", "ollama")

# 每百萬 token 的美元價格：(輸入, 輸出, 讀快取)。讀快取的價格不確定時是 None，這時有命中快取就不算費用。
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, None),
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-opus-5": (5.0, 25.0, None),
    "claude-sonnet-5": (2.0, 10.0, None),
    "claude-haiku-4-5": (1.0, 5.0, None),
}
PRICE_PROMPT_LIMIT = {"claude-haiku-5-5": 100_000}  # 這個價格只適用到這麼長的 prompt；更長的不算費用

MAX_ATTEMPTS = 4          # 同一個引擎遇到限流最多試幾次（含第一次）
BACKOFF_BASE = 2.0        # 第 n 次重試前等 BACKOFF_BASE * 2^n 秒
BACKOFF_MAX = 30.0        # 每次最多等這麼久（上游的 Retry-After 也截在這裡）
CALL_TIMEOUT = 600        # API 一次呼叫最多等幾秒
CHECK_TIMEOUT = 20        # 「儲存並測試」最多等幾秒
ANTHROPIC_MAX_TOKENS = 16000
MAX_OPENAI = 10
MAX_KEY = 300
MAX_URL = 300
MAX_NAME = 40
MAX_MODEL = 100
MAX_BODY = 16 * 1024
OLLAMA_BASE = "http://127.0.0.1:11434/v1"
TAIPEI = timezone(timedelta(hours=8))  # 台灣沒有日光節約；Windows 的 zoneinfo 沒有內建時區資料
LOOPBACK = ("localhost", "127.0.0.1", "::1")
CODES = ("NO_AI", "PAUSED", "AUTH_INVALID", "RATE_LIMITED", "UPSTREAM_ERROR", "NETWORK", "TIMEOUT", "BAD_REQUEST",
         "ENGINE_MISSING", "OUTPUT_TRUNCATED", "ENGINE_ERROR", "CANCELLED", "QUOTA_PAUSED", "API_CAP", "BACKGROUND_NO_API")
TRIGGERS = ("background", "manual")  # 背景工作（排程自己跑的）/ 使用者手動按的


def message(code: str) -> str:
    """錯誤代碼對應的固定訊息。不帶上游原文。"""
    return {
        "NO_AI": tr("沒有可以用的 AI。"),
        "PAUSED": tr("這個工作暫停了：key 失效，也沒有可以用的備用引擎。"),
        "AUTH_INVALID": tr("key 無效或登入過期了。"),
        "RATE_LIMITED": tr("被限流了，重試幾次還是不行，請稍後再試。"),
        "UPSTREAM_ERROR": tr("AI 服務暫時出錯。"),
        "NETWORK": tr("連不上 AI 服務。"),
        "TIMEOUT": tr("AI 太久沒有回應。"),
        "BAD_REQUEST": tr("AI 服務不接受這個請求（模型名稱或權限不對）。"),
        "ENGINE_MISSING": tr("找不到這個引擎。"),
        "OUTPUT_TRUNCATED": tr("模型的回答太長，被截斷了。"),
        "CANCELLED": tr("已取消。"),
        "QUOTA_PAUSED": tr("訂閱額度超過你設的門檻，背景工作暫停到額度重置。"),
        "API_CAP": tr("API 這個月的花費到了上限。"),
        "BACKGROUND_NO_API": tr("背景工作不用訂閱，也沒有可以用的 API key 或本機模型。"),
    }.get(code, tr("AI 引擎出錯。"))


class AIError(RuntimeError):
    """code 是 CODES 之一；detail 是過了 scrubber 的上游原文，只給除錯用，不寫 log、不回給畫面。"""

    def __init__(self, code: str, detail="", retry_after: float | None = None, status: int | None = None,
                 usage: dict | None = None):
        self.code = code if code in CODES else "ENGINE_ERROR"
        self.detail = fetch.scrub(detail)[:300] if detail else ""
        self.retry_after = retry_after
        self.status = status
        self.usage = usage  # 失敗了但已經用掉 token 的呼叫（例如回答被截斷），照樣記用量
        super().__init__(self.code)

    def __str__(self) -> str:
        return f"{self.code}: {message(self.code)}"


class InputError(ValueError):
    def __init__(self, msg: str, field: str):
        super().__init__(msg)
        self.field = field


class NotFound(LookupError):
    pass


# ---------- 本機設定檔 ai.json ----------
def _now() -> str:
    return ledger.iso(datetime.now(timezone.utc))


def _empty() -> dict:
    return {"tasks": {t: {"primary": None, "fallback": None} for t in TASKS}, "anthropic": None, "openai": [], "engines": {},
            "guard": quota_guard.defaults()}


def _clean_choice(c) -> dict | None:
    if not isinstance(c, dict) or c.get("engine") not in ENGINES:
        return None
    model, entry = c.get("model"), c.get("entry")
    return {"engine": c["engine"], "model": model[:MAX_MODEL] if isinstance(model, str) else "",
            "entry": entry if isinstance(entry, str) else ""}


def _clean(raw) -> dict:
    """手改過、壞掉或舊版的 ai.json 都整理成固定的樣子。"""
    out = _empty()
    if not isinstance(raw, dict):
        return out
    for t in TASKS:
        cur = (raw.get("tasks") or {}).get(t) if isinstance(raw.get("tasks"), dict) else None
        if isinstance(cur, dict):
            out["tasks"][t] = {"primary": _clean_choice(cur.get("primary")), "fallback": _clean_choice(cur.get("fallback"))}
    a = raw.get("anthropic")
    if isinstance(a, dict) and isinstance(a.get("key"), str) and a["key"]:
        out["anthropic"] = {k: a.get(k) for k in ("key", "status", "tested_at", "code")}
    for o in (raw.get("openai") or [])[:MAX_OPENAI] if isinstance(raw.get("openai"), list) else []:
        if isinstance(o, dict) and isinstance(o.get("id"), str) and isinstance(o.get("base_url"), str):
            out["openai"].append({k: o.get(k) for k in ("id", "name", "base_url", "api", "model", "key", "status", "tested_at", "code")})
    if isinstance(raw.get("engines"), dict):
        out["engines"] = {e: dict(v) for e, v in raw["engines"].items() if e in CLI and isinstance(v, dict)}
    out["guard"] = quota_guard.clean(raw.get("guard"))
    return out


class Settings:
    """ai.json：選了哪些引擎、key 和它們的狀態。只存在這台電腦，不跟 config.json 放一起（/api/config 會整份回給頁面）。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            return _clean(read_json(self.path, {}))

    def update(self, fn) -> dict:
        with self._lock:
            data = self.load()
            fn(data)
            # 0600：只有自己能讀（Windows 沿用使用者資料夾的權限）。暫存檔建立時就是這個權限
            write_json_atomic(self.path, data, mode=0o600)
            return data


def last4(key: str | None) -> str:
    """畫面只顯示末四碼；太短的 key 連末四碼都不顯示（不然等於整把露出來）。"""
    return key[-4:] if isinstance(key, str) and len(key) >= 12 else ""


# ---------- 價格與錯誤分類 ----------
def price(model: str, fresh: int, cache_read: int, cache_write: int, output: int) -> float | None:
    """API 的費用（美元）。不認得的模型、價格不確定的情況回 None（費用不明），不亂估。"""
    p = PRICES.get(model)
    if not p or cache_write or (cache_read and p[2] is None):
        return None
    if fresh + cache_read > PRICE_PROMPT_LIMIT.get(model, math.inf):
        return None
    return round((fresh * p[0] + cache_read * (p[2] or 0) + output * p[1]) / 1_000_000, 6)


def _retry_after(value) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return min(n, BACKOFF_MAX) if math.isfinite(n) and n >= 0 else None


def from_status(status, detail="", retry_after=None) -> AIError:
    status = status if isinstance(status, int) else None
    if status == 401:
        return AIError("AUTH_INVALID", detail, status=status)
    if status == 429:
        return AIError("RATE_LIMITED", detail, _retry_after(retry_after), status=status)
    if status is not None and status >= 500:
        return AIError("UPSTREAM_ERROR", detail, status=status)
    if status is not None and 400 <= status < 500:
        return AIError("BAD_REQUEST", detail, status=status)
    return AIError("ENGINE_ERROR", detail, status=status)


def from_sdk(e: BaseException) -> AIError:
    """anthropic SDK 的例外 → AIError。用類別名稱和 status_code 判斷，不綁特定 SDK 版本。"""
    names = {c.__name__ for c in type(e).__mro__}
    if "APITimeoutError" in names:
        return AIError("TIMEOUT", str(e))
    if "APIConnectionError" in names:
        return AIError("NETWORK", str(e))
    headers = getattr(getattr(e, "response", None), "headers", None) or {}
    return from_status(getattr(e, "status_code", None), str(e), headers.get("retry-after"))


# 只認明確的片語：一般錯誤訊息裡的 "backlog"、"401 tokens"、"cli.js:401" 不能讓整個引擎被標成登入失效
_AUTH_TEXT = re.compile(r"not logged in|please run /login|\b401 unauthori[sz]ed|\bunauthori[sz]ed\b|authentication_error|"
                        r"invalid (x-)?api[ -]key|oauth token (has )?expired|login (has )?expired", re.I)
_RATE_TEXT = re.compile(r"rate.?limit|usage limit|too many requests|\b429\b|overloaded", re.I)


def from_cli(e: engines.EngineError, timeout: int) -> AIError:
    text = str(e)
    if text == tr("超过 {n} 秒没有结果", n=timeout):
        return AIError("TIMEOUT")
    if _RATE_TEXT.search(text):
        return AIError("RATE_LIMITED", text)
    if _AUTH_TEXT.search(text):
        return AIError("AUTH_INVALID", text)
    return AIError("ENGINE_ERROR", text)


def from_openai(e: engines.EngineError) -> AIError:
    status = getattr(e, "status", None)
    if status is None:
        if getattr(e, "code", "") == "OUTPUT_TRUNCATED":
            return AIError("OUTPUT_TRUNCATED")
        return AIError("NETWORK" if getattr(e, "network", False) else "ENGINE_ERROR", str(e))
    return from_status(status, str(e), getattr(e, "retry_after", None))


# ---------- 真的引擎（測試換成假的） ----------
def _spent(meter: usage.Meter) -> dict | None:
    """失敗的呼叫如果已經回報過 token，交給 Engines 記用量（費用不明）。"""
    snap = meter.snapshot()
    if not snap.get("calls"):
        return None
    return {"input": int(snap.get("input", 0)), "cached": int(snap.get("cached", 0)), "output": int(snap.get("output", 0)),
            "cost_usd": snap.get("cost_usd"), "quota": snap.get("limits")}


def _result(text: str, snap: dict, cost, billing: str) -> dict:
    return {"text": text, "input": int(snap.get("input", 0)), "cached": int(snap.get("cached", 0)),
            "output": int(snap.get("output", 0)), "cost_usd": cost, "quota": snap.get("limits"), "billing": billing}


class CliAdapter:
    """本機的 Claude Code / Codex CLI / Antigravity CLI，用使用者自己的登入。"""

    def __init__(self, engine: str):
        self.engine = engine

    def call(self, spec: dict, prompt: str, cancel=None, json_mode: bool = False) -> dict:
        cfg = config.load()
        c = {**cfg[self.engine], "lean": True}
        if spec.get("tools") is False:
            if self.engine != "claude":  # Engines.run 已經跳過；這裡再擋一次，免得別的呼叫端漏掉
                raise AIError("ENGINE_MISSING", "tools cannot be disabled")
            c["no_tools"] = True
        if spec.get("model"):
            c["model"] = spec["model"]
        finder = {"claude": engines.claude_path, "codex": engines.codex_path, "antigravity": engines.antigravity_path}[self.engine]
        if not finder(c):
            raise AIError("ENGINE_MISSING")
        meter = usage.Meter(self.engine)
        timeout = int(c.get("timeout") or 1200)
        # ignore_cleanup_errors：取消時 CLI 的子行程可能還佔著資料夾，清不掉不能蓋掉原本的錯誤代碼
        with tempfile.TemporaryDirectory(prefix="newsread-ai-", ignore_cleanup_errors=True) as cwd:
            try:
                if self.engine == "claude":
                    text = engines.run_claude(c, prompt, Path(cwd), cancel, meter)
                elif self.engine == "codex":
                    text = engines.run_codex(c, prompt, Path(cwd), [], cancel, meter)
                else:
                    text = engines.run_antigravity(c, prompt, Path(cwd), cancel, meter)
            except engines.Cancelled:
                raise AIError("CANCELLED", usage=_spent(meter)) from None
            except engines.EngineError as e:
                err = from_cli(e, timeout)
                err.usage = _spent(meter)
                raise err from None
            except Exception as e:  # noqa: BLE001 例如偵測之後執行檔被移除（FileNotFoundError）
                raise AIError("ENGINE_ERROR", type(e).__name__, usage=_spent(meter)) from None
        snap = meter.snapshot()
        # Claude Code 有回報額度就是訂閱，訂閱時的金額只是折算、不記；沒有額度、有金額時是用 API 計費
        billing = "subscription" if snap.get("limits") or "cost_usd" not in snap else "api"
        return _result(text, snap, snap.get("cost_usd") if billing == "api" else None, billing)


class OpenAIAdapter:
    """OpenAI 相容接口（含本機的 Ollama）。重試由 Engines 管，這裡一次只發一個請求。"""

    def __init__(self, local: bool = False):
        self.local = local

    def _options(self, spec: dict, timeout: int) -> dict:
        if self.local:
            return {"preset": "ollama", "base_url": OLLAMA_BASE, "api": "chat", "model": spec["model"], "timeout": timeout,
                    "request_attempts": 1}
        return {"base_url": spec["base_url"], "api": spec.get("api") or "chat", "api_key": spec.get("key") or "",
                "model": spec["model"], "timeout": timeout, "request_attempts": 1}

    def call(self, spec: dict, prompt: str, cancel=None, json_mode: bool = False) -> dict:
        from . import openai_api
        meter = usage.Meter("ollama" if self.local else "openai")
        try:
            text = openai_api.complete(self._options(spec, CALL_TIMEOUT), prompt, [], cancel, meter, json_mode)
        except engines.Cancelled:
            raise AIError("CANCELLED", usage=_spent(meter)) from None
        except engines.EngineError as e:
            err = from_openai(e)
            err.usage = _spent(meter)
            raise err from None
        except Exception as e:  # noqa: BLE001 例如地址填錯、回了 HTML（JSONDecodeError）或連線讀到一半斷掉
            raise AIError("ENGINE_ERROR", type(e).__name__, usage=_spent(meter)) from None
        snap = meter.snapshot()
        if self.local:
            return _result(text, snap, 0.0, "local")
        return _result(text, snap, snap.get("cost_usd"), "api")  # 服務商沒回報費用就是不明

    def check(self, spec: dict) -> None:
        from . import openai_api
        try:
            openai_api.models(self._options(spec, CHECK_TIMEOUT))
        except engines.EngineError as e:
            raise from_openai(e) from None
        except Exception as e:  # noqa: BLE001
            raise AIError("ENGINE_ERROR", type(e).__name__) from None


def _anthropic_client(key: str, timeout: float):
    try:
        import anthropic
    except ImportError:
        raise AIError("ENGINE_MISSING") from None
    # max_retries=0：限流退避由 Engines 統一處理，不讓 SDK 自己再重試
    return anthropic.Anthropic(api_key=key, max_retries=0, timeout=timeout)


class AnthropicAdapter:
    """Anthropic API（官方 SDK）。"""

    def __init__(self, client_factory=None):
        self.client_factory = client_factory or _anthropic_client

    def call(self, spec: dict, prompt: str, cancel=None, json_mode: bool = False) -> dict:
        client = self.client_factory(spec["key"], CALL_TIMEOUT)
        try:
            with client.messages.stream(model=spec["model"], max_tokens=ANTHROPIC_MAX_TOKENS,
                                        messages=[{"role": "user", "content": prompt}]) as stream:
                for _ in stream.text_stream:
                    if cancel is not None and cancel.is_set():
                        raise AIError("CANCELLED")
                msg = stream.get_final_message()
        except AIError:
            raise
        except Exception as e:  # noqa: BLE001 SDK 的例外都在這裡轉成錯誤代碼
            raise from_sdk(e) from None
        finally:
            _close(client)
        text = "".join(getattr(b, "text", "") for b in (getattr(msg, "content", None) or []) if getattr(b, "type", "") == "text")
        u = getattr(msg, "usage", None)
        fresh = int(getattr(u, "input_tokens", 0) or 0)
        read = int(getattr(u, "cache_read_input_tokens", 0) or 0)
        write = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        out = int(getattr(u, "output_tokens", 0) or 0)
        res = {"text": text, "input": fresh + read + write, "cached": read, "output": out,
               "cost_usd": price(spec["model"], fresh, read, write, out), "quota": None, "billing": "api"}
        if getattr(msg, "stop_reason", None) == "max_tokens":
            raise AIError("OUTPUT_TRUNCATED", usage=res)  # 截斷了也已經付了錢
        return res

    def check(self, spec: dict) -> None:
        """列模型清單不花 token，用它確認 key 能用。"""
        client = self.client_factory(spec["key"], CHECK_TIMEOUT)
        try:
            client.models.list(limit=1)
        except Exception as e:  # noqa: BLE001
            raise from_sdk(e) from None
        finally:
            _close(client)


def _close(client) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001 關連線失敗不影響結果
            pass


def default_adapters() -> dict:
    return {"claude": CliAdapter("claude"), "codex": CliAdapter("codex"), "antigravity": CliAdapter("antigravity"),
            "ollama": OpenAIAdapter(local=True), "anthropic": AnthropicAdapter(), "openai": OpenAIAdapter()}


def _wait(seconds: float, cancel) -> None:
    if cancel is None:
        time.sleep(seconds)
    elif cancel.wait(seconds):
        raise AIError("CANCELLED")


def anthropic_installed() -> bool:
    return importlib.util.find_spec("anthropic") is not None


# ---------- 選引擎、呼叫、記用量 ----------
class Engines:
    def __init__(self, settings: Settings, index: ledger.Index | None, *, adapters: dict | None = None,
                 detector=None, wait=_wait, has_sdk=anthropic_installed, quota=usage.latest, now=time.time,
                 notifier=quota_guard.notify):
        self.settings, self.index = settings, index
        self.adapters = adapters or default_adapters()
        self.detector = detector or (lambda fresh=False: detect.detect(config.load(), fresh=fresh))
        self.wait = wait
        self.has_sdk = has_sdk
        self.quota = quota
        self.now = now            # Unix 秒：額度的重置時間、API 花費的月份都用它
        self.notifier = notifier  # API 上限通知（ticket 16 接 Telegram）
        self._events: quota_guard.Events | None = None

    # ----- 哪些能用 -----
    def _entry(self, data: dict, entry_id: str) -> dict | None:
        return next((o for o in data["openai"] if o["id"] == entry_id), None)

    def usable(self, choice: dict, data: dict, found: dict) -> tuple[bool, str]:
        """(能不能用, 不能用的原因)。原因：missing（沒裝、沒在執行、沒填）、auth_invalid（key 失效、登入過期）。"""
        e = choice["engine"]
        if e in CLI:
            if not (found.get(e) or {}).get("found"):
                return False, "missing"
            return ((data["engines"].get(e) or {}).get("auth") != "invalid"), "auth_invalid"
        if e == "ollama":
            o = found.get("ollama") or {}
            return bool(o.get("running") and choice["model"] in (o.get("models") or [])), "missing"
        if e == "anthropic":
            a = data["anthropic"]
            if not a or not self.has_sdk():
                return False, "missing"
            return a.get("status") != "invalid", "auth_invalid"
        o = self._entry(data, choice["entry"])
        if not o or not o.get("model"):
            return False, "missing"
        return o.get("status") != "invalid", "auth_invalid"

    def _usable_for(self, task: str, choice: dict, data: dict, found: dict, tools: bool = True, gate=None) -> tuple[bool, str]:
        """這個工作能不能用這個選項。不能有工具的工作（NO_TOOLS_TASKS 或呼叫端 tools=False）不用關不掉工具的 CLI，
        原因是 no_tools。gate 是背景工作的額度保護（_bg_gate）。plan 和 run 都走這裡，available() 才會跟實際呼叫一致。"""
        if (not tools or task in NO_TOOLS_TASKS) and choice["engine"] in NO_TOOLS_UNSUPPORTED:
            return False, "no_tools"
        why = gate(choice) if gate is not None else None
        if why:
            return False, why
        return self.usable(choice, data, found)

    @staticmethod
    def kind(choice: dict, data: dict) -> str:
        """subscription / api / local。本機 CLI 最近一次是用 API 計費（例如設了 API key）就算 api。"""
        e = choice["engine"]
        if e in CLI and (data["engines"].get(e) or {}).get("billing") == "api":
            return "api"
        return KIND[e]

    def candidates(self, task: str, data: dict, found: dict) -> list[dict]:
        """「自動」時依序考慮的選項。"""
        out = []
        for e in AUTO_ORDER:
            if e in CLI and (found.get(e) or {}).get("found"):
                out.append({"engine": e, "model": DEFAULT_MODEL[task] if e == "claude" else "", "entry": ""})
            elif e == "anthropic" and data["anthropic"]:
                out.append({"engine": e, "model": DEFAULT_MODEL[task], "entry": ""})
            elif e == "openai":
                out += [{"engine": e, "model": o.get("model") or "", "entry": o["id"]} for o in data["openai"]]
            elif e == "ollama" and (found.get("ollama") or {}).get("running"):
                out += [{"engine": e, "model": m, "entry": ""} for m in (found["ollama"].get("models") or [])[:1]]
        return out

    def plan(self, task: str, data: dict, found: dict, tools: bool = True, gate=None, use_api: bool = False) -> dict:
        """這個工作現在會用哪個引擎。state：ready / fallback（主要的不能用，改用備用）/ paused（key 失效、沒備用）/ no_ai。
        gate、use_api 給背景工作的額度保護用：use_api 時，設定的引擎都不能用就接著試 API key 和本機模型。
        reasons 是依序試過、不能用的原因。"""
        t = data["tasks"][task]
        primary, fallback = t["primary"], t["fallback"]
        extra: list[dict] = []
        if primary is None:  # 自動：第一個能用的；都不能用時，key 失效的那個當成主要的，好說明為什麼暫停
            options = self.candidates(task, data, found)
            primary = next((c for c in options if self._usable_for(task, c, data, found, tools, gate)[0]), None) or \
                next((c for c in options if self._usable_for(task, c, data, found, tools, gate)[1] == "auth_invalid"), None)
            # 自動時其他能用的都當備用：呼叫到一半發現 key 失效，這次就改用下一個，不用等下一次
            extra = [c for c in options if c is not primary and choice_id(c) != choice_id(fallback)]
        order = [c for c in (primary, fallback) if c] + extra
        if use_api:  # 背景工作改用 API key（和本機模型）：設定裡沒選的也接在後面
            seen = {choice_id(c) for c in order}
            order += [c for c in self.candidates(task, data, found)
                      if self.kind(c, data) != "subscription" and choice_id(c) not in seen]
        reasons = []
        for i, c in enumerate(order):
            ok, why = self._usable_for(task, c, data, found, tools, gate)
            if ok:
                return {"primary": primary, "fallback": fallback, "using": c, "state": "ready" if i == 0 else "fallback",
                        "reason": reasons[0] if reasons else None, "reasons": reasons, "order": order[i:]}
            reasons.append(why)
        state = "paused" if "auth_invalid" in reasons else "no_ai"
        return {"primary": primary, "fallback": fallback, "using": None, "state": state,
                "reason": reasons[0] if reasons else None, "reasons": reasons, "order": []}

    def available(self, task: str) -> bool:
        """其他模組用：這個工作現在有沒有 AI 可以用（沒有就在畫面標「沒有 AI」）。"""
        return self.plan(task, self.settings.load(), self.detector())["using"] is not None

    def _spec(self, choice: dict, data: dict) -> dict:
        spec = dict(choice)
        if choice["engine"] == "anthropic":
            spec["key"] = data["anthropic"]["key"]
        elif choice["engine"] == "openai":
            o = self._entry(data, choice["entry"]) or {}
            spec.update(base_url=o.get("base_url") or "", api=o.get("api") or "chat", key=o.get("key") or "",
                        model=o.get("model") or "")
        return spec

    def _mark(self, choice: dict, ok: bool, code: str | None = None, billing: str | None = None) -> None:
        """記下這個引擎 / key 最近一次的結果。狀態沒變就不寫檔（分類一天會跑上百次）。"""
        e, now = choice["engine"], _now()

        def change(d):
            if e in CLI:
                d["engines"][e] = {"auth": "ok" if ok else "invalid", "at": now, "billing": billing or
                                   (d["engines"].get(e) or {}).get("billing")}
            else:
                target = d["anthropic"] if e == "anthropic" else self._entry(d, choice["entry"])
                if target is not None:
                    target.update(status="ok" if ok else "invalid", tested_at=now, code=code)

        data = self.settings.load()
        if e in CLI:
            cur = data["engines"].get(e) or {}
            if cur.get("auth") == ("ok" if ok else "invalid") and (not billing or cur.get("billing") == billing):
                return
        else:
            cur = data["anthropic"] if e == "anthropic" else self._entry(data, choice["entry"])
            if cur is None or cur.get("status") == ("ok" if ok else "invalid"):
                return
        self.settings.update(change)

    def _call(self, choice: dict, spec: dict, prompt: str, cancel, json_mode: bool) -> dict:
        """限流時指數退避，最多 MAX_ATTEMPTS 次；其他錯誤直接往外丟。"""
        adapter = self.adapters[choice["engine"]]
        for attempt in range(MAX_ATTEMPTS):
            if cancel is not None and cancel.is_set():
                raise AIError("CANCELLED")
            try:
                return adapter.call(spec, prompt, cancel=cancel, json_mode=json_mode)
            except AIError as e:
                if e.code != "RATE_LIMITED" or attempt == MAX_ATTEMPTS - 1:
                    raise
                delay = min(BACKOFF_MAX, max(e.retry_after or 0.0, BACKOFF_BASE * 2 ** attempt))
                log.info("AI 限流，%.0f 秒後重試 engine=%s attempt=%d", delay, choice["engine"], attempt + 1)
                self.wait(delay, cancel)
        raise AIError("RATE_LIMITED")  # 走不到；MAX_ATTEMPTS >= 1

    def run(self, task: str, prompt: str, *, prompt_version: str, trigger: str, source: str = "newsread", cancel=None,
            json_mode: bool = False, context_manifest: str | None = None, tools: bool = True) -> dict:
        """呼叫這個工作設定的引擎。回傳 {text, engine, model, prompt_version, fallback, notice, quota_notice, usage_seq}。

        trigger 一定要給：background（排程自己跑的分類、翻譯、起草、論點變化偵測）或 manual（使用者按了才跑的）。
        背景工作受額度保護（quota_guard）：預設不用訂閱 CLI，改用 API key 或本機模型（都沒有丟 BACKGROUND_NO_API）；
        設定允許用訂閱時，Claude Code 5 小時額度超過門檻就丟 QUOTA_PAUSED（等重置）或改用 API key；
        API 這個月到上限時翻譯和起草丟 API_CAP，其他背景工作不用 API。每次觸發都記一筆事件。
        手動的照跑；額度超過門檻（用 Claude Code 訂閱時）或 API 到上限（用 API 時）在 quota_notice 帶
        QUOTA_OVER / API_CAP，讓畫面提醒。
        prompt_version 是呼叫端 prompt 的版本；實際記進帳本的是「版本@引擎/模型」，換引擎或模型就是另一個版本。
        key 失效（AUTH_INVALID）不重試同一把：標成失效，有備用就改用並在 notice 帶 AUTH_INVALID，沒有就丟 PAUSED。
        tools=False：prompt 裡有外部內容（文章全文），引擎不能有任何工具；NO_TOOLS_TASKS 的工作一律如此。
        Claude Code 用 --tools ""；Codex（read-only sandbox 照樣能讀檔）和 Antigravity（沒有關工具的選項）關不掉，
        這次跳過，改用下一個；只剩它們時丟 NO_AI。
        """
        if task not in TASKS:
            raise ValueError(f"unknown task {task!r}")
        if trigger not in TRIGGERS:
            raise ValueError(f"trigger must be one of {TRIGGERS}")
        if not prompt_version:
            raise ValueError("prompt_version is required")
        if self.index is None:
            raise ValueError("a ledger index is required to record usage")
        if context_manifest:  # 先確認，免得 AI 跑完、錢花了才發現記不進帳本
            with self.index.read() as db:
                if not db.execute("SELECT 1 FROM context_manifests WHERE id=?", (context_manifest,)).fetchone():
                    raise ValueError("context manifest not found")
        no_tools = not tools or task in NO_TOOLS_TASKS
        data, found = self.settings.load(), self.detector()
        g = self._guard(data)
        background = trigger == "background" and task in quota_guard.BACKGROUND_TASKS
        gate, use_api, switching = None, False, False
        if background:
            gate, use_api, switching = self._before_background(task, data, found, g, not no_tools)
        p = self.plan(task, data, found, tools=not no_tools, gate=gate, use_api=use_api)
        auth_failed = p["state"] in ("fallback", "paused") and p["reason"] == "auth_invalid"
        for choice in p["order"]:
            if not self._usable_for(task, choice, data, found, tools=not no_tools, gate=gate)[0]:
                continue
            spec = self._spec(choice, data)
            if no_tools:
                spec["tools"] = False
            kind = self.kind(choice, data)
            try:
                res = self._call(choice, spec, prompt, cancel, json_mode)
            except AIError as e:
                log.warning("AI 呼叫失敗 task=%s engine=%s code=%s", task, choice["engine"], e.code)
                if e.usage:
                    try:
                        self._record(task, choice, spec, e.usage, source, context_manifest)
                        self._after_spend(e.usage.get("cost_usd"), data)
                    except Exception as rec:  # noqa: BLE001 記不進帳本不能蓋掉原本的錯誤代碼
                        log.warning("AI 用量記錄失敗 task=%s %s", task, type(rec).__name__)
                if e.code != "AUTH_INVALID":
                    raise
                self._mark(choice, False, e.code)
                auth_failed = True
                data = self.settings.load()
                continue
            self._mark(choice, True, billing=res.get("billing") if choice["engine"] in CLI else None)
            model = spec.get("model") or ""
            # OpenAI 相容服務帶上是哪一個：兩家用同一個模型名稱時，結果也要分開算
            engine = f"openai:{choice['entry']}" if choice["engine"] == "openai" else choice["engine"]
            effective = f"{prompt_version}@{engine}/{model or 'default'}"
            self.index.register_prompt(task, effective, f"base={prompt_version}\nengine={engine}\nmodel={model}")
            seq = self._record(task, choice, spec, res, source, context_manifest)
            if switching and kind != "subscription":
                self._event("QUOTA_SWITCHED_API", task, g, key=_until_key(g))
            self._after_spend(res.get("cost_usd"), data)
            quota_notice = None
            if not background:  # 手動（或不受保護的工作）照跑，但提醒
                if choice["engine"] == "claude" and kind == "subscription" and g["quota"]["over"]:
                    quota_notice = "QUOTA_OVER"
                elif kind == "api" and g["api_reached"]:
                    quota_notice = "API_CAP"
            return {"text": res.get("text") or "", "engine": choice["engine"], "model": model, "prompt_version": effective,
                    "fallback": choice is not p["primary"], "notice": "AUTH_INVALID" if auth_failed else None,
                    "quota_notice": quota_notice, "usage_seq": seq}
        if background and not auth_failed:
            reasons = set(p["reasons"])
            for why, code, event in (("quota_guard", "QUOTA_PAUSED", "QUOTA_PAUSED"), ("api_cap", "API_CAP", "API_CAP_STOPPED"),
                                     ("background_api_only", "BACKGROUND_NO_API", "BACKGROUND_NO_API")):
                if why in reasons:
                    self._event(event, task, g, key=_until_key(g) if why == "quota_guard" else g["month"])  # 其他的每月一段
                    raise AIError(code)
        raise AIError("PAUSED" if auth_failed else "NO_AI")

    # ----- 額度保護（ticket 68） -----
    def events(self) -> quota_guard.Events | None:
        if self.index is None:
            return None
        if self._events is None:
            self._events = quota_guard.Events(self.index)
        return self._events

    def _guard(self, data: dict) -> dict:
        """現在的保護設定、Claude Code 額度、這個月的 API 花費。"""
        g = dict(data["guard"])
        now = self.now()
        try:
            latest = self.quota()
        except Exception as e:  # noqa: BLE001 額度檔壞了或被鎖住：當作沒有額度資料，不讓每個 AI 呼叫都失敗；log 只記類型
            log.warning("Claude Code 額度讀不到 %s", type(e).__name__)
            latest = None
        q = quota_guard.quota_state(latest, g["threshold"], now)
        spent = 0.0
        if self.index is not None:
            with self.index.read() as db:
                spent = quota_guard.api_spent(db, now)
        cap = g["api_monthly_usd"]
        # 上限 0 = 背景不用 API（api_blocked），不算「到上限」：不通知、不停掉能用本機模型的翻譯和起草、右上角不顯示暫停
        reached = cap > 0 and spent >= cap
        return {**g, "now": now, "quota": q, "spent": spent, "month": quota_guard.month_key(now),
                "api_warn": cap > 0 and spent >= cap * quota_guard.WARN_RATIO, "api_reached": reached,
                "api_blocked": cap <= 0 or reached}

    def _bg_gate(self, g: dict, data: dict):
        """背景工作不能用哪些引擎：訂閱（設定不允許，或 Claude Code 額度超過門檻）、API（這個月到上限）。"""
        def gate(choice):
            kind = self.kind(choice, data)
            if kind == "subscription":
                if not g["background_subscription"]:
                    return "background_api_only"
                if choice["engine"] == "claude" and g["quota"]["over"]:
                    return "quota_guard"
            elif kind == "api" and g["api_blocked"]:
                return "api_cap"
            return None
        return gate

    def _guarded(self, task: str, data: dict, found: dict, g: dict, tools: bool) -> bool:
        """允許背景用訂閱、額度超過門檻，而且這個工作本來就會用 Claude Code 訂閱（不是設定成 API 之類的）。"""
        if not (g["background_subscription"] and g["quota"]["over"]):
            return False
        using = self.plan(task, data, found, tools=tools)["using"]
        return bool(using) and using["engine"] == "claude" and self.kind(using, data) == "subscription"

    def _before_background(self, task: str, data: dict, found: dict, g: dict, tools: bool):
        """背景工作呼叫前：該停的直接丟錯誤代碼（並記事件），不然回傳 (gate, use_api, switching)。
        switching：額度超過門檻，這次從 Claude Code 訂閱改用 API key。"""
        if task in quota_guard.STOP_AT_CAP and g["api_reached"]:
            self._event("API_CAP_STOPPED", task, g, key=g["month"])
            raise AIError("API_CAP")
        guarded = self._guarded(task, data, found, g, tools)
        if guarded and g["on_exceed"] == "wait":
            self._event("QUOTA_PAUSED", task, g, key=_until_key(g))
            raise AIError("QUOTA_PAUSED")  # 等重置，不改用 API
        use_api = not g["background_subscription"] or (g["quota"]["over"] and g["on_exceed"] == "api")
        return self._bg_gate(g, data), use_api, guarded

    def _event(self, code: str, task: str, g: dict, key: str = "", once: bool = False) -> dict | None:
        """記一筆額度保護事件（只有代碼和固定欄位的數字）。記不進去只寫 log，不蓋掉原本的結果或錯誤代碼。"""
        q = g["quota"]
        data = {"threshold": g["threshold"], "cap_usd": g["api_monthly_usd"], "spent_usd": g["spent"], "month": g["month"]}
        if q["used"] is not None:
            data["used"] = q["used"]
        if q["until"]:
            data["until"] = q["until"]
        try:
            ev = self.events()
            return ev.add(code, task, data, key=key, once=once) if ev else None
        except Exception as e:  # noqa: BLE001
            log.warning("額度保護事件記不進去 code=%s %s", code, type(e).__name__)
            return None

    def _after_spend(self, cost, data: dict) -> None:
        """有費用的呼叫記完之後：這個月的 API 花費到 80%、到上限時，各記一筆並通知一次（每個月一次）。"""
        if not cost:
            return
        try:
            g = self._guard(data)
        except Exception as e:  # noqa: BLE001 讀不到花費不影響這次已經成功的呼叫
            log.warning("API 花費讀不到 %s", type(e).__name__)
            return
        for reached, code in ((g["api_reached"], "API_CAP_REACHED"), (g["api_warn"], "API_CAP_WARN")):
            if reached:
                ev = self._event(code, "", g, key=g["month"], once=True)
                if ev:
                    try:
                        self.notifier({"code": ev["code"], "message": ev["message"], "data": ev["data"]})
                    except Exception as e:  # noqa: BLE001 通知送不出去不影響這次呼叫；只記類型
                        log.warning("額度通知送不出去 %s", type(e).__name__)
                break  # 已經到上限就不另外送 80% 的通知

    def guard_status(self, data: dict | None = None, found: dict | None = None) -> dict:
        """GET /api/ai/guard（每頁右上角）和設定頁要的：背景工作現在是不是暫停、為什麼、到什麼時候。
        reason：quota（額度超過門檻、等重置）/ api_cap（API 到上限）/ no_api（背景不用訂閱，又沒有 API key 或本機模型）。
        用分類（triage）判斷，因為它是一直在跑的背景工作；根本沒有 AI 時不算保護。"""
        data = data or self.settings.load()
        found = found if found is not None else self.detector()
        g = self._guard(data)
        q = g["quota"]
        reason = None
        if self.plan("triage", data, found, tools=False)["using"] is not None:
            if g["on_exceed"] == "wait" and self._guarded("triage", data, found, g, False):
                reason = "quota"
            else:
                use_api = not g["background_subscription"] or (q["over"] and g["on_exceed"] == "api")
                p = self.plan("triage", data, found, tools=False, gate=self._bg_gate(g, data), use_api=use_api)
                reasons = set(p["reasons"]) if p["using"] is None else set()
                for why, name in (("quota_guard", "quota"), ("api_cap", "api_cap"), ("background_api_only", "no_api")):
                    if why in reasons:
                        reason = name
                        break
        if reason is None and g["api_reached"]:
            reason = "api_cap"  # 背景的翻譯和起草停下
        return {"settings": {k: g[k] for k in quota_guard.defaults()},
                "quota": {k: q[k] for k in ("used", "resets_at", "at", "over", "until")},
                "api": {"spent_usd": g["spent"], "cap_usd": g["api_monthly_usd"], "month": g["month"],
                        "warn": g["api_warn"], "reached": g["api_reached"]},
                "background": {"paused": reason is not None, "reason": reason,
                               "until": q["until"] if reason == "quota" else None}}

    def set_guard(self, body: dict) -> dict:
        """POST /api/ai/guard：只改有帶的欄位。"""
        changes = parse_guard(body)
        self.settings.update(lambda d: d.__setitem__("guard", quota_guard.clean({**d["guard"], **changes})))
        return self.view()

    def _record(self, task: str, choice: dict, spec: dict, res: dict, source: str, context_manifest) -> int:
        return self.index.record_usage(source=source, task=task, engine=choice["engine"], model=spec.get("model") or "",
                                       input_tokens=res.get("input", 0), cached_tokens=res.get("cached", 0),
                                       output_tokens=res.get("output", 0), cost_usd=res.get("cost_usd"),
                                       quota=res.get("quota") or None, context_manifest=context_manifest)

    # ----- 給設定頁的資料 -----
    def _summary(self) -> dict:
        """每種工作今天呼叫幾次、這個月 API 花多少（台北時間）。"""
        out = {t: {"today": 0, "month_cost": None} for t in TASKS}
        if self.index is None:
            return out
        now = datetime.now(TAIPEI)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = day.replace(day=1)
        with self.index.read() as db:
            rows = db.execute("SELECT task, SUM(at >= ?) AS today, SUM(cost_usd) AS cost FROM ai_usage WHERE at >= ? "
                              "GROUP BY task", (ledger.iso(day), ledger.iso(month))).fetchall()
        for r in rows:
            if r["task"] in out:
                out[r["task"]] = {"today": int(r["today"] or 0),
                                  "month_cost": None if r["cost"] is None else round(float(r["cost"]), 4)}
        return out

    def choices(self, data: dict, found: dict) -> list[dict]:
        """每個下拉選單可以選的。目前選著、但現在不能用的也列出來（標 usable=false）。"""
        out: list[dict] = []

        def add(c):
            cid = choice_id(c)
            if any(x["id"] == cid for x in out):
                return
            o = self._entry(data, c["entry"]) if c["engine"] == "openai" else None
            out.append({"id": cid, "engine": c["engine"], "model": c["model"], "entry": c["entry"],
                        "model_label": CLAUDE_MODELS.get(c["model"], c["model"]), "name": (o or {}).get("name") or "",
                        "kind": KIND[c["engine"]], "usable": self.usable(c, data, found)[0]})

        for e in CLI:
            if (found.get(e) or {}).get("found"):
                for m in (CLAUDE_MODELS if e == "claude" else [""]):
                    add({"engine": e, "model": m, "entry": ""})
        if data["anthropic"]:
            for m in CLAUDE_MODELS:
                add({"engine": "anthropic", "model": m, "entry": ""})
        for o in data["openai"]:
            add({"engine": "openai", "model": o.get("model") or "", "entry": o["id"]})
        for m in ((found.get("ollama") or {}).get("models") or [])[:50] if (found.get("ollama") or {}).get("running") else []:
            add({"engine": "ollama", "model": m, "entry": ""})
        for t in TASKS:
            for c in (data["tasks"][t]["primary"], data["tasks"][t]["fallback"]):
                if c:
                    add(c)
        return out

    def view(self, fresh: bool = False) -> dict:
        """GET /api/ai：設定頁要的全部東西。key 只給末四碼。"""
        found = self.detector(fresh=fresh) if fresh else self.detector()
        data = self.settings.load()
        summary = self._summary()
        tasks = {}
        for t in TASKS:
            p = self.plan(t, data, found)
            tasks[t] = {"primary": choice_id(data["tasks"][t]["primary"]), "fallback": choice_id(data["tasks"][t]["fallback"]),
                        "resolved": choice_id(p["primary"]), "using": choice_id(p["using"]), "state": p["state"],
                        "reason": p["reason"], **summary[t]}
        a = data["anthropic"]
        latest = self.quota() or {}
        return {
            "detected": {e: {"found": bool((found.get(e) or {}).get("found")), "version": (found.get(e) or {}).get("version") or "",
                             "auth": (data["engines"].get(e) or {}).get("auth"),
                             "billing": (data["engines"].get(e) or {}).get("billing")} for e in CLI}
            | {"ollama": {"running": bool((found.get("ollama") or {}).get("running")),
                          "models": list(((found.get("ollama") or {}).get("models") or [])[:50])}},
            "detected_at": detect.detected_at(),
            "claude_quota": latest.get("limits") if isinstance(latest, dict) else None,
            "anthropic": None if not a else {"last4": last4(a["key"]), "status": a.get("status") or "untested",
                                             "tested_at": a.get("tested_at"), "code": a.get("code")},
            "anthropic_sdk": self.has_sdk(),
            "openai": [{"id": o["id"], "name": o.get("name") or "", "base_url": o["base_url"], "api": o.get("api") or "chat",
                        "model": o.get("model") or "", "last4": last4(o.get("key")), "has_key": bool(o.get("key")),
                        "status": o.get("status") or "untested", "tested_at": o.get("tested_at"), "code": o.get("code")}
                       for o in data["openai"]],
            "tasks": tasks,
            "choices": self.choices(data, found),
            "any_ai": any(v["using"] for v in tasks.values()),
            "guard": self.guard_status(data, found),
        }

    # ----- 設定頁的寫入 -----
    def _check(self, engine: str, spec: dict, entry: str = "") -> dict:
        """儲存並測試：401 / 403 標成失效；連不上、不支援列模型清單時標「沒驗證到」，照樣存著。"""
        try:
            self.adapters[engine].check(spec)
            status, code = "ok", None
        except AIError as e:
            status = "invalid" if e.code == "AUTH_INVALID" or e.status == 403 else "unverified"
            code = e.code
            log.warning("AI key 測試沒通過 engine=%s code=%s", engine, code)

        def change(d):
            target = d["anthropic"] if engine == "anthropic" else self._entry(d, entry)
            if target is not None:
                target.update(status=status, tested_at=_now(), code=code)

        self.settings.update(change)
        return {"ok": status == "ok", "status": status, "code": code, "message": message(code) if code else ""}

    def set_anthropic(self, body: dict) -> dict:
        key = _key(body.get("key"), required=True)
        self.settings.update(lambda d: d.__setitem__("anthropic", {"key": key, "status": "untested", "tested_at": None, "code": None}))
        test = self._check("anthropic", {"key": key}) if self.has_sdk() else \
            {"ok": False, "status": "untested", "code": "ENGINE_MISSING", "message": message("ENGINE_MISSING")}
        return {**self.view(), "test": test}

    def remove_anthropic(self) -> dict:
        self.settings.update(lambda d: d.__setitem__("anthropic", None))
        return self.view()

    def set_openai(self, body: dict, entry_id: str | None = None) -> dict:
        name = _text(body.get("name"), "name", MAX_NAME) or tr("OpenAI 相容")
        base = _base_url(body.get("base_url"))
        api = body.get("api") or "chat"
        if api not in ("chat", "responses"):
            raise InputError(tr("接口格式不對。"), "api")
        model = _text(body.get("model"), "model", MAX_MODEL)
        if not model:
            raise InputError(tr("請填模型名稱。"), "model")
        key = _key(body.get("key"), required=False)
        holder: dict = {}

        def change(d):
            if entry_id is None:
                if len(d["openai"]) >= MAX_OPENAI:
                    raise InputError(tr("最多 {n} 個 OpenAI 相容服務。", n=MAX_OPENAI), "form")
                o = {"id": "o" + secrets.token_hex(6), "key": ""}
                d["openai"].append(o)
            else:
                o = self._entry(d, entry_id)
                if o is None:
                    raise NotFound(entry_id)
            if key is not None:
                o["key"] = key
            elif o.get("base_url") and o["base_url"] != base:
                o["key"] = ""  # 換了地址就不把舊的 key 送到新地址
            o.update(name=name, base_url=base, api=api, model=model, status="untested", tested_at=None, code=None)
            holder["o"] = dict(o)

        self.settings.update(change)
        o = holder["o"]
        if not o["key"] and not _is_loopback(base):
            test = {"ok": False, "status": "untested", "code": None, "message": tr("還沒填 key。")}
        else:
            test = self._check("openai", self._spec({"engine": "openai", "model": model, "entry": o["id"]}, self.settings.load()), o["id"])
        return {**self.view(), "test": test, "id": o["id"]}

    def remove_openai(self, entry_id: str) -> dict:
        def change(d):
            if self._entry(d, entry_id) is None:
                raise NotFound(entry_id)
            d["openai"] = [o for o in d["openai"] if o["id"] != entry_id]
            for t in TASKS:  # 選了這個服務的工作改回自動
                for k in ("primary", "fallback"):
                    c = d["tasks"][t][k]
                    if c and c["engine"] == "openai" and c["entry"] == entry_id:
                        d["tasks"][t][k] = None
        self.settings.update(change)
        return self.view()

    def set_task(self, body: dict) -> dict:
        task = body.get("task")
        if task not in TASKS:
            raise InputError(tr("沒有這種工作。"), "task")
        data = self.settings.load()
        primary = parse_choice(body.get("primary"), data, "primary")
        fallback = parse_choice(body.get("fallback"), data, "fallback")
        if fallback and primary and choice_id(fallback) == choice_id(primary):
            fallback = None
        self.settings.update(lambda d: d["tasks"].__setitem__(task, {"primary": primary, "fallback": fallback}))
        return self.view()

    def redetect(self) -> dict:
        """重新偵測：重新登入過的 CLI 不再當成失效，下次呼叫再看結果。"""
        def change(d):
            for e in CLI:
                if (d["engines"].get(e) or {}).get("auth") == "invalid":
                    d["engines"][e]["auth"] = None
        self.settings.update(change)
        return self.view(fresh=True)


def _until_key(g: dict) -> str:
    """同一段暫停（同一個重置時間）只記一筆事件。"""
    return str(int(g["quota"]["until"] or 0))


# ---------- 輸入檢查 ----------
def parse_guard(body: dict) -> dict:
    """額度保護的設定。只回傳有帶、而且格式對的欄位；格式不對丟 InputError。"""
    out = {}
    if "background_subscription" in body:
        if not isinstance(body["background_subscription"], bool):
            raise InputError(tr("資料格式不對。"), "background_subscription")
        out["background_subscription"] = body["background_subscription"]
    if "threshold" in body:
        if not quota_guard.valid_threshold(body["threshold"]):
            raise InputError(tr("門檻要是 1 到 100 的整數。"), "threshold")
        out["threshold"] = body["threshold"]
    if "on_exceed" in body:
        if body["on_exceed"] not in quota_guard.ON_EXCEED:
            raise InputError(tr("選項不對。"), "on_exceed")
        out["on_exceed"] = body["on_exceed"]
    if "api_monthly_usd" in body:
        if not quota_guard.valid_cap(body["api_monthly_usd"]):
            raise InputError(tr("每月上限要是 0 到 {n} 美元。", n=int(quota_guard.MAX_API_MONTHLY_USD)), "api_monthly_usd")
        out["api_monthly_usd"] = body["api_monthly_usd"]
    return out


def choice_id(c: dict | None) -> str | None:
    return None if not c else f"{c['engine']}|{c.get('entry') or ''}|{c.get('model') or ''}"


def parse_choice(value, data: dict, field: str) -> dict | None:
    if value in (None, "", "auto"):
        return None
    if not isinstance(value, str) or len(value) > MAX_MODEL + 40:
        raise InputError(tr("選項不對。"), field)
    parts = value.split("|", 2)
    if len(parts) != 3 or parts[0] not in ENGINES:
        raise InputError(tr("選項不對。"), field)
    engine, entry, model = parts
    if engine == "openai":
        o = next((x for x in data["openai"] if x["id"] == entry), None)
        if o is None:
            raise InputError(tr("選項不對。"), field)
        model = o.get("model") or ""
    elif entry:
        raise InputError(tr("選項不對。"), field)
    if engine in ("anthropic",) and model not in CLAUDE_MODELS:
        raise InputError(tr("選項不對。"), field)
    if engine == "claude" and model and model not in CLAUDE_MODELS:
        raise InputError(tr("選項不對。"), field)
    if engine in ("codex", "antigravity") and model:
        raise InputError(tr("選項不對。"), field)
    if engine == "ollama" and (not model or not model.isprintable()):
        raise InputError(tr("選項不對。"), field)
    return {"engine": engine, "model": model, "entry": entry}


def _text(value, field: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InputError(tr("資料格式不對。"), field)
    value = " ".join(value.split())
    if len(value) > limit or not value.isprintable():
        raise InputError(tr("太長了（最多 {n} 字）。", n=limit), field)
    return value


def _key(value, required: bool) -> str | None:
    """None = 不改（編輯時沒填）。key 只能是 ASCII 可見字元，不能有空白。"""
    if value is None or value == "":
        if required:
            raise InputError(tr("請貼上 key。"), "key")
        return None
    if not isinstance(value, str):
        raise InputError(tr("資料格式不對。"), "key")
    value = value.strip()
    if not 8 <= len(value) <= MAX_KEY or not value.isascii() or not value.isprintable() or any(ch.isspace() for ch in value):
        raise InputError(tr("key 的格式不對。"), "key")
    return value


def _is_loopback(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOOPBACK


def _base_url(value) -> str:
    """https 才送 key；http 只接受本機（LM Studio、自架的 Ollama）。不接受帳密、query 和 fragment。"""
    if not isinstance(value, str) or not value.strip():
        raise InputError(tr("請填 base URL。"), "base_url")
    url = value.strip().rstrip("/")
    if len(url) > MAX_URL or not url.isascii() or any(ch.isspace() for ch in url):
        raise InputError(tr("base URL 的格式不對。"), "base_url")
    try:
        p = urlparse(url)
        host = p.hostname or ""
        p.port  # noqa: B018 不合法的 port 會丟 ValueError
    except ValueError:
        raise InputError(tr("base URL 的格式不對。"), "base_url") from None
    if p.scheme not in ("http", "https") or not host or p.username or p.password or p.query or p.fragment:
        raise InputError(tr("base URL 的格式不對。"), "base_url")
    if p.scheme == "http" and host not in LOOPBACK:
        raise InputError(tr("不是這台電腦上的服務要用 https，key 才不會明文送出去。"), "base_url")
    return url


# ---------- HTTP ----------
_ENGINES: dict[tuple, Engines] = {}
_ENGINES_LOCK = threading.Lock()


def settings_path(app=None) -> Path:
    return Path(getattr(app, "ai_path", None) or (config.HOME / FILE_NAME))


def for_app(app, create_index: bool = True) -> Engines:
    """伺服器和其他模組共用的 Engines。帳本檔還不存在時，唯讀的 GET 不建檔。"""
    spath = settings_path(app)
    lpath = Path(getattr(app, "ledger_path", None) or ledger.default_path())
    with _ENGINES_LOCK:
        key = (spath, lpath)
        eng = _ENGINES.get(key)
        if eng is None or (eng.index is None and (create_index or lpath.exists())):
            index = ledger.shared(lpath, create=create_index)
            eng = Engines(Settings(spath), index, **(getattr(app, "ai_options", None) or {}))
            _ENGINES[key] = eng
        return eng


def _route(path: str) -> list[str] | None:
    if path != PREFIX and not path.startswith(PREFIX + "/"):
        return None
    return [p for p in path[len(PREFIX):].split("/") if p]


def api_get(app, path: str) -> dict | None:
    parts = _route(path)
    if parts is None:
        return None
    eng = for_app(app, create_index=False)
    if parts == ["guard"]:  # 額度保護的狀態（每頁右上角「背景工作暫停」）
        return eng.guard_status()
    if parts == ["guard", "events"]:  # 額度保護、API 上限的事件，新的在前（用量頁，ticket 29）
        ev = eng.events()
        return {"events": ev.list() if ev else []}
    if parts:
        raise NotFound(path)
    return eng.view()


def api_post(app, path: str, body) -> dict | None:
    parts = _route(path)
    if parts is None:
        return None
    body = body if isinstance(body, dict) else {}
    eng = for_app(app, create_index=False)
    if parts == ["detect"]:
        return eng.redetect()
    if parts == ["tasks"]:
        return eng.set_task(body)
    if parts == ["guard"]:
        return eng.set_guard(body)
    if parts == ["keys", "anthropic"]:
        return eng.set_anthropic(body)
    if parts == ["keys", "anthropic", "remove"]:
        return eng.remove_anthropic()
    if parts == ["keys", "openai"]:
        return eng.set_openai(body)
    if len(parts) == 3 and parts[:2] == ["keys", "openai"]:
        return eng.set_openai(body, parts[2])
    if len(parts) == 4 and parts[:2] == ["keys", "openai"] and parts[3] == "remove":
        return eng.remove_openai(parts[2])
    raise NotFound(path)
