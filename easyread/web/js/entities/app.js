/* 追蹤對象頁（ticket 13）：列表、類型篩選、編輯抽屜、封存、手動連結資料。
   畫面照核准的 Mockup A（docs/mockups/v1-a/entities.html）。「AI 建議追蹤」（#18）和最新收盤（#30）還沒做。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  const TYPES = ["company", "industry", "macro", "event", "theme"];
  const MARKETS = ["TW", "US"];
  const MAX_LISTINGS = 5, MAX_ALIASES = 20, MAX_ALIAS = 60;
  const MAX_CHOICES = 200;  // 手動連結的下拉選單最多列幾則資料
  // 指數名稱是資料，不是介面文字
  const DEFAULT_BENCHMARK = { TW: "發行量加權股價報酬指數", US: "S&P 500 Total Return" };  // i18n-ok
  const PRICE_ONLY = { TW: "發行量加權股價指數", US: "S&P 500" };  // i18n-ok
  const FIELDS = ["type", "name", "benchmark", "industry_index", "item_id"];

  /* 畫面文字集中在這裡（i18n_check 只看得到一般字串裡的 PR.t，看不到 template 裡的） */
  const T = () => ({
    company: PR.t("公司"), industry: PR.t("產業 / 供應鏈"), macro: PR.t("總經 / 政策"), event: PR.t("事件"), theme: PR.t("題材"),
    TW: PR.t("台股"), US: PR.t("美股"),
    aliasesOf: (list) => PR.t("別名：{list}", { list }),
    archivedChip: PR.t("已封存"),
    noIndustry: PR.t("產業指數未設定"),
    items: (n) => PR.t("{n} 則", { n }),
    idle: PR.t("選一個追蹤對象來編輯，或按「＋ 新增」。"),
    editing: (name) => PR.t("編輯：{name}", { name }),
    adding: PR.t("新增追蹤對象"),
    type: PR.t("類型"), name: PR.t("名稱"), symbol: PR.t("代號"), market: PR.t("市場"), remove: PR.t("移除"),
    addSymbol: PR.t("＋ 代號"), primaryHint: PR.t("打分以主要代號為準（第一個）。"),
    aliases: PR.t("別名"), removeAlias: (name) => PR.t("移除別名 {name}", { name }), newAlias: PR.t("新增別名"),
    aliasHint: PR.t("AI 用別名把資料連到這個對象。按 Enter 加入。"),
    benchmark: PR.t("基準指數"), benchmarkHint: PR.t("預設含息，避免除息日誤判。"),
    defaultIs: (name) => PR.t("預設：{name}", { name }), defaultByMarket: PR.t("預設（依主要代號的市場）"),
    twPriceOnly: PR.t("加權指數（不含息，不建議）"), usPriceOnly: PR.t("S&P 500（不含息，不建議）"),
    industryIndex: PR.t("產業指數"), unset: PR.t("未設定"), industryHint: PR.t("例如：半導體類指數、SOX。"),
    linked: PR.t("連到這個對象的資料（最近）"), aiLink: PR.t("AI 連結"), manual: PR.t("手動"),
    noLinks: PR.t("還沒有資料連到這個對象。"), pickItem: PR.t("選一則資料"), pickItemPrompt: PR.t("選一則資料手動連結…"),
    link: PR.t("連結"), save: PR.t("儲存"), cancel: PR.t("取消"), archive: PR.t("封存"), unarchive: PR.t("取消封存"),
    archiveNote: PR.t("封存不會刪掉帳本裡跟它有關的判斷。"),
    filterBy: PR.t("依類型篩選"), all: (n) => PR.t("全部 {n}", { n }), archivedCount: (n) => PR.t("已封存 {n}", { n }),
    loadFailed: PR.t("讀不到追蹤對象"), loadFailedBody: PR.t("本機資料庫暫時讀不到。資料沒有遺失。"), retry: PR.t("重試"),
    emptyTitle: PR.t("還沒有追蹤對象"), emptyBody: PR.t("先加幾個你關心的：一家公司、一個題材、一個總經主題。"),
    emptyHint: PR.t("建議從你熟悉的產業開始。"), addFirst: PR.t("＋ 新增第一個"),
    noneOfType: PR.t("這個類型還沒有追蹤對象。"), benchCol: PR.t("基準 / 產業"), recentCol: PR.t("近 7 天"),
  });
  const esc = (s) => PR.esc(s);
  const typeLabel = (k, tx) => (TYPES.includes(k) ? tx[k] : k);
  const joinList = (xs) => xs.join(PR.lang === "en" ? ", " : "、");  // i18n-ok：列表分隔符號

  /* ---------- 純函式（測試直接呼叫） ---------- */
  function blankDraft() {
    return { id: null, title: "", type: "company", name: "", listings: [{ market: "TW", symbol: "" }], aliases: [],
             benchmark: "", industry_index: "", archived: false, mentions: [], aliasInput: "" };
  }

  function toDraft(e) {
    return { id: e.id, title: e.name, type: e.type, name: e.name,
             listings: (e.listings || []).map((l) => ({ market: l.market, symbol: l.symbol })),
             aliases: (e.aliases || []).slice(), benchmark: e.benchmark_default ? "" : (e.benchmark || ""),
             industry_index: e.industry_index || "", archived: !!e.archived, mentions: e.mentions || [], aliasInput: "" };
  }

  /* 要送出的內容。空白的代號列不送；kept[i] 是第 i 個送出的代號在畫面上是第幾列（對應錯誤欄位用）。 */
  function payload(d) {
    const company = d.type === "company";
    const kept = [];
    const listings = [];
    if (company) d.listings.forEach((l, i) => {
      const symbol = String(l.symbol || "").trim();
      if (symbol) { kept.push(i); listings.push({ market: l.market, symbol }); }
    });
    return {
      kept,
      body: { type: d.type, name: String(d.name || "").trim(), aliases: d.aliases.slice(), listings,
              benchmark: company && d.benchmark ? d.benchmark : null,
              industry_index: company ? (String(d.industry_index || "").trim() || null) : null },
    };
  }

  /* 伺服器回的欄位名稱 → 畫面上要標紅的位置 */
  function fieldKey(field, kept) {
    if (typeof field !== "string" || !field) return "form";
    const m = /^listings\.(\d+)\.(symbol|market)$/.exec(field);
    if (m) {
      const row = kept && kept[Number(m[1])];
      return row == null ? "listings" : `listings.${row}.${m[2]}`;
    }
    if (field.startsWith("listings")) return "listings";
    if (field.startsWith("aliases")) return "aliases";
    return FIELDS.includes(field) ? field : "form";
  }

  function primaryMarket(d) {
    const first = d.listings.find((l) => String(l.symbol || "").trim()) || d.listings[0];
    return first ? first.market : null;
  }

  function benchmarkOptions(d) {
    const tx = T(), market = primaryMarket(d);
    const opts = [["", market ? tx.defaultIs(DEFAULT_BENCHMARK[market]) : tx.defaultByMarket]];
    if (market === "TW") opts.push([PRICE_ONLY.TW, tx.twPriceOnly]);
    if (market === "US") opts.push([PRICE_ONLY.US, tx.usPriceOnly]);
    if (d.benchmark && !opts.some(([v]) => v === d.benchmark)) opts.push([d.benchmark, d.benchmark]);
    return opts;
  }

  function addAlias(d, raw) {
    const alias = String(raw || "").split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_ALIAS);
    if (!alias || d.aliases.length >= MAX_ALIASES) return false;
    const folded = alias.toLowerCase();
    if (folded === String(d.name || "").trim().toLowerCase() || d.aliases.some((a) => a.toLowerCase() === folded)) return false;
    d.aliases.push(alias);
    return true;
  }

  function itemTitle(item) {
    if (!item) return "";
    const main = PR.titles ? PR.titles(item).main : "";
    return main || item.title || item.id;
  }

  function rowHtml(e, selected) {
    const tx = T();
    const aliases = e.aliases && e.aliases.length ? `<span class="sub" data-no-i18n>${esc(tx.aliasesOf(joinList(e.aliases)))}</span>` : "";
    const archived = e.archived ? ` <span class="chip">${esc(tx.archivedChip)}</span>` : "";
    const symbols = e.listings && e.listings.length
      ? e.listings.map((l) => `<span class="num">${esc(l.symbol)}</span>`).join("<br>")
      : `<span class="muted">—</span>`;
    const bench = e.type === "company"
      ? `<span data-no-i18n>${esc(e.benchmark || "—")}<span class="sub">${esc(e.industry_index || tx.noIndustry)}</span></span>`
      : `<span class="muted">—</span>`;
    return `<tr${selected ? ' class="sel"' : ""}><td><button type="button" class="name" data-no-i18n data-open="${esc(e.id)}">${esc(e.name)}</button>${archived}${aliases}</td>`
      + `<td>${esc(typeLabel(e.type, tx))}</td><td>${symbols}</td><td class="hide-sm bench">${bench}</td>`
      + `<td>${esc(tx.items(e.recent_mentions || 0))}</td></tr>`;
  }

  function listingsHtml(d, tx, err, bad) {
    let h = `<div class="field"><label>${esc(tx.symbol)}</label>`;
    d.listings.forEach((l, i) => {
      const sym = `listings.${i}.symbol`, mkt = `listings.${i}.market`;
      h += `<div class="listing"><select class="input${bad(mkt)}" data-listing="${i}" data-part="market" aria-label="${esc(tx.market)}">`
        + MARKETS.map((m) => `<option value="${m}"${m === l.market ? " selected" : ""}>${esc(tx[m])}</option>`).join("")
        + `</select><input class="input num${bad(sym)}" data-listing="${i}" data-part="symbol" value="${esc(l.symbol)}" placeholder="${l.market === "US" ? "NVDA" : "2330"}" aria-label="${esc(tx.symbol)}" maxlength="12" autocomplete="off">`
        + `<button type="button" class="btn sm ghost" data-act="del-listing" data-i="${i}">${esc(tx.remove)}</button></div>${err(sym)}${err(mkt)}`;
    });
    h += err("listings");
    if (d.listings.length < MAX_LISTINGS) h += `<div><button type="button" class="btn sm" data-act="add-listing">${esc(tx.addSymbol)}</button></div>`;
    return h + `<span class="hint">${esc(tx.primaryHint)}</span></div>`;
  }

  function mentionsHtml(d, tx, items, err) {
    const byId = new Map((items || []).filter((i) => i && typeof i.id === "string").map((i) => [i.id, i]));
    let h = `<div class="field"><label>${esc(tx.linked)}</label><div class="mentions">`;
    h += d.mentions.length
      ? d.mentions.map((m) => `<div class="row"><span class="mt" data-no-i18n>${esc(itemTitle(byId.get(m.item_id)) || m.item_id)}</span>`
        + `<span class="chip ${m.source === "ai" ? "ai" : "mine"}">${esc(m.source === "ai" ? tx.aiLink : tx.manual)}</span>`
        + `<button type="button" class="linkish" data-act="unlink" data-item="${esc(m.item_id)}">${esc(tx.remove)}</button></div>`).join("")
      : `<span class="hint">${esc(tx.noLinks)}</span>`;
    const linked = new Set(d.mentions.map((m) => m.item_id));
    const choices = [...byId.values()].filter((i) => !linked.has(i.id)).slice(0, MAX_CHOICES);
    if (choices.length) {
      h += `<div class="row add-link"><select class="input" id="f-link" data-no-i18n aria-label="${esc(tx.pickItem)}"><option value="">${esc(tx.pickItemPrompt)}</option>`
        + choices.map((i) => `<option value="${esc(i.id)}">${esc(itemTitle(i))}</option>`).join("")
        + `</select><button type="button" class="btn sm" data-act="link">${esc(tx.link)}</button></div>`;
    }
    return h + `${err("item_id")}</div></div>`;
  }

  function drawerHtml(d, errors, items, busy) {
    const tx = T();
    if (!d) return `<div class="card drawer idle"><p>${esc(tx.idle)}</p></div>`;
    errors = errors || {};
    const err = (k) => errors[k] ? `<div class="err" role="alert">${esc(errors[k])}</div>` : "";
    const bad = (k) => errors[k] ? " invalid" : "";
    const company = d.type === "company";
    // busy 時整張表單停用，請求回來前不能改內容或再按一次
    let h = `<form class="card drawer" id="drawer" novalidate><fieldset class="plain"${busy ? " disabled" : ""}><h2 data-no-i18n>${esc(d.id ? tx.editing(d.title) : tx.adding)}</h2>`;
    h += `<div class="field"><label for="f-type">${esc(tx.type)}</label><select class="input${bad("type")}" id="f-type" data-k="type">`
      + TYPES.map((k) => `<option value="${k}"${k === d.type ? " selected" : ""}>${esc(tx[k])}</option>`).join("")
      + `</select>${err("type")}</div>`;
    h += `<div class="field"><label for="f-name">${esc(tx.name)}</label><input class="input${bad("name")}" id="f-name" data-k="name" maxlength="100" value="${esc(d.name)}" autocomplete="off">${err("name")}</div>`;
    if (company) h += listingsHtml(d, tx, err, bad);
    h += `<div class="field"><label for="f-alias">${esc(tx.aliases)}</label><div class="row">`
      + d.aliases.map((a, i) => `<span class="chip" data-no-i18n>${esc(a)}<button type="button" class="x" data-act="del-alias" data-i="${i}" aria-label="${esc(tx.removeAlias(a))}">×</button></span>`).join("")
      + (d.aliases.length < MAX_ALIASES ? `<input class="input${bad("aliases")}" id="f-alias" style="width:140px" maxlength="${MAX_ALIAS}" value="${esc(d.aliasInput || "")}" placeholder="${esc(tx.newAlias)}" autocomplete="off">` : "")
      + `</div>${err("aliases")}<span class="hint">${esc(tx.aliasHint)}</span></div>`;
    if (company) {
      h += `<div class="grid2"><div class="field"><label for="f-bench">${esc(tx.benchmark)}</label><select class="input${bad("benchmark")}" id="f-bench" data-k="benchmark" data-no-i18n>`
        + benchmarkOptions(d).map(([v, label]) => `<option value="${esc(v)}"${v === (d.benchmark || "") ? " selected" : ""}>${esc(label)}</option>`).join("")
        + `</select>${err("benchmark")}<span class="hint">${esc(tx.benchmarkHint)}</span></div>`
        + `<div class="field"><label for="f-ind">${esc(tx.industryIndex)}</label><input class="input${bad("industry_index")}" id="f-ind" data-k="industry_index" maxlength="80" value="${esc(d.industry_index)}" placeholder="${esc(tx.unset)}" autocomplete="off">${err("industry_index")}<span class="hint">${esc(tx.industryHint)}</span></div></div>`;
    }
    if (d.id) h += mentionsHtml(d, tx, items, err);
    h += err("form");
    h += `<div class="row"><button type="submit" class="btn primary"${busy ? " disabled" : ""}>${esc(tx.save)}</button>`
      + `<button type="button" class="btn ghost" data-act="cancel">${esc(tx.cancel)}</button><span class="grow"></span>`
      + (d.id ? `<button type="button" class="btn ghost danger" data-act="archive"${busy ? " disabled" : ""}>${esc(d.archived ? tx.unarchive : tx.archive)}</button>` : "")
      + `</div>`;
    if (d.id) h += `<p class="hint note">${esc(tx.archiveNote)}</p>`;
    return h + `</fieldset></form>`;
  }

  function typesHtml(S, tx) {
    let h = `<div class="types" role="group" aria-label="${esc(tx.filterBy)}">`
      + `<button type="button" data-type="" aria-pressed="${S.filter === ""}">${esc(tx.all(S.total || 0))}</button>`
      + TYPES.map((k) => `<button type="button" data-type="${k}" aria-pressed="${S.filter === k}">${esc(tx[k])} ${Number(S.counts[k]) || 0}</button>`).join("");
    if (S.archived) h += `<span class="sep"></span><button type="button" data-act="toggle-archived" aria-pressed="${S.showArchived}">${esc(tx.archivedCount(S.archived))}</button>`;
    return h + `</div>`;
  }

  function viewHtml(S) {
    const tx = T();
    if (S.status === "loading") {
      return `<div class="card" style="padding:16px; display:grid; gap:12px" aria-busy="true"><div class="skel" style="width:30%"></div><div class="skel"></div><div class="skel"></div><div class="skel" style="width:70%"></div></div>`;
    }
    if (S.status === "error") {
      return `<div class="empty" role="alert"><h2>${esc(tx.loadFailed)}</h2><p>${esc(tx.loadFailedBody)} <button type="button" class="btn sm" data-act="retry">${esc(tx.retry)}</button></p></div>`;
    }
    if (!S.list.length && !S.archived && !S.draft) {
      return `<div class="empty"><h2>${esc(tx.emptyTitle)}</h2><p>${esc(tx.emptyBody)}<br>${esc(tx.emptyHint)}</p><button type="button" class="btn primary" data-act="new">${esc(tx.addFirst)}</button></div>`;
    }
    const rows = S.list.filter((e) => !S.filter || e.type === S.filter);
    const sel = S.draft && S.draft.id;
    const body = rows.length
      ? rows.map((e) => rowHtml(e, e.id === sel)).join("")
      : `<tr><td colspan="5" class="muted">${esc(tx.noneOfType)}</td></tr>`;
    return typesHtml(S, tx)
      + `<div class="split"><div class="card" style="overflow-x:auto"><table class="tbl"><thead><tr><th>${esc(tx.name)}</th><th>${esc(tx.type)}</th><th>${esc(tx.symbol)}</th>`
      + `<th class="hide-sm">${esc(tx.benchCol)}</th><th>${esc(tx.recentCol)}</th></tr></thead><tbody>${body}</tbody></table></div>`
      + drawerHtml(S.draft, S.errors, S.items, S.busy) + `</div>`;
  }

  PR.entities = { blankDraft, toDraft, payload, fieldKey, benchmarkOptions, addAlias, rowHtml, drawerHtml, viewHtml };

  /* ---------- 頁面 ---------- */
  const S = { status: "loading", list: [], counts: {}, total: 0, archived: 0, filter: "", showArchived: false,
              draft: null, errors: {}, busy: false, items: [] };
  let itemsLoaded = false;
  let loadSeq = 0, openSeq = 0;

  function render(focus) {
    const view = PR.$("#view");
    if (!view) return;
    view.innerHTML = viewHtml(S);
    const summary = PR.$("#summary");
    if (summary) summary.textContent = S.status === "ready" ? PR.t("{n} 個", { n: S.total }) : "";
    if (focus) {
      const el = PR.$(focus, view);
      if (el) el.focus();
    }
  }

  async function load(quiet) {
    const seq = ++loadSeq;
    if (!quiet) { S.status = "loading"; render(); }
    try {
      const data = await PR.api("/api/entities" + (S.showArchived ? "?archived=1" : ""));
      if (seq !== loadSeq) return;  // 後面又發了一次，這次的結果過期了
      Object.assign(S, { list: Array.isArray(data.entities) ? data.entities : [], counts: data.counts || {},
                         total: data.total || 0, archived: data.archived || 0, status: "ready" });
    } catch (e) {
      if (seq !== loadSeq) return;
      S.status = "error";
    }
    render();
  }

  /* 文獻庫的資料清單：手動連結要選資料、顯示標題；順便拿到寫入要用的 token */
  async function loadItems() {
    if (itemsLoaded) return;
    try {
      const lib = await PR.api("/api/library");
      if (lib && lib.token) PR.token = lib.token;
      S.items = lib && Array.isArray(lib.items) ? lib.items : [];
      itemsLoaded = true;
    } catch (e) {
      S.items = [];
    }
  }

  async function open(id) {
    if (S.busy) return;
    const seq = ++openSeq;
    try {
      const [entity] = await Promise.all([PR.api("/api/entities/" + encodeURIComponent(id)), loadItems()]);
      if (seq !== openSeq || S.busy) return;  // 已經點了別的，或開始存檔了
      S.draft = toDraft(entity);
      S.errors = {};
    } catch (e) {
      if (seq !== openSeq) return;
      PR.toast(esc(PR.t("讀不到這個追蹤對象。")));
    }
    render("#f-name");
  }

  function errorMessage(e, fallback) {
    const data = (e && e.data) || {};
    return e && e.status && e.status < 500 && typeof data.error === "string" ? data.error : fallback;
  }

  async function save() {
    const d = S.draft;
    if (!d || S.busy) return;
    if (d.aliasInput && d.aliasInput.trim()) { addAlias(d, d.aliasInput); d.aliasInput = ""; }
    const { body, kept } = payload(d);
    openSeq++;  // 存檔前點開、還沒回來的對象不要蓋掉這張表單
    S.busy = true;
    S.errors = {};
    render();
    let failed = false;
    try {
      const saved = await PR.api(d.id ? "/api/entities/" + encodeURIComponent(d.id) : "/api/entities", { method: "POST", body });
      S.draft = toDraft(saved);
      PR.toast(esc(PR.t("已儲存。")));
    } catch (e) {
      failed = true;
      S.errors = { [fieldKey(e && e.data && e.data.field, kept)]: errorMessage(e, PR.t("儲存失敗，請再試一次。")) };
    }
    S.busy = false;
    await load(true);
    if (failed) { const bad = PR.$("#drawer .invalid"); if (bad) bad.focus(); }
  }

  async function archive() {
    const d = S.draft;
    if (!d || !d.id || S.busy) return;
    S.busy = true;
    render();
    try {
      const saved = await PR.api("/api/entities/" + encodeURIComponent(d.id) + "/archive", { method: "POST", body: { archived: !d.archived } });
      d.archived = !!saved.archived;  // 只改封存狀態，表單上還沒存的修改留著
      S.errors = {};
      PR.toast(esc(saved.archived ? PR.t("已封存。") : PR.t("已取消封存。")));
    } catch (e) {
      S.errors = { form: errorMessage(e, PR.t("封存失敗，請再試一次。")) };
    }
    S.busy = false;
    await load(true);
  }

  async function changeLink(itemId, remove) {
    const d = S.draft;
    if (!d || !d.id || !itemId || S.busy) return;
    const base = "/api/entities/" + encodeURIComponent(d.id) + "/mentions";
    S.busy = true;
    render();
    try {
      await PR.api(remove ? base + "/" + encodeURIComponent(itemId) + "/remove" : base, { method: "POST", body: remove ? {} : { item_id: itemId } });
      const fresh = await PR.api("/api/entities/" + encodeURIComponent(d.id));
      d.mentions = fresh.mentions || [];
      S.errors = {};
    } catch (e) {
      S.errors = { item_id: errorMessage(e, PR.t("連結沒有改成功，請再試一次。")) };
    }
    S.busy = false;
    await load(true);
  }

  function startNew() {
    if (S.busy) return;
    openSeq++;
    S.draft = blankDraft();
    S.errors = {};
    S.status = "ready";
    render("#f-name");
    loadItems();
  }

  function onClick(ev) {
    const target = ev.target.closest("[data-act], [data-open], [data-type]");
    if (!target) return;
    if (target.dataset.open) return void open(target.dataset.open);
    if (target.dataset.type != null && !target.dataset.act) { S.filter = target.dataset.type; return void render(); }
    const d = S.draft;
    switch (target.dataset.act) {
      case "retry": return void load();
      case "new": return void startNew();
      case "toggle-archived":
        if (S.busy) return;  // 存檔中換列表，存檔回來的那次重畫會被當成過期丟掉
        S.showArchived = !S.showArchived;
        return void load(true);
    }
    if (!d || S.busy) return;
    switch (target.dataset.act) {
      case "cancel": {
        openSeq++;
        S.draft = null;
        S.errors = {};
        render();
        const b = PR.$("#newBtn");
        return void (b && b.focus());
      }
      case "archive": return void archive();
      case "add-listing":
        if (d.listings.length >= MAX_LISTINGS) return;
        d.listings.push({ market: (d.listings[d.listings.length - 1] || {}).market || "TW", symbol: "" });
        return void render(`[data-listing="${d.listings.length - 1}"][data-part="symbol"]`);
      case "del-listing": d.listings.splice(Number(target.dataset.i), 1); S.errors = {}; return void render();
      case "del-alias": d.aliases.splice(Number(target.dataset.i), 1); return void render("#f-alias");
      case "link": { const sel = PR.$("#f-link"); return void changeLink(sel && sel.value, false); }
      case "unlink": return void changeLink(target.dataset.item, true);
    }
  }

  function onInput(ev) {
    const d = S.draft, el = ev.target;
    if (!d) return;
    if (el.dataset.k === "name" || el.dataset.k === "industry_index") d[el.dataset.k] = el.value;
    else if (el.id === "f-alias") d.aliasInput = el.value;  // 還沒按 Enter 的別名，重畫時留著
    else if (el.dataset.part === "symbol" && d.listings[Number(el.dataset.listing)]) d.listings[Number(el.dataset.listing)].symbol = el.value;
  }

  function onChange(ev) {
    const d = S.draft, el = ev.target;
    if (!d) return;
    if (el.dataset.k === "type") { d.type = el.value; S.errors = {}; render("#f-type"); }
    else if (el.dataset.k === "benchmark") d.benchmark = el.value;
    else if (el.dataset.part === "market" && d.listings[Number(el.dataset.listing)]) {
      d.listings[Number(el.dataset.listing)].market = el.value;
      render(`[data-listing="${Number(el.dataset.listing)}"][data-part="market"]`);
    }
  }

  function onKey(ev) {
    if (ev.target.id !== "f-alias" || ev.key !== "Enter" || ev.isComposing) return;
    ev.preventDefault();
    if (!S.draft) return;
    addAlias(S.draft, ev.target.value);  // 重複或空白的不加
    S.draft.aliasInput = "";
    render("#f-alias");
  }

  document.addEventListener("DOMContentLoaded", () => {
    const view = PR.$("#view");
    if (!view) return;
    view.addEventListener("click", onClick);
    view.addEventListener("input", onInput);
    view.addEventListener("change", onChange);
    view.addEventListener("keydown", onKey);
    view.addEventListener("submit", (ev) => { ev.preventDefault(); save(); });
    const btn = PR.$("#newBtn");
    if (btn) btn.addEventListener("click", startNew);
    load();
  });
})(window.PR);
