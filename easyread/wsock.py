"""最小的 WebSocket 服务端：只用来知道页面还开着（握手、读到断开为止），不收发业务数据。

为什么不用一直挂着的普通 HTTP 请求（SSE）：浏览器对同一个地址最多同时开 6 条 HTTP 连接，
每个标签页占一条，开到五六个标签页所有请求都要排队。WebSocket 不占这 6 条的名额。
"""
from __future__ import annotations

import base64
import hashlib
import struct

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def is_upgrade(headers) -> bool:
    return (headers.get("Upgrade") or "").lower() == "websocket" and bool(headers.get("Sec-WebSocket-Key"))


def accept(handler) -> None:
    """回 101，连接从此是 WebSocket。"""
    key = handler.headers["Sec-WebSocket-Key"].strip()
    digest = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
    handler.send_response(101, "Switching Protocols")
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", digest)
    handler.end_headers()
    handler.wfile.flush()


def _read(rfile, n: int) -> bytes:
    data = rfile.read(n)
    if len(data) < n:
        raise EOFError
    return data


def _send(wfile, opcode: int, payload: bytes = b"") -> None:
    wfile.write(bytes([0x80 | opcode, len(payload)]) + payload)  # 只发控制帧，长度不会超过 125
    wfile.flush()


def hold(handler) -> None:
    """一直读，直到页面关掉（收到关闭帧或连接断开）。ping 回 pong，其余消息忽略。"""
    rfile, wfile = handler.rfile, handler.wfile
    try:
        while True:
            b0, b1 = _read(rfile, 2)
            opcode, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", _read(rfile, 2))[0]
            elif n == 127:
                n = struct.unpack(">Q", _read(rfile, 8))[0]
            mask = _read(rfile, 4) if b1 & 0x80 else b""
            payload = _read(rfile, n) if n else b""
            if mask:
                payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
            if opcode == 0x8:  # 关闭：回一个关闭帧
                _send(wfile, 0x8, payload[:2])
                return
            if opcode == 0x9:
                _send(wfile, 0xA, payload[:125])
    except (EOFError, OSError, ValueError):
        return
