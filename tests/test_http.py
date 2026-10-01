import datetime
import os
import ssl
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from easyread import http


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


class HTTPSVerificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cert = Path(cls.tmp.name) / "cert.pem"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EasyRead test root CA")])
        now = datetime.datetime.now(datetime.timezone.utc)
        ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
              .not_valid_after(now + datetime.timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
              .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, None, None), critical=True)
              .sign(ca_key, hashes.SHA256()))
        cls.cert.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(ca_name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                .sign(ca_key, hashes.SHA256()))
        server_cert = Path(cls.tmp.name) / "server.pem"
        server_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path = Path(cls.tmp.name) / "key.pem"
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                               serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(server_cert, key_path)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.srv.socket = context.wrap_socket(cls.srv.socket, server_side=True)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()
        http._context.cache_clear()

    def test_untrusted_certificate_is_rejected(self):
        with patch.dict(os.environ, {"SSL_CERT_FILE": "", "SSL_CERT_DIR": ""}):
            with self.assertRaises(urllib.error.URLError):
                http.urlopen(f"https://localhost:{self.srv.server_port}", timeout=5)

    def test_explicit_trusted_certificate_is_used(self):
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(self.cert), "SSL_CERT_DIR": ""}):
            with http.urlopen(f"https://localhost:{self.srv.server_port}", timeout=5) as response:
                self.assertEqual(response.read(), b"ok")

    def test_hostname_mismatch_is_rejected(self):
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(self.cert), "SSL_CERT_DIR": ""}):
            with self.assertRaises(urllib.error.URLError):
                http.urlopen(f"https://127.0.0.1:{self.srv.server_port}", timeout=5)
