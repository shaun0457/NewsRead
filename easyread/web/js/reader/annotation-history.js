/* Session-local undo for annotations, replayed through the normal durable operation queue. */
(function (PR) {
  "use strict";
  const undo = [], redo = [];
  const commit = PR.commit;
  let replaying = false;
  const copy = n => n ? JSON.parse(JSON.stringify(n)) : null;
  const current = id => copy((PR.state.reader.notes || {})[id]);
  const content = n => {
    if (!n || n.deleted) return "deleted";
    const value = { ...n }; delete value.updated;
    // Server JSON may reorder keys, including keys inside cross-block parts.
    return JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
  };

  PR.commit = function (op) {
    const id = op.op === "note" ? op.note.id : op.op === "note_del" ? op.id : null;
    const before = id && current(id);
    commit(op);
    if (!id || replaying) return;
    const after = current(id);
    if (!(before?.quote || after?.quote) || content(before) === content(after)) return;
    undo.push({ id, before, after });
    if (undo.length > 100) undo.shift();
    redo.length = 0;
  };

  function replay(from, to, reverse, id) {
    const entry = from[from.length - 1];
    if (!entry || (id && id !== entry.id)) return false;
    const expected = reverse ? entry.after : entry.before;
    const now = current(entry.id);
    // Another device or agent has edited this annotation since the local action.
    if (content(now) !== content(expected)) {
      undo.length = redo.length = 0;
      PR.toast(PR.t("标记已在其他地方修改，无法撤销"));
      return false;
    }
    const value = copy(reverse ? entry.before : entry.after);
    // The store compares timestamps as strings; keep the writer's local-offset format.
    const at = [PR.nowIso(), now?.updated || ""].sort().pop();
    replaying = true;
    try {
      if (!value || value.deleted) PR.commit({ op: "note_del", id: entry.id, at });
      else PR.commit({ op: "note", note: { ...value, updated: at }, at });
    } finally { replaying = false; }
    from.pop(); to.push(entry);
    PR.hidePopover?.();
    PR.applyMarks?.();
    PR.renderMargin?.();
    if (PR.notesPanelOpen?.()) PR.renderNotesPanel();
    return true;
  }
  PR.undoAnnotation = id => replay(undo, redo, true, id);
  PR.redoAnnotation = () => replay(redo, undo, false);
  document.addEventListener("keydown", e => {
    if (e.defaultPrevented || e.isComposing || e.altKey || !(e.ctrlKey || e.metaKey) ||
        e.target.closest?.("input, textarea, [contenteditable], [role=textbox]") ||
        document.body.classList.contains("mobile-read")) return;
    const key = String(e.key).toLowerCase();
    const isZ = key === "z" || e.code === "KeyZ";
    const isRedo = (isZ && e.shiftKey) || (e.ctrlKey && !e.metaKey && key === "y");
    if (!isZ && !isRedo) return;
    if ((isRedo ? PR.redoAnnotation() : PR.undoAnnotation())) e.preventDefault();
  });
})(window.PR);
