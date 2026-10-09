from __future__ import annotations

import difflib
import json
import os
import re
import time
import uuid
from pathlib import Path

from .. import config, engines
from .. import library as library_module
from ..i18n import tr
from ..store import dir_lock, read_json, write_json_atomic
from . import workflows
from .markdown import FRONTMATTER, metadata, new_note
from .store import atomic_replace, markdown_path, sha256_text, state_dir, validate_vault_path, vault_path


def _relative(root: Path, path: Path) -> str:
    """Return a Vault-relative POSIX path across Windows long/short spellings."""
    # Windows runners can spell the same temporary directory as either its
    # long path or an 8.3 path (for example RUNNER~1).  ``Path.relative_to``
    # compares those strings literally, so use the platform's relpath logic
    # after the path has already passed validate_vault_path().
    root_real = os.path.realpath(str(root))
    path_real = os.path.realpath(str(path))
    return os.path.relpath(path_real, root_real).replace(os.sep, "/")


def _proposal_file(identity: str) -> Path:
    if not re.fullmatch(r"[0-9a-f-]{36}", identity or ""):
        raise ValueError(tr("提案編號格式不正確。"))
    return state_dir() / "proposals" / f"{identity}.json"


def list_notes() -> list[dict]:
    root = vault_path()
    if root is None:
        return []
    notes = []
    for path in root.glob("Research/**/*.md"):
        try:
            text = path.read_text(encoding="utf-8-sig")
            meta, body = metadata(text)
            if not meta.get("research_id"):
                continue
            title = next((m.group(1).strip() for line in body.splitlines() if (m := re.match(r"^#\s+(.+)$", line))), path.stem)
            notes.append({"path": _relative(root, path), "title": title, "kind": meta.get("type", ""),
                          "id": meta.get("research_id", "")})
        except (OSError, UnicodeError):
            continue
    return sorted(notes, key=lambda item: (item["kind"], item["title"].casefold()))


