"""對外抓取規則（ticket 09）：每個上限都有測試碰到、錯誤分類、scrubber、連線釋放、測試替身、不連真實網路。"""
import http.client
import socket
import unittest
import unittest.mock
import urllib.error
import urllib.request

from easyread import fetch
from easyread.fetch import FetchError, Limits

from tests.doubles import PUBLIC_IP, FakeEngine, FakeMonotonic, FakeResponse, FakeTransport, dns, fixture, public_dns

HTML = ("text/html",)


class FetchCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeMonotonic()
        self.budget = fetch.Budget(clock=self.clock)

    def run_fetch(self, transport, limits=Limits(), **kw):
        kw.setdefault("accept", HTML)
        return fetch.fetch("https://news.example/a", source="news", limits=limits, transport=transport,
                           budget=self.budget, sleep=self.clock.sleep, checker=lambda u: fetch.check_url(u, public_dns),
                           jitter=lambda: 0.0, **kw)

    def assertKind(self, kind, transport, **kw):
        with self.assertRaises(FetchError) as ctx:
            self.run_fetch(transport, **kw)
        self.assertEqual(ctx.exception.kind, kind)
        return ctx.exception


class LimitsTest(FetchCase):
    def test_success_reads_fixture_and_closes(self):
        t = FakeTransport(fixture("article.html"))
        got = self.run_fetch(t)
        self.assertIn("範例晶圓廠", got.text())
        self.assertEqual((got.status, got.content_type, got.attempts), (200, "text/html", 1))
        self.assertTrue(t.responses[0].closed)
        sent = t.requests[0]
        self.assertEqual(sent["timeout"], Limits().timeout)
        self.assertEqual(sent["max_redirects"], Limits().max_redirects)
        self.assertTrue(sent["headers"]["User-Agent"].startswith("NewsRead/"))

    def test_timeout_is_passed_and_timeouts_are_classified(self):
        t = FakeTransport(TimeoutError(), urllib.error.URLError(socket.timeout("timed out")))
        e = self.assertKind("timeout", t, limits=Limits(timeout=3, retries=1))
        self.assertEqual([r["timeout"] for r in t.requests], [3, 3])
        self.assertEqual(e.message, "連線逾時")

    def test_max_bytes_from_content_length_and_from_streamed_body(self):
        declared = FakeResponse(body=b"x" * 10, headers={"Content-Type": "text/html", "Content-Length": "11"})
        self.assertKind("too_large", FakeTransport(declared), limits=Limits(max_bytes=10))
        self.assertTrue(declared.closed)
        self.assertEqual(declared.read_calls, 0)
        streamed = FakeResponse(body=b"x" * 11, headers={"Content-Type": "text/html"}, chunk=4)
        self.assertKind("too_large", FakeTransport(streamed), limits=Limits(max_bytes=10))
        self.assertTrue(streamed.closed)
        exact = FakeResponse(body=b"x" * 10, headers={"Content-Type": "text/html"}, chunk=3)
        self.assertEqual(len(self.run_fetch(FakeTransport(exact), limits=Limits(max_bytes=10)).body), 10)

    def test_never_reads_more_than_max_bytes_plus_one(self):
        res = FakeResponse(body=b"x" * 1_000_000, headers={"Content-Type": "text/html"})
        self.assertKind("too_large", FakeTransport(res), limits=Limits(max_bytes=100))
        self.assertLessEqual(res._pos, 101)

    def test_max_items(self):
        items, cut = fetch.cap_items(iter(range(10)), Limits(max_items=3))
        self.assertEqual((items, cut), ([0, 1, 2], True))
        self.assertEqual(fetch.cap_items([1, 2, 3], Limits(max_items=3)), ([1, 2, 3], False))

        def endless():
            n = 0
            while True:
                yield n
                n += 1
        self.assertEqual(len(fetch.cap_items(endless(), Limits(max_items=5))[0]), 5)

    def test_retries_with_exponential_backoff_then_gives_up(self):
        t = FakeTransport(*[FakeResponse(status=503, body="down") for _ in range(4)])
        e = self.assertKind("upstream", t, limits=Limits(retries=3, backoff=1.0))
        self.assertEqual(len(t.requests), 4)
        self.assertEqual(self.clock.slept, [1.0, 2.0, 4.0])
        self.assertTrue(all(r.closed for r in t.responses))
        self.assertEqual(e.status, 503)

    def test_retry_after_is_honoured_up_to_the_backoff_cap(self):
        t = FakeTransport(FakeResponse(status=429, headers={"Retry-After": "10"}), fixture("article.html"))
        got = self.run_fetch(t, limits=Limits(retries=2, backoff_max=30))
        self.assertEqual(got.attempts, 2)
        self.assertEqual(self.clock.slept, [10])

    def test_retry_after_longer_than_the_cap_gives_up_instead_of_retrying_early(self):
        t = FakeTransport(FakeResponse(status=429, headers={"Retry-After": "120"}))
        e = self.assertKind("blocked", t, limits=Limits(retries=2, backoff_max=30))
        self.assertEqual((len(t.requests), self.clock.slept, e.retry_after), (1, [], 120.0))

    def test_budget_grows_when_a_source_uses_a_larger_limit(self):
        b = fetch.Budget(clock=self.clock)
        for _ in range(3):
            b.take("s", 3)
        with self.assertRaises(FetchError):
            b.take("s", 3)
        for _ in range(7):
            b.take("s", 10)
        with self.assertRaises(FetchError):
            b.take("s", 10)  # 第 11 次：上限 10 要真的有效
        self.assertEqual(b.used("s"), 10)

    def test_budget_prunes_idle_sources_and_caps_their_number(self):
        b = fetch.Budget(clock=self.clock)
        b.MAX_SOURCES = 3
        for name in ("a", "b", "c"):
            b.take(name, 5)
        with self.assertRaises(FetchError):
            b.take("d", 5)  # 三個都還在這一小時內：不清，拒絕新的來源
        self.clock.now += 3600
        b.take("d", 5)
        self.assertEqual(sorted(b._calls), ["d"])

    def test_non_retryable_errors_do_not_retry(self):
        for status, kind in ((401, "blocked"), (403, "blocked"), (402, "paywall"), (404, "not_found"), (410, "not_found")):
            with self.subTest(status=status):
                t = FakeTransport(FakeResponse(status=status))
                self.assertKind(kind, t, limits=Limits(retries=3))
                self.assertEqual(len(t.requests), 1)
                self.assertTrue(t.responses[0].closed)

    def test_unsupported_content_type(self):
        res = FakeResponse(body=b"%PDF", headers={"Content-Type": "application/pdf"})
        self.assertKind("unsupported", FakeTransport(res))
        self.assertTrue(res.closed)

    def test_hourly_limit_per_source_counts_retries(self):
        limits = Limits(per_hour=3, retries=5, backoff=1)
        t = FakeTransport(*[FakeResponse(status=500) for _ in range(5)])
        self.assertKind("over_limit", t, limits=limits)
        self.assertEqual(len(t.requests), 3)  # 第 4 次嘗試被每小時上限擋下
        self.assertKind("over_limit", FakeTransport(), limits=limits)
        other = fetch.fetch("https://other.example/", source="other", limits=limits, transport=FakeTransport(fixture("article.html")),
                            budget=self.budget, sleep=self.clock.sleep, checker=lambda u: fetch.check_url(u, public_dns))
        self.assertEqual(other.status, 200)
        self.clock.now += 3600
        self.assertEqual(self.run_fetch(FakeTransport(fixture("article.html")), limits=limits).status, 200)

    def test_budget_memory_is_bounded(self):
        b = fetch.Budget(clock=self.clock)
        for _ in range(5):
            b.take("s", 5)
            self.clock.now += 1000
        self.assertLessEqual(len(b._calls["s"]), 5)


