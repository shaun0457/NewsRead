"""Ticket 77：POST 的路由沒讀 body 就回應（404、400）時，伺服器先把 body 讀掉（有上限）。

不讀的話，Windows 上連線會被中止（WinError 10053）；HTTP/1.1 保持連線時，留下的 body 還會被當成下一個請求。"""
from __future__ import annotations

import http.client
import socket
import unittest
from unittest import mock

from easyread import server
from tests.doubles import ApiTestCase


class DrainUnreadBodyTest(ApiTestCase):
    def port(self) -> int:
        return int(self.base.rsplit(":", 1)[1])

    def raw(self, request: bytes, *, shut: bool = False) -> bytes:
        """直接用 socket 送，讀到對方關連線或逾時為止（最多 64 KB）。"""
        with socket.create_connection(("127.0.0.1", self.port()), timeout=5) as sock:
            sock.sendall(request)
            if shut:
                sock.shutdown(socket.SHUT_WR)
            out = b""
            try:
                while len(out) < 65536:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    out += chunk
            except TimeoutError:
                pass
            return out

    def headers(self, length: int) -> bytes:
        return (f"POST /api/no-such-route HTTP/1.1\r\nHost: 127.0.0.1:{self.port()}\r\nX-Token: {self.token}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {length}\r\n\r\n").encode()  # 保持連線：要不要關由伺服器決定

    def test_unknown_post_route_with_body_is_404_every_time(self):
        body = {"text": "x" * 4096}
        for _ in range(20):
            self.assertEqual(self.request("POST", "/api/no-such-route", body)[0], 404)

    def test_keep_alive_connection_survives_an_unread_body(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port(), timeout=5)
        self.addCleanup(conn.close)
        for _ in range(3):  # 同一條連線連送三次；body 沒讀掉的話第二次會被當成壞掉的請求
            conn.request("POST", "/api/no-such-route", body=b'{"a": 1}',
                         headers={"X-Token": self.token, "Content-Type": "application/json"})
            res = conn.getresponse()
            res.read()
            self.assertEqual(res.status, 404)

    def test_body_over_the_drain_limit_closes_without_waiting(self):
        with mock.patch.object(server, "DRAIN_MAX", 16):
            # 宣告 100 bytes 但一個都不送：超過上限就不讀，直接回應並關連線，不會卡在等 body
            out = self.raw(self.headers(100))
        self.assertTrue(out.startswith(b"HTTP/1.1 404"), out[:40])
        self.assertIn(b"Connection: close", out)

    def test_short_body_ends_the_connection(self):
        # 宣告 50 bytes、只送 5 bytes 就收手：讀到 EOF 為止，回應後關連線
        out = self.raw(self.headers(50) + b'{"a":', shut=True)
        self.assertTrue(out.startswith(b"HTTP/1.1 404"), out[:40])
        self.assertIn(b"Connection: close", out)

    def test_lengths_it_cannot_trust_close_the_connection(self):
        base = self.headers(0).replace(b"Content-Length: 0\r\n", b"")
        cases = {
            "chunked": b"Transfer-Encoding: chunked\r\n",
            "two lengths": b"Content-Length: 2\r\nContent-Length: 4\r\n",
            "huge": b"Content-Length: " + b"9" * 5000 + b"\r\n",
            "negative": b"Content-Length: -1\r\n",
            "not ascii": "Content-Length: \uff11\r\n".encode(),
        }
        for name, header in cases.items():
            with self.subTest(name):
                out = self.raw(base.replace(b"\r\n\r\n", b"\r\n" + header + b"\r\n", 1), shut=True)
                self.assertTrue(out.startswith(b"HTTP/1.1 4"), out[:40])
                self.assertIn(b"Connection: close", out)
                self.assertNotIn(b"digits", out)  # 不帶直譯器的錯誤原文

    def test_a_route_rejects_a_chunked_body(self):
        req = self.headers(0).replace(b"/api/no-such-route", b"/api/trash").replace(b"Content-Length: 0", b"Transfer-Encoding: chunked")
        out = self.raw(req + b"2\r\n{}\r\n0\r\n\r\n", shut=True)
        self.assertTrue(out.startswith(b"HTTP/1.1 4"), out[:40])
        self.assertIn(b"Connection: close", out)

    def test_known_routes_still_read_their_own_body(self):
        status, _ = self.request("POST", "/api/trash", {"action": "nope"})
        self.assertIn(status, (400, 404))  # 路由自己讀 body，不會被讀第二次而卡住

    def test_bad_host_body_is_not_read(self):
        out = self.raw(self.headers(100).replace(f"Host: 127.0.0.1:{self.port()}".encode(), b"Host: evil.example"))
        self.assertTrue(out.startswith(b"HTTP/1.1 403"), out[:40])


if __name__ == "__main__":
    unittest.main()
