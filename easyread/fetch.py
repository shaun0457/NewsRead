"""所有來源共用的對外抓取規則。

每次抓取都有：逾時（每次連線 / 讀取）、每次嘗試的總時限、最大位元組數、重試次數（指數退避）、
每個來源每小時的呼叫上限；列表類來源（RSS 等）用 cap_items 限制最大筆數。轉址次數也有上限。

只連公開網路：解析網域和檢查 IP 在建立連線的那一刻一起做，而且直接連到檢查過的 IP，
所以 DNS 在檢查和連線之間換成本機或內網位址（DNS rebinding）也打不到本機服務。
轉址的每一跳都重新檢查；跨網域轉址時拿掉帶機密的 header；不走環境變數設定的 proxy。

錯誤分成固定的幾類（FetchError.kind），log 和存檔只用 kind 加固定訊息；
上游回傳的原文只能經過 scrub() 才能保留（FetchError.detail），用來除錯，不直接顯示。

網路層透過 Transport 介面注入，測試用假的 transport，不連真實網路。
"""
from __future__ import annotations

import http.client
import inspect
import ipaddress
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol
from urllib.parse import urlsplit

from . import __version__, http as _http
from .i18n import tr

# ---------- 上限 ----------


@dataclass(frozen=True)
class Limits:
    timeout: float = 20.0               # 每次連線 / 讀取的逾時（秒）
    deadline: float = 60.0              # 每次嘗試從連線到讀完的總時限（秒）；慢慢滴資料的伺服器也會被切掉
    max_bytes: int = 5 * 1024 * 1024    # 回應本文最多讀幾個位元組
    max_items: int = 200                # 一次最多處理幾筆（RSS 項目等）
    retries: int = 2                    # 失敗後最多再試幾次（不含第一次）
    backoff: float = 1.0                # 第一次重試前等幾秒，之後每次乘 2
    backoff_max: float = 30.0           # 單次等待最多幾秒（含上游的 Retry-After）
    per_hour: int = 60                  # 每個來源每小時最多呼叫幾次（含重試）
    max_redirects: int = 5


DEFAULT = Limits()
CHUNK = 64 * 1024
PREVIEW_BYTES = 2048                    # 錯誤狀態時最多讀幾個位元組當除錯預覽
USER_AGENT = f"NewsRead/{__version__} (+local desktop app)"
DETAIL_CHARS = 300
SCRUB_MAX_CHARS = 64 * 1024             # scrub 最多處理幾個字（之後的直接丟掉）
SENSITIVE_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key", "x-auth-token"})

# ---------- 錯誤分類 ----------


def _messages() -> dict:
    """固定訊息。每次建立錯誤時才翻譯，跟著目前的介面語言。"""
    return {
        "timeout": tr("連線逾時"),
        "blocked": tr("來源拒絕存取"),
        "paywall": tr("需要付費或登入，只有預覽"),
        "unsupported": tr("格式不支援"),
        "too_large": tr("內容太大"),
        "over_limit": tr("超過這個來源的抓取上限，稍後再試"),
        "not_found": tr("找不到這個網址"),
        "network": tr("網路連線失敗"),
        "upstream": tr("來源暫時無法回應"),
        "invalid_url": tr("網址不正確或不允許"),
        "redirect": tr("轉址太多次或沒有完成"),
    }


KINDS = frozenset(_messages())


class FetchError(Exception):
    """kind 是固定的類別；message 是固定訊息；detail 只放 scrub 過、截短的上游原文。"""

    def __init__(self, kind: str, status: int | None = None, detail: str = "", retry_after: float | None = None):
        if kind not in KINDS:
            raise ValueError(f"unknown fetch error kind: {kind}")
        super().__init__(kind)
        self.kind = kind
        self.status = status
        self.message = _messages()[kind]
        self.detail = scrub(detail)[:DETAIL_CHARS] if detail else ""
        self.retry_after = retry_after
        self.retryable = kind in ("timeout", "network", "upstream") or status == 429

    def log_line(self) -> str:
        """可以寫進 log 的內容：只有類別、狀態碼和固定訊息。"""
        return f"fetch_error kind={self.kind} status={self.status or '-'} {self.message}"

    def public(self) -> dict:
        return {"kind": self.kind, "message": self.message, "status": self.status}


# ---------- scrubber ----------

_KEY_NAMES = (r"api[_-]?key|access[_-]?key|secret[_-]?key|private[_-]?key|aws[_-]?secret[_-]?access[_-]?key|"
              r"access[_-]?token|refresh[_-]?token|id[_-]?token|token|secret|password|passwd|pwd|key|"
              r"session(?:id)?|cookie|auth(?:orization)?|client[_-]?secret|signature|sig")
