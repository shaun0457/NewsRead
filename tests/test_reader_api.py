"""閱讀器自己的 API（ticket 03）：Vault 設定、Obsidian / zip 匯出、心智圖，不經過研究工作區。

匯出結果跟抽出來之前逐字相同：tests/fixtures/obsidian_export_golden.json 是用改動前的程式（git HEAD 的
easyread/research/obsidian_export.py）跑 tests/fixtures/obsidian_export_documents.json 產生的。
"""
from __future__ import annotations

import base64
import io
import json
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from easyread import chat_models, engines, mindmap, obsidian_export, planning_store, prefs, reader_api, tasks, vault

from tests.doubles import ApiTestCase

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_TIME = 1_700_000_000.0


def documents():
    return json.loads((FIXTURES / "obsidian_export_documents.json").read_text(encoding="utf-8"))


def golden():
    return json.loads((FIXTURES / "obsidian_export_golden.json").read_text(encoding="utf-8"))


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.read_text(encoding="utf-8") if p.suffix in (".md", ".json")
                                             else "base64:" + base64.b64encode(p.read_bytes()).decode("ascii"))
            for p in sorted(root.rglob("*")) if p.is_file()}


class Workspace:
    def __init__(self, identity, paper):
        self.id = identity
        self.values = {"paper": paper, "item": {}}

    def load(self, name):
        return self.values.get(name)


class Library:
    def __init__(self, root):
        self.root = root
        self.workspaces = {}

    def ws(self, identity):
        return self.workspaces.get(identity)

    def all(self):
        return list(self.workspaces.values())


class ReaderApiCase(ApiTestCase):
    def make_app(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.vault_dir = base / "vault"
        self.vault_dir.mkdir()
        self.lib_root = base / "library"
        self.lib_root.mkdir()
        self.lib = Library(self.lib_root)
        return {"lib": self.lib}

    def use_vault(self, root: Path | None):
        patcher = mock.patch.object(vault, "vault_path", lambda: root)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(obsidian_export, "vault_path", lambda: root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def freeze_time(self):
        patcher = mock.patch.object(obsidian_export.time, "time", lambda: FIXED_TIME)
        patcher.start()
        self.addCleanup(patcher.stop)


class ExportTest(ReaderApiCase):
    def test_obsidian_export_matches_the_output_from_before_the_extraction(self):
        self.use_vault(self.vault_dir)
        self.freeze_time()
        want = golden()
        status, first = self.request("POST", "/api/reader/export/obsidian", {"documents": documents()})
        self.assertEqual(status, 200)
        self.assertEqual(first, want["first"])
        self.assertEqual(tree(self.vault_dir), want["after_first"])

    def test_re_export_keeps_handwritten_text_outside_the_managed_block(self):
        self.use_vault(self.vault_dir)
        self.freeze_time()
        want = golden()
        self.request("POST", "/api/reader/export/obsidian", {"documents": documents()})
        note = next(p for p in self.vault_dir.rglob("*.md") if "analysis" in p.name)
        note.write_text(note.read_text(encoding="utf-8") + "\n我在 Obsidian 手寫的段落（範例）\n", encoding="utf-8")
        status, second = self.request("POST", "/api/reader/export/obsidian", {"documents": documents()})
        self.assertEqual(status, 200)
        self.assertEqual(second, want["second"])
        after = tree(self.vault_dir)
        self.assertEqual(after, want["after_second"])
        self.assertIn("我在 Obsidian 手寫的段落（範例）", after[note.relative_to(self.vault_dir).as_posix()])

    def test_zip_export_matches_the_output_from_before_the_extraction(self):
        self.use_vault(self.vault_dir)
        self.freeze_time()
        want = golden()
        # golden 的 zip 是在兩次匯出之後打包的：先把 Vault 弄成同樣的狀態
        self.request("POST", "/api/reader/export/obsidian", {"documents": documents()})
        note = next(p for p in self.vault_dir.rglob("*.md") if "analysis" in p.name)
        note.write_text(note.read_text(encoding="utf-8") + "\n我在 Obsidian 手寫的段落（範例）\n", encoding="utf-8")
        self.request("POST", "/api/reader/export/obsidian", {"documents": documents()})
        status, result = self.request("POST", "/api/reader/export/zip", {"documents": documents()})
        self.assertEqual(status, 200)
        self.assertEqual(result["filename"], want["zip_filename"])
        self.assertEqual(result["conflicts"], want["zip_conflicts"])
        archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(result["content_base64"])))
        entries = {name: base64.b64encode(archive.read(name)).decode("ascii") for name in sorted(archive.namelist())}
        self.assertEqual(entries, want["zip_entries"])

    def test_export_without_a_vault_is_refused(self):
        self.use_vault(None)
        status, body = self.request("POST", "/api/reader/export/obsidian", {"documents": documents()})
        self.assertEqual(status, 400)
        self.assertIn("Vault", body["error"])
        self.assertEqual(list(self.vault_dir.iterdir()), [])

    def test_writes_need_the_token(self):
        self.use_vault(self.vault_dir)
        status, _ = self.request("POST", "/api/reader/export/obsidian", {"documents": documents()}, token="wrong")
        self.assertEqual(status, 403)
        self.assertEqual(list(self.vault_dir.iterdir()), [])