class ReleaseTest(FetchCase):
    def test_connection_released_when_body_read_fails(self):
        res = FakeResponse(body=b"abcdef", headers={"Content-Type": "text/html"}, chunk=2, read_error=ConnectionResetError())
        self.assertKind("network", FakeTransport(res, res), limits=Limits(retries=0))
        self.assertTrue(res.closed)

    def test_connection_released_when_read_times_out(self):
        res = FakeResponse(body=b"abcdef", headers={"Content-Type": "text/html"}, chunk=2, read_error=TimeoutError())
        self.assertKind("timeout", FakeTransport(res), limits=Limits(retries=0))
        self.assertTrue(res.closed)

    def test_connection_released_on_early_exit_from_caller(self):
        class Stop(BaseException):
            pass

        res = FakeResponse(body=b"abcdef", headers={"Content-Type": "text/html"}, chunk=2, read_error=Stop())
        with self.assertRaises(Stop):
            self.run_fetch(FakeTransport(res))
        self.assertTrue(res.closed)


class ErrorsTest(unittest.TestCase):
    def test_log_line_is_fixed_and_detail_is_scrubbed(self):
        raw = ("error for fred@example.com: api_key=sk-ant-abcdefghijklmnopqrstuv token: 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawq "
               "Authorization: Bearer abcdefghijklmnop https://alice:hunter2@news.example/x?user=alice&q=1")
        e = FetchError("blocked", status=403, detail=raw)
        self.assertEqual(e.log_line(), "fetch_error kind=blocked status=403 來源拒絕存取")
        for secret in ("fred@example.com", "sk-ant-abcdefghijklmnopqrstuv", "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawq",
                       "abcdefghijklmnop", "hunter2", "user=alice"):
            self.assertNotIn(secret, e.detail)
            self.assertNotIn(secret, e.log_line())
        self.assertLessEqual(len(FetchError("upstream", detail="x" * 5000).detail), fetch.DETAIL_CHARS)
        self.assertEqual(e.public(), {"kind": "blocked", "message": "來源拒絕存取", "status": 403})

    def test_scrub_common_key_formats(self):
        samples = ["ghp_abcdefghijklmnopqrstuvwxyz0123", "AKIAABCDEFGHIJKLMNOP", "AIzaSyA1234567890abcdefghijklmnopqrs",
                   "xoxb-1234567890-abcdef", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghij",
                   '"password": "s3cret!"', "sessionid=abcd1234", "sk-proj-ABCDEFGHIJKLMNOPQRSTUV",
                   "sk_live_abcdefghijklmnop", "rk_test_abcdefghijklmnop", "secret_key=abc123zz", "aws_secret_access_key=ABCDEFzz",
                   "key=abc123zz", "access_key=abc123zz", "OPENAI_API_KEY=abc123zz", "x_api_key=abc123zz",
                   "GITHUB_TOKEN=abc123zz", "DB_PASSWORD=abc123zz", "stripe_secret_key=abc123zz"]
        for s in samples:
            with self.subTest(s=s):
                out = fetch.scrub(f"before {s} after")
                self.assertTrue(out.startswith("before ") and out.endswith(" after"), out)
                self.assertNotIn(s.split(":")[-1].strip(' "'), out)
        self.assertEqual(fetch.scrub(b"plain \xe4\xb8\xad"), "plain 中")
        self.assertNotIn("fred", fetch.scrub("see fred%40example.com now"))
        self.assertEqual(fetch.scrub("monkey=banana"), "monkey=banana")
        url = "https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawq/sendMessage"
        self.assertNotIn("AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawq", fetch.scrub(url))  # 名稱裡剛好有 key 的一般文字不遮

    def test_scrub_input_is_capped(self):
        self.assertEqual(len(fetch.scrub("a" * (fetch.SCRUB_MAX_CHARS * 3))), fetch.SCRUB_MAX_CHARS)
        self.assertEqual(fetch.scrub(None), "")

    def test_paywall_detail_keeps_only_a_scrubbed_preview(self):
        body = "請登入 " + "x" * 10_000 + " reader@example.org"
        clock = FakeMonotonic()
        t = FakeTransport(FakeResponse(status=402, body=body))
        with self.assertRaises(FetchError) as ctx:
            fetch.fetch("https://news.example/p", source="news", transport=t, budget=fetch.Budget(clock), sleep=clock.sleep,
                        checker=lambda u: fetch.check_url(u, public_dns))
        self.assertEqual(ctx.exception.kind, "paywall")
        self.assertLessEqual(len(ctx.exception.detail), fetch.DETAIL_CHARS)
        self.assertTrue(t.responses[0].closed)


