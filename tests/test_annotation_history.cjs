const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

async function reader() {
  const handlers = {}, storage = new Map();
  const PR = { t: s => s, uid: () => "client", nowIso: () => new Date().toISOString(), emit() {},
    toast() {}, ls: { get: (key, fallback) => storage.get(key) || fallback, set: (key, value) => { storage.set(key, value); return true; } } };
  const context = vm.createContext({ window: { PR, addEventListener() {} }, location: { pathname: "" },
    document: { addEventListener: (key, fn) => { handlers[key] = fn; }, body: { classList: { contains: () => false } },
      getElementById: () => ({ textContent: JSON.stringify({ paper: { meta: { source_sha256: "history" } }, reader: {} }) }) },
    setTimeout() {}, clearTimeout() {} });
  for (const file of ["store", "annotation-history"]) vm.runInContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/reader/" + file + ".js"), "utf8"), context);
  await PR.load();
  const put = patch => PR.commit({ op: "note", note: { ...PR.state.reader.notes.n, ...patch, updated: PR.nowIso() } });
  return { PR, handlers, put };
}

test("add, recolor, delete, undo and redo all persist through the offline operation queue", async () => {
  const { PR, put } = await reader();
  put({ id: "n", anchor: "p1", quote: "text", kind: "highlight", color: "yellow", body: "Keep this note" });
  put({ color: "blue", style: "underline" });
  PR.commit({ op: "note_del", id: "n" });
  assert.equal(PR.undoAnnotation(), true);
  assert.equal(PR.state.reader.notes.n.color, "blue");
  assert.equal(PR.state.reader.notes.n.body, "Keep this note");
  assert.equal(PR.undoAnnotation(), true);
  assert.equal(PR.state.reader.notes.n.color, "yellow");
  assert.equal(PR.state.reader.notes.n.style, undefined);
  assert.equal(PR.undoAnnotation(), true);
  assert.equal(PR.state.reader.notes.n.deleted, true);
  assert.equal(PR.redoAnnotation(), true);
  assert.equal(PR.state.reader.notes.n.color, "yellow");
  assert.ok(PR.exportOps().ops.length);
  put({ color: "green" });
  assert.equal(PR.redoAnnotation(), false);
});

test("Ctrl+Z and Command+Z handle annotations, while text fields keep native undo", async () => {
  const { PR, handlers, put } = await reader();
  put({ id: "n", anchor: "p1", quote: "text", kind: "highlight", color: "yellow" });
  let prevented = 0;
  const event = { key: "z", code: "KeyZ", ctrlKey: true, target: { closest: () => true }, preventDefault() { prevented++; } };
  handlers.keydown(event);
  assert.equal(prevented, 0);
  assert.equal(PR.state.reader.notes.n.deleted, undefined);
  event.target.closest = () => false;
  handlers.keydown(event);
  assert.equal(prevented, 1);
  assert.equal(PR.state.reader.notes.n.deleted, true);
  handlers.keydown({ ...event, ctrlKey: false, metaKey: true, shiftKey: true });
  assert.equal(PR.state.reader.notes.n.deleted, undefined);
  handlers.keydown({ ...event, ctrlKey: false, metaKey: true });
  assert.equal(PR.state.reader.notes.n.deleted, true);
});

test("undo does not overwrite an annotation modified remotely", async () => {
  const { PR, put } = await reader();
  put({ id: "n", anchor: "p1", quote: "text", kind: "highlight", color: "yellow" });
  PR.state.reader.notes.n.body = "Changed on another device";
  assert.equal(PR.undoAnnotation(), false);
  assert.equal(PR.state.reader.notes.n.body, "Changed on another device");
});

test("server key ordering does not prevent undo of a formula spanning annotation", async () => {
  const { PR, put } = await reader();
  PR.nowIso = () => "2099-10-15T16:00:00.000+08:00";
  put({ id: "n", anchor: "p1", quote: "text formula", kind: "highlight", color: "blue", style: "underline",
    parts: [{ anchor: "p1", key: "p1", quote: "text" }, { anchor: "eq1", key: "eq1", quote: "formula", math: true }] });
  PR.state.reader.notes.n = JSON.parse(JSON.stringify(PR.state.reader.notes.n, (_key, item) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item));
  assert.equal(PR.undoAnnotation(), true);
  assert.equal(PR.state.reader.notes.n.deleted, true);
  assert.equal(PR.redoAnnotation(), true);
  assert.equal(PR.state.reader.notes.n.parts[1].anchor, "eq1");
});