class VaultTest(ReaderApiCase):
    def test_status_before_and_after_setup(self):
        saved = {}
        with mock.patch.object(prefs, "load", lambda: saved), \
                mock.patch.object(prefs, "save", lambda patch: saved.update(patch)):
            status, before = self.request("GET", "/api/reader/vault")
            self.assertEqual((status, before), (200, {"vault": "", "configured": False}))
            status, after = self.request("POST", "/api/reader/vault", {"vault": str(self.vault_dir)})
            self.assertEqual(status, 200)
            self.assertTrue(after["configured"])
            self.assertEqual(Path(after["vault"]), self.vault_dir.resolve())
            self.assertEqual(self.request("GET", "/api/reader/vault"), (200, after))
        # 設定沿用舊鍵名 research.vault，舊使用者的設定照樣讀得到
        self.assertEqual(Path(saved["research"]["vault"]), self.vault_dir.resolve())
        self.assertTrue((self.vault_dir / "Research" / "02-心智圖").is_dir())

    def test_empty_vault_path_is_refused(self):
        with mock.patch.object(prefs, "save") as save:
            status, _ = self.request("POST", "/api/reader/vault", {"vault": "  "})
        self.assertEqual(status, 400)
        save.assert_not_called()


class MindmapTest(ReaderApiCase):
    PAPER = {"meta": {"title_en": "Sample fab expansion"}, "blocks": [
        {"id": "s1", "type": "paragraph", "page": 1, "en": "A sample finding."}]}

    def setUp(self):
        super().setUp()
        self.lib.workspaces["p1"] = Workspace("p1", json.loads(json.dumps(self.PAPER)))
        cfg, model = {"engine": "fake"}, {"name": "fake-model"}
        for target, attr, value in ((chat_models, "engine_cfg", lambda *a: (cfg, model)),
                                    (engines, "for_translation", lambda value: value)):
            patcher = mock.patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls = []

        def fake_run(cfg, prompt, cwd, images=None, cancel=None, meter=None):
            self.calls.append(prompt)
            return "mindmap\n  root((Sample))\n    Capacity"

        patcher = mock.patch.object(engines, "run", fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_reads_the_cache_and_post_regenerates(self):
        status, empty = self.request("GET", "/api/reader/paper/p1/mindmap")
        self.assertEqual(status, 200)
        self.assertFalse(empty["cached"])
        self.assertEqual(self.calls, [])
        status, made = self.request("POST", "/api/reader/paper/p1/mindmap", {})
        self.assertEqual(status, 200)
        self.assertTrue(made["mermaid"].startswith("mindmap"))
        self.assertEqual(len(self.calls), 1)
        status, again = self.request("GET", "/api/reader/paper/p1/mindmap")
        self.assertTrue(again["cached"])
        self.assertEqual(again["mermaid"], made["mermaid"])
        self.assertEqual(len(self.calls), 1)  # GET 只讀快取，不呼叫模型

    def test_reads_a_mindmap_cached_by_the_research_workspace(self):
        """舊版（研究工作區）產生的心智圖還在 planning_store 快取裡，新 API 照樣讀得到。"""
        _, source_hash = mindmap.paper_source(self.lib.workspaces["p1"].values["paper"])
        key = "mindmap:" + mindmap.sha256(source_hash.encode()).hexdigest()
        planning_store.cache_put(self.lib_root, key, {"mermaid": "mindmap\n  root((Old))", "source_sha256": source_hash})
        status, result = self.request("GET", "/api/reader/paper/p1/mindmap")
        self.assertEqual(status, 200)
        self.assertTrue(result["cached"])
        self.assertIn("Old", result["mermaid"])

    def test_background_task_runs_and_can_be_acknowledged(self):
        status, submitted = self.request("POST", "/api/reader/paper/p1/mindmap/tasks", {})
        self.assertEqual(status, 200)
        identity = submitted["task"]["id"]
        deadline = time.monotonic() + 5
        task = submitted["task"]
        while task.get("state") not in ("completed", "failed") and time.monotonic() < deadline:
            time.sleep(0.02)
            task = self.request("GET", f"/api/reader/paper/p1/mindmap/tasks/{identity}")[1]["task"]
        self.assertEqual(task["state"], "completed")
        status, listed = self.request("GET", "/api/reader/tasks")
        self.assertEqual(status, 200)
        self.assertIn(identity, [t["id"] for t in listed["tasks"]])
        self.assertEqual(listed["scope_id"], tasks.scope_id(self.lib_root))
        status, acked = self.request("POST", f"/api/reader/paper/p1/mindmap/tasks/{identity}/ack", {})
        self.assertEqual(status, 200)
        self.assertTrue(acked["task"]["acknowledged"])
        self.assertEqual(self.request("GET", "/api/reader/paper/p1/mindmap/tasks/current")[1]["task"]["id"], identity)

    def test_tasks_list_leaves_out_research_workspace_work(self):
        scope = tasks.scope_id(self.lib_root)
        tasks.register_external("reading-path-x", "reading-path", scope=scope)
        tasks.register_external("smart-x", "smart-annotate", scope=scope)
        self.addCleanup(tasks.update_external, "reading-path-x", state="completed")
        self.addCleanup(tasks.update_external, "smart-x", state="completed")
        status, listed = self.request("GET", "/api/reader/tasks")
        self.assertEqual(status, 200)
        ids = [t["id"] for t in listed["tasks"]]
        self.assertNotIn("reading-path-x", ids)
        self.assertIn("smart-x", ids)  # 智慧標註是閱讀器的功能，照樣提示

    def test_cancel_unknown_task_is_a_bad_request(self):
        status, _ = self.request("POST", "/api/reader/paper/p1/mindmap/tasks/nope/cancel", {})
        self.assertEqual(status, 400)

    def test_cancel_and_ack_leave_other_kinds_of_work_alone(self):
        scope = tasks.scope_id(self.lib_root)
        tasks.register_external("smart-y", "smart-annotate", scope=scope, cancel_event=threading.Event())
        self.addCleanup(tasks.update_external, "smart-y", state="completed")
        for action in ("cancel", "ack"):
            status, _ = self.request("POST", f"/api/reader/paper/p1/mindmap/tasks/smart-y/{action}", {})
            self.assertEqual(status, 400, action)
        self.assertEqual(tasks.get("smart-y", scope=scope)["state"], "queued")  # 沒被取消

    def test_only_a_short_model_name_is_stored_with_the_task(self):
        for model, expected in (({"nested": ["x"] * 50}, None), ("m" * 101, None), ("fake-model", "fake-model")):
            with mock.patch.object(mindmap, "persist_task") as persist:
                status, submitted = self.request("POST", "/api/reader/paper/p1/mindmap/tasks", {"model": model})
                self.assertEqual(status, 200)
                self.assertEqual(persist.call_args.args[2], {"model": expected})
                deadline = time.monotonic() + 5  # 等這個工作結束，下一輪才不會被同一篇論文的去重吃掉
                while (tasks.get(submitted["task"]["id"], scope=tasks.scope_id(self.lib_root)) or {}).get("state") in (
                        "queued", "running") and time.monotonic() < deadline:
                    time.sleep(0.02)

    def test_unknown_paper_is_refused_without_calling_the_model(self):
        status, _ = self.request("POST", "/api/reader/paper/missing/mindmap", {})
        self.assertEqual(status, 400)
        self.assertEqual(self.calls, [])


class RoutingTest(ReaderApiCase):
    def test_unknown_paths_are_not_found(self):
        self.assertEqual(self.request("GET", "/api/reader/nope")[0], 404)
        self.assertEqual(self.request("GET", "/api/reader/paper/p1/mindmap/tasks")[0], 404)
        self.assertEqual(self.request("POST", "/api/reader/nope", {})[0], 404)
        # 工作 id 剛好叫 mindmap 也不能被當成「同步產生心智圖」
        self.assertEqual(self.request("POST", "/api/reader/paper/p1/mindmap/tasks/mindmap", {})[0], 404)

    def test_other_prefixes_are_left_alone(self):
        app = SimpleNamespace(lib=Library(Path(".")))
        self.assertIsNone(reader_api.get(app, "/api/readerx/vault"))
        self.assertIsNone(reader_api.post(app, "/api/research/v2/export/obsidian", {}))
