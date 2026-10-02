"""论文笔记的 AI 帮手：点评、帮我改、起草稿。

和“问 AI”对话分开：结果直接流回笔记面板，不进对话记录；由读者决定要不要替换或追加到笔记里。
输出格式和对话一样：一行一个 JSON，{"t": 片段} … 最后 {"done": true} 或 {"error": …}。
"""
from __future__ import annotations

import json
import threading

from . import langs
from . import chat, chat_models, config, engines
from .i18n import tr
from .log import log
from .prompts import _block_text
from .store import Workspace

PAPER_BUDGET = 14000  # 不能自己读文件的引擎：随提示词附上的译文字数上限

ASK = {
    "review": ("请点评这份笔记：哪些理解是准确的；哪些地方和论文不符或理解有误（说清论文实际怎么说、在哪一节）；"  # i18n-ok 提示词
               "漏掉了哪些重要内容；还可以往哪想。直接、具体，分条写，不要客套，不要重写整份笔记。"),  # i18n-ok
    "revise": ("请帮读者修改这份笔记：保留他的观点、结构和口吻，修正和论文不符的地方，补上明显漏掉的要点，把表达理顺。"  # i18n-ok
               "只输出修改后的完整笔记（Markdown，公式写 $TeX$），不要解释改了什么。"),  # i18n-ok
    "draft": ("读者还没写笔记。请帮他起一个读书笔记草稿，留出他自己思考的空间：核心问题、方法要点、主要结论、"  # i18n-ok
              "局限或疑问（这一项只列问题，不替他下结论）。用 Markdown，简洁，公式写 $TeX$。只输出笔记本身。"),  # i18n-ok
}


def _paper_text(ws: Workspace) -> str:
    out, used = [], 0
    for b in ws.load("paper").get("blocks", []):
        if b.get("type") == "references":
            break
        t = _block_text(b) if b.get("type") != "heading" else "\n## " + (b.get("zh") or b.get("en") or "")
        if not t:
            continue
        if used + len(t) > PAPER_BUDGET:
            out.append("……（后面的内容略）")  # i18n-ok 提示词
            break
        out.append(t)
        used += len(t)
    return "\n".join(out)


def prompt(ws: Workspace, mode: str, note: str, engine: str) -> str:
    meta = ws.load("paper").get("meta", {})
    title = meta.get("title_zh") or meta.get("title_en") or ""
    paper = ("论文全文在当前目录的 paper.json 里（blocks 里是译文和原文），需要核对时用 Read 工具去读。"  # i18n-ok 提示词
             if engine == "claude" else "论文译文（节选）：\n" + _paper_text(ws))  # i18n-ok
    return (f"你在帮读者整理读论文《{title}》的笔记。用{langs.reply_lang(meta)}。{ASK[mode]}\n\n{paper}\n\n"  # i18n-ok
            + (f"读者的笔记：\n<<<\n{note}\n>>>" if note.strip() else ""))  # i18n-ok


def handle(handler, ws: Workspace, body: dict) -> None:
    """server.py 里 POST /api/p/<id>/notehelp 调这里；handler 是那次请求的 BaseHTTPRequestHandler。"""
    mode = body.get("mode")
    note = str(body.get("note") or "")[:20000]
    if mode not in ASK:
        raise ValueError(tr("mode 只能是 review / revise / draft"))
    if mode != "draft" and not note.strip():
        raise ValueError(tr("笔记还是空的"))
    ecfg, m = chat_models.engine_cfg(config.load(), body.get("model"))
    text = prompt(ws, mode, note, ecfg["engine"])
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True
    cancel = threading.Event()

    def send(obj):
        handler.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        handler.wfile.flush()
    try:
        send({"model": chat_models.label(m)})
        for piece in chat.stream(ecfg, text, ws.root, cancel):
            send({"t": piece})
        send({"done": True})
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        cancel.set()  # 读者点了停止或关了页面
    except engines.Cancelled:
        pass
    except Exception as e:  # noqa: BLE001
        log.exception("笔记帮手出错 %s", ws.id)
        try:
            send({"error": str(e)[:500]})
        except OSError:
            pass