class UrlCheckTest(unittest.TestCase):
    def test_only_public_http_urls(self):
        self.assertEqual(fetch.check_url("https://news.example/a?b=1", public_dns), "https://news.example/a?b=1")
        local = lambda h, p=None: dns("127.0.0.1")(h, p) if h == "localhost" else public_dns(h, p)  # noqa: E731
        for url in ("file:///etc/passwd", "ftp://x.example/", "javascript:alert(1)", "https://", "http://127.0.0.1:8765/api/ledger",
                    "http://localhost/", "http://[::1]/", "http://10.0.0.5/", "http://192.168.1.1/", "http://169.254.169.254/latest",
                    "http://0.0.0.0/", "https://user:pw@news.example/", "http://100.64.0.1/", "http://[::ffff:127.0.0.1]/",
                    "http://[64:ff9b::7f00:1]/", "https://news.example/a b", "http://news.example:99999/"):
            with self.subTest(url=url), self.assertRaises(FetchError) as ctx:
                fetch.check_url(url, local)
            self.assertEqual(ctx.exception.kind, "invalid_url")
        with self.assertRaises(FetchError) as ctx:
            fetch.check_url("https://rebind.example/", dns(PUBLIC_IP, "10.1.2.3"))
        self.assertEqual(ctx.exception.kind, "invalid_url")

    def test_allowed_ip_only_accepts_global_addresses(self):
        for ip in ("8.8.8.8", PUBLIC_IP, "2606:4700::1111"):
            self.assertTrue(fetch.allowed_ip(ip), ip)
        for ip in ("127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.0.1", "100.64.0.1", "192.0.0.1", "169.254.1.1", "0.0.0.0",
                   "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "2002:7f00:1::",
                   "64:ff9b::7f00:1", "64:ff9b::808:808", "2001::1", "::7f00:1", "fec0::1", "not-an-ip"):
            self.assertFalse(fetch.allowed_ip(ip), ip)

    def test_dns_failure_is_network_and_bad_hostnames_do_not_escape(self):
        def fail(host, port=None):
            raise socket.gaierror("no such host")
        for resolve in (fail, fetch._resolve):
            host = "nope.example" if resolve is fail else "a" * 70 + ".example"  # 標籤超過 63 字：idna 丟 UnicodeError
            with self.subTest(host=host), self.assertRaises(FetchError) as ctx:
                fetch.public_addresses(host, 443, resolve)
            self.assertEqual(ctx.exception.kind, "network")

    def test_format_check_does_not_resolve_without_a_resolver(self):
        self.assertEqual(fetch.check_url("https://unresolvable.invalid/x"), "https://unresolvable.invalid/x")

    def test_invalid_url_is_checked_before_any_request(self):
        t = FakeTransport()
        with self.assertRaises(FetchError):
            fetch.fetch("http://127.0.0.1/", source="x", transport=t, budget=fetch.Budget(FakeMonotonic()))
        self.assertEqual(t.requests, [])


