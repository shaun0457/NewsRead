/* 題材頁的因果鏈清單（ticket 59）：顯示每一環和出處、新增 / 修改 / 確認 / 移除、營收占比、領漲 / 補漲。
   畫面照核准的 Mockup A（docs/mockups/v1-a/theme.html 的「因果鏈」區塊）。資料和規則在後端（easyread/chain.py）。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  const MAX_CHOICES = 200;  // 下拉選單最多列幾則（追蹤對象、資料）
  const MAX_LINKS = 100;    // 跟後端一樣；滿了就不給新增
  const ROLES = ["leader", "laggard", "unknown"];

  const T = () => ({
    heading: PR.t("因果鏈"),
    legend: PR.t("實線 = 有出處 · 虛線 = AI 推論（不會進定稿，除非你確認）"),
    inferred: PR.t("AI 推論"), confirmedChip: PR.t("你確認過"),
    noSource: PR.t("沒有出處"), item: (id) => PR.t("資料 {id}", { id }),
    unknown: PR.t("不知道"), share: PR.t("營收占比"),
    leader: PR.t("領漲"), laggard: PR.t("補漲"), roleUnknown: PR.t("未知"),
    suggest: (role) => PR.t("建議：{role}", { role }),
    noMarket: PR.t("領漲 / 補漲：unknown（行情還沒接上）"),
    useSuggestion: PR.t("採用建議"),
    edit: PR.t("修改"), remove: PR.t("移除"), confirm: PR.t("我確認這一環"), add: PR.t("＋ 新增一環"),
    save: PR.t("儲存"), cancel: PR.t("取消"), publish: PR.t("確認成定稿"),
    from: PR.t("從"), to: PR.t("到"), relation: PR.t("關係說明"), kindLabel: PR.t("環節名稱"), kindEntity: PR.t("追蹤對象"),
    pickEntity: PR.t("選一個追蹤對象…"), source: PR.t("出處網址"), sourceItem: PR.t("或選資料庫裡的一則資料"), noneItem: PR.t("不選"),
    shareMode: PR.t("營收占比"), shareUnknown: PR.t("不知道"), shareValue: PR.t("一個數值（%）"), shareRange: PR.t("一個區間（%）"),
    shareSource: PR.t("營收占比的出處網址（沒有出處就是不知道）"), low: PR.t("下限"), high: PR.t("上限"), value: PR.t("數值"),
    role: PR.t("領漲 / 補漲"), shareHint: PR.t("營收占比只引用來源，AI 不會估。"),
    roleHint: PR.t("「領漲 / 補漲」依題材起點以來的相對報酬建議，你確認過才算。"),
    empty: PR.t("還沒有因果鏈。從「需求來源」開始加第一環。"),
    stateDraft: (v) => PR.t("草稿 v{v}", { v }), stateFinal: (v) => PR.t("定稿 v{v}", { v }),
    unconfirmed: (n) => PR.t("還有 {n} 個 AI 推論的環節沒確認，確認前不能進定稿。", { n }),
    loadFailed: PR.t("讀不到這個題材"), loadFailedBody: PR.t("本機資料庫暫時讀不到。資料沒有遺失。"), retry: PR.t("重試"),
    saved: PR.t("已存成草稿。"), published: PR.t("已確認成定稿。"), removed: PR.t("已移除這一環。"),
    saveFailed: PR.t("存不了，請稍後再試。"), stale: PR.t("這一頁已經有新的版本，已重新載入。"),
    full: (n) => PR.t("最多 {n} 環。", { n }),
    conflict: (v) => PR.t("另一個分頁已經存了新版本（v{v}）。你這邊打的內容還在，還沒送出。", { v }),
    conflictAdd: (v) => PR.t("另一個分頁已經存了新版本（v{v}），上面已經是新版的因果鏈。你這邊打的內容還在，還沒送出。", { v }),
    conflictMoved: (v) => PR.t("另一個分頁已經存了新版本（v{v}），這一環在新版裡被移除，或改了從、到。你這邊打的內容還在，重送會加成新的一環。", { v }),
    conflictUnread: PR.t("另一個分頁已經存了新版本，但現在讀不到新版。你這邊打的內容還在，稍後再按「用我的內容重送」。"),
    seeNew: PR.t("看新版"), resend: PR.t("用我的內容重送"), discard: PR.t("放棄我的，改用新版"),
    theirs: PR.t("新版"), theirsChip: (v) => PR.t("v{v} · 另一個分頁", { v }), mine: PR.t("我的內容"), mineChip: PR.t("還沒送出"),
    sourceCol: PR.t("出處"),
  });
  const esc = (s) => PR.esc(s);

  /* ---------- 純函式（測試直接呼叫） ---------- */
  function sourceView(source) {
    if (source && typeof source.url === "string" && /^https?:\/\//i.test(source.url)) return { kind: "url", url: source.url };
    if (source && typeof source.item_id === "string") return { kind: "item", id: source.item_id };
    return { kind: "none" };
  }

  /* 營收占比：不知道 / 數值 / 區間（都附出處）。沒有出處的一律不知道（後端也是這樣）。 */
  function shareView(share) {
    if (!share || share === "unknown" || typeof share !== "object") return { kind: "unknown" };
    if (Array.isArray(share.range)) return { kind: "range", text: share.range[0] + "–" + share.range[1] + "%", source: sourceView(share.source) };
    if (typeof share.value === "number") return { kind: "value", text: share.value + "%", source: sourceView(share.source) };
    return { kind: "unknown" };
  }

  function nodeText(node) {
    if (!node) return "";
    return node.name || node.label || (node.entity_id ? "?" : "");
  }

  function pending(link) { return !!link.inferred && !link.confirmed; }

  function blankDraft() {
    return { from: { kind: "label", text: "", entity: "" }, to: { kind: "label", text: "", entity: "" }, relation: "", url: "", item: "",
             shareMode: "unknown", shareValue: "", shareLow: "", shareHigh: "", shareUrl: "", shareItem: "", role: "unknown" };
  }

  function nodeDraft(node) {
    return node && node.entity_id ? { kind: "entity", text: "", entity: node.entity_id } : { kind: "label", text: (node && node.label) || "", entity: "" };
  }

  function toDraft(link) {
    const d = blankDraft();
    d.from = nodeDraft(link.from); d.to = nodeDraft(link.to); d.relation = link.relation || "";
    const src = link.source || {};
    d.url = src.url || ""; d.item = src.item_id || "";
    const share = link.revenue_share;
    if (share && typeof share === "object") {
      const s = share.source || {};
      d.shareUrl = s.url || ""; d.shareItem = s.item_id || "";
      if (Array.isArray(share.range)) { d.shareMode = "range"; d.shareLow = String(share.range[0]); d.shareHigh = String(share.range[1]); }
      else if (typeof share.value === "number") { d.shareMode = "value"; d.shareValue = String(share.value); }
    }
    d.role = ROLES.includes(link.role) ? link.role : "unknown";
    return d;
  }

  function nodePayload(n) {
    return n.kind === "entity" ? { entity_id: n.entity } : { label: String(n.text || "").trim() };
  }

  function sourcePayload(url, item) {
    url = String(url || "").trim();
    if (url) return { url };
    return item ? { item_id: item } : null;
  }

  /* 要送出的環節。公司環節才帶營收占比和 role（isCompany 由畫面查追蹤對象的類型）。數字欄位不是數字就送 null，讓後端回欄位錯誤。 */
  function payload(d, isCompany) {
    const link = { from: nodePayload(d.from), to: nodePayload(d.to), relation: String(d.relation || "").trim(),
                   source: sourcePayload(d.url, d.item) };
    if (isCompany) {
      const num = (x) => (String(x).trim() !== "" && Number.isFinite(Number(x)) ? Number(x) : null);
      const src = sourcePayload(d.shareUrl, d.shareItem);
      if (d.shareMode === "value") link.revenue_share = { value: num(d.shareValue), source: src };
      else if (d.shareMode === "range") link.revenue_share = { range: [num(d.shareLow), num(d.shareHigh)], source: src };
      else link.revenue_share = "unknown";
      link.role = ROLES.includes(d.role) ? d.role : "unknown";
    }
    return link;
  }

  /* 伺服器回的欄位名稱（chain.3.revenue_share.value、link、index…）→ 表單上要標紅的位置。
     後端每次驗證整條鏈：錯在別的環節（chain.N 的 N 不是正在改的這一環）時，顯示成整張表單的錯誤。 */
  function fieldKey(field, index) {
    const f = String(field || "");
    const at = /^chain\.(\d+)(\.|$)/.exec(f);
    if (at && index !== undefined && index !== null && Number(at[1]) !== index) return "form";
    if (/(^|\.)from(\.|$)/.test(f)) return "from";
    if (/(^|\.)to(\.|$)/.test(f)) return "to";
    if (/relation$/.test(f)) return "relation";
    if (/revenue_share/.test(f)) return "share";
    if (/(^|\.)source/.test(f)) return "source";
    if (/role$/.test(f)) return "role";
    return "form";
  }

  /* 後端回來的資料有可能很多：下拉選單只列前 MAX_CHOICES 個（已選的一定要在） */
  function capChoices(list, selected) {
    const head = list.slice(0, MAX_CHOICES);
    if (selected && !head.some((x) => x.id === selected)) {
      const hit = list.find((x) => x.id === selected);
      if (hit) head.push(hit);
    }
    return head;
  }

  /* 追蹤對象名單沒載入（或還沒回來）時，改用因果鏈回應裡帶的類型，免得把公司環節的占比和 role 清掉 */
  function entityIsCompany(entities, id, links) {
    const e = (entities || []).find((x) => x.id === id);
    if (e) return e.type === "company";
    return (links || []).some((l) => ["from", "to"].some((s) => l[s] && l[s].entity_id === id && l[s].type === "company"));
  }

  /* 版本衝突（ticket 108）：另一個分頁先存了新版本時，正在改的那一環在新版裡是哪一環。
     同一個位置、從和到都一樣就是它；不然找從和到都一樣的唯一一環；找不到（被移除、改了從或到、有好幾個一樣的）回 null。 */
  function nodeKey(n) {
    if (!n) return "";
    return n.entity_id ? "e:" + n.entity_id : "l:" + String(n.label || "");
  }

  function matchLink(before, index, links) {
    if (!before) return null;
    const same = (l) => l && nodeKey(l.from) === nodeKey(before.from) && nodeKey(l.to) === nodeKey(before.to);
    if (index !== null && index !== undefined && same(links[index])) return index;
    const hits = links.map((l, i) => (same(l) ? i : -1)).filter((i) => i >= 0);
    return hits.length === 1 ? hits[0] : null;
  }

  /* 比較用：一環的各欄位顯示成文字（新版的環節，或我的草稿轉成的環節） */
  function cmpRows(link, tx, withCompany) {
    const src = (s) => { const v = sourceView(s); return v.kind === "url" ? v.url : v.kind === "item" ? tx.item(v.id) : tx.noSource; };
    const rows = [[tx.from + " → " + tx.to, nodeText(link.from) + " → " + nodeText(link.to)], [tx.relation, link.relation || ""],
                  [tx.sourceCol, src(link.source)]];
    if (withCompany) {
      const share = shareView(link.revenue_share);
      const role = ROLES.includes(link.role) ? link.role : "unknown";
      rows.push([tx.share, share.kind === "unknown" ? tx.unknown : share.text + " · " + src(link.revenue_share.source)],
                [tx.role, role === "leader" ? tx.leader : role === "laggard" ? tx.laggard : tx.roleUnknown]);
    }
    return rows;
  }

  /* 我的草稿 → 跟新版同形狀的環節（追蹤對象補上名稱，比較時才看得懂） */
  function draftLink(d, S) {
    const company = d.to.kind === "entity" && entityIsCompany(S.entities, d.to.entity, S.view && S.view.links);
    const link = payload(d, company);
    for (const side of ["from", "to"]) {
      const id = link[side].entity_id;
      if (id) {
        const e = (S.entities || []).find((x) => x.id === id);
        link[side] = Object.assign({}, link[side], { name: e ? e.name : id });
      }
    }
    return link;
  }

  /* 收起的比較區：支援 hidden="until-found" 的瀏覽器用它（頁內搜尋找得到）；不支援的退回一般的 hidden，
     不然那些瀏覽器會把它當成沒隱藏（作者樣式的 display: grid 蓋過預設的 display: none） */
  function collapsedAttr() {
    const body = typeof document !== "undefined" && document.body;
    return body && "onbeforematch" in body ? ' hidden="until-found"' : " hidden";
  }

  function compareHtml(S, tx) {
    const c = S.conflict, ed = S.editing;
    if (!c || !c.theirs || !ed) return "";
    const mine = draftLink(ed.draft, S);
    const withCompany = "revenue_share" in c.theirs || "revenue_share" in mine;
    const a = cmpRows(c.theirs, tx, withCompany), b = cmpRows(mine, tx, withCompany);
    const dl = (rows, other) => `<dl>${rows.map(([k, v], i) => `<dt>${esc(k)}</dt><dd${v !== other[i][1] ? ' class="chg"' : ""} data-no-i18n>${esc(v)}</dd>`).join("")}</dl>`;
    return `<div class="cmp" id="chain-cmp"${c.open ? "" : collapsedAttr()}>`
      + `<div><h3>${esc(tx.theirs)} <span class="chip">${esc(tx.theirsChip(c.version))}</span></h3>${dl(a, b)}</div>`
      + `<div><h3>${esc(tx.mine)} <span class="chip mine">${esc(tx.mineChip)}</span></h3>${dl(b, a)}</div></div>`;
  }

  function conflictHtml(S, tx) {
    const c = S.conflict;
    if (!c || !S.editing) return "";
    const text = c.unread ? tx.conflictUnread : c.moved ? tx.conflictMoved(c.version) : c.theirs ? tx.conflict(c.version) : tx.conflictAdd(c.version);
    const see = c.theirs ? `<button class="btn sm" type="button" data-act="compare" aria-expanded="${c.open ? "true" : "false"}" aria-controls="chain-cmp">${esc(tx.seeNew)}</button>` : "";
    return `<div class="banner warn" role="alert"><span class="ico">!</span><div>${esc(text)}<div class="acts">${see}`
      + `<button class="btn sm primary" type="button" data-act="resend"${S.busy ? " disabled" : ""}>${esc(tx.resend)}</button>`
      + `<button class="btn sm ghost" type="button" data-act="discard"${S.busy ? " disabled" : ""}>${esc(tx.discard)}</button></div></div></div>`;
  }

  /* ---------- 畫面 ---------- */
  function sourceHtml(src, tx) {
    const s = sourceView(src);
    if (s.kind === "url") return `<a class="cite" href="${esc(s.url)}" title="${esc(s.url)}" target="_blank" rel="noopener noreferrer" data-no-i18n>${esc(s.url)}</a>`;
    if (s.kind === "item") return `<span class="cite" data-no-i18n>${esc(tx.item(s.id))}</span>`;
    return `<span class="cite none">${esc(tx.noSource)}</span>`;
  }

  function companyHtml(link, view, tx, locked) {
    const share = shareView(link.revenue_share);
    const shareHtml = share.kind === "unknown"
      ? `<span class="muted">${esc(tx.share)}${PR.lang === "en" ? ": " : "："}<b>${esc(tx.unknown)}</b></span>`  // i18n-ok：標點
      : `<span>${esc(tx.share)} <b>${esc(share.text)}</b> ${sourceHtml(link.revenue_share.source, tx)}</span>`;
    const role = ROLES.includes(link.role) ? link.role : "unknown";
    const roleLabel = role === "leader" ? tx.leader : role === "laggard" ? tx.laggard : tx.roleUnknown;
    let suggestion = "";
    if (role === "unknown") {
      const sg = link.role_suggestion;
      if (!view.market_data) suggestion = `<span class="muted" style="font-size:12.5px">${esc(tx.noMarket)}</span>`;
      else if (sg === "leader" || sg === "laggard") {
        suggestion = `<span class="muted" style="font-size:12.5px">${esc(tx.suggest(sg === "leader" ? tx.leader : tx.laggard))}</span> `
          + `<button class="btn sm" type="button" data-act="role" data-i="${link.index}" data-role="${sg}"${locked ? " disabled" : ""}>${esc(tx.useSuggestion)}</button>`;
      }
    }
    return `<div class="co"><span data-no-i18n>${esc(nodeText(link.to))}</span>${shareHtml}`
      + `<span><span class="chip${role === "unknown" ? "" : " mine"}">${esc(roleLabel)}</span></span>`
      + (suggestion ? `<span style="grid-column:1/-1">${suggestion}</span>` : "") + `</div>`;
  }

  /* locked：有表單開著或請求還沒回來。這時其他環節的動作都停用：移除前面的環節會讓表單的 index 對到別的環節 */
  function linkHtml(link, view, tx, locked) {
    const infer = pending(link);
    const chips = infer ? `<span class="chip warn">${esc(tx.inferred)}</span>`
      : link.inferred && link.confirmed ? `<span class="chip mine">${esc(tx.confirmedChip)}</span>` : "";
    const company = "revenue_share" in link;
    const name = `${nodeText(link.from)} → ${nodeText(link.to)}`;
    const btn = (act, cls, label) => `<button class="btn sm${cls}" type="button" data-act="${act}" data-i="${link.index}"`
      + ` aria-label="${esc(label + "：" + name)}"${locked ? " disabled" : ""}>${esc(label)}</button>`;  // i18n-ok：標點
    const acts = `<div class="acts">${btn("edit", "", tx.edit)}`
      + (infer ? btn("confirm", " primary", tx.confirm) : "")
      + `${btn("remove", " ghost danger", tx.remove)}</div>`;
    return `<li class="${infer ? "infer" : ""}"><span class="k">${esc(tx.from)} → ${esc(tx.to)}</span>`
      + `<span data-no-i18n>${esc(nodeText(link.from))} → ${esc(nodeText(link.to))}</span> ${chips}`
      + `<div class="rel" data-no-i18n>${esc(link.relation)}</div><div>${sourceHtml(link.source, tx)}</div>`
      + (company ? companyHtml(link, view, tx, locked) : "") + acts + `</li>`;
  }

  function nodeFieldHtml(name, n, entities, tx, err) {
    const list = capChoices(entities, n.entity);
    const opts = [`<option value="">${esc(tx.pickEntity)}</option>`].concat(list.map((e) =>
      `<option value="${esc(e.id)}"${e.id === n.entity ? " selected" : ""} data-no-i18n>${esc(e.name)}</option>`)).join("");
    return `<fieldset><legend>${esc(name === "from" ? tx.from : tx.to)}</legend>`
      + `<div class="two"><select class="input" data-k="${name}.kind" aria-label="${esc(name === "from" ? tx.from : tx.to)}">`
      + `<option value="label"${n.kind === "label" ? " selected" : ""}>${esc(tx.kindLabel)}</option>`
      + `<option value="entity"${n.kind === "entity" ? " selected" : ""}>${esc(tx.kindEntity)}</option></select>`
      + (n.kind === "entity"
        ? `<select class="input${err ? " invalid" : ""}" data-k="${name}.entity" aria-label="${esc(tx.kindEntity)}"${err ? ' aria-invalid="true"' : ""}>${opts}</select>`
        : `<input class="input${err ? " invalid" : ""}" data-k="${name}.text" value="${esc(n.text)}" maxlength="60"${err ? ' aria-invalid="true"' : ""} aria-label="${esc(tx.kindLabel)}">`)
      + `</div>${err ? `<span class="err" role="alert">${esc(err)}</span>` : ""}</fieldset>`;
  }

  function formHtml(ed, S, tx) {
    const d = ed.draft, e = ed.errors || {};
    const company = d.to.kind === "entity" && entityIsCompany(S.entities, d.to.entity, S.view && S.view.links);
    const itemOptions = (selected) => `<option value="">${esc(tx.noneItem)}</option>` + capChoices(S.items, selected).map((it) =>
      `<option value="${esc(it.id)}"${it.id === selected ? " selected" : ""} data-no-i18n>${esc(it.title || it.id)}</option>`).join("");
    const itemOpts = itemOptions(d.item);
    // 錯誤放在 label 外面：放在裡面會被讀屏併進欄位名稱
    const errHtml = (key) => (e[key] ? `<span class="err" role="alert">${esc(e[key])}</span>` : "");
    const field = (key, label, input) => `<label>${esc(label)}${input}</label>${errHtml(key)}`;
    let share = "";
    if (company) {
      const num = (k, v, lab) => field(k, lab, `<input class="input num" inputmode="decimal" data-k="${k}" value="${esc(v)}" aria-label="${esc(lab)}">`);
      share = `<fieldset><legend>${esc(tx.shareMode)}</legend><div class="two">`
        + `<select class="input" data-k="shareMode" aria-label="${esc(tx.shareMode)}">`
        + ["unknown", "value", "range"].map((m) => `<option value="${m}"${d.shareMode === m ? " selected" : ""}>${esc(m === "unknown" ? tx.shareUnknown : m === "value" ? tx.shareValue : tx.shareRange)}</option>`).join("")
        + `</select></div>`
        + (d.shareMode === "value" ? `<div class="two">${num("shareValue", d.shareValue, tx.value)}</div>` : "")
        + (d.shareMode === "range" ? `<div class="two">${num("shareLow", d.shareLow, tx.low)}${num("shareHigh", d.shareHigh, tx.high)}</div>` : "")
        + (d.shareMode !== "unknown"
          ? field("share", tx.shareSource, `<input class="input" data-k="shareUrl" value="${esc(d.shareUrl)}" inputmode="url">`)
            + `<label>${esc(tx.sourceItem)}<select class="input" data-k="shareItem">${itemOptions(d.shareItem)}</select></label>`
          : "")
        + `<span class="hint">${esc(tx.shareHint)}</span></fieldset>`
        + `<fieldset><legend>${esc(tx.role)}</legend><div class="two"><select class="input" data-k="role" aria-label="${esc(tx.role)}">`
        + ROLES.map((r) => `<option value="${r}"${d.role === r ? " selected" : ""}>${esc(r === "leader" ? tx.leader : r === "laggard" ? tx.laggard : tx.roleUnknown)}</option>`).join("")
        + `</select></div>${errHtml("role")}<span class="hint">${esc(tx.roleHint)}</span></fieldset>`;
    }
    return `<form class="chain-form" data-form novalidate>`
      + nodeFieldHtml("from", d.from, S.entities, tx, e.from) + nodeFieldHtml("to", d.to, S.entities, tx, e.to)
      + field("relation", tx.relation, `<input class="input${e.relation ? " invalid" : ""}" data-k="relation" value="${esc(d.relation)}" maxlength="300">`)
      + field("source", tx.source, `<input class="input" data-k="url" value="${esc(d.url)}" inputmode="url">`)
      + `<label>${esc(tx.sourceItem)}<select class="input" data-k="item">${itemOpts}</select></label>`
      + share
      + (e.form ? `<div class="err" role="alert">${esc(e.form)}</div>` : "")
      + `<div class="row"><button class="btn primary sm" type="submit"${S.busy ? " disabled" : ""}>${esc(S.conflict ? tx.resend : tx.save)}</button>`
      + `<button class="btn sm ghost" type="button" data-act="cancel"${S.busy ? " disabled" : ""}>${esc(tx.cancel)}</button></div></form>`;
  }

  function viewHtml(S) {
    const tx = T();
    if (S.status === "loading") return `<div class="card sec" aria-busy="true"><div class="skel" style="width:60%"></div><div class="skel"></div></div>`;
    if (S.status === "error") {
      return `<div class="card sec"><div class="empty"><h2>${esc(tx.loadFailed)}</h2><p>${esc(tx.loadFailedBody)}</p>`
        + `<button class="btn" type="button" data-act="retry">${esc(tx.retry)}</button></div></div>`;
    }
    const v = S.view, ed = S.editing;
    const locked = !!ed || S.busy;
    const form = () => `<li class="edit">${compareHtml(S, tx)}${formHtml(ed, S, tx)}</li>`;
    const links = v.links.map((l) => (ed && ed.index === l.index ? form() : linkHtml(l, v, tx, locked))).join("");
    const adding = ed && ed.index === null ? form() : "";
    const full = v.links.length >= MAX_LINKS;
    const banner = v.status === "draft" && v.unconfirmed > 0 ? `<div class="banner warn"><span class="ico">!</span><div>${esc(tx.unconfirmed(v.unconfirmed))}</div></div>` : "";
    const note = S.note ? `<div class="banner bad" role="alert"><span class="ico">!</span><div>${esc(S.note)}</div></div>` : "";
    return `<section class="card sec" id="chain"><h2>${esc(tx.heading)} <span class="muted" style="font-size:12.5px;font-weight:400">${esc(tx.legend)}</span></h2>`
      + note + conflictHtml(S, tx) + banner
      + (v.links.length || adding ? `<ol class="chain">${links}${adding}</ol>` : `<p class="muted">${esc(tx.empty)}</p>`)
      + `<div class="row" style="margin-top:10px"><button class="btn sm" type="button" data-act="add"${full || ed ? " disabled" : ""}>${esc(tx.add)}</button>`
      + (full ? `<span class="muted">${esc(tx.full(MAX_LINKS))}</span>` : "")
      + (v.status === "draft" ? `<span class="grow"></span><button class="btn sm primary" type="button" data-act="publish"${S.busy || ed ? " disabled" : ""}>${esc(tx.publish)}</button>` : "")
      + `</div></section>`;
  }

  /* ---------- 狀態與動作 ---------- */
  // conflict：送出被擋（另一個分頁先存了新版本）時保留表單（ticket 108）。{version, theirs, moved, unread, open}
  const S = { id: null, title: "", view: null, entities: [], items: [], editing: null, status: "loading", busy: false, note: "", conflict: null };
  let seq = 0;

  function render(focus) {
    const root = PR.$("#view");
    if (!root) return;
    root.innerHTML = viewHtml(S);
    const state = PR.$("#state"), tx = T();
    if (state && S.view) state.innerHTML = S.view.status ? `<span class="chip mine">${esc(S.view.status === "draft" ? tx.stateDraft(S.view.version) : tx.stateFinal(S.view.version))}</span>` : "";
    const title = PR.$("#title");
    if (title) title.textContent = S.title;
    if (focus) { const el = PR.$(focus, root); if (el) el.focus(); }
  }

  function errorInfo(e, fallback) {
    const data = (e && e.data) || {};
    const ok = e && e.status && e.status < 500 && typeof data.error === "string";
    return { message: ok ? data.error : fallback, field: ok ? data.field : null, status: e && e.status };
  }

  async function load(quiet) {
    const my = ++seq;
    if (!quiet) { S.status = "loading"; render(); }
    try {
      const view = await PR.api("/api/themes/" + encodeURIComponent(S.id) + "/chain");
      if (my !== seq) return;
      S.view = view; S.status = "ready";
    } catch (e) {
      if (my !== seq) return;
      S.status = "error";
    }
    render();
  }

  async function loadLists() {
    try {
      const [ents, lib] = await Promise.all([PR.api("/api/entities"), PR.api("/api/library")]);
      if (lib && lib.token) PR.token = lib.token;
      const all = ents && Array.isArray(ents.entities) ? ents.entities : [];
      const me = all.find((x) => x.id === S.id);
      S.title = me ? me.name : "";
      S.entities = all.filter((x) => x.id !== S.id);
      S.items = lib && Array.isArray(lib.items) ? lib.items.map((i) => ({ id: i.id, title: PR.titles ? PR.titles(i).main || i.title : i.title })) : [];
    } catch (e) { /* 名單讀不到也能看因果鏈；新增時下拉選單是空的 */ }
  }

  const chainUrl = () => "/api/themes/" + encodeURIComponent(S.id) + "/chain";

  /* 新增或修改一環時被擋：讀新版、表單和打的內容留著；要改的那一環在新版裡找不到時改成新增。讀不到新版就留在舊版，下次重送再試 */
  async function keepForm() {
    const ed = S.editing, before = ed.index === null ? null : S.view.links[ed.index];
    seq++;  // 之前還沒回來的 load 不要蓋掉這次讀到的
    let fresh;
    try { fresh = await PR.api(chainUrl()); } catch (e) { fresh = null; }
    if (S.editing !== ed) return;
    if (!fresh || !Array.isArray(fresh.links)) { S.conflict = { unread: true, theirs: null, open: false }; return; }
    const at = matchLink(before, ed.index, fresh.links);
    S.view = fresh; S.status = "ready";
    S.conflict = { version: fresh.version, theirs: at === null ? null : fresh.links[at], moved: !!before && at === null, unread: false,
                   open: !!(S.conflict && S.conflict.open) };
    ed.index = before ? at : null;
    ed.errors = {};
  }

  async function post(body) {
    if (S.busy) return null;
    S.busy = true; S.note = "";
    render();  // 馬上停用按鈕：回應回來前開了別的表單，index 可能對到移除後的另一環
    try {
      const view = await PR.api(chainUrl(), { method: "POST", body: Object.assign({ base_version: S.view.version }, body) });
      S.view = view;
      return view;
    } catch (e) {
      const info = errorInfo(e, T().saveFailed);
      if (info.field === "base_version" && S.editing && (body.op === "add" || body.op === "update")) await keepForm();
      else if (info.field === "base_version") { S.note = T().stale; S.editing = null; S.conflict = null; await load(true); }
      else if (S.editing) {
        const at = S.editing.index === null ? S.view.links.length : S.editing.index;
        S.editing.errors = { [fieldKey(info.field, at)]: info.message };
      }
      else S.note = info.message;
      return null;
    } finally {
      S.busy = false;
    }
  }

  async function submit() {
    const ed = S.editing;
    if (!ed) return;
    const company = ed.draft.to.kind === "entity" && entityIsCompany(S.entities, ed.draft.to.entity, S.view && S.view.links);
    const link = payload(ed.draft, company);
    const view = await post(ed.index === null ? { op: "add", link } : { op: "update", index: ed.index, link });
    if (view) { S.editing = null; S.conflict = null; PR.toast(esc(T().saved)); render("[data-act=add]"); }
    else render(S.conflict ? "[data-act=resend]" : ".chain-form .invalid, .chain-form .err");
  }

  async function act(name, i, extra) {
    if (S.busy && name !== "retry") return;  // 請求進行中：不開表單、不取消，等回應回來
    if (name === "edit") { S.editing = { index: i, draft: toDraft(S.view.links[i]), errors: {} }; return void render(".chain-form input"); }
    if (name === "add") { S.editing = { index: null, draft: blankDraft(), errors: {} }; return void render(".chain-form input"); }
    if (name === "cancel") { S.editing = null; S.conflict = null; return void render(); }
    if (name === "compare" && S.conflict) { S.conflict.open = !S.conflict.open; return void render("[data-act=compare]"); }
    if (name === "resend") return submit();
    if (name === "discard") { S.editing = null; S.conflict = null; return load(true); }
    if (name === "retry") return void load();
    let view;
    if (name === "confirm") view = await post({ op: "confirm", index: i });
    else if (name === "remove") view = await post({ op: "remove", index: i });
    else if (name === "role") view = await post({ op: "role", index: i, role: extra });  // 只換 role：確認和占比都留著
    else if (name === "publish") view = await post({ op: "publish" });
    if (view && name === "publish") PR.toast(esc(T().published));
    if (view && name === "remove") PR.toast(esc(T().removed));
    render();
  }

  function onClick(ev) {
    const b = ev.target.closest("[data-act]");
    if (!b || b.disabled || !S.view && b.dataset.act !== "retry") return;
    act(b.dataset.act, b.dataset.i === undefined ? null : Number(b.dataset.i), b.dataset.role)
      .catch(() => { S.busy = false; S.note = T().saveFailed; render(); });
  }

  function setDraft(d, k, value) {
    const [a, b] = k.split(".");
    if (b) d[a][b] = value; else d[k] = value;
  }

  function onInput(ev) {
    const el = ev.target;
    if (S.editing && el.dataset.k) setDraft(S.editing.draft, el.dataset.k, el.value);
  }

  function onChange(ev) {
    const el = ev.target, k = el.dataset.k;
    if (!S.editing || !k) return;
    setDraft(S.editing.draft, k, el.value);
    if (/\.kind$|^shareMode$|\.entity$/.test(k)) render(`[data-k="${k}"]`);  // 換了類型，要重畫表單
  }

  function init() {
    const m = /^\/theme\/([^/]+)$/.exec(location.pathname);
    if (!m) return;
    try { S.id = decodeURIComponent(m[1]); } catch (e) { S.id = m[1]; }  // 壞掉的 %xx：照原樣送，後端回找不到
    const root = PR.$("#view");
    if (!root) return;
    root.addEventListener("click", onClick);
    root.addEventListener("input", onInput);
    root.addEventListener("change", onChange);
    root.addEventListener("submit", (ev) => { ev.preventDefault(); submit(); });
    // 頁內搜尋找到收起來的比較內容時，瀏覽器會自己打開它：按鈕的狀態跟著改（不重畫，免得搜尋位置跑掉）
    root.addEventListener("beforematch", (ev) => {
      if (!S.conflict || !ev.target || ev.target.id !== "chain-cmp") return;
      S.conflict.open = true;
      const b = PR.$("[data-act=compare]", root);
      if (b) b.setAttribute("aria-expanded", "true");
    });
    loadLists().then(() => { const t = PR.$("#title"); if (t) t.textContent = S.title; });
    load();
  }

  PR.themeChain = { sourceView, shareView, nodeText, pending, blankDraft, toDraft, payload, fieldKey, capChoices, entityIsCompany,
                    matchLink, cmpRows, viewHtml, act, submit, MAX_CHOICES, MAX_LINKS, state: S };
  document.addEventListener("DOMContentLoaded", init);
})(window.PR);