_SCRUB = [
    # 常見的 key / token 格式
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"), "[key]"),
    (re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{10,}"), "[key]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}"), "[key]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[key]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[key]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[key]"),
    (re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_\-]{30,}"), "[key]"),           # Telegram bot token（含網址裡的 bot<id>:<token>）
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 [key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"), "[key]"),  # JWT
    # key=value / "key": "value" 形式的機密欄位
    (re.compile(r"(?i)([\"']?(?<![A-Za-z0-9])(?:" + _KEY_NAMES + r")[\"']?\s*[=:]\s*[\"']?)[^\s\"'&,;}]+"), r"\1[redacted]"),
    # 帳號：email（含網址編碼的 %40）、網址裡的帳密、帳號類查詢參數
    (re.compile(r"[A-Za-z0-9._+\-]{1,64}(?:@|%40)[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?i)\b(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1[account]@"),
    (re.compile(r"(?i)([?&](?:user(?:name)?|account|login|email|uid)=)[^&\s]+"), r"\1[account]"),
]


def scrub(text) -> str:
    """把上游原文裡可能的 key、帳號、email 遮掉。用在任何要寫進 log 或存起來的上游文字。

    只處理前 SCRUB_MAX_CHARS 個字，之後的丟掉，避免很長的文字拖慢正規表示式。
    """
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text[:SCRUB_MAX_CHARS * 4].decode("utf-8", "replace")
    out = str(text)[:SCRUB_MAX_CHARS]
    for pattern, repl in _SCRUB:
        out = pattern.sub(repl, out)
    return out


# ---------- 網址與位址檢查 ----------

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")
_DEPRECATED_V6 = (ipaddress.ip_network("::/96"), ipaddress.ip_network("fec0::/10"))  # IPv4-compatible、site-local


def allowed_ip(address: str) -> bool:
    """只允許公開網路的位址。IPv6 裡包著的 IPv4（mapped、6to4、NAT64）拆出來再檢查一次。"""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6:
        if ip in _NAT64 or ip in _NAT64_LOCAL or ip.teredo or any(ip in net for net in _DEPRECATED_V6):
            return False
        inner = ip.ipv4_mapped or ip.sixtofour
        if inner is not None:
            ip = inner
    return ip.is_global and not ip.is_multicast


def _resolve(host: str, port: int | None = None) -> list[tuple]:
    """回傳 [(family, sockaddr)]。"""
    return [(info[0], info[4]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def public_addresses(host: str, port: int | None, resolve: Callable = _resolve) -> list[tuple]:
    """解析 host；任何一個位址不是公開網路就整個拒絕（混了內網位址的回應不能信）。"""
    if _is_ip(host):
        addrs = [(socket.AF_INET6 if ":" in host else socket.AF_INET, (host, port))]
    else:
        try:
            addrs = resolve(host, port)
        except (OSError, UnicodeError, ValueError):
            raise FetchError("network") from None
    if not addrs:
        raise FetchError("network")
    for _family, sockaddr in addrs:
        if not allowed_ip(sockaddr[0]):
            raise FetchError("invalid_url")
    return addrs


def check_url(url: str, resolve: Callable | None = None) -> str:
    """只允許 http / https、沒有帳密、指向公開網路的網址。resolve 給測試用；
    沒給時只檢查格式，位址留到真正連線時才檢查（見 _PinnedConnection），避免檢查和連線之間被換掉。"""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise FetchError("invalid_url") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("invalid_url")
    if parts.username or parts.password or any(c in url for c in " \t\r\n\x00"):
        raise FetchError("invalid_url")
    if _is_ip(parts.hostname) or resolve is not None:
        public_addresses(parts.hostname, port, resolve or _resolve)
    return url


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


# ---------- 每個來源的每小時上限 ----------


class Budget:
    """滑動一小時的呼叫次數。每個來源最多記 per_hour 筆時間戳，最多記 MAX_SOURCES 個來源，記憶體有上限。"""

    MAX_SOURCES = 10_000

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._calls: dict[str, deque] = {}
        self._lock = threading.Lock()

    def take(self, source: str, per_hour: int) -> None:
        now = self.clock()
        with self._lock:
            calls = self._calls.get(source)
            if calls is None:
                if len(self._calls) >= self.MAX_SOURCES:
                    self._prune(now)
                calls = self._calls[source] = deque(maxlen=max(1, per_hour))
            elif calls.maxlen < per_hour:  # 同一個來源換成比較大的上限：舊的 deque 太短會讓上限失效
                calls = self._calls[source] = deque(calls, maxlen=per_hour)
            while calls and now - calls[0] >= 3600:
                calls.popleft()
            if len(calls) >= per_hour:
                raise FetchError("over_limit")
            calls.append(now)

    def _prune(self, now: float) -> None:
        for key in [k for k, q in self._calls.items() if not q or now - q[-1] >= 3600]:
            del self._calls[key]
        if len(self._calls) >= self.MAX_SOURCES:
            raise FetchError("over_limit")

    def used(self, source: str) -> int:
        now = self.clock()
        with self._lock:
            return sum(1 for t in self._calls.get(source, ()) if now - t < 3600)


BUDGET = Budget()

# ---------- 網路層 ----------


class Response(Protocol):
    status: int
    headers: dict

    def read(self, n: int = -1) -> bytes: ...
    def close(self) -> None: ...


class Transport(Protocol):
    def open(self, url: str, headers: dict, timeout: float, max_redirects: int) -> Response: ...


_ATTEMPT = threading.local()


def _watch(sock: socket.socket) -> None:
    """讓這次嘗試的計時器知道要關哪條 socket。

    登記的是 dup 出來的副本：TLS 包裝會把原本的 socket 物件 detach，但副本還指向同一條連線，
    所以 TLS 交握、讀 header 和本文都會被總時限切掉；TCP 連線階段由每個位址的 timeout 管。
    副本在這次嘗試結束時關掉。
    Linux / macOS 上 shutdown 會立刻叫醒卡住的 recv；Windows 不會，要等到該次 recv 的 timeout，
    所以 Windows 上實際上限是 deadline + timeout。
    """
    watchdog = getattr(_ATTEMPT, "watchdog", None)
    if watchdog is None:
        return
    try:
        copy = sock.dup()
    except OSError:
        return
    watchdog.add(copy)


class _Watchdog:
    """時間到就把這次嘗試開的 socket 關掉，卡在 recv 的那一邊會立刻收到錯誤。"""

    def __init__(self, seconds: float):
        self.fired = False
        self._socks: list[socket.socket] = []
        self._lock = threading.Lock()
        self._timer = threading.Timer(max(0.0, seconds), self._fire)
        self._timer.daemon = True

    def add(self, sock):
        with self._lock:
            self._socks.append(sock)
            fired = self.fired
        if fired:
            _shutdown(sock)

    def _fire(self):
        with self._lock:
            self.fired = True
            socks = list(self._socks)
        for sock in socks:
            _shutdown(sock)

    def __enter__(self):
        _ATTEMPT.watchdog = self
        self._timer.start()
        return self

    def __exit__(self, *exc):
        self._timer.cancel()
        self._timer.join(timeout=1)
        _ATTEMPT.watchdog = None
        with self._lock:
            socks, self._socks = self._socks, []
        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass
        return False


def _shutdown(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class _PinnedConnection(http.client.HTTPConnection):
    """連線前才解析並檢查位址，然後直接連到檢查過的 IP；連上後再確認對方位址。"""

    resolve: Callable = staticmethod(_resolve)

    def connect(self):
        addrs = public_addresses(self.host, self.port, self.resolve)
        last: OSError | None = None
        for family, sockaddr in addrs:
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(self.timeout)
                sock.connect(sockaddr)
                if not allowed_ip(sock.getpeername()[0]):
                    raise FetchError("invalid_url")
            except OSError as e:
                sock.close()
                last = e
                continue
            except BaseException:
                sock.close()
                raise
            self.sock = sock
            _watch(sock)  # 連上之後才登記：Windows 上連線前 dup 的副本切不到之後的連線
            return
        raise last or OSError("connect failed")


class _PinnedHTTPSConnection(http.client.HTTPSConnection, _PinnedConnection):
    """HTTPSConnection.connect 先呼叫 super().connect()（就是上面的 _PinnedConnection），再用原本的網域做 TLS 和 SNI。"""


_HTTPS_KW = {"check_hostname"} & set(inspect.signature(http.client.HTTPSConnection.__init__).parameters)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        kw = {"context": self._context}
        if "check_hostname" in _HTTPS_KW:  # Python 3.10 / 3.11 才有這個參數
            kw["check_hostname"] = getattr(self, "_check_hostname", None)
        return self.do_open(_PinnedHTTPSConnection, req, **kw)


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirects: int, checker: Callable[[str], str]):
        self.max_redirections = max_redirects
        self.checker = checker

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            self.checker(newurl)  # 每一跳都重新檢查格式；位址在連線時檢查
        except FetchError:
            if fp is not None:  # 3xx 那條連線先關掉再丟錯
                try:
                    fp.close()
                except OSError:
                    pass
            raise
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
            for name in list(new.headers):
                if name.lower() in SENSITIVE_HEADERS:
                    del new.headers[name]
            for name in list(new.unredirected_hdrs):
                if name.lower() in SENSITIVE_HEADERS:
                    del new.unredirected_hdrs[name]
        return new


class UrllibTransport:
    """真正連網的 transport：系統憑證、連線時才檢查並固定 IP、轉址次數有上限、不走 proxy。"""

    def __init__(self, checker: Callable[[str], str] = check_url):
        self.checker = checker

    def open(self, url, headers, timeout, max_redirects):
        context = _http._context(None, None)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHTTPHandler(),
                                             _PinnedHTTPSHandler(context=context),
                                             _CheckedRedirect(max_redirects, self.checker))
        req = urllib.request.Request(url, headers=headers)
        try:
            res = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            return _HTTPErrorResponse(e)
        return _UrllibResponse(res)


class _UrllibResponse:
    def __init__(self, res):
        self._res = res
        self.status = res.status
        self.headers = {k.lower(): v for k, v in res.headers.items()}
        self.url = res.geturl()

    def read(self, n=-1):
        # read1 收到一次資料就回來；read(n) 會一直等到讀滿 n 個位元組，伺服器慢慢滴資料時總時限就檢查不到
        read1 = getattr(self._res, "read1", None)
        return read1(n) if read1 and n and n > 0 else self._res.read(n)

    def close(self):
        self._res.close()


class _HTTPErrorResponse(_UrllibResponse):
    def __init__(self, e: urllib.error.HTTPError):
        self._res = e
        self.status = e.code
        self.headers = {k.lower(): v for k, v in (e.headers or {}).items()}
        self.url = e.geturl()


# ---------- 抓取 ----------


@dataclass
class Fetched:
    url: str
    status: int
    content_type: str
    body: bytes
    attempts: int
    headers: dict = field(default_factory=dict)

    def text(self) -> str:
        charset = "utf-8"
        m = re.search(r"charset=([\w\-]+)", self.headers.get("content-type", ""), re.I)
        if m:
            charset = m.group(1)
        try:
            return self.body.decode(charset, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


def _classify(status: int, content_type: str, allowed: tuple[str, ...] | None) -> str | None:
    if 300 <= status < 400:
        return "redirect"  # 轉址太多次，或是沒有跟著走的 3xx
    if status in (401, 403, 451):
        return "blocked"
    if status == 402:
        return "paywall"
    if status in (404, 410):
        return "not_found"
    if status == 429:
        return "blocked"
    if status >= 500:
        return "upstream"
    if status >= 400 or status < 200:
        return "blocked"
    if allowed and not any(content_type.startswith(a) for a in allowed):
        return "unsupported"
    return None


_DIGITS = re.compile(r"[0-9]{1,15}")


def _int_header(value) -> int | None:
    """只接受 ASCII 數字（"²".isdigit() 也是 True，但 int() 會失敗）。"""
    value = (value or "").strip()
    return int(value) if _DIGITS.fullmatch(value) else None


def _read_upto(res: Response, n: int, deadline: float, clock: Callable[[], float]) -> bytes:
    """最多讀 n 個位元組（錯誤狀態的除錯預覽），到總時限就停，不丟錯。"""
    chunks, total = [], 0
    while total < n and clock() <= deadline:
        chunk = res.read(n - total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _read_capped(res: Response, max_bytes: int, deadline: float, clock: Callable[[], float]) -> bytes:
    declared = _int_header(res.headers.get("content-length"))
    if declared is not None and declared > max_bytes:
        raise FetchError("too_large")
    chunks, total = [], 0
    while True:
        if clock() > deadline:
            raise FetchError("timeout")
        chunk = res.read(min(CHUNK, max_bytes + 1 - total))
        if not chunk:
            # 帶 Transfer-Encoding 時 http.client 依規定忽略 Content-Length，長度就不能拿來比
            if declared is not None and total < declared and not res.headers.get("transfer-encoding"):
                raise FetchError("network")  # 連線提早結束，本文不完整
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise FetchError("too_large")
        chunks.append(chunk)


def fetch(url: str, *, source: str, limits: Limits = DEFAULT, transport: Transport | None = None,
          headers: dict | None = None, accept: tuple[str, ...] | None = None, budget: Budget | None = None,
          sleep: Callable[[float], None] = time.sleep, checker: Callable[[str], str] = check_url,
          jitter: Callable[[], float] = random.random, clock: Callable[[], float] = time.monotonic) -> Fetched:
    """抓一個網址。成功回 Fetched；失敗丟 FetchError（已分類）。

    accept：允許的 Content-Type 前綴，例如 ("text/html", "application/xhtml")；不在裡面就是 unsupported。
    headers：額外的 header；不要放機密（跨網域轉址時會拿掉常見的機密 header，但不保證全部）。
    每次嘗試（含重試）都算進 source 的每小時上限。每次嘗試結束都會關掉連線。
    """
    checker(url)
    transport = transport or UrllibTransport(checker)
    budget = budget or BUDGET
    send = {"User-Agent": USER_AGENT, "Accept": ", ".join(accept) if accept else "*/*", **(headers or {})}
    attempt = 0
    while True:
        attempt += 1
        budget.take(source, limits.per_hour)
        try:
            return _attempt(url, transport, send, limits, accept, attempt, clock)
        except FetchError as e:
            if not e.retryable or attempt > limits.retries:
                raise
            wait = limits.backoff * (2 ** (attempt - 1)) * (1 + 0.25 * jitter())
            if e.retry_after is not None:
                if e.retry_after > limits.backoff_max:
                    raise  # 上游要我們等更久：不要提早重試，留給下一輪排程
                wait = max(wait, e.retry_after)
            sleep(min(wait, limits.backoff_max))


# 從網路層冒出來、要分類成 FetchError 的例外。http.client.HTTPException（BadStatusLine、IncompleteRead、
# InvalidURL…）不是 OSError；header 值不合法會丟 ValueError；網域格式錯會丟 UnicodeError。
_NETWORK_ERRORS = (OSError, http.client.HTTPException, UnicodeError, ValueError)


def _classify_exception(e: BaseException) -> FetchError:
    if isinstance(e, FetchError):
        return e
    if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
        reason = e.reason
        if isinstance(reason, FetchError):
            return reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return FetchError("timeout")
        return FetchError("network")
    if isinstance(e, (TimeoutError, socket.timeout)):
        return FetchError("timeout")
    if isinstance(e, (http.client.InvalidURL, UnicodeError)):
        return FetchError("invalid_url")
    return FetchError("network")


def _attempt(url, transport, send, limits, accept, attempt, clock) -> Fetched:
    res = None
    deadline = clock() + limits.deadline
    watchdog = _Watchdog(limits.deadline)
    try:
        try:
            with watchdog:
                res = transport.open(url, send, limits.timeout, limits.max_redirects)
                content_type = (res.headers.get("content-type") or "").split(";")[0].strip().lower()
                kind = _classify(res.status, content_type, accept)
                if kind:
                    try:
                        preview = _read_upto(res, PREVIEW_BYTES, deadline, clock)
                    except _NETWORK_ERRORS:
                        preview = b""
                    retry_after = _int_header(res.headers.get("retry-after")) if res.status == 429 else None
                    raise FetchError(kind, status=res.status, detail=preview,
                                     retry_after=float(retry_after) if retry_after is not None else None)
                body = _read_capped(res, limits.max_bytes, deadline, clock)
                if watchdog.fired:  # Linux / macOS 上被關掉的 socket 會回 EOF，不能當成讀完
                    raise FetchError("timeout")
        except FetchError as e:
            if watchdog.fired and e.kind == "network":  # 計時器關掉 socket 造成的提早結束，算逾時
                raise FetchError("timeout") from None
            raise
        except _NETWORK_ERRORS as e:
            if watchdog.fired:  # 計時器關掉了 socket：這是總時限到了，不是網路斷線
                raise FetchError("timeout") from None
            raise _classify_exception(e) from None
        return Fetched(url=getattr(res, "url", url) or url, status=res.status, content_type=content_type,
                       body=body, attempts=attempt, headers=dict(res.headers))
    finally:
        if res is not None:
            try:
                res.close()
            except _NETWORK_ERRORS:
                pass


def cap_items(items: Iterable, limits: Limits = DEFAULT) -> tuple[list, bool]:
    """最多取 max_items 筆。回傳 (前幾筆, 有沒有被截掉)。不會先把整個 iterable 讀完。"""
    out = []
    for item in items:
        if len(out) >= limits.max_items:
            return out, True
        out.append(item)
    return out, False