def create(title: str, kind: str, task: str, library, model: str = "", paper_id: str = "", block_id: str = "",
           target: str = "", limit: int = 10) -> dict:
    root = vault_path()
    if root is None:
        raise ValueError(tr("請先設定 Obsidian Vault 資料夾。"))
    if not task.strip():
        raise ValueError(tr("請描述要整理的研究內容。"))
    if kind not in workflows.KIND_GUIDANCE:
        raise ValueError(tr("不支援的研究筆記類型。"))
    title = re.sub(r"[\r\n\t]", " ", title or "").strip()[:180] or task.strip()[:100]
    found = workflows.gather(task, library, paper_id, block_id, limit)
    sources = found["sources"]
    existing = ""
    target_path = ""
    if target:
        destination = validate_vault_path(Path(target))
        if not destination.is_file():
            raise ValueError(tr("找不到要更新的 Obsidian 筆記。"))
        if destination.suffix.lower() != ".md":
            raise ValueError(tr("只能更新 Markdown 筆記。"))
        original = destination.read_text(encoding="utf-8-sig")
        meta, body = metadata(original)
        if not meta.get("research_id"):
            raise ValueError(tr("只能更新由 Research OS 建立並具有 research_id 的筆記。"))
        existing = body
        base_content = original
        target_path = _relative(root, destination)

    from .. import chat_models
    cfg = config.load()
    engine_cfg, selected = chat_models.engine_cfg(cfg, model or (cfg.get("chat") or {}).get("default"))
    prompt = workflows._prompt(task, kind, sources, existing)
    meter = __import__("easyread.usage", fromlist=["Meter"]).Meter(engine_cfg.get("engine", ""))
    output = engines.run(engines.for_translation(engine_cfg), prompt, root, [], None, meter).strip()
    if not output:
        raise ValueError(tr("模型沒有產生筆記內容。"))
    # Some models ignore the no-frontmatter instruction. Keep the existing user-owned
    # properties intact and use only the generated body.
    generated_meta, generated_body = metadata(output)
    body = workflows._cite_body(generated_body if generated_meta else output, sources)
    if target_path:
        match = FRONTMATTER.match(base_content)
        prefix = match.group(0) if match else ""
        next_content = prefix + "\n" + body.rstrip() + "\n"
    else:
        paper_sources = sorted({f"sha256:{item['sha256']}" for item in sources if item.get("sha256")})
        evidence = sorted({f"{item['sha256']}:{item['block']}:{sha256_text(item['quote'])}"
                           for item in sources if item.get("sha256") and item.get("block")})
        extra = {"source_papers": paper_sources, "source_evidence": evidence}
        if kind == "hypothesis":
            extra["status"] = "proposed"
        next_content = new_note(kind, title, body, extra)
        identity = re.search(r'research_id: "([^\"]+)"', next_content).group(1)
        target_path = _relative(root, markdown_path(root, kind, title, identity))
        base_content = ""

    destination = validate_vault_path(Path(target_path))
    before_hash = sha256_text(base_content) if target_path and base_content else ""
    proposal = {
        "id": str(uuid.uuid4()), "status": "pending", "kind": kind, "title": title,
        "task": task[:3000], "target": target_path, "base_hash": before_hash,
        "before": base_content, "after": next_content, "diff": "\n".join(difflib.unified_diff(
            base_content.splitlines(), next_content.splitlines(), fromfile="Obsidian 現有內容" if base_content else "/dev/null",
            tofile="Research OS 提案", lineterm="")),
        "sources": sources, "model": selected.get("name") or selected.get("id"),
        "model_id": selected.get("id"), "usage": meter.snapshot(), "created": time.time(),
        "vault_relative": _relative(root, destination),
    }
    path = _proposal_file(proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def from_comparison(title: str, body: str, papers: list[dict], model: str, model_usage: dict) -> dict:
    """Stage a new comparison note; only decide() may write it to the Vault."""
    root = vault_path()
    if root is None:
        raise ValueError(tr("請先設定 Obsidian Vault 資料夾。"))
    paper_links = []
    papers_dir = root / "Research" / "Papers"
    def normalize(value: str) -> str:
        return " ".join(value.casefold().split())

    for note in papers_dir.rglob("*.md") if papers_dir.is_dir() else []:
        try:
            text = note.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        meta, note_body = metadata(text)
        note_title = next((match.group(1).strip() for line in note_body.splitlines()
                           if (match := re.match(r"^#\s+(.+)$", line))), note.stem)
        linked_by_hash = meta.get("type") == "paper" and any(
            item.get("sha256") and item["sha256"] in text for item in papers)
        linked_by_title = any(normalize(note_title) in {
            normalize(item.get("title") or ""), normalize(item.get("title_en") or ""),
            normalize(item.get("title_zh") or ""),
        } - {""} for item in papers)
        if linked_by_hash or linked_by_title:
            paper_links.append(f"- [[{Path(_relative(root, note)).with_suffix('').as_posix()}]]")
    if paper_links:
        body = body.rstrip() + "\n\n## 相關單篇筆記\n\n" + "\n".join(sorted(set(paper_links)))
    title = re.sub(r"[\r\n\t]", " ", title).strip()[:100] or "論文比較"
    extra = {"source_papers": [f"sha256:{item['sha256']}" for item in papers if item.get("sha256")],
             "comparison_model": model}
    content = new_note("comparison", title, body, extra)
    identity = re.search(r'research_id: "([^\"]+)"', content).group(1)
    destination = markdown_path(root, "comparison", title, identity)
    target = _relative(root, destination)
    proposal = {"id": str(uuid.uuid4()), "status": "pending", "kind": "comparison", "title": title,
                "task": "比較指定的論文", "target": target, "base_hash": "", "before": "", "after": content,
                "diff": "\n".join(difflib.unified_diff([], content.splitlines(), fromfile="/dev/null",
                                                    tofile="Obsidian 比較筆記提案", lineterm="")),
                "sources": papers, "model": model, "usage": model_usage, "created": time.time(),
                "vault_relative": target}
    path = _proposal_file(proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def from_topic_matrix(topic_path: str, row: dict, model: str, model_usage: dict) -> dict:
    """Stage a single matrix-row patch while preserving every byte outside its managed region."""
    root = vault_path()
    if root is None:
        raise ValueError(tr("請先設定 Obsidian Vault 資料夾。"))
    destination = validate_vault_path(Path(topic_path))
    if not destination.is_file():
        raise ValueError(tr("找不到要加入矩陣的主題筆記。"))
    before = destination.read_text(encoding="utf-8-sig")
    meta, body = metadata(before)
    if meta.get("type") != "topic" or not meta.get("research_id"):
        raise ValueError(tr("只能更新 Research OS 建立的 Topic 筆記。"))

    start = "<!-- research-os:topic-matrix:start -->"
    end = "<!-- research-os:topic-matrix:end -->"
    has_start, has_end = start in body, end in body
    if has_start != has_end:
        raise ValueError(tr("主題矩陣標記不完整，請先修復或移除標記後再試。"))
    headers = ["論文", "研究問題", "方法與核心機制", "輸入與輸出", "實驗證據與條件", "限制", "我的判斷"]
    row_cells = row.get("cells") or {}
    paper_hash = str(row.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", paper_hash):
        raise ValueError(tr("矩陣列缺少有效的論文 SHA-256。"))

    def render_row(judgment: str | None = None) -> str:
        values = [row_cells.get("title", ""), row_cells.get("problem", "未報告"), row_cells.get("method", "未報告"),
                  row_cells.get("io", "未報告"), row_cells.get("evidence", "未報告"), row_cells.get("limitations", "未報告"),
                  judgment if judgment is not None else row_cells.get("judgment", "待自行補充")]
        values[-1] = (values[-1] or "待自行補充") + f" <!-- research-os:paper-sha256:{paper_hash} -->"
        return "| " + " | ".join(str(value).replace("\r", " ").replace("\n", " ") for value in values) + " |"

    candidate_row = render_row()
    if has_start:
        left, rest = body.split(start, 1)
        managed, right = rest.split(end, 1)
        existing_row = next((line for line in managed.splitlines()
                             if f"research-os:paper-sha256:{paper_hash}" in line), "")
        if existing_row:
            cells = re.split(r"(?<!\\)\|", existing_row.strip().strip("|"))
            previous_judgment = cells[6].strip() if len(cells) >= 7 else "待自行補充"
            previous_judgment = re.sub(r"\s*<!--\s*research-os:paper-sha256:[0-9a-f]{64}\s*-->\s*", "", previous_judgment)
            candidate_row = render_row(previous_judgment or "待自行補充")
            managed_lines = [line for line in managed.splitlines() if line != existing_row]
            managed = "\n".join(managed_lines).strip("\n")
        if not managed.strip():
            managed = "\n" + "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |"
        if candidate_row not in managed:
            managed = managed.rstrip() + "\n" + candidate_row
        after_body = left + start + "\n\n" + managed.strip("\r\n") + "\n\n" + end + right
    else:
        table = ("\n\n## 主題研究矩陣\n\n" + start + "\n\n| " + " | ".join(headers) + " |\n| " +
                 " | ".join("---" for _ in headers) + " |\n" + candidate_row + "\n\n" + end + "\n")
        after_body = body.rstrip() + table
    match = FRONTMATTER.match(before)
    prefix = match.group(0) if match else ""
    after = prefix + after_body
    if not after.endswith("\n"):
        after += "\n"
    relative = _relative(root, destination)
    proposal = {
        "id": str(uuid.uuid4()), "status": "pending", "kind": "matrix", "title": row.get("title") or "主題研究矩陣",
        "task": "將一篇論文加入主題研究矩陣", "target": relative, "base_hash": sha256_text(before),
        "before": before, "after": after,
        "diff": "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                                   fromfile="Obsidian 主題筆記", tofile="主題矩陣提案", lineterm="")),
        "sources": [{"title": row.get("title", ""), "sha256": paper_hash}], "model": model,
        "usage": model_usage, "created": time.time(), "vault_relative": relative,
    }
    path = _proposal_file(proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def create_topic(title: str) -> dict:
    """Stage an empty, user-editable topic note without inventing research claims."""
    root = vault_path()
    if root is None:
        raise ValueError(tr("請先設定 Obsidian Vault 資料夾。"))
    if latest_pending_topic():
        raise ValueError(tr("請先審閱或捨棄目前的新 Topic 提案。"))
    title = re.sub(r"[\r\n\t]", " ", str(title or "")).strip()[:120]
    if not title:
        raise ValueError(tr("請輸入主題名稱。"))
    body = ("## 主題範圍\n\n待補充。\n\n## 研究方法族群\n\n待補充。\n\n"
            "## 代表論文\n\n待補充。\n\n## 共識與爭議\n\n待補充。\n\n"
            "## 開放問題\n\n待補充。\n\n## 主題研究矩陣\n\n"
            "<!-- research-os:topic-matrix:start -->\n\n"
            "| 論文 | 研究問題 | 方法與核心機制 | 輸入與輸出 | 實驗證據與條件 | 限制 | 我的判斷 |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "\n<!-- research-os:topic-matrix:end -->\n")
    content = new_note("topic", title, body)
    identity = re.search(r'research_id: "([^\"]+)"', content).group(1)
    destination = markdown_path(root, "topic", title, identity)
    relative = _relative(root, destination)
    proposal = {"id": str(uuid.uuid4()), "status": "pending", "kind": "topic", "title": title,
                "task": "建立空白 Topic 筆記範本", "target": relative, "base_hash": "", "before": "",
                "after": content, "diff": "\n".join(difflib.unified_diff([], content.splitlines(),
                    fromfile="/dev/null", tofile="Obsidian Topic 筆記提案", lineterm="")),
                "sources": [], "model": "", "usage": {}, "created": time.time(), "vault_relative": relative}
    path = _proposal_file(proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, proposal)
    return _public_proposal(proposal)


def _public_proposal(proposal: dict) -> dict:
    result = {key: proposal.get(key) for key in ("id", "status", "kind", "title", "task", "target", "diff", "sources", "model", "usage", "conflict")}
    if proposal.get("kind") in ("comparison", "matrix", "topic"):
        result["content"] = metadata(proposal.get("after") or "")[1]
    return result


def get(identity: str) -> dict:
    proposal = read_json(_proposal_file(identity), None)
    if not proposal:
        raise ValueError(tr("找不到這個研究提案。"))
    return _public_proposal(proposal)


def latest_pending_comparison() -> dict | None:
    return _latest_pending("comparison")


def latest_pending_matrix() -> dict | None:
    return _latest_pending("matrix")


def latest_pending_topic() -> dict | None:
    return _latest_pending("topic")


def _latest_pending(kind: str) -> dict | None:
    folder = state_dir() / "proposals"
    if not folder.is_dir():
        return None
    candidates = []
    for path in folder.glob("*.json"):
        proposal = read_json(path, None)
        if proposal and proposal.get("kind") == kind and proposal.get("status") == "pending":
            candidates.append(proposal)
    return _public_proposal(max(candidates, key=lambda item: item.get("created", 0))) if candidates else None


def decide(identity: str, accept: bool) -> dict:
    path = _proposal_file(identity)
    proposal = read_json(path, None)
    if not proposal:
        raise ValueError(tr("找不到這個研究提案。"))
    if proposal.get("status") != "pending":
        return _public_proposal(proposal)
    if not accept:
        proposal["status"] = "rejected"
        write_json_atomic(path, proposal)
        return _public_proposal(proposal)

    root = vault_path()
    if root is None:
        raise ValueError(tr("Obsidian Vault 資料夾尚未設定。"))
    destination = validate_vault_path(Path(proposal["target"]))
    with dir_lock(state_dir(), ".proposal-review.lock", timeout=15):
        exists = destination.exists()
        current = destination.read_text(encoding="utf-8-sig") if exists else ""
        current_hash = sha256_text(current) if exists else ""
        stale = current_hash != proposal.get("base_hash", "")
        if stale:
            proposal["status"] = "conflict"
            proposal["conflict"] = True
            proposal["latest_diff"] = "\n".join(difflib.unified_diff(
                proposal.get("before", "").splitlines(), current.splitlines(), fromfile="審閱時的基準", tofile="Obsidian 目前內容", lineterm=""))
            write_json_atomic(path, proposal)
            return {**_public_proposal(proposal), "conflict": True,
                    "error": tr("審閱期間筆記已變更，沒有套用這份提案。請重新建立提案，再檢查新的差異。")}

        if exists:
            backup_dir = state_dir() / "backups" / identity
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"{int(time.time())}-{destination.name}"
            backup.write_bytes(destination.read_bytes())
            proposal["backup"] = str(backup)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
        # Repeat the content check immediately before replacing the note. If it changed
        # after the backup was made, retain both versions and ask for another review.
        latest = destination.read_text(encoding="utf-8-sig") if destination.exists() else ""
        if (sha256_text(latest) if latest else "") != proposal.get("base_hash", ""):
            proposal["status"] = "conflict"
            proposal["conflict"] = True
            write_json_atomic(path, proposal)
            return {**_public_proposal(proposal), "conflict": True,
                    "error": tr("Obsidian 筆記在儲存前又有變更，請重新檢查差異。")}
        atomic_replace(destination, proposal["after"].encode("utf-8"))
        proposal["status"] = "accepted"
        proposal["accepted_at"] = time.time()
        proposal["written_path"] = _relative(root, destination)
        write_json_atomic(path, proposal)
    from . import index
    try:
        index.index_vault(rebuild=False)
    except Exception:  # Keep the accepted note even if the derived index is unavailable.
        pass
    return {**_public_proposal(proposal), "path": proposal.get("written_path"), "backup": proposal.get("backup")}
