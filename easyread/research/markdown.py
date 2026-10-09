from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path


FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)


@dataclass
class MarkdownNote:
    identity: str
    kind: str
    title: str
    body: str
    path: str
    headings: tuple[str, ...]
    tags: tuple[str, ...]


def metadata(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER.match(text)
    fields = {}
    if not match:
        return fields, text
    for line in match.group(1).splitlines():
        found = re.match(r"^([\w-]+):\s*(.*?)\s*$", line)
        if found:
            fields[found.group(1)] = found.group(2).strip("\"'")
    return fields, text[match.end():]


def readable(text: str) -> str:
    _, body = metadata(text)
    body = re.sub(r"```.*?```", " ", body, flags=re.S)
    body = re.sub(r"`([^`]*)`", r"\1", body)
    body = re.sub(r"!?(?:\[([^\]]*)\]\([^)]+\)|\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\])", lambda m: m.group(3) or m.group(1) or m.group(2) or "", body)
    body = re.sub(r"^\s{0,3}(?:>|[-*+] |\d+\. )", "", body, flags=re.M)
    body = re.sub(r"[*_~#]", "", body)
    return re.sub(r"\s+", " ", body).strip()


def parse_note(path: Path, relative: str, text: str) -> MarkdownNote:
    meta, body = metadata(text)
    title = next((m.group(1).strip() for line in body.splitlines() if (m := re.match(r"^#\s+(.+)$", line))), path.stem)
    headings = tuple(m.group(1).strip() for line in body.splitlines() if (m := re.match(r"^#{1,4}\s+(.+)$", line)))
    identity = meta.get("research_id") or "note-" + __import__("hashlib").sha256(relative.encode()).hexdigest()[:24]
    tags = tuple(m.group(1) for m in re.finditer(r"(?<![\w/])#([\w/-]{2,})", body))
    return MarkdownNote(identity, meta.get("type", "note"), title, body, relative, headings, tags)


def chunks(note: MarkdownNote, text: str, max_chars: int = 1050) -> list[tuple[str, str]]:
    _, body = metadata(text)
    section = "Introduction"
    paragraphs: list[tuple[str, str]] = []
    current: list[str] = []
    current_section = section

    def flush():
        value = "\n".join(current).strip()
        if value:
            paragraphs.append((current_section, value))
        current.clear()

    for line in body.splitlines():
        heading = re.match(r"^#{1,4}\s+(.+)$", line)
        if heading:
            flush()
            section = heading.group(1).strip()
            current_section = section
        elif not line.strip():
            flush()
            current_section = section
        else:
            current.append(line)
    flush()

    output: list[tuple[str, str]] = []
    for heading, paragraph in paragraphs:
        cjk = sum("\u3400" <= char <= "\u9fff" for char in paragraph) / max(1, len(paragraph)) > 0.08
        cap = min(max_chars, 320) if cjk else max_chars
        if len(paragraph) <= cap:
            output.append((heading, paragraph))
            continue
        step = max(1, cap - min(100, cap // 4))
        for start in range(0, len(paragraph), step):
            piece = paragraph[start:start + cap].strip()
            if piece:
                output.append((heading, piece))
    return output


def new_note(kind: str, title: str, body: str, extra: dict | None = None) -> str:
    identity = str(uuid.uuid4())
    safe_title = title.strip() or kind.title()
    lines = ["---", f'research_id: "{identity}"', f'type: "{kind}"', 'schema_version: 1']
    for key, value in (extra or {}).items():
        if key in ("source_papers", "source_evidence") and isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f'  - "{str(item).replace(chr(34), chr(92) + chr(34))}"' for item in value)
        elif re.fullmatch(r"[\w-]+", key):
            escaped = str(value).replace('"', '\\"').replace("\n", " ")
            lines.append(f'{key}: "{escaped}"')
    lines.extend(["---", "", f"# {safe_title}", "", body.strip(), ""])
    return "\n".join(lines)