class PinnedConnectionTest(unittest.TestCase):
    """DNS rebinding：位址在連線那一刻才解析和檢查，而且直接連到檢查過的 IP。"""

    def connect(self, resolve, host="news.example"):
        conn = fetch._PinnedConnection(host, 80, timeout=1)
        conn.resolve = resolve  # 實例屬性，不會被綁成方法
        try:
            conn.connect()
        finally:
            conn.close()

    def test_host_resolving_to_loopback_at_connect_time_is_refused(self):
        calls = []

        def flip(host, port=None):  # 第一次查是公開位址（通過預先檢查），連線時改成本機
            calls.append(host)
            return public_dns(host, port) if len(calls) == 1 else dns("127.0.0.1")(host, port)

        self.assertEqual(fetch.check_url("http://news.example/", flip), "http://news.example/")
        with self.assertRaises(FetchError) as ctx:
            self.connect(flip)
        self.assertEqual(ctx.exception.kind, "invalid_url")
        self.assertEqual(len(calls), 2)

    def test_connects_to_the_checked_ip_not_the_hostname(self):
        with self.assertRaisesRegex(OSError, PUBLIC_IP.replace(".", r"\.")):  # 測試的網路防護擋下，訊息裡是檢查過的 IP
            self.connect(public_dns)

    def test_mixed_answers_are_refused_before_any_socket_opens(self):
        with self.assertRaises(FetchError):
            self.connect(dns(PUBLIC_IP, "192.168.1.10"))

    def test_https_connection_uses_the_pinned_connect(self):
        mro = fetch._PinnedHTTPSConnection.__mro__
        self.assertLess(mro.index(fetch.http.client.HTTPSConnection), mro.index(fetch._PinnedConnection))
        self.assertLess(mro.index(fetch._PinnedConnection), mro.index(fetch.http.client.HTTPConnection))

    def test_transport_ignores_proxy_environment(self):
        handlers = []
        real = urllib.request.build_opener

        def spy(*hs):
            handlers.extend(hs)
            return real(*hs)

        env = {"HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
        with unittest.mock.patch.dict("os.environ", env), unittest.mock.patch("urllib.request.build_opener", spy), \
                self.assertRaises(FetchError):
            fetch.UrllibTransport().open("http://127.0.0.1:9/", {}, 1, 5)
        proxies = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual([p.proxies for p in proxies], [{}])


class RedirectTest(unittest.TestCase):
    def handler(self):
        return fetch._CheckedRedirect(5, lambda u: fetch.check_url(u, public_dns))

    def test_redirect_to_private_address_is_refused(self):
        h = self.handler()
        req = urllib.request.Request("https://news.example/a")
        with self.assertRaises(FetchError) as ctx:
            h.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:8765/api/ledger")
        self.assertEqual(ctx.exception.kind, "invalid_url")
        self.assertEqual(h.max_redirections, 5)

    def test_refused_redirect_closes_the_3xx_response(self):
        class Fp:
            closed = False

            def close(self):
                self.closed = True

        fp = Fp()
        with self.assertRaises(FetchError):
            self.handler().redirect_request(urllib.request.Request("https://news.example/a"), fp, 302, "Found", {},
                                            "http://10.0.0.1/")
        self.assertTrue(fp.closed)

    def test_sensitive_headers_dropped_on_cross_host_redirect_only(self):
        h = self.handler()
        req = urllib.request.Request("https://news.example/a", headers={"Authorization": "Bearer x", "Cookie": "a=b", "User-Agent": "NewsRead"})
        other = h.redirect_request(req, None, 302, "Found", {}, "https://elsewhere.example/b")
        names = {k.lower() for k in other.headers}
        self.assertNotIn("authorization", names)
        self.assertNotIn("cookie", names)
        self.assertIn("user-agent", names)
        same = h.redirect_request(req, None, 302, "Found", {}, "https://news.example/c")
        self.assertIn("authorization", {k.lower() for k in same.headers})

    def test_unfollowed_or_exhausted_redirect_is_an_error(self):
        clock = FakeMonotonic()
        for status in (301, 302, 304, 307):
            with self.subTest(status=status):
                t = FakeTransport(FakeResponse(status=status, body="moved", headers={"Content-Type": "text/html"}))
                with self.assertRaises(FetchError) as ctx:
                    fetch.fetch("https://news.example/", source="r", transport=t, budget=fetch.Budget(clock), sleep=clock.sleep,
                                checker=lambda u: fetch.check_url(u, public_dns))
                self.assertEqual(ctx.exception.kind, "redirect")
                self.assertTrue(t.responses[0].closed)


class HostileServerTest(FetchCase):
    def test_protocol_errors_are_classified(self):
        cases = [(http.client.BadStatusLine("garbage"), "network"), (http.client.InvalidURL("bad url"), "invalid_url"),
                 (ValueError("Invalid header value b'secret\r\n'"), "network"), (UnicodeError("label too long"), "invalid_url"),
                 (urllib.error.URLError(ConnectionRefusedError()), "network")]
        for exc, kind in cases:
            with self.subTest(exc=type(exc).__name__):
                e = self.assertKind(kind, FakeTransport(exc), limits=Limits(retries=0))
                self.assertNotIn("secret", e.log_line())

    def test_incomplete_body_is_network_and_released(self):
        res = FakeResponse(body=b"abcdef", headers={"Content-Type": "text/html"}, chunk=2,
                           read_error=http.client.IncompleteRead(b"ab", 10))
        self.assertKind("network", FakeTransport(res), limits=Limits(retries=0))
        self.assertTrue(res.closed)

    def test_non_ascii_digits_in_numeric_headers_do_not_crash(self):
        res = FakeResponse(body=b"ok", headers={"Content-Type": "text/html", "Content-Length": "²"})
        self.assertEqual(self.run_fetch(FakeTransport(res)).body, b"ok")
        t = FakeTransport(FakeResponse(status=429, headers={"Retry-After": "²"}), fixture("article.html"))
        self.assertEqual(self.run_fetch(t, limits=Limits(retries=1, backoff=1)).attempts, 2)
        self.assertEqual(self.clock.slept, [1.0])

    def test_slow_drip_hits_the_per_attempt_deadline(self):
        clock = self.clock

        class Drip(FakeResponse):
            def read(self, n=-1):
                clock.now += 10  # 每次讀一個位元組要 10 秒，單次讀取不逾時，但總時間會超過
                return super().read(1)

        res = Drip(body=b"x" * 100, headers={"Content-Type": "text/html"})
        self.assertKind("timeout", FakeTransport(res), limits=Limits(deadline=35, retries=0), clock=clock)
        self.assertTrue(res.closed)
        self.assertLessEqual(res._pos, 4)

    def test_watchdog_cuts_slow_headers_through_the_real_transport(self):
        """連線之後一直不送完 header：每 0.2 秒送一行。總時限到了，計時器關掉 socket，回 timeout。"""
        import threading
        import time as real_time

        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        stop = threading.Event()

        def serve():
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.recv(4096)
                conn.sendall(b"HTTP/1.1 200 OK\r\n")
                n = 0
                while not stop.is_set() and n < 200:
                    try:
                        conn.sendall(f"X-Slow-{n}: 1\r\n".encode())
                    except OSError:
                        return
                    n += 1
                    real_time.sleep(0.2)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(server.close)
        self.addCleanup(stop.set)
        port = server.getsockname()[1]
        before = threading.active_count()
        started = real_time.monotonic()
        with unittest.mock.patch.object(fetch, "allowed_ip", lambda address: True):  # 只在這個測試放行本機
            with self.assertRaises(FetchError) as ctx:
                fetch.fetch(f"http://127.0.0.1:{port}/", source="slow", limits=Limits(timeout=1, deadline=1.0, retries=0),
                            budget=fetch.Budget(), checker=lambda u: u)
        self.assertEqual(ctx.exception.kind, "timeout")
        self.assertLess(real_time.monotonic() - started, 4.0)
        stop.set()
        thread.join(timeout=5)
        self.assertLessEqual(threading.active_count(), before)  # 計時器執行緒有收掉

    def test_watchdog_cuts_slow_headers_over_https(self):
        """HTTPS 版本：TLS 包裝後計時器還是切得掉。用 openssl 臨時產生自簽憑證；沒有 openssl 就跳過。"""
        import shutil
        import ssl
        import subprocess
        import tempfile
        import threading
        import time as real_time
        from pathlib import Path

        openssl = shutil.which("openssl")
        if not openssl:
            self.skipTest("沒有 openssl，產生不了測試憑證")  # i18n-ok：測試訊息
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        cert, key = Path(tmp.name) / "cert.pem", Path(tmp.name) / "key.pem"
        made = subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                               "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
                               "-keyout", str(key), "-out", str(cert)], capture_output=True, timeout=30)
        if made.returncode != 0:
            self.skipTest("openssl 產生憑證失敗")  # i18n-ok：測試訊息
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert, key)
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        stop = threading.Event()

        def serve():
            try:
                raw, _ = server.accept()
                conn = server_ctx.wrap_socket(raw, server_side=True)
            except (OSError, ssl.SSLError):
                return
            with conn:
                try:
                    conn.recv(4096)
                    conn.sendall(b"HTTP/1.1 200 OK\r\n")
                    n = 0
                    while not stop.is_set() and n < 200:
                        conn.sendall(f"X-Slow-{n}: 1\r\n".encode())
                        n += 1
                        real_time.sleep(0.2)
                except (OSError, ssl.SSLError):
                    return

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(server.close)
        self.addCleanup(stop.set)
        port = server.getsockname()[1]
        client_ctx = ssl.create_default_context(cafile=str(cert))
        started = real_time.monotonic()
        with unittest.mock.patch.object(fetch, "allowed_ip", lambda address: True),                 unittest.mock.patch.object(fetch._http, "_context", lambda *a: client_ctx):
            with self.assertRaises(FetchError) as ctx:
                fetch.fetch(f"https://127.0.0.1:{port}/", source="slow-tls", limits=Limits(timeout=1, deadline=1.0, retries=0),
                            budget=fetch.Budget(), checker=lambda u: u)
        self.assertEqual(ctx.exception.kind, "timeout")
        self.assertLess(real_time.monotonic() - started, 4.0)
        stop.set()
        thread.join(timeout=5)

    def test_eof_after_the_watchdog_fired_is_a_timeout_not_a_short_body(self):
        """Linux / macOS 上，計時器關掉 socket 後，卡住的 recv 會回 b""。收到一半的本文不能當成成功。"""
        import time as real_time

        class Stall(FakeResponse):
            def read(self, n=-1):
                if self._pos == 0:
                    return super().read(10)
                real_time.sleep(0.3)  # 卡著等封包，這段時間計時器觸發
                return b""

        res = Stall(body=b"x" * 1000, headers={"Content-Type": "text/html"})
        with self.assertRaises(FetchError) as ctx:
            fetch.fetch("https://news.example/a", source="news", limits=Limits(deadline=0.1, retries=0),
                        transport=FakeTransport(res), budget=fetch.Budget(), checker=lambda u: u, accept=HTML)
        self.assertEqual(ctx.exception.kind, "timeout")
        self.assertTrue(res.closed)

    def test_body_shorter_than_content_length_is_a_network_error(self):
        res = FakeResponse(body=b"x" * 10, headers={"Content-Type": "text/html", "Content-Length": "1000"})
        self.assertKind("network", FakeTransport(res), limits=Limits(retries=0))
        self.assertTrue(res.closed)

    def test_chunked_body_ignores_a_conflicting_content_length(self):
        res = FakeResponse(body=b"x" * 10, headers={"Content-Type": "text/html", "Content-Length": "1000",
                                                    "Transfer-Encoding": "chunked"})
        self.assertEqual(self.run_fetch(FakeTransport(res)).body, b"x" * 10)

    def test_short_body_after_the_watchdog_fired_is_a_timeout(self):
        import time as real_time

        class Stall(FakeResponse):
            def read(self, n=-1):
                if self._pos == 0:
                    return super().read(10)
                real_time.sleep(0.3)
                return b""

        res = Stall(body=b"x" * 1000, headers={"Content-Type": "text/html", "Content-Length": "1000"})
        with self.assertRaises(FetchError) as ctx:
            fetch.fetch("https://news.example/a", source="news", limits=Limits(deadline=0.1, retries=0),
                        transport=FakeTransport(res), budget=fetch.Budget(), checker=lambda u: u, accept=HTML)
        self.assertEqual(ctx.exception.kind, "timeout")

    def test_watchdog_still_cuts_a_socket_after_it_is_rewrapped(self):
        """TLS 包裝會 detach 原本的 socket 物件；計時器登記的是副本，照樣切得掉。這次嘗試結束後副本也關掉。"""
        import time as real_time

        a, b = socket.socketpair()
        self.addCleanup(b.close)
        watchdog = fetch._Watchdog(0.05)
        with watchdog:
            fetch._watch(a)
            wrapped = socket.socket(fileno=a.detach())  # 模擬 ssl 包裝換掉 socket 物件
            self.addCleanup(wrapped.close)
            copies = list(watchdog._socks)
            real_time.sleep(0.3)
            self.assertTrue(watchdog.fired)
            b.settimeout(2)
            self.assertEqual(b.recv(10), b"")  # 對方收到連線關閉
        self.assertEqual(len(copies), 1)
        self.assertTrue(all(c.fileno() == -1 for c in copies))

    def test_real_slow_drip_socket_is_cut_at_the_deadline(self):
        """真的本機 socket：每 0.2 秒送 1 個位元組。read(65536) 會一直等，所以要用 read1 才檢查得到總時限。"""
        import threading
        import time as real_time

        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        stop = threading.Event()

        def serve():
            conn, _ = server.accept()
            with conn:
                conn.recv(4096)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                while not stop.is_set():
                    try:
                        conn.sendall(b"x")
                    except OSError:
                        return
                    real_time.sleep(0.2)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(server.close)
        self.addCleanup(stop.set)
        conn = http.client.HTTPConnection("127.0.0.1", server.getsockname()[1], timeout=1)
        conn.request("GET", "/")
        raw = conn.getresponse()
        raw.url = "http://127.0.0.1/"  # urllib 才會設這個屬性；直接用 http.client 時自己補
        res = fetch._UrllibResponse(raw)
        started = real_time.monotonic()
        with self.assertRaises(FetchError) as ctx:
            fetch._read_capped(res, 1_000_000, real_time.monotonic() + 1.0, real_time.monotonic)
        elapsed = real_time.monotonic() - started
        res.close()
        conn.close()
        self.assertEqual(ctx.exception.kind, "timeout")
        self.assertLess(elapsed, 3.0)  # 總時限 1 秒 + 最多一次 socket 逾時 1 秒


