"""本地服务：只监听 127.0.0.1。文献库页、阅读页、数据接口、导入、后台任务。"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import re
import sqlite3
import sys
import threading

from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import __version__, answer_styles, figures, chat, chat_models, chat_store, cli_models, config, detect, documents, engines, i18n, langs, notehelp, open_link, paperdata, pdfwork, prefs, settings_api, trash, library_api, translate_api, updates, usage, wsock, jobs_api, presets as api_presets
from . import article_ask, ingest, planning_store
from . import ai_engines, chain, entities, ledger, narratives, reader_api, triage, usage_report
from . import today  # 今日新聞（ticket 15）
from .log import log, tail
from .jobs import Jobs, LedgerMeter
from .library import Library
from .i18n import tr
from .store import now_iso
from .reader_files import refresh_layout as _refresh_layout, warm as _warm, reveal as _reveal, _warming

WEB = config.WEB
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")
DRAIN_MAX = 1024 * 1024  # 超過上限的請求，最多先讀掉多少再回錯誤
DRAIN_CHUNK = 64 * 1024
class ClientTimeout(Exception):
    """讀請求 body 或寫回應時 socket 逾時（對方停住了）。和等鎖逾時這類 TimeoutError 分開：只有這種直接關連線、不回應。"""


REQUEST_TIMEOUT = 30.0  # 一般請求每次讀寫 socket 最多等幾秒；宣告了 body 卻不送的連線逾時就關掉（presence WebSocket 例外）
MAX_UPLOAD = 200 * 1024 * 1024
MAX_ANSWER_CHARS = 200_000  # 一則問 AI 的回答最多收幾個字；超過就停掉引擎、截斷存下
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def host_name(header: str | None) -> str:
    """Host header 去掉 port 與結尾的點：'[::1]:8765' → '::1'，'LocalHost:8765' → 'localhost'。"""
    h = (header or "").strip().lower()
    if "://" in h:
        # 設定值偶爾會以完整 URL 傳入；只取 hostname，避免 allowlist
        # 收到「https」或帶路徑的錯誤項目。
        h = urlparse(h).hostname or ""
    elif h.startswith("["):
        h = h[1:].split("]", 1)[0]
    elif h.count(":") == 1:
        h = h.split(":", 1)[0]
    return h.rstrip(".")


def allowed_hosts(bind_host: str | None = None, public_host: str | None = None, extra: str | None = None) -> frozenset:
    """可接受的 Host：本機迴環、明確綁定的位址、PAPERREAD_PUBLIC_HOST，以及 PAPERREAD_ALLOWED_HOSTS（逗號分隔）。

    擋 DNS rebinding：惡意網域解析到 127.0.0.1 時，瀏覽器送來的 Host 仍是那個網域，
    若不檢查，對方頁面可以讀到 /api/library 的 token，再拿去發 POST。
    """
    hosts = set(LOOPBACK_HOSTS)
    if bind_host and bind_host not in ("0.0.0.0", "::"):
        hosts.add(host_name(bind_host))
    if public_host:
        hosts.add(host_name(public_host))
    for item in (extra or "").split(","):
        if item.strip():
            hosts.add(host_name(item))
    hosts.discard("")
    return frozenset(hosts)


def _safe(base: Path, rel: str) -> Path | None:
    target = (base / rel).resolve()
    return target if target.is_relative_to(base.resolve()) and target.is_file() else None


class App:
    def __init__(self, cfg: dict, gate_required: bool = False):
        self.lib = Library(config.library_dir(cfg))
        self.jobs = Jobs(self.lib, gate_required=gate_required)
        self.token = os.urandom(12).hex()
        self.location = library_api.LibraryLocation(self)
        self.presence = None  # presence.Presence，serve() 里设
        self.scheduler = None  # scheduler.Scheduler，serve() 里设


def declared_length(headers) -> int:
    """請求宣告的 body 長度；看不懂的一律回 -1（呼叫的地方會關連線）：用 Transfer-Encoding 送的（不支援分塊，
    留在連線上會被當成下一個請求）、Content-Length 出現不只一次、不是 ASCII 數字（含負數、前後有空白）、超過 12 位數。"""
    get_all = getattr(headers, "get_all", None)
    values = (get_all("Content-Length") if get_all else None) or [headers.get("Content-Length", "0")]
    raw = values[0]
    if headers.get("Transfer-Encoding") is not None or len(values) > 1:
        return -1
    return int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 12 else -1


class Handler(BaseHTTPRequestHandler):
    app: App
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT  # socketserver 在 setup() 套到連線上；逾時由 handle_one_request 關連線
    allowed_hosts: frozenset = LOOPBACK_HOSTS  # launch.serve() 依綁定位址與環境變數覆寫

    def _host_ok(self) -> bool:
        """瀏覽器必須提供 Host，且只能使用啟動時建立的白名單。"""
        host = self.headers.get("Host")
        if host is not None and host_name(host) in self.allowed_hosts:
            return True
        self.close_connection = True
        self._body_read = True  # 不認得的 Host 不收 body，回完直接斷線
        self._json(400 if host is None else 403, {"error": "missing host" if host is None else "bad host"})
        return False

    def log_message(self, fmt, *args):
        if len(args) > 1 and str(args[1]).startswith(("4", "5")):  # 逾時這類 log_error 只帶一個參數
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    # ---------- 输出 ----------
    def send_response(self, code, message=None):
        self._drain_unread()  # 先把請求收完再回應，所有回應（含 404、400）都經過這裡
        super().send_response(code, message)

    def _drain_unread(self):
        """POST 的路由沒讀 body 就要回應（找不到路由、參數錯）：讀掉丟棄，連線才不會被中止，
        留在連線上的 body 也不會被當成下一個請求。最多讀 DRAIN_MAX；更大或長度不對就關連線。"""
        if self.command != "POST" or getattr(self, "_body_read", True):
            return
        self._body_read = True
        left = declared_length(self.headers)
        if left < 0 or left > DRAIN_MAX:
            self.close_connection = True
            return
        try:
            while left > 0:  # 分段讀、讀完就丟
                chunk = self.rfile.read(min(left, DRAIN_CHUNK))
                if not chunk:
                    self.close_connection = True
                    return
                left -= len(chunk)
        except TimeoutError:  # 宣告了 body 卻不送完：照樣回應，然後關連線
            self.close_connection = True

    def _write(self, body: bytes) -> None:
        try:
            self.wfile.write(body)
        except TimeoutError as e:  # 對方不讀了：回應送到一半，不能再補一個錯誤回應
            self.close_connection = True
            raise ClientTimeout from e

    def _send(self, code: int, body: bytes, ctype: str, cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        if getattr(self, "close_connection", False):
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self._write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _file(self, path: Path | None, cache=False, ctype=None):
        if not path:
            return self._json(404, {"error": "not found"})
        ctype = ctype or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype, cache)

    def _redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _page(self, path: Path):
        self._send(200, i18n.inject(path.read_text(encoding="utf-8")).encode("utf-8"), "text/html; charset=utf-8")

    def _download(self, body: bytes, filename: str, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f"attachment; filename=\"export.html\"; filename*=UTF-8''{quote(filename)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write(body)

    def _chat(self, ws, body: dict):
        """流式回答：一行一个 JSON，{"t": 片段} … 最后 {"done": true, "id": …} 或 {"error": …}。"""
        text = (body.get("text") or "").strip()
        if not text:
            raise ValueError(tr("问题是空的"))
        thread = chat_store.get(ws, body.get("thread"))
        style = answer_styles.parse(body.get("answer_style", (thread or {}).get("answer_style")))
        cfg = config.load()
        ecfg, m = chat_models.engine_cfg(cfg, body.get("model"))
        from . import chat_options
        options = chat_options.apply(ecfg, body.get("chat_options"))
        images = []
        model = chat_models.label(m)
        tid = thread["id"] if thread else chat_store.new_id()
        refs = [{"anchor": str(r.get("anchor") or ""), "quote": str(r.get("quote") or "")[:1000]}
                for r in (body.get("refs") or [])[:12] if isinstance(r, dict) and r.get("anchor")]
        first = refs[0] if refs else {}
        user = {"content": text, "anchor": body.get("anchor") or first.get("anchor"), "quote": (body.get("quote") or first.get("quote") or "")[:1000],
                "note": body.get("note"), "refs": refs, "answer_style": style, "chat_options": options, "images": images}
        user["documents"] = documents.extract(body.get("documents"))
        past = (thread or {}).get("messages", [])
        convo = [{"role": x["role"], "content": x["content"]} for x in past] + [{"role": "user", "content": text}]
        article = article_ask.is_article(ws)  # 文章：範圍只有全文，回答分三段、對過引述（ticket 12）
        if article:
            prompt_text = article_ask.prompt(ws, convo, user["anchor"], user["quote"], style)
        else:
            prompt_text = chat.prompt(ws, convo, user["anchor"], user["quote"], ecfg["engine"], refs, answer_style=style)
        prompt_text += documents.context((past + [user])[-chat.HISTORY:])
        images = chat.receive_images(ws, body.get("images"), ecfg)
        user["images"] = images
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        cancel = threading.Event()
        pieces: list[str] = []
        version = manifest_id = None
        if article:
            version, manifest_id, ledger_path = self._ask_records(ws, ecfg["engine"], m.get("model") or "")
            meter = LedgerMeter(ecfg["engine"], m.get("model") or "", ledger_path, task=article_ask.TASK, manifest=manifest_id)
        else:
            meter = usage.Meter(ecfg["engine"])

        def extra():  # 文章：拆好的段落、prompt 版本、manifest（答完和按停止都存）
            if not article:
                return None
            return {"answer": article_ask.parse("".join(pieces), article_ask.paragraphs(ws)),
                    "prompt_version": version, "manifest": manifest_id}

        def send(obj):
            self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()
        try:
            send({"model": model, "thread": tid, "answer_style": style,
                  "documents": [{k: f[k] for k in ("name", "truncated")} for f in user["documents"]]})
            def seen(actual):
                chat_models.remember(m.get("model", ""), actual)
                if m.get("engine") in ("claude", "antigravity"):
                    send({"model": chat_models.label(m)})
            attachments = chat.image_paths(ws, past + [user])
            image_options = {"images": attachments} if attachments else {}
            if article and not attachments:
                image_options["tools"] = False  # 文章是外部內容：Claude 不給任何工具（防文章裡的指示叫它讀檔）
            received = 0
            for piece in chat.stream(ecfg, prompt_text, ws.root, cancel, seen, meter, **image_options):
                if article and not received:
                    self._ask_exposure(ledger_path, ws)  # 有回答出來才算揭露
                piece = piece[:MAX_ANSWER_CHARS - received]
                received += len(piece)
                pieces.append(piece)
                send({"t": piece})
                if received >= MAX_ANSWER_CHARS:
                    cancel.set()  # 回答太長：停掉引擎（關掉 generator 時也會 kill 子程序）
                    tail = "\n\n" + tr("（回答太長，已截斷）")
                    pieces.append(tail)
                    send({"t": tail})
                    break
            msg = chat_store.append(ws, tid, user, "".join(pieces), m["id"], model, meter.snapshot(), extra())
            send({"done": True, "id": msg["id"], "usage": msg.get("usage"), "answer": msg.get("answer"),
                  "prompt_version": msg.get("prompt_version")})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            cancel.set()  # 读者点了停止或关了页面
            if pieces:
                chat_store.append(ws, tid, {**user, "note": None}, "".join(pieces) + "\n\n" + tr("（已停止）"), m["id"], model, meter.snapshot(),
                                  extra())
        except engines.Cancelled:
            pass
        except Exception as e:  # noqa: BLE001
            log.exception("对话出错 %s", ws.id)
            try:
                send({"error": str(e)[:500]})
            except OSError:
                pass
        finally:
            saved = chat_store.get(ws, tid) or {}
            retained = {name for message in saved.get("messages", [])
                        for name in message.get("images", [])}
            for path in chat.image_paths(ws, [{"images": images}]):
                if path.relative_to(ws.root.resolve()).as_posix() not in retained:
                    path.unlink(missing_ok=True)

    def _ask_records(self, ws, engine: str, model: str) -> tuple[str, str | None, Path]:
        """文章問 AI 之前：登記 prompt 版本（內容含固定 prompt 的雜湊）、寫 ContextManifest。
        帳本出錯不擋回答，只寫 log；這時回答的用量照樣記，但不指向 manifest。揭露紀錄等回答出來才寫（_ask_exposure）。"""
        version = f"{article_ask.PROMPT_VERSION}@{engine or 'unknown'}/{model or 'default'}"
        path = Path(getattr(self.app, "ledger_path", None) or ledger.default_path())
        manifest_id = None
        try:
            index = ledger.shared(path, create=True)
            index.register_prompt(article_ask.TASK, version, f"base={article_ask.PROMPT_VERSION}\nrules_sha256={article_ask.RULES_SHA256}\n"
                                  f"engine={engine}\nmodel={model}", make_current=False)
            manifest_id = article_ask.manifest(index, ws, version)
        except (OSError, ValueError, sqlite3.Error) as e:
            log.warning("問 AI 的帳本紀錄沒寫完：%s", type(e).__name__)
        return version, manifest_id, path

    @staticmethod
    def _ask_exposure(path: Path, ws) -> None:
        """盲判之前問 AI：寫揭露紀錄（地點 = 問 AI），之後的判斷 blind = false。同一篇只記第一次。"""
        try:
            ledger.shared(path, create=True).record_exposure(ws.id, "ask_ai")
        except (OSError, ValueError, sqlite3.Error) as e:
            log.warning("問 AI 的揭露紀錄沒寫進去：%s", type(e).__name__)

    def _body(self, limit: int = MAX_UPLOAD) -> bytes:
        self._body_read = True
        n = declared_length(self.headers)
        try:
            if n < 0 or n > limit:
                self.close_connection = True
                if 0 < n <= limit + DRAIN_MAX:  # 不大的就先讀掉，對方才收得到錯誤回應（不然 Windows 會直接中止連線）
                    left = n
                    while left > 0:  # 分段讀、讀完就丟，不為了丟掉而整塊放進記憶體
                        chunk = self.rfile.read(min(left, DRAIN_CHUNK))
                        if not chunk:
                            break
                        left -= len(chunk)
                raise ValueError(tr("文件太大"))
            return self.rfile.read(n) if n else b""
        except TimeoutError as e:
            self.close_connection = True  # 讀到一半的連線不能再拿來接下一個請求
            raise ClientTimeout from e

    def _import_result(self, ws, fresh, translate_after, scope, read=False, model="", target=""):
        # A failed first preparation still leaves a library entry. Re-importing
        # that PDF must retry preparation instead of silently skipping it.
        paper = ws.load("paper") or {}
        active = (ws.load("job") or {}).get("state") in ("queued", "running")
        queued = fresh or (not paper.get("meta", {}).get("pages") and not active)
        if queued:
            if translate_after and not read:
                langs.remember(ws, target)  # 导入框里选的译文语言
            # 匯入後接著翻譯 / 整理：算背景工作，受額度保護（ticket 68）
            self.app.jobs.enqueue(ws, translate_after=translate_after, scope=scope, read=read, model=model, background=translate_after)
        return self._json(200, {"id": ws.id, "new": fresh, "queued": queued})

    # ---------- GET ----------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return
        try:
            with self.app.location.request(self.command, self.path):
                self._get()
        except ClientTimeout:
            self.close_connection = True  # 回應送到一半對方停住：直接關連線
        except ValueError as e:
            self._json(409, {"error": str(e), "library_status": self.app.location.status})
        except Exception as e:  # noqa: BLE001
            log.exception("请求出错 %s", self.path)
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _entities(self, call, missing: str | None = None):
        """追蹤對象、題材頁 API 的錯誤對應：輸入不對 400（附欄位），找不到 404。"""
        try:
            result = call()
        except entities.EntityError as e:
            return self._json(400, {"error": str(e), "field": e.field})
        except entities.NotFound:
            return self._json(404, {"error": missing or tr("找不到這個追蹤對象。")})
        except sqlite3.Error as e:  # 資料庫被鎖住、磁碟錯誤：只記錯誤類型，不回原文
            log.warning("追蹤對象資料庫錯誤 %s", type(e).__name__)
            return self._json(500, {"error": tr("本機資料庫暫時不能用，請稍後再試。")})
        return self._json(200, result) if result is not None else self._json(404, {"error": "not found"})

    def _ai(self, call, failed: str | None = None):
        """AI 引擎設定 API 的錯誤對應。回應和 log 都不帶 key 或上游原文。failed：其他錯誤時的固定訊息。"""
        try:
            result = call()
        except ai_engines.InputError as e:
            return self._json(400, {"error": str(e), "field": e.field})
        except ai_engines.AIError as e:
            return self._json(400, {"error": ai_engines.message(e.code), "code": e.code})
        except ai_engines.NotFound:
            return self._json(404, {"error": tr("找不到這個設定。")})
        except Exception as e:  # noqa: BLE001 只記類型：例外訊息可能帶設定內容
            log.warning("AI 設定 API 出錯 %s", type(e).__name__)
            return self._json(500, {"error": failed or tr("設定暫時存不了，請稍後再試。")})
        return self._json(200, result) if result is not None else self._json(404, {"error": "not found"})

    def _get(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        app, lib = self.app, self.app.lib
        if path == "/api/ledger":  # 帳本唯讀列表，給驗收和之後的頁面用
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                return self._json(200, ledger.api_get(getattr(app, "ledger_path", None), q))
            except ledger.QueryError:
                return self._json(400, {"error": "bad ledger query"})
        if path == reader_api.PREFIX or path.startswith(reader_api.PREFIX + "/"):  # 閱讀器的匯出和心智圖
            result = reader_api.get(app, path)
            return self._json(200, result) if result is not None else self._json(404, {"error": "not found"})
        if path == entities.PREFIX or path.startswith(entities.PREFIX + "/"):  # 追蹤對象
            return self._entities(lambda: entities.api_get(app, path, {k: v[0] for k, v in parse_qs(url.query).items()}))
        if path == "/today":  # 今日新聞（ticket 15）；資料走 POST /api/today（會寫揭露紀錄，要 X-Token）
            return self._page(WEB / "today.html")
        if triage.handles(path):  # AI 分類的狀態和結果（ticket 14）
            return self._entities(lambda: triage.api_get(app, path), tr("這則還沒有排進 AI 分類。"))
        if narratives.handles(path):  # 題材頁與論點（ticket 57）
            return self._entities(lambda: (chain.api_get(app, path, {}) or narratives.api_get(app, path, {k: v[0] for k, v in parse_qs(url.query).items()})),
                                  tr("找不到這個題材或論點。"))
        if path == "/entities":
            return self._page(WEB / "entities.html")
        if path.startswith("/theme/") and path.count("/") == 2:  # 題材頁（ticket 59：先有因果鏈區塊）
            return self._page(WEB / "theme.html")
        if path == ai_engines.PREFIX or path.startswith(ai_engines.PREFIX + "/"):  # AI 引擎、自帶 key、每種工作用哪個
            return self._ai(lambda: ai_engines.api_get(app, path))
        if usage_report.handles(path):  # 用量頁的報表（ticket 29）：唯讀，帳本還沒建就回空的
            return self._ai(lambda: usage_report.build(app, parse_qs(url.query).get("period", ["month"])[0]),
                            tr("用量暫時讀不到，請稍後再試。"))
        if path == "/usage":
            return self._page(WEB / "usage.html")
        if path == "/settings":
            return self._page(WEB / "settings.html")
        if path in ("/", "/index.html"):
            return self._page(WEB / "library.html")
        if path == "/web/tabs.html":
            return self._page(WEB / "tabs.html")
        if path.startswith("/read/"):
            return self._page(WEB / "reader.html")
        if path == "/open":  # 外部工具打开指定论文/段落；桌面版的 easyread://open 也转到这里
            return self._redirect(open_link.target(lib, parse_qs(url.query)))
        if path == "/api/version":
            return self._json(200, open_link.version())
        if path.startswith("/web/"):
            return self._file(_safe(WEB, path[5:]), cache=path.startswith("/web/vendor/"))
        if path == "/api/presence" and wsock.is_upgrade(self.headers):
            return self._presence()
        location = library_api.get(app, path)
        if location is not None:
            return self._json(200, location)
        if path == "/api/library":
            cfg = config.load()
            return self._json(200, {"items": lib.list(), "token": app.token, "jobs": app.jobs.small_status(),
                                    "research_statuses": planning_store.statuses(lib.root),
                                    "library_status": app.location.status, "other_device": app.location.marker.other_device(),
                                    "engine": cfg.get("engine"), "engine_label": cli_models.engine_label(cfg),
                                    "first_run": config.is_first_run(), "version": __version__, "trash": len(trash.items(lib.root))})
        if path == "/api/update":  # 有没有新版本（一天最多问一次 GitHub）
            return self._json(200, updates.check(force=parse_qs(url.query).get("force") == ["1"]))
        if path == "/api/trash":
            # 研究工作區的摘要回收站隨 ticket 04 移除；資料留在使用者資料夾，只是不再讀取
            return self._json(200, {"items": [{**item, "type": "paper"} for item in trash.items(lib.root)]})
        if path == "/api/config":
            return self._json(200, {"config": config.public(config.load()), "presets": api_presets.presets(),
                                    "api_choices": api_presets.api_choices()})
        if path == "/api/engines":
            cfg = config.load()
            found = detect.detect(cfg, fresh=parse_qs(url.query).get("fresh") == ["1"])
            return self._json(200, {"found": found, "ready": detect.ready(cfg, found), "engine": cfg.get("engine"), "models": cli_models.listing()})
        if path == "/api/prefs":
            return self._json(200, prefs.load())
        if path == "/api/chat/models":
            return self._json(200, chat_models.listing(config.load()))
        if path == "/api/log":
            return self._json(200, {"text": tail(config.LOG_PATH, 200), "path": str(config.LOG_PATH)})
        if path == "/api/jobs":
            return self._json(200, {"jobs": app.jobs.small_status(parse_qs(url.query).get("pid", [None])[0])})
        if path.startswith("/api/p/"):
            parts = path.split("/")  # ['', 'api', 'p', id, action, name?]
            ws = lib.ws(parts[3]) if len(parts) > 4 else None
            if not ws:
                return self._json(404, {"error": tr("没有这篇论文")})
            action = parts[4]
            if action == "state":
                if config.load().get("target") == "zh-TW" and app.location.status == "idle" and (ws.load("job") or {}).get("state") not in ("queued", "running"):
                    from . import traditional
                    traditional.migrate(ws)
                # 舊版智慧標註可能仍以英文原文為定位。讀取閱讀頁時，
                # 以穩定的英文來源重新對齊目前的繁中譯文；只更新 AI
                # 標註，不會碰使用者手動建立的筆記或標註。
                try:
                    reader = ws.load("reader") or {}
                    if reader.get("ai_annotations"):
                        from .smart_annotations import refresh_after_translation
                        refresh_after_translation(ws)
                except Exception:  # noqa: BLE001 —— 相容性同步失敗不阻斷閱讀頁
                    log.exception("智慧標註讀取時同步失敗 %s", ws.id)
                opened = {"last_opened": now_iso()}
                if app.location.status == "idle":
                    ws.patch_item(opened)
                    _warm(ws.root, app.location)
                    _refresh_layout(ws)
                state = {**{n: ws.load(n) for n in ("paper", "discussion", "reader", "layout", "item", "job")},
                         "versions": ws.versions(), "token": app.token, "id": ws.id, "library_status": app.location.status,
                         "engine": config.load().get("engine")}
                # 旧论文的图按定位框补截图；等内容和版本号都取完再开始，页面轮询到 paper 变了就会重画
                if app.location.status == "idle" and (state["job"] or {}).get("state") not in ("queued", "running"):
                    pass  # NewsRead does not generate cropped figure assets.
                return self._json(200, state)
            if action == "versions":
                return self._json(200, {**ws.versions(), "library_status": app.location.status})
            if action == "chat":
                return self._json(200, {"threads": chat_store.threads(ws), **chat_models.listing(config.load()), "limits": usage.latest()})
            if action == "log":
                return self._json(200, {"text": tail(ws.root / "job.log", 300)})
            if action == "export":
                if app.location.status != "idle":
                    raise app.location._error()
                from .build import build
                out = build(ws, mobile=parse_qs(url.query).get("mobile") == ["1"])
                return self._download(out.read_bytes(), out.name, "text/html; charset=utf-8")
            if action == "part" and len(parts) > 5 and parts[5] in ("paper", "discussion", "reader", "layout", "job"):
                return self._json(200, {"data": ws.load(parts[5]), "version": ws.versions()[parts[5]]})
        if path.startswith("/p/"):
            _, _, pid, rel = path.split("/", 3)
            ws = lib.ws(pid)
            if ws and re.fullmatch(r"extract/page-[0-9]{3,6}\.chars\.json", rel):
                if parse_qs(url.query).get("selection") == ["2"]:
                    from .selectable_text import page_file
                    return self._file(page_file(ws.root, ws.source_pdf, int(rel[13:-11])))
                return self._file(_safe(ws.root, rel), cache=True)
            if ws and app.location.status == "idle" and rel.startswith("pages/") and "w=" in url.query:  # 原页面板用的小一号图，第一次请求时生成
                try:
                    w = int(parse_qs(url.query)["w"][0])
                except (KeyError, IndexError, ValueError):
                    w = 1000
                variant = pdfwork.page_variant(ws.root, rel, w)
                return self._file(variant or _safe(ws.root, rel), cache=True)
            if ws and re.fullmatch(r"chat-media/[0-9a-f]{32}\.png", rel):
                return self._file(_safe(ws.root, rel), cache=True)
            if ws and (rel.split("/", 1)[0] in ("pages", "figures") or rel == "source.pdf"):
                source = ws.source_pdf if rel == "source.pdf" else _safe(ws.root, rel)
                return self._file(source if source and source.is_file() else None, cache=rel != "source.pdf",
                                  ctype="application/pdf" if rel == "source.pdf" else None)
        return self._json(404, {"error": "not found"})

    def _ingest(self, app):
        """POST /api/ingest。錯誤一律回 {"error": 固定訊息, "kind": 類別}；不回上游原文、不回使用者輸入。"""
        try:
            raw = self._body(ingest.MAX_BODY)
        except ValueError:
            return self._json(413, {"error": tr("資料太大。"), "kind": "too_large"})
        try:
            body = json.loads(raw or b"{}")
        except (ValueError, RecursionError):  # 壞掉的、或巢狀深到解不開的 JSON
            return self._json(400, {"error": ingest.message("bad_input"), "kind": "bad_input"})
        try:
            return self._json(200, ingest.handle(app, body))
        except ingest.IngestError as e:
            return self._json(ingest.http_status(e.kind), e.public() | {"error": e.message})
        except Exception as e:  # 鎖逾時、磁碟錯誤…：例外原文可能帶本機路徑，只記類型、回固定訊息
            log.warning("ingest failed: %s", type(e).__name__)
            return self._json(500, {"error": ingest.message("internal"), "kind": "internal"})

    # ---------- POST ----------
    def do_POST(self):
        self._body_read = False  # 同一條連線可以有好幾個請求（HTTP/1.1）
        if not self._host_ok():
            self.close_connection = True
            return
        if not hmac.compare_digest((self.headers.get("X-Token") or "").encode(), str(self.app.token).encode()):  # 挡住别的网页跨站写
            self.close_connection = True
            try:
                self._body(0)  # 沒通過 token 的請求不收 body：小的讀掉丟棄，大的直接斷線
            except Exception:
                pass
            return self._json(403, {"error": "bad token"})
        try:
            with self.app.location.request("POST", self.path):
                self._post()
        except ClientTimeout:
            self.close_connection = True  # 對方的 body 送到一半停住：不回應、直接關連線
        except (ValueError, KeyError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            log.exception("请求出错 %s", self.path)
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def _presence(self):
        """页面开着就一直连着这条 WebSocket；断开就是页面关了（见 presence.py）。"""
        host = self.headers.get("Host") or ""
        if self.headers.get("Origin") not in (None, f"http://{host}"):  # 别的网站不能来占着
            self.close_connection = True
            return self._json(403, {"error": "bad origin"})
        p = self.app.presence
        self.app.location.enter_page()
        try:
            wsock.accept(self)
            self.close_connection = True
            self.connection.settimeout(None)  # 頁面開著就一直連著，不套一般請求的逾時
            wsock.hold(self)
        finally:
            if p:
                p.leave()

    def _post(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        app, lib = self.app, self.app.lib

        if path == reader_api.PREFIX or path.startswith(reader_api.PREFIX + "/"):  # 閱讀器的匯出和心智圖
            result = reader_api.post(app, path, json.loads(self._body() or b"{}"))
            return self._json(200, result) if result is not None else self._json(404, {"error": "not found"})

        if path == "/api/ingest":  # 貼新聞連結 / 手動貼全文（ticket 11）
            return self._ingest(app)

        if path == entities.PREFIX or path.startswith(entities.PREFIX + "/"):  # 追蹤對象
            try:
                body = self._body(entities.MAX_BODY)
            except ValueError:
                return self._json(413, {"error": tr("資料太大。")})
            try:
                data = json.loads(body or b"{}")
            except (ValueError, RecursionError):  # RecursionError：很深的巢狀 [[[…]]]
                return self._json(400, {"error": tr("資料格式不對。")})
            return self._entities(lambda: entities.api_post(app, path, data))

        if today.handles(path):  # 今日新聞（ticket 15）：回傳 AI 的看法前會寫揭露紀錄，所以只走要 token 的 POST
            try:
                body = self._body(today.MAX_BODY)
            except ValueError:
                return self._json(413, {"error": tr("資料太大。")})
            try:
                data = json.loads(body or b"{}")
            except (ValueError, RecursionError):
                return self._json(400, {"error": tr("資料格式不對。")})
            return self._entities(lambda: today.api_post(app, path, data))

        if triage.handles(path):  # 重試 AI 分類（ticket 14）；body 讀掉但不用（最多 1 KB）
            try:
                self._body(1024)
            except ValueError:
                return self._json(413, {"error": tr("資料太大。")})
            return self._entities(lambda: triage.api_post(app, path), tr("這則還沒有排進 AI 分類。"))
        if narratives.handles(path):  # 題材頁與論點（ticket 57）
            try:
                body = self._body(narratives.MAX_BODY)
            except ValueError:
                return self._json(413, {"error": tr("資料太大。")})
            try:
                data = json.loads(body or b"{}")
            except (ValueError, RecursionError):
                return self._json(400, {"error": tr("資料格式不對。")})
            return self._entities(lambda: (chain.api_post(app, path, data) or narratives.api_post(app, path, data)), tr("找不到這個題材或論點。"))

        if path == ai_engines.PREFIX or path.startswith(ai_engines.PREFIX + "/"):  # AI 引擎設定
            try:
                body = self._body(ai_engines.MAX_BODY)
            except ValueError:
                return self._json(413, {"error": tr("資料太大。")})
            try:
                data = json.loads(body or b"{}")
            except (ValueError, RecursionError):
                return self._json(400, {"error": tr("資料格式不對。")})
            return self._ai(lambda: ai_engines.api_post(app, path, data))

        if path in library_api.POST:
            return self._json(200, library_api.post(app, path, json.loads(self._body() or b"{}")))
        if path in jobs_api.POST:  # 一键停止翻译
            return self._json(200, jobs_api.post(app, path, json.loads(self._body() or b"{}")))
        if path == "/api/update":  # 开关“自动检查新版本”
            config.save({"check_updates": bool(json.loads(self._body() or b"{}").get("enabled"))})
            return self._json(200, updates.check())
        if path == "/api/presence/keep":  # easyread serve 复用了关页会退出的服务：改成常驻
            if app.presence:
                app.presence.keep()
            return self._json(200, {"ok": True})
        if path == "/api/import":  # 请求体就是 PDF 文件
            data = self._body()
            ws, fresh = lib.create_from_pdf(data, q.get("name", "paper.pdf"))
            return self._import_result(ws, fresh, q.get("translate", "1") == "1", q.get("scope"),
                                       read=q.get("read") == "1", model=q.get("model", ""), target=q.get("target", ""))
        if path in ("/api/import-url", "/api/import-arxiv"):
            body = json.loads(self._body() or b"{}")
            data, name, meta = lib.fetch(body.get("ref", ""))  # sources.SourceError 是 ValueError，回 400
            ws, fresh = lib.create_from_pdf(data, name, meta)
            return self._import_result(ws, fresh, bool(body.get("translate", True)), body.get("scope"),
                                       read=bool(body.get("read")), model=str(body.get("model") or ""), target=str(body.get("target") or ""))
        if path in settings_api.POST:  # 设置页：保存配置、模型名单、试一下、取模型列表
            return self._json(200, settings_api.POST[path](json.loads(self._body() or b"{}")))
        if path == "/api/prefs":
            return self._json(200, prefs.save(json.loads(self._body() or b"{}")))
        if path == "/api/trash":  # 回收站：還原或永久刪除論文
            body = json.loads(self._body() or b"{}")
            act, name, item_type = body.get("action"), body.get("name", ""), body.get("type", "paper")
            if act not in ("restore", "purge", "empty"):
                raise ValueError(tr("action 只能是 restore / purge / empty"))
            if item_type != "paper":
                raise ValueError(tr("回收站項目類型不正確"))
            if act == "restore":
                return self._json(200, {"id": trash.restore(lib.root, name)})
            if act == "purge":
                return self._json(200, {"deleted": trash.purge(lib.root, name)})
            return self._json(200, {"deleted": trash.empty(lib.root)})

        if path.startswith("/api/p/"):
            parts = path.split("/")
            ws = lib.ws(parts[3]) if len(parts) > 4 else None
            if not ws:
                return self._json(404, {"error": tr("没有这篇论文")})
            action = parts[4]
            body = json.loads(self._body() or b"{}")
            if action == "chat" and len(parts) > 5:
                sub, tid = parts[5], body.get("thread", "")
                if sub == "pin":
                    chat_store.pin(ws, tid, body.get("id", ""))
                elif sub == "rename":
                    chat_store.rename(ws, tid, body.get("title", ""))
                elif sub == "delete":
                    chat_store.delete(ws, tid)
                elif sub == "rate":  # 逐句標「正確 / 錯誤 / 編造」（ticket 12）
                    verdict = body.get("verdict")
                    return self._json(200, {"ratings": chat_store.rate(ws, str(tid)[:64], str(body.get("id", ""))[:64],
                                                                         str(body.get("key", "")), verdict if verdict else None)})
                return self._json(200, {"threads": chat_store.threads(ws)})
            if action == "chat":
                return self._chat(ws, body)
            if action == "chat-export":
                from .chat_markdown import export
                return self._json(200, export(ws, body))
            if action == "notehelp":
                return notehelp.handle(self, ws, body)
            if action == "discussion_del":
                return self._json(200, {"deleted": paperdata.delete_discussion(ws, str(body.get("id", "")))})
            if action == "smart-annotate":
                scope = str(body.get("scope") or "all")
                mode = str(body.get("mode") or "auto")
                intensity = str(body.get("intensity") or "standard")
                if scope not in ("all", "section"):
                    raise ValueError(tr("智慧標註範圍不正確"))
                if mode not in ("auto", "suggest", "purpose"):
                    raise ValueError(tr("智慧標註模式不正確"))
                if intensity not in ("concise", "standard", "detailed"):
                    raise ValueError(tr("智慧標註強度不正確"))
                meta = (ws.load("paper") or {}).get("meta") or {}
                title = str(meta.get("title_zh") or meta.get("title_en") or tr("未命名論文"))[:300]
                return self._json(200, app.jobs.submit_small(
                    "smart-annotate", ws.id, scope=scope, section_id=str(body.get("section_id") or ""),
                    mode=mode, intensity=intensity, purpose=str(body.get("purpose") or "")[:500],
                    model=str(body.get("model") or ""), title=title,
                ))
            if action == "smart-annotate-cancel":
                return self._json(200, {"cancelled": app.jobs.cancel_small(str(body.get("job") or ""))})
            if action == "smart-annotation":
                from . import smart_annotations
                return self._json(200, smart_annotations.apply_action(ws, body))
            if action == "ops":
                ops = body.get("ops") or []
                if not isinstance(ops, list):
                    raise ValueError(tr("ops 必须是数组"))
                res = ws.apply_reader_ops(ops, client=str(body.get("client", ""))[:40])
                res["versions"] = ws.versions()
                return self._json(200, res)
            if action == "item":
                return self._json(200, ws.patch_item(body))
            if action == "translate":
                return self._json(200, translate_api.enqueue(app.jobs, ws, body))
            if action == "reveal":  # 在资源管理器 / 访达里打开这篇的文件夹
                _reveal(ws.root)
                return self._json(200, {"ok": True})
            if action == "cancel":
                app.jobs.cancel(ws.id)
                return self._json(200, {"ok": True})
            if action == "answer":
                return self._json(200, app.jobs.submit_small("answer", ws.id, note=body["note"]))
            if action == "retranslate":
                return self._json(200, app.jobs.submit_small("retranslate", ws.id, key=body["key"], hint=body.get("hint", "")))
            if action == "delete":
                app.jobs.cancel(ws.id)
                return self._json(200, {"trash": str(lib.trash(ws.id))})
        return self._json(404, {"error": "not found"})

