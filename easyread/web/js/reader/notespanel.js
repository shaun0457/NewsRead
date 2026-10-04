/* 右侧笔记面板：全部批注按原文顺序排好（可筛选、可就地编辑），以及整篇的“论文笔记”。 */
(function (PR) {
  "use strict";
  const S = PR.state;
  let tab = PR.ls.get("easyread-np-tab", "notes");
  let filter = "all";
  let editing = null;
  let preview = false;
  const panel = () => PR.$("#notespanel");

  PR.notesPanelOpen = () => PR.side === "notes";
  PR.toggleNotesPanel = function (force) {
    const open = force != null ? force : PR.side !== "notes";
    PR.openSide(open ? "notes" : null);
    if (open) PR.renderNotesPanel();
    else editing = null;
  };

  function sectionOf(id) {
    let cur = null;
    for (const b of S.paper.blocks || []) {
      if (b.type === "heading" || b.type === "references") cur = b;
      if (b.id === id) break;
    }
    return cur ? (cur.num ? cur.num + " " : "") + PR.plain(PR.textFor(cur.id) || cur.zh) : PR.t("论文开头");
  }
  PR.sectionOf = sectionOf;

  function items() {
    const replied = new Set((S.discussion.entries || []).map((e) => e.reply_to).filter(Boolean));
    const out = [];
    for (const n of PR.myNotes()) out.push({ src: "mine", anchor: n.anchor || "head", t: n.created || "", data: n });
    for (const e of S.discussion.entries || []) out.push({ src: "agent", anchor: PR.anchorOfEntry(e), t: e.at || "", data: e });
    const keep = {
      all: () => true, mine: (i) => i.src === "mine" && i.data.kind !== "highlight", agent: (i) => i.src === "agent",
      hl: (i) => i.src === "mine" && i.data.quote, open: (i) => i.src === "mine" && i.data.kind === "question" && !replied.has(i.data.id),
    }[filter];
    const order = (a) => (a === "head" ? -1 : PR.order[a] ?? 1e9);
    return out.filter(keep).sort((a, b) => order(a.anchor) - order(b.anchor) || (a.t < b.t ? -1 : 1));
  }

  PR.renderNotesPanel = function (editId) {
    if (editId !== undefined) { editing = editId; tab = "notes"; }
    const el = panel();
    if (el.contains(document.activeElement) && document.activeElement.matches("textarea") && editId === undefined) return; // 正在打字，不打断
    const list = items();
    const count = PR.myNotes().length + (S.discussion.entries || []).length;
    let h = '<div class="np-head"><div class="seg"><button data-np="notes" class="' + (tab === "notes" ? "on" : "") + '">' + PR.t("批注 {n}", { n: count }) + '</button><button data-np="paper" class="' + (tab === "paper" ? "on" : "") + '">' + PR.t("论文笔记") + "</button></div>" +
      '<span class="grow"></span><button class="btn sm" data-np-act="md" title="' + PR.t("导出 Markdown") + '">' + PR.t("导出") + '</button><button class="btn icon" data-np-act="close" title="' + PR.t("关闭（M）") + '">×</button></div>';
    if (tab === "paper") {
      const body = (S.reader.paper_note || {}).body || "";
      h += '<div class="np-paper"><div class="np-tools"><span class="hint">' + PR.t("整篇的感悟、总结、待办。自动保存。") + '</span><span class="grow"></span>' + PR.noteHelpButtons() +
        '<button class="btn sm' + (preview ? " on" : "") + '" data-np-act="preview">' + (preview ? PR.t("编辑") : PR.t("预览")) + "</button></div>" +
        (preview ? '<div class="np-preview">' + (body ? PR.mdBlocks(body) : '<p class="hint">' + PR.t("还没有写。") + "</p>") + "</div>"
          : '<textarea id="paperNote" placeholder="' + PR.t("读完这篇，你怎么看？&#10;&#10;可以写：核心论点、我同意/不同意的地方、能用到哪里、还没搞懂的问题……&#10;支持 $公式$、**粗体**，空行分段。") + '">' + PR.esc(body) + "</textarea>") + PR.noteHelpBox() + "</div>";
    } else {
      const chips = [["all", PR.t("全部")], ["mine", PR.t("我的笔记")], ["hl", PR.t("划线")], ["agent", "AI"], ["open", PR.t("待回答")]]
        .map(([k, l]) => '<button data-nf="' + k + '" class="' + (filter === k ? "on" : "") + '">' + l + "</button>").join("");
      h += '<div class="np-filters">' + chips + '</div><div class="np-add"><button class="btn sm line" data-np-act="add">' + PR.icon("plus", "sm") + PR.t("给当前段写笔记") + "</button></div><div class=\"np-list\">";
      let lastSec = null;
      for (const it of list) {
        const sec = it.anchor === "head" ? PR.t("论文开头") : PR.t("第 {page} 页", { page: (PR.blockById[it.anchor] || {}).page }) + " · " + sectionOf(it.anchor);
        if (sec !== lastSec) { h += '<div class="np-sec">' + PR.esc(sec) + "</div>"; lastSec = sec; }
        h += PR.cardHtml(it, editing);
      }
      if (!list.length) h += '<p class="hint np-empty">' + (filter === "all" ? PR.t("还没有批注。选中正文文字可以划线、写笔记、提问；点一下段落也能加笔记。") : PR.t("这个分类下没有内容。")) + "</p>";
      h += "</div>";
    }
    el.innerHTML = h;
    PR.$$("textarea", el).forEach(PR.autosize);
    const ta = editing && el.querySelector('.card[data-note="' + editing + '"] textarea');
    if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); ta.scrollIntoView({ block: "nearest" }); }
  };

  const savePaperNote = PR.debounce(() => { const ta = PR.$("#paperNote"); if (ta) PR.commit({ op: "paper_note", body: ta.value }); }, 600);
  const saveEditing = PR.debounce(() => {
    const ta = editing && panel().querySelector('.card[data-note="' + editing + '"] textarea');
    const n = editing && (S.reader.notes || {})[editing];
    if (ta && n && ta.value.trim() !== (n.body || "")) PR.saveNote(Object.assign({}, n, { body: ta.value.trim(), kind: n.kind === "highlight" && ta.value.trim() ? "note" : n.kind }));
  }, 600);
  function stopEditing() {
    const ta = editing && panel().querySelector('.card[data-note="' + editing + '"] textarea');
    const n = editing && (S.reader.notes || {})[editing];
    saveEditing.cancel();
    if (ta && n) PR.finishNote(n, ta.value);
    editing = null;
    PR.renderNotesPanel();
    PR.applyMarks();
  }

  panel().addEventListener("input", (e) => {
    PR.autosize(e.target);
    if (e.target.id === "paperNote") {
      savePaperNote();
      const btns = PR.$("#notespanel .nh-btns");  // 笔记从空变成有内容（或反过来）：“起草稿”换成“点评 / 帮我改”
      if (btns && (btns.querySelector('[data-nh="draft"]') ? 1 : 0) !== (e.target.value.trim() ? 0 : 1)) btns.outerHTML = PR.noteHelpButtons();
    }
    else if (e.target.matches(".card textarea")) saveEditing();
  });
  panel().addEventListener("keydown", (e) => {
    if (e.target.matches(".card textarea") && (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey)))) { e.preventDefault(); stopEditing(); }
  });
  panel().addEventListener("focusout", (e) => {
    if (e.target.id === "paperNote") savePaperNote.flush();
    if (!e.target.matches(".card textarea")) return;
    setTimeout(() => { const card = e.target.closest(".card"); if (card && card.isConnected && !card.contains(document.activeElement) && editing === card.dataset.note) stopEditing(); }, 150);
  });
  panel().addEventListener("click", (e) => {
    const np = e.target.closest("[data-np]");
    if (np) { tab = np.dataset.np; PR.ls.set("easyread-np-tab", tab); return PR.renderNotesPanel(); }
    const nf = e.target.closest("[data-nf]");
    if (nf) { filter = nf.dataset.nf; return PR.renderNotesPanel(); }
    const act = e.target.closest("[data-np-act]");
    if (act) {
      const a = act.dataset.npAct;
      if (a === "close") PR.toggleNotesPanel(false);
      if (a === "md") PR.openExport();
      if (a === "preview") { savePaperNote.flush(); preview = !preview; PR.renderNotesPanel(); }
      if (a === "add") { const id = (PR.currentBlock && PR.currentBlock()) || PR.readingBlock(); if (PR.blockById[id]) PR.startNote({ anchor: id }); }
      return;
    }
    const card = e.target.closest(".card");
    if (!card) return;
    if (card.dataset.note && (e.target.closest(".body") || e.target.closest('[data-a="edit"]')) && !e.target.closest("a")) {
      editing = card.dataset.note; PR.renderNotesPanel(editing); return;
    }
    if (PR.cardClick(e, true)) return;
    if (card.dataset.anchor) { PR.jumpTo("b-" + card.dataset.anchor); if (card.dataset.note) setTimeout(() => PR.$$('mark[data-note="' + card.dataset.note + '"]').forEach((m) => m.classList.add("active")), 400); }
  });

  /* 导出的 Markdown：论文笔记 + 按原文顺序的批注 */
  /* pick：{paper, note, highlight, question, ai, chat, quote}，不传就全要 */
  PR.notesMarkdown = function (pick, chat) {
    pick = pick || { paper: true, note: true, highlight: true, question: true, ai: true, quote: true };
    const m = S.paper.meta || {};
    const link = m.url || (m.arxiv ? "https://arxiv.org/abs/" + String(m.arxiv).replace(/^arXiv:/i, "").split(/[\sv]/)[0] : "");
    const out = ["# " + (m.title_zh || m.title_en || ""), "", m.title_en ? "*" + m.title_en + "*  " : "", [m.authors, m.date, link].filter(Boolean).join(" · "), ""];
    const pn = (S.reader.paper_note || {}).body;
    if (pick.paper && pn) out.push("## " + PR.t("论文笔记"), "", pn, "");
    const want = (it) => it.src === "mine" ? !!pick[it.data.kind === "question" ? "question" : it.data.kind === "highlight" ? "highlight" : "note"] : !!pick.ai;
    const list = (() => { const f = filter; filter = "all"; const r = items().filter(want); filter = f; return r; })();
    if (list.length) out.push("## " + PR.t("批注"), "");
    let lastSec = "";
    for (const it of list) {
      const sec = it.anchor === "head" ? PR.t("论文开头") : sectionOf(it.anchor);
      if (sec !== lastSec) { out.push("### " + sec, ""); lastSec = sec; }
      const d = it.data;
      const q = pick.quote && d.quote ? PR.t("「{q}」", { q: d.quote }) + (it.src === "mine" && d.side === "en" ? PR.t("（原文）") : "") : "";
      if (it.src === "mine") out.push("- **" + ({ question: PR.t("我的问题"), highlight: PR.t("划线") }[d.kind] || PR.t("我的笔记")) + "**" + q + (d.body ? PR.t("：") + d.body : ""));
      else out.push("- **AI" + (d.kind === "reply" ? " " + PR.t("回答") : "") + (d.title ? PR.t("：") + d.title : "") + "**" + q + (d.q ? PR.t("（问：{q}）", { q: d.q }) : "") + "\n\n  " + (d.body || "").replace(/\n/g, "\n  "));
    }
    if (pick.chat && chat && chat.length) {
      out.push("", "## " + PR.t("问 AI 的对话"), "");
      for (const c of chat) out.push(c.role === "user" ? PR.t("**我**：") + c.content : PR.t("**AI**（{model}）：", { model: c.model || "" }) + c.content, "");
    }
    return out.join("\n");
  };
})(window.PR);