class DoublesTest(unittest.TestCase):
    def test_fake_engine_returns_fixed_output_and_records_calls(self):
        engine = FakeEngine({"triage": {"importance": "high"}}, model="m1")
        out = engine.run("triage", "prompt text")
        self.assertEqual(out["text"], '{"importance": "high"}')
        self.assertEqual((out["model"], out["cost_usd"]), ("m1", None))
        self.assertEqual(engine.calls[0]["prompt"], "prompt text")
        with self.assertRaises(AssertionError):
            engine.run("translate", "x")
        seq = FakeEngine(["a", RuntimeError("rate limited")])
        self.assertEqual(seq.run("t", "p")["text"], "a")
        with self.assertRaises(RuntimeError):
            seq.run("t", "p")

    def test_tests_cannot_use_connect_ex_or_dns(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaisesRegex(OSError, "may not use the network"):
                s.connect_ex(("192.0.2.1", 80))
        finally:
            s.close()
        with self.assertRaisesRegex(OSError, "may not use the network"):
            socket.getaddrinfo("example.com", 443)
        self.assertTrue(socket.getaddrinfo("127.0.0.1", 80))

    def test_tests_cannot_reach_the_real_network(self):
        with self.assertRaisesRegex(OSError, "may not use the network"):
            socket.create_connection(("93.184.216.34", 80), timeout=1)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaisesRegex(OSError, "may not use the network"):
                s.connect(("93.184.216.34", 443))
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
