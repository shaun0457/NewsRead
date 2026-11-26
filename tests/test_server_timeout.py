"""Ticket 73：一般請求讀寫 socket 有逾時；宣告了 body 卻不送的連線逾時後被關掉。presence WebSocket 不受影響。"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock

from easyread import launch, presence, server
from tests.test_presence import _ws_connect

SHORT = 0.5


class SocketTimeoutTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(server.Handler, "timeout", SHORT)
        patcher.start()
        self.addCleanup(patcher.stop)
        lib = tempfile.TemporaryDirectory()
        self.addCleanup(lib.cleanup)
        env = mock.patch.dict(os.environ, {"EASYREAD_LIBRARY": lib.name})
        env.start()
        self.addCleanup(env.stop)
        self.app = server.App(server.config.load())
        server.Handler.app = self.app
        self.app.presence = presence.Presence(self.app.jobs.busy, lambda: None, enabled=False)
        self.httpd = launch._Server(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()

        def stop():
            self.httpd.shutdown()
            self.httpd.server_close()
            thread.join(5)
        self.addCleanup(stop)

    def closed_within(self, sock: socket.socket, seconds: float) -> tuple[bool, bytes]:
        """等對方關連線（recv 回空）；最多等 seconds 秒。回傳 (有沒有關, 收到的東西)。"""
        sock.settimeout(seconds)
        out = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    return True, out
                out += chunk
        except TimeoutError:
            return False, out

    def test_declared_body_that_never_arrives_is_closed(self):
        token = self.app.token
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall((f"POST /api/ingest HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nX-Token: {token}\r\n"
                          f"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n").encode() + b'{"url": ')
            started = time.monotonic()
            closed, out = self.closed_within(sock, 5)
        self.assertTrue(closed)
        self.assertLess(time.monotonic() - started, 4)  # 約 SHORT 秒就關，不是一直卡著
        self.assertEqual(out, b"")  # 不回應，直接關

    def test_unread_body_on_an_unknown_route_is_closed(self):  # ticket 71 的「先讀掉 body」也受逾時保護
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall((f"POST /api/no-such-route HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nX-Token: {self.app.token}\r\n"
                          f"Content-Length: 100\r\n\r\n").encode())
            closed, out = self.closed_within(sock, 5)
        self.assertTrue(closed)
        self.assertTrue(out.startswith(b"HTTP/1.1 404"), out[:40])
        self.assertIn(b"Connection: close", out)

    def test_half_sent_request_line_is_closed(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(b"GET /api/version HTTP/1.1\r\nHost: 127.0.0.1")
            closed, _ = self.closed_within(sock, 5)
        self.assertTrue(closed)

    def test_presence_websocket_outlives_the_timeout(self):
        sock, resp = _ws_connect(self.port, f"http://127.0.0.1:{self.port}")
        with sock:
            self.assertIn(b"101", resp.split(b"\r\n", 1)[0])
            time.sleep(SHORT * 3)
            sock.sendall(bytes([0x89, 0x80]) + os.urandom(4))  # 遮罩過的空 ping
            sock.settimeout(2)
            pong = sock.recv(16)
        self.assertEqual(pong[:1], b"\x8a")  # 還連著，收到 pong

    def test_normal_requests_still_work(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(f"GET /api/version HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
            sock.settimeout(5)
            self.assertTrue(sock.recv(64).startswith(b"HTTP/1.1 200"))

    def test_other_timeouts_still_get_a_500(self):  # 例如等鎖逾時：不是對方停住，照樣回錯誤
        with mock.patch.object(server.Handler, "_post", side_effect=TimeoutError("lock")):
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
                sock.sendall((f"POST /api/x HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nX-Token: {self.app.token}\r\n"
                              f"Content-Length: 0\r\n\r\n").encode())
                sock.settimeout(5)
                self.assertTrue(sock.recv(64).startswith(b"HTTP/1.1 500"))

    def test_log_message_with_one_argument(self):
        handler = server.Handler.__new__(server.Handler)
        handler.log_message("Request timed out: %r", TimeoutError("x"))  # 以前會 IndexError


class DefaultTimeoutTest(unittest.TestCase):
    def test_requests_time_out_after_30_seconds_by_default(self):
        self.assertEqual(server.REQUEST_TIMEOUT, 30.0)
        self.assertEqual(server.Handler.timeout, server.REQUEST_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
