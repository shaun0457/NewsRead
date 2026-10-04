"""界面文字对账：哪些中文还没套 PR.t / tr，哪些词条缺英文。

    python scripts/i18n_check.py            # 列出问题，有问题时退出码 1
    python scripts/i18n_check.py --missing  # 只输出缺英文的词条（JSON，补翻译时用）

规则：前端界面文字写 PR.t("中文")，后端会显示到界面上的写 tr("中文")。
确实不该翻译的中文（匹配后端输出的正则、给模型的提示词……）在那一行末尾写注释 i18n-ok。
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "easyread" / "web"
EN = WEB / "i18n" / "en.json"
CJK = re.compile("[、-〿一-鿿！-～]")  # 汉字和全角标点

# 后端里只检查会显示到界面上的模块；cli（命令行）、prompts*（给模型的提示词）不翻
PY_SKIP = {"cli.py", "prompts.py", "prompts_en.py", "front_context.py", "i18n.py", "log.py", "__main__.py"}

_JS_STR = r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`'
_PY_STR = r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\''


def _unquote(lit: str) -> str:
    body = lit[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m[1], m[1]), body)


def _strip_js_comments(src: str) -> str:
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            m = re.compile(_JS_STR, re.S).match(src, i)
            if m:
                out.append(m[0]); i = m.end(); continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j])); i = j; continue
        out.append(c); i += 1
    return "".join(out)


def scan_js(path: Path, keys: set, raw: list):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    code = _strip_js_comments(text)
    for m in re.finditer(_JS_STR, code, re.S):
        lit = m[0]
        if not CJK.search(lit):
            continue
        line_no = code.count("\n", 0, m.start()) + 1
        if "i18n-ok" in lines[line_no - 1]:
            continue
        before = code[max(0, m.start() - 6):m.start()]
        if re.search(r"\bt\(\s*$", before) and not lit.startswith("`"):
            keys.add(_unquote(lit))
        else:
            raw.append(f"{path.relative_to(ROOT)}:{line_no}: {lit[:70]}")


def scan_py(path: Path, keys: set, raw: list):
    lines = path.read_text(encoding="utf-8").splitlines()
    in_doc = False
    for no, line in enumerate(lines, 1):
        s = line.strip()
        if s.count('"""') % 2 == 1:
            in_doc = not in_doc
            continue
        if in_doc or s.startswith("#") or s.startswith('"""') or "i18n-ok" in line:
            continue
        code = line.split("  #")[0]
        for m in re.finditer(r"(f?)(" + _PY_STR + ")", code):
            lit = m[2]
            if not CJK.search(lit):
                continue
            if re.search(r"\btr\(\s*$", code[:m.start()]) and not m[1]:
                keys.add(_unquote(lit))
            elif not re.search(r"\blog\.\w+\(\s*$", code[:m.start()]):  # 日志给人排查用，不翻
                raw.append(f"{path.relative_to(ROOT)}:{no}: {m[0][:70]}")


class _Html(HTMLParser):
    ATTRS = {"placeholder", "title", "aria-label", "alt"}

    def __init__(self):
        super().__init__()
        self.found, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for k, v in attrs:
            if k in self.ATTRS and v and CJK.search(v):
                self.found.append(v.strip())

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and CJK.search(data):
            self.found.append(data.strip())


def collect():
    keys, raw = set(), []
    for path in sorted((WEB / "js").rglob("*.js")):
        if path.name != "i18n.js":
            scan_js(path, keys, raw)
    for path in sorted(WEB.glob("*.html")):
        parser = _Html()
        parser.feed(path.read_text(encoding="utf-8"))
        keys.update(parser.found)
    for path in sorted((ROOT / "easyread").glob("*.py")):
        if path.name not in PY_SKIP:
            scan_py(path, keys, raw)
    return keys, raw


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    keys, raw = collect()
    en = json.loads(EN.read_text(encoding="utf-8"))
    missing = sorted(k for k in keys if not en.get(k))
    if "--missing" in sys.argv:
        print(json.dumps(missing, ensure_ascii=False, indent=1))
        return
    unused = sorted(set(en) - keys)
    for line in raw:
        print("没套 PR.t / tr：", line)
    for k in missing:
        print("缺英文：", k)
    for k in unused:
        print("用不到的英文（可以删）：", k)
    print(f"词条 {len(keys)}，缺英文 {len(missing)}，没套的中文 {len(raw)}，用不到 {len(unused)}")
    sys.exit(1 if raw or missing else 0)


if __name__ == "__main__":
    main()
