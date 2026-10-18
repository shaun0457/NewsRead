import http.client
import json
import os
import tempfile
import threading
import unittest

from easyread import launch, server


class HostNameTest(unittest.TestCase):
    def test_strips_port_case_and_trailing_dot(self):
        self.assertEqual(server.host_name("LocalHost:8765"), "localhost")
        self.assertEqual(server.host_name("127.0.0.1"), "127.0.0.1")
        self.assertEqual(server.host_name("[::1]:8765"), "::1")
        self.assertEqual(server.host_name("::1"), "::1")
        self.assertEqual(server.host_name("example.com.:80"), "example.com")
        self.assertEqual(server.host_name(None), "")

    def test_allowed_hosts(self):
        self.assertEqual(server.allowed_hosts(), server.LOOPBACK_HOSTS)
        wildcard = server.allowed_hosts("0.0.0.0", "localhost", "")
        self.assertEqual(wildcard, server.LOOPBACK_HOSTS)
        lan = server.allowed_hosts("192.168.1.20", None, " paperread.lan , NAS.local:8765,")
        self.assertTrue({"192.168.1.20", "paperread.lan", "nas.local"} <= lan)
        self.assertNotIn("", lan)


class HostHeaderTest(unittest.TestCase):
    """DNS rebinding: an attacker domain resolving to 127.0.0.1 still sends its own Host header."""

    def setUp(self):
        os.environ["EASYREAD_LIBRARY"] = tempfile.mkdtemp()
        self.app = server.App(server.config.load())
        server.Handler.app = self.app
        server.Handler.allowed_hosts = server.LOOPBACK_HOSTS
        self.httpd = launch._Server(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.Handler.allowed_hosts = server.LOOPBACK_HOSTS
        os.environ.pop("EASYREAD_LIBRARY", None)

    def request(self, method, path, host, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest(method, path, skip_host=True)
            conn.putheader("Host", host)
            for k, v in (headers or {}).items():
                conn.putheader(k, v)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def test_loopback_hosts_accepted(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"):
            status, body = self.request("GET", "/api/library", host)
            self.assertEqual(status, 200, host)
            self.assertIn("token", json.loads(body))

    def test_foreign_host_cannot_read_token(self):
        status, body = self.request("GET", "/api/library", f"rebind.attacker.example:{self.port}")
        self.assertEqual(status, 403)
        self.assertNotIn(self.app.token.encode(), body)

    def test_foreign_host_cannot_post_even_with_token(self):
        status, _ = self.request("POST", "/api/presence/keep", f"rebind.attacker.example:{self.port}",
                                 {"X-Token": self.app.token, "Content-Type": "application/json"}, b"{}")
        self.assertEqual(status, 403)

    def test_configured_extra_host_accepted(self):
        server.Handler.allowed_hosts = server.allowed_hosts("0.0.0.0", "localhost", "paperread.lan")
        status, _ = self.request("GET", "/api/version", f"paperread.lan:{self.port}")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
