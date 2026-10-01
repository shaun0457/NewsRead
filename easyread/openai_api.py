"""OpenAI 兼容接口：两种格式都支持。

- chat：POST {base}/chat/completions，几乎所有服务商都支持（DeepSeek、智谱、Ollama……）。
- responses：POST {base}/responses，OpenAI 新接口；DeepSeek 等也已支持。中转站只开了这个时选它。

另外 models() 读 {base}/models，给设置页“获取模型列表”用。
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

from . import __version__, usage
from .engines import Cancelled, EngineError

API_KINDS = [("chat", "Chat Completions（通用）"), ("responses", "Responses（OpenAI 新接口）")]
_HINT = {401: "（Key 不对或过期了）", 402: "（余额不足）", 403: "（没有权限用这个模型）",
         404: "（地址、模型名或接口格式不对）", 429: "（被限流了，稍后重试或换个模型）"}


def kind(o: dict) -> str:
    return "responses" if o.get("api") == "responses" else "chat"


def _base(o: dict) -> str:
    base = (o.get("base_url") or "").strip().rstrip("/")
    if not base or not o.get("model"):
        raise EngineError("API 没填地址或模型（设置 → 翻译引擎）")
    return base


def _headers(o: dict, stream: bool = False) -> dict:
    # 要带 User-Agent：Python 默认的 "Python-urllib/x" 会被 Cloudflare 后面的接口（比如 OpenCode）直接拦掉，报 403 error code: 1010
    h = {"Content-Type": "application/json", "User-Agent": f"EasyRead/{__version__}"}
    if stream:
        h["Accept"] = "text/event-stream"
    if o.get("api_key"):
        h["Authorization"] = "Bearer " + o["api_key"]
    return h


def _body(o: dict, prompt: str, images: list[Path], stream: bool, temperature: float | None) -> dict:
    urls = ["data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode() for p in images] if o.get("vision") else []
    if kind(o) == "responses":
        content = [{"type": "input_text", "text": prompt}] + [{"type": "input_image", "image_url": u} for u in urls]
        body = {"model": o["model"], "input": [{"role": "user", "content": content}], "store": False}
    else:
        content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": u}} for u in urls] if urls else prompt
        body = {"model": o["model"], "messages": [{"role": "user", "content": content}]}
    if temperature is not None:
        body["temperature"] = temperature
    if stream:
        body["stream"] = True
        if kind(o) == "chat":
            body["stream_options"] = {"include_usage": True}  # 最后一块带上 token 用量；不认这个参数的接口会去掉再发
    return body


def _open(o: dict, body: dict, stream: bool):
    """发请求。有的模型（推理模型、Kimi K2 系列）不让改 temperature、有的接口不认 stream_options，报 400 时去掉再发。"""
    path = "/responses" if kind(o) == "responses" else "/chat/completions"
    for _ in range(3):
        req = urllib.request.Request(_base(o) + path, data=json.dumps(body).encode(), headers=_headers(o, stream))
        try:
            return urllib.request.urlopen(req, timeout=int(o.get("timeout") or 600))
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            drop = next((k for k in ("temperature", "stream_options") if k in detail and k in body), None)
            if e.code == 400 and drop:
                body = {k: v for k, v in body.items() if k != drop}
                continue
            e.detail = detail
            raise


def _http_error(e: urllib.error.HTTPError) -> EngineError:
    return EngineError(f"接口返回 {e.code}{_HINT.get(e.code, '')}：{getattr(e, 'detail', '')}")


# ---------- 一次拿到整段（翻译用） ----------
def complete(o: dict, prompt: str, images: list[Path], cancel=None, meter=None) -> str:
    body = _body(o, prompt, images, False, None if kind(o) == "responses" else 0.2)
    res = None
    for attempt in range(4):  # 限流、服务端错误、网络抖动：等一会儿再试
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            with _open(o, body, False) as r:
                res = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                _sleep(float(e.headers.get("Retry-After") or 0) or 5 * 2 ** attempt, cancel)
                continue
            raise _http_error(e)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt < 2:
                _sleep(5, cancel)
                continue
            raise EngineError(f"连不上接口：{e}")
    if meter is not None and isinstance(res, dict):
        meter.add(**usage.from_openai(res))
    return _responses_text(res) if kind(o) == "responses" else _chat_text(res)


def _chat_text(res) -> str:
    try:
        choice = res["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise EngineError(f"接口返回格式不对：{str(res)[:300]}")
    if choice.get("finish_reason") == "length":
        raise _truncated()
    return text


def _responses_text(res) -> str:
    if not isinstance(res, dict) or "output" not in res:
        raise EngineError(f"接口返回格式不对：{str(res)[:300]}")
    if res.get("status") == "incomplete" and (res.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
        raise _truncated()
    if res.get("status") == "failed":
        raise EngineError(f"接口返回出错：{res.get('error')}")
    return "".join(c.get("text") or "" for item in res["output"] if item.get("type") == "message"
                   for c in item.get("content") or [] if c.get("type") == "output_text")


def _truncated() -> EngineError:
    return EngineError("模型输出被截断了（超过它的输出长度上限）。在设置里把“每次交给模型的页数”调成 1 页再试。")


def _sleep(seconds: float, cancel) -> None:
    end = time.time() + min(seconds, 90)
    while time.time() < end:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        time.sleep(0.5)


# ---------- 逐字输出（问 AI 用） ----------
def stream(o: dict, text: str, cancel, meter=None) -> Iterator[str]:
    body = _body(o, text, [], True, None if kind(o) == "responses" else 0.4)
    try:
        r = _open(o, body, True)
    except urllib.error.HTTPError as e:
        raise _http_error(e)
    except Exception as e:  # noqa: BLE001
        raise EngineError(f"连不上接口：{e}")
    pieces = _responses_pieces(r, cancel, meter) if kind(o) == "responses" else _chat_pieces(r, cancel, meter)
    yield from _strip_think(pieces)


def _events(r, cancel) -> Iterator[dict | None]:
    """SSE 的每个 data 行；[DONE] 给 None。"""
    with r:
        for raw in r:
            if cancel.is_set():
                raise Cancelled()
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                yield None
                return
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue


def _chat_pieces(r, cancel, meter=None) -> Iterator[str]:
    for ev in _events(r, cancel):
        if ev is None:
            return
        if ev.get("usage") and meter is not None:  # 开了 include_usage 时最后一块只有 usage、choices 为空
            meter.add(**usage.from_openai(ev))
        yield ((ev.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""


def _responses_pieces(r, cancel, meter=None) -> Iterator[str]:
    for ev in _events(r, cancel):
        t = (ev or {}).get("type", "")
        if t == "response.completed" and meter is not None:
            meter.add(**usage.from_openai(ev.get("response") or {}))
        if ev is None or t == "response.completed":
            return
        if t == "response.output_text.delta":
            yield ev.get("delta") or ""
        elif t in ("response.failed", "error"):
            err = (ev.get("response") or {}).get("error") or ev.get("error") or ev.get("message")
            raise EngineError(f"接口返回出错：{err}")


def _strip_think(pieces: Iterator[str]) -> Iterator[str]:
    """推理模型把思考过程包在 <think> 里，读者不需要看。"""
    thinking = False
    for piece in pieces:
        if "<think>" in piece:
            thinking, piece = True, piece.split("<think>")[0]
        if thinking:
            if "</think>" not in piece:
                continue
            thinking, piece = False, piece.split("</think>", 1)[1]
        if piece:
            yield piece


# ---------- 模型列表 ----------
def models(o: dict) -> list[str]:
    """GET {base}/models，返回模型名（排好序）。"""
    base = (o.get("base_url") or "").strip().rstrip("/")
    if not base:
        raise EngineError("先填接口地址")
    req = urllib.request.Request(base + "/models", headers=_headers(o))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as e:
        e.detail = e.read()[:300].decode("utf-8", "replace")
        raise _http_error(e)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise EngineError(f"连不上接口：{e}")
    except json.JSONDecodeError:
        raise EngineError("这个地址不提供模型列表，手填模型名")
    items = res.get("data") if isinstance(res, dict) else res
    if not isinstance(items, list):  # Gemini 的旧格式是 {"models": [...]}
        items = (res or {}).get("models") or []
    ids = [str(m.get("id") or m.get("name") or "").removeprefix("models/") if isinstance(m, dict) else str(m) for m in items]
    return sorted({i for i in ids if i})
