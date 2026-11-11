"""之後每張 ticket 共用的測試替身：假的網路回應、回固定輸出的假 AI 引擎、HTTP API 測試的共用基底、假時鐘。"""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import types
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ---------- 假時鐘 ----------
class FakeClock:
    """每次呼叫往前走 step；advance() 手動快轉。給 datetime 用的時鐘。"""

    def __init__(self, start=datetime(2026, 11, 11, 1, 0, tzinfo=timezone.utc), step=timedelta(seconds=1)):
        self.t, self.step = start, step

    def __call__(self):
        self.t += self.step
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class FakeMonotonic:
    """給 time.monotonic / time.sleep 用的假時間：sleep 只把時間往前推，不真的等。"""

    def __init__(self, start: float = 1000.0):
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


# ---------- 假的網路回應 ----------
class FakeResponse:
    """跟 fetch.Response 同介面。closed 用來確認連線有被釋放；read_error 模擬讀到一半斷線。"""

    def __init__(self, status=200, body=b"", headers=None, url="", chunk=None, read_error=None):
        self.status = status
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.url = url
        self.chunk = chunk
        self.read_error = read_error
        self.closed = False
        self.read_calls = 0
        self._pos = 0

    def read(self, n=-1):
        if self.closed:
            raise ValueError("read on closed response")
        self.read_calls += 1
        if self.read_error and self._pos > 0:
            raise self.read_error
        size = len(self.body) - self._pos if n is None or n < 0 else n
        if self.chunk:
            size = min(size, self.chunk)
        out = self.body[self._pos:self._pos + size]
        self._pos += len(out)
        if self.read_error and not out:
            raise self.read_error
        return out

    def close(self):
        self.closed = True


class FakeTransport:
    """依序回傳排好的回應或丟出排好的例外，並記下每次請求。"""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests: list[dict] = []
        self.responses: list[FakeResponse] = []

    def open(self, url, headers, timeout, max_redirects):
        self.requests.append({"url": url, "headers": dict(headers), "timeout": timeout, "max_redirects": max_redirects})
        if not self.steps:
            raise AssertionError(f"unexpected request: {url}")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, FakeResponse):
            step.url = step.url or url
            self.responses.append(step)
            return step
        raise TypeError(step)


def fixture(name: str, **kw) -> FakeResponse:
    """tests/fixtures/<name> 當成回應本文；Content-Type 依副檔名猜。"""
    path = FIXTURES / name
    types_ = {".html": "text/html; charset=utf-8", ".xml": "application/rss+xml", ".json": "application/json"}
    headers = {"Content-Type": types_.get(path.suffix, "application/octet-stream"), **kw.pop("headers", {})}
    return FakeResponse(body=path.read_bytes(), headers=headers, **kw)


PUBLIC_IP = "93.184.216.34"


def public_dns(host: str, port=None) -> list[tuple]:
    """check_url / public_addresses 用的假 DNS：任何網域都解析成一個公開位址，不真的查 DNS。"""
    return [(socket.AF_INET, (PUBLIC_IP, port))]


def dns(*addresses):
    """回傳固定位址的假 DNS，例如 dns("127.0.0.1") 模擬網域被指到本機。"""
    def resolve(host, port=None):
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, (a, port)) for a in addresses]
    return resolve


# ---------- 假 AI 引擎 ----------
class FakeEngine:
    """回固定輸出的假引擎。outputs 可以是 {task: 文字或 dict} 或依序回傳的 list；calls 記下每次呼叫。

    usage 跟真引擎回報的一樣：token 數、費用（None = 訂閱制、不明）。
    """

    def __init__(self, outputs, *, engine="fake", model="fake-model", usage=None, cost_usd=None):
        self.outputs = outputs
        self.engine, self.model = engine, model
        self.usage = usage or {"input": 100, "cached": 0, "output": 20}
        self.cost_usd = cost_usd
        self.calls: list[dict] = []

    def run(self, task: str, prompt: str, **kw) -> dict:
        self.calls.append({"task": task, "prompt": prompt, **kw})
        if isinstance(self.outputs, list):
            if not self.outputs:
                raise AssertionError(f"FakeEngine ran out of outputs (task={task})")
            out = self.outputs.pop(0)
        else:
            if task not in self.outputs:
                raise AssertionError(f"FakeEngine has no output for task {task}")
            out = self.outputs[task]
        if isinstance(out, BaseException):
            raise out
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return {"text": text, "engine": self.engine, "model": self.model, "usage": dict(self.usage), "cost_usd": self.cost_usd}


# ---------- HTTP API 測試的共用基底 ----------
class ApiTestCase(unittest.TestCase):
    """啟動真的 Handler（綁 127.0.0.1 隨機埠）。子類別覆寫 make_app() 提供 app 的欄位。"""

    token = "test-token"

    def make_app(self) -> dict:
        return {}

    def setUp(self):
        super().setUp()
        from easyread.server import Handler

        fields = {"token": self.token, "lib": None,
                  "location": types.SimpleNamespace(status="idle", request=lambda *a: contextlib.nullcontext()),
                  **self.make_app()}

        class TestHandler(Handler):
            app = types.SimpleNamespace(**fields)

            def log_message(self, *args):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.base = f"http://127.0.0.1:{srv.server_port}"

    def request(self, method: str, path: str, body=None, token: str | None = None, headers=None):
        """回傳 (狀態碼, 解析後的 JSON 或原文)。4xx / 5xx 不丟例外。"""
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        h = {"Content-Type": "application/json", **(headers or {})}
        if method != "GET":
            h["X-Token"] = self.token if token is None else token
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                status, raw = res.status, res.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
            e.close()
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw.decode("utf-8", "replace")

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, body=None, token: str | None = None):
        return self.request("POST", path, body or {}, token=token)


# ---------- 不連真實網路 ----------
_real_connect = socket.socket.connect
_real_create_connection = socket.create_connection
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _loopback(address) -> bool:
    host = address[0] if isinstance(address, tuple) else address
    return isinstance(host, str) and (host in ("localhost", "::1") or host.startswith("127."))


def block_network() -> None:
    """測試只能連 127.0.0.1，也不能查 DNS（localhost 和 IP 字面值除外）；其他一律丟 OSError。
    設 NEWSREAD_ALLOW_NETWORK=1 可以關掉。子程序不受這裡管。"""

    def refuse(address):
        raise OSError(f"tests may not use the network: {address!r}")

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address):
            refuse(address)
        return _real_connect(self, address)

    def connect_ex(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address):
            refuse(address)
        return _real_connect_ex(self, address)

    def create_connection(address, *a, **kw):
        if not _loopback(address):
            refuse(address)
        return _real_create_connection(address, *a, **kw)

    def getaddrinfo(host, *a, **kw):
        name = host.decode() if isinstance(host, bytes) else host
        if name not in (None, "", "localhost") and not _ip_literal(name):
            refuse((name,))
        return _real_getaddrinfo(host, *a, **kw)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo


def _ip_literal(name: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(name.split("%", 1)[0])
        return True
    except ValueError:
        return False
