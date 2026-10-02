"""HTTPS with system trust and bundled roots, including in frozen builds."""
from __future__ import annotations

import os
import ssl
import urllib.request
from functools import lru_cache

import certifi
import truststore


@lru_cache(maxsize=4)
def _context(cafile: str | None, capath: str | None):
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Native trust handles macOS Keychain / Windows roots; certifi also makes
    # Linux and PyInstaller builds independent of build-machine CA paths.
    context.load_verify_locations(cafile=certifi.where())
    if cafile or capath:
        context.load_verify_locations(cafile=cafile or None, capath=capath or None)
    return context


def urlopen(url, *args, **kwargs):
    # urllib can redirect an HTTP request to HTTPS, so use this context for
    # both schemes. It keeps hostname and certificate verification enabled.
    kwargs.setdefault("context", _context(os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_CERT_DIR")))
    return urllib.request.urlopen(url, *args, **kwargs)
