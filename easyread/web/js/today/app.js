/* 今日新聞頁（ticket 15）：今天的資料，依重要度和追蹤對象列出，點開看相對於每個論點的判斷。
   畫面照核准的 Mockup A（docs/mockups/v1-a/today.html）。「先判斷，再看 AI」模式屬於判斷的 ticket（#37、#38），這裡還沒做。
   這頁顯示的是 AI 的看法：資料走 POST /api/today（要 X-Token），伺服器在回傳之前寫揭露紀錄（地點 = today），畫面只畫伺服器回來的。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  const LEVELS = ["high", "mid", "none", "low", "noise"];
  const DEFAULT_LEVELS = ["high", "mid", "none"];
  const PAGE = 50, MAX_LIMIT = 200;  // 跟伺服器的 DEFAULT_LIMIT / MAX_LIMIT 一致
  const TIMEOUT_MS = 20000;          // 等伺服器最多這麼久，超過就當失敗、可以重試
  const BADGE = { high: "h", mid: "m", low: "l", noise: "n", none: "u" };
  const NOISE_GROUP = "group:noise";  // 雜訊組 <details> 的 data-id（跟資料 ID 分開，資料 ID 沒有冒號）
  const own = (map, key) => Object.prototype.hasOwnProperty.call(map, key);
  const ENGINE = { codex: "Codex CLI", antigravity: "Antigravity CLI" };  // i18n-ok：產品名稱
  const joinList = (xs) => xs.join(PR.lang === "en" ? ", " : "、");  // i18n-ok：列表分隔符號
  /* 分類因為只有關不掉工具的 CLI 停著（ticket 104，伺服器的 triage_block） */
  const noTools = (S) => !!(S && S.triageBlock && S.triageBlock.reason === "no_tools");

  const T = () => ({
    levels: { high: PR.t("高"), mid: PR.t("中"), low: PR.t("低"), noise: PR.t("雜訊"), none: PR.t("未分類") },
    groups: { high: PR.t("重要"), mid: PR.t("值得看"), low: PR.t("次要"), noise: PR.t("AI 判為雜訊"), none: PR.t("還沒有 AI 看法") },
    relations: { bull: PR.t("偏多"), bear: PR.t("偏空"), neutral: PR.t("中性"), noise: PR.t("雜訊"),
                 strengthens: PR.t("加強"), weakens: PR.t("削弱"), related_no_change: PR.t("有關但不改變") },
    noise: { priced_in: PR.t("已反映"), rehash: PR.t("舊聞重炒"), no_new_info: PR.t("沒有新資訊"),
             unreliable: PR.t("來源不可靠"), unrelated: PR.t("無關"), short_term: PR.t("短期波動") },
    confidence: { low: PR.t("低"), mid: PR.t("中"), high: PR.t("高") },
    states: { pending: PR.t("等待 AI 分類"), failed: PR.t("分類失敗"), done: PR.t("沒有相關的追蹤對象或論點") },
    pendingNoTools: PR.t("等待 AI 分類：分類要 Claude Code、API key 或本機模型"),
    blocked: (n, engines) => PR.t("有 {n} 則等著分類，但現在沒有能分類的引擎：{engines} 可以閱讀和翻譯，不支援分類。分類要 Claude Code、API key 或本機模型。", { n, engines }),
    blockedNone: (n) => PR.t("有 {n} 則等著分類，但現在沒有能分類的引擎。分類要 Claude Code、API key 或本機模型。", { n }),
    toSettings: PR.t("到設定的 AI 模型"),
    ai: PR.t("AI："), preview: PR.t("只有預覽"), stale: PR.t("內容已更新，看法可能過期"), retro: PR.t("事後補判"),
    filters: PR.t("篩選"), filterImportance: PR.t("重要度"), filterEntity: PR.t("追蹤對象"), allEntities: PR.t("全部"),
    detail: PR.t("相對於每個論點的判斷"), detailEntities: PR.t("相對於每個追蹤對象的判斷"),
    thesisOf: (theme) => PR.t("題材：{theme}", { theme }),
    confidenceOf: (c) => PR.t("信心 {c}", { c }),
    gradeOf: (g) => PR.t("證據 {g} 級", { g }),
    importedAt: (t) => PR.t("{time} 匯入", { time: t }),
    importedTitle: PR.t("發布時間不明，這是匯入時間"),
    countOf: (n) => PR.t("共 {n} 則", { n }),
    countShownOf: (n, shown) => PR.t("共 {n} 則 · 顯示 {shown}", { n, shown }),
    shownOf: (shown, total) => PR.t("顯示 {shown} / {total} 則", { shown, total }),
    more: PR.t("顯示更多"), moreCapped: (n) => PR.t("沒顯示的還有 {n} 則，請用篩選縮小範圍。", { n }),
    truncated: PR.t("最近有動靜的資料太多，只讀了最新的一部分，今天有些資料可能沒列出。"),
    note: PR.t("這頁會顯示 AI 的重要度和理由，所以每顯示一則，系統就記一筆「揭露紀錄」；之後再對這則做判斷，就不算盲判。"),
    loadFailed: PR.t("無法載入今天的資料"), retry: PR.t("重試"), reset: PR.t("重設篩選"),
    errors: { timeout: PR.t("等太久沒有回應。資料沒有遺失，可以再試一次。"),
              network: PR.t("連不上 NewsRead 本機服務。確認 NewsRead 開著，再試一次。"),
              bad: PR.t("篩選條件不對。重設篩選再試一次。"),
              expired: PR.t("這個頁面開太久，連線憑證過期了。重新整理頁面再試一次。"),
              server: PR.t("本機資料庫暫時讀不到。資料沒有遺失。") },
    emptyTitle: PR.t("今天還沒有資料"),
    emptyBody: PR.t("今天還沒有新資料。可以新增追蹤對象，或貼一則新聞連結。"),
    emptyEntities: PR.t("新增追蹤對象"), emptyPaste: PR.t("＋ 貼網址"),
    noMatch: PR.t("這個篩選沒有資料。"),
    dayOf: (date) => PR.t("{date}（台北時間）", { date }),
  });
  const esc = (s) => PR.esc(s);
  const label = (map, key) => (own(map, key) ? map[key] : String(key == null ? "" : key));

  /* ---------- 純函式（測試直接呼叫） ---------- */
  function params(S) {
    const levels = LEVELS.filter((l) => S.levels.includes(l));
    const out = { importance: (levels.length ? levels : DEFAULT_LEVELS).join(","), limit: Math.max(1, Math.min(MAX_LIMIT, S.limit || PAGE)) };
    if (S.entity) out.entity = S.entity;
    return out;
  }

  function toggleLevel(levels, level) {
    if (!LEVELS.includes(level)) return levels.slice();
    const next = levels.includes(level) ? levels.filter((l) => l !== level) : levels.concat(level);
    return LEVELS.filter((l) => next.includes(l));
  }

  function nextLimit(limit) { return Math.min(MAX_LIMIT, (limit || PAGE) + PAGE); }

  function readerHref(id) { return "/read/" + encodeURIComponent(id); }

  /* 錯誤只分種類，畫面用固定文案（不顯示伺服器或瀏覽器的原文） */
  function errorKind(error, timedOut) {
    if (timedOut) return "timeout";
    const status = error && error.status;
    if (!status) return "network";
    if (status === 400) return "bad";
    return status === 403 ? "expired" : "server";
  }

  function time(item) {
    const d = new Date(item.at);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString(PR.lang === "en" ? "en-GB" : "zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Taipei" });
  }

  function badge(level, tx) {
    return `<span class="imp ${own(BADGE, level) ? BADGE[level] : "u"}">${esc(label(tx.levels, level))}</span>`;
  }

  function judgeLine(j, tx, withGrade) {
    const noise = j.noise_kind ? `<span class="chip">${esc(label(tx.noise, j.noise_kind))}</span>` : "";
    const grade = withGrade && j.grade ? `<span class="chip">${esc(tx.gradeOf(j.grade))}</span>` : "";
    return `<span class="chip ai">${esc(label(tx.relations, j.relation))}</span>${noise}${grade}`
      + `<span class="muted">${esc(tx.confidenceOf(label(tx.confidence, j.confidence)))}</span>`;
  }

  function detailHtml(item, tx) {
    tx = tx || T();
    const theses = item.theses || [], ents = item.entities || [];
    if (!theses.length && !ents.length) return "";
    const rows = (list, kind) => list.map((j) => {
      const name = kind === "thesis" ? (j.claim || j.id) : (j.name || j.id);
      const sub = kind === "thesis" && j.theme_name ? `<span class="sub" data-no-i18n>${esc(tx.thesisOf(j.theme_name))}</span>` : "";
      return `<li><div class="jh">${badge(j.importance, tx)}<b data-no-i18n>${esc(name)}</b>${sub}</div>`
        + `<div class="jm">${judgeLine(j, tx, kind === "thesis")}</div><div class="jr" data-no-i18n>${esc(j.reason || "")}</div></li>`;
    }).join("");
    let h = `<details class="detail" data-id="${esc(item.id)}"><summary>${esc(theses.length ? tx.detail : tx.detailEntities)}</summary>`;
    if (theses.length) h += `<ul class="judges">${rows(theses, "thesis")}</ul>`;
    if (ents.length) h += (theses.length ? `<h4>${esc(tx.detailEntities)}</h4>` : "") + `<ul class="judges">${rows(ents, "entity")}</ul>`;
    return h + `</details>`;
  }

  function rowHtml(item, tx, index, S) {
    tx = tx || T();
    const t = time(item);
    const when = !t ? "" : item.time_known === false
      ? `<span title="${esc(tx.importedTitle)}">${esc(tx.importedAt(t))}</span>` : `<span>${esc(t)}</span>`;
    const meta = [item.publisher ? `<span data-no-i18n>${esc(item.publisher)}</span>` : "", when,
                  item.preview_only ? `<span class="chip warn">${esc(tx.preview)}</span>` : "",
                  item.stale ? `<span class="chip warn">${esc(tx.stale)}</span>` : "",
                  item.retrospective ? `<span class="chip">${esc(tx.retro)}</span>` : ""].filter(Boolean).join("");
    const why = item.top
      ? `<div class="why"><b>${esc(tx.ai)}</b><span data-no-i18n>${esc(item.top.reason)}</span></div>`
      : `<div class="why muted">${esc(item.state === "pending" && noTools(S) ? tx.pendingNoTools : label(tx.states, item.state))}</div>`;
    const ents = (item.entities || []).filter((e) => e.noise_kind !== "unrelated").slice(0, 6)
      .map((e) => `<span class="chip entity" data-no-i18n>${esc(e.name || e.id)}</span>`).join("");
    const top = item.top ? `<span class="chip ai">${esc(tx.ai)}${esc(label(tx.relations, item.top.relation))}·${esc(label(tx.confidence, item.top.confidence))}</span>` : "";
    const at = index == null ? "" : ` data-i="${Number(index)}"`;
    return `<article class="story"${at}><div class="aside">${badge(item.importance, tx)}</div>`
      + `<div class="t"><a href="${esc(readerHref(item.id))}" data-no-i18n>${esc(item.title)}</a></div>`
      + `<div class="meta">${meta}</div>${why}`
      + (ents || top ? `<div class="ents">${ents}${top}</div>` : "") + detailHtml(item, tx) + `</article>`;
  }

  function filtersHtml(S, tx) {
    const counts = S.counts || {};
    const levels = LEVELS.map((l) => `<label><input type="checkbox" data-level="${l}"${S.levels.includes(l) ? " checked" : ""}> ${esc(tx.levels[l])}`
      + ` <span class="n">${Number(counts[l]) || 0}</span></label>`).join("");
    const ents = `<label><input type="radio" name="entity" data-entity=""${S.entity ? "" : " checked"}> ${esc(tx.allEntities)}</label>`
      + (S.entities || []).map((e) => `<label><input type="radio" name="entity" data-entity="${esc(e.id)}"${S.entity === e.id ? " checked" : ""}>`
        + ` <span data-no-i18n>${esc(e.name)}</span> <span class="n">${Number(e.count) || 0}</span></label>`).join("");
    return `<aside class="filters" aria-label="${esc(tx.filters)}"><fieldset><legend>${esc(tx.filterImportance)}</legend>${levels}</fieldset>`
      + `<fieldset><legend>${esc(tx.filterEntity)}</legend>${ents}</fieldset></aside>`;
  }

  /* 依重要度分組（伺服器已經依重要度排好）；雜訊那組收合 */
  function groupsHtml(S, tx) {
    const counts = S.counts || {};
    let index = 0, h = "";
    for (const level of LEVELS) {
      const items = S.items.filter((i) => (LEVELS.includes(i.importance) ? i.importance : "none") === level);
      if (!items.length) continue;
      const n = Math.max(Number(counts[level]) || 0, items.length);
      const count = n > items.length ? tx.countShownOf(n, items.length) : tx.countOf(n);
      const title = `${badge(level, tx)} ${esc(tx.groups[level])} <span class="count">${esc(count)}</span>`;
      const rows = items.map((i) => rowHtml(i, tx, index++, S)).join("");
      h += level === "noise"
        ? `<details class="group noise-group" data-id="${NOISE_GROUP}"><summary class="section-title">${title}</summary><div class="card noise-list">${rows}</div></details>`
        : `<section class="group"><h2 class="section-title">${title}</h2><div class="card">${rows}</div></section>`;
    }
    return h;
  }

  function listHtml(S, tx) {
    const all = LEVELS.reduce((n, l) => n + (Number((S.counts || {})[l]) || 0), 0);
    if (!S.items.length) {
      if (!all && !S.entity) {
        return `<div class="empty"><h2>${esc(tx.emptyTitle)}</h2><p>${esc(tx.emptyBody)}</p>`
          + `<p class="acts"><a class="btn sm" href="/entities">${esc(tx.emptyEntities)}</a>`
          + `<button type="button" class="btn sm line" data-act="paste">${esc(tx.emptyPaste)}</button></p></div>`;
      }
      return `<div class="empty"><p>${esc(tx.noMatch)}</p></div>`;
    }
    let h = `<p class="muted shown">${esc(tx.shownOf(S.items.length, S.total))}</p>${groupsHtml(S, tx)}`;
    if (S.more) {
      h += S.limit < MAX_LIMIT
        ? `<p><button type="button" class="btn ghost" data-act="more"${S.busy ? ' aria-disabled="true"' : ""}>${esc(tx.more)}</button></p>`
        : `<p class="muted">${esc(tx.moreCapped(S.total - S.items.length))}</p>`;
    }
    return h;
  }

  function errorHtml(S, tx) {
    return `<div class="empty" role="alert"><h2>${esc(tx.loadFailed)}</h2><p>${esc(own(tx.errors, S.error) ? tx.errors[S.error] : tx.errors.server)}</p>`
      + `<p class="acts"><button type="button" class="btn sm" data-act="retry">${esc(tx.retry)}</button>`
      + `<button type="button" class="btn sm line" data-act="reset">${esc(tx.reset)}</button></p></div>`;
  }

  /* 今天有待分類的、而分類只能等 Claude Code、API key 或本機模型時（ticket 104） */
  function blockedHtml(S, tx) {
    const n = Number(S.pending) || 0;
    if (!noTools(S) || n < 1) return "";
    const engines = (Array.isArray(S.triageBlock.engines) ? S.triageBlock.engines : []).filter((e) => own(ENGINE, e)).map((e) => ENGINE[e]);
    const text = engines.length ? tx.blocked(n, joinList(engines)) : tx.blockedNone(n);
    return `<div class="banner warn"><span class="ico">!</span><div>${esc(text)}`
      + `<div class="acts"><a class="btn sm" href="/settings#models">${esc(tx.toSettings)}</a></div></div></div>`;
  }

  function viewHtml(S) {
    const tx = T();
    if (S.status === "loading") {
      return `<div class="card" style="padding:16px; display:grid; gap:12px" aria-busy="true"><div class="skel" style="width:40%"></div><div class="skel" style="width:90%"></div><div class="skel" style="width:70%"></div></div>`;
    }
    const warn = (S.status !== "error" && S.truncated ? `<div class="banner warn"><span class="ico">!</span><div>${esc(tx.truncated)}</div></div>` : "")
      + (S.status !== "error" ? blockedHtml(S, tx) : "");
    const main = S.status === "error" ? errorHtml(S, tx) : listHtml(S, tx);
    return `<p class="today-note">${esc(tx.note)}</p>${warn}<div class="t-layout">${filtersHtml(S, tx)}<div>${main}</div></div>`;
  }

  /* 畫完之後要把焦點放回哪裡（鍵盤和螢幕閱讀器使用者不會被丟回頁首） */
  function focusFor(target) {
    if (!target || !target.dataset) return null;
    if (target.dataset.level) return `input[data-level="${target.dataset.level}"]`;
    if (target.dataset.entity !== undefined) return { entity: target.dataset.entity };
    return null;
  }

  /* ---------- 頁面 ---------- */
  const S = { status: "loading", levels: DEFAULT_LEVELS.slice(), entity: "", limit: PAGE, items: [], counts: {}, entities: [],
              total: 0, more: false, truncated: false, date: "", busy: false, error: null, pending: 0, triageBlock: null };
  let seq = 0;

  function find(view, focus) {
    if (!focus) return null;
    if (Array.isArray(focus)) {  // 依序找，找到第一個能用的（請求失敗或資料變少時退回按鈕或篩選）
      for (const f of focus) { const el = find(view, f); if (el && !el.disabled) return el; }
      return null;
    }
    if (typeof focus === "string") return view.querySelector(focus);
    return Array.from(view.querySelectorAll("input[data-entity]")).find((el) => el.dataset.entity === focus.entity) || null;
  }

  function render(focus) {
    const view = PR.$("#view");
    if (!view) return;
    const open = new Set(Array.from(view.querySelectorAll ? view.querySelectorAll("details[open][data-id]") : []).map((d) => d.dataset.id));
    view.innerHTML = viewHtml(S);
    view.setAttribute("aria-busy", S.busy ? "true" : "false");
    if (open.size && view.querySelectorAll) view.querySelectorAll("details[data-id]").forEach((d) => { if (open.has(d.dataset.id)) d.open = true; });
    const day = PR.$("#day");
    if (day) day.textContent = S.status === "ready" && S.date ? T().dayOf(S.date) : "";
    const live = PR.$("#todayStatus");
    if (live) live.textContent = S.status === "ready" ? T().shownOf(S.items.length, S.total) : "";
    const el = view.querySelector ? find(view, focus) : null;
    if (!el) return;
    const fold = el.closest ? el.closest("details") : null;
    if (fold && !fold.open) fold.open = true;  // 目標在收起的雜訊組裡：先打開，不然 focus 不會生效
    el.focus();
  }

  async function load(quiet, focus) {
    const mine = ++seq;
    S.busy = true;
    if (!quiet) S.status = "loading";
    render(focus);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), PR.today.timeoutMs);
    try {
      const data = await PR.api("/api/today", { method: "POST", body: params(S), signal: ctrl.signal });
      if (mine !== seq) return;  // 後面又發了一次，這次的結果過期了
      if (ctrl.signal.aborted) throw new Error("timeout");  // 讀 body 時才逾時：PR.api 會回 {}，不能當成「今天沒有資料」
      const before = S.entities;
      Object.assign(S, { items: Array.isArray(data.items) ? data.items : [], counts: data.counts || {},
                         entities: Array.isArray(data.entities) ? data.entities : [], total: data.total || 0, more: !!data.more,
                         truncated: !!data.truncated, date: data.date || "", status: "ready", error: null,
                         pending: Number(data.pending) || 0, triageBlock: data.triage_block || null });
      if (S.entity && !S.entities.some((e) => e.id === S.entity)) {  // 選的對象這次沒資料：名稱沿用上一次的，不顯示 ID
        const old = (before || []).find((e) => e.id === S.entity);
        S.entities = S.entities.concat({ id: S.entity, name: old ? old.name : S.entity, count: 0 });
      }
    } catch (e) {
      if (mine !== seq) return;
      S.status = "error";
      S.error = errorKind(e, ctrl.signal.aborted);
    } finally {
      clearTimeout(timer);
    }
    S.busy = false;
    render(focus);
  }

  function onChange(ev) {
    const t = ev.target;
    if (t.dataset.level) {
      const next = toggleLevel(S.levels, t.dataset.level);
      if (!next.length) { t.checked = true; return; }  // 至少留一個
      S.levels = next; S.limit = PAGE; return load(true, focusFor(t));
    }
    if (t.dataset.entity !== undefined) {
      S.entity = t.dataset.entity; S.limit = PAGE; return load(true, focusFor(t));
    }
  }

  function onClick(ev) {
    const b = ev.target.closest("[data-act]");
    if (!b) return;
    const act = b.dataset.act;
    if (act === "retry") return load(false, ["[data-act=retry]", "input[data-level]"]);
    if (act === "reset") {
      Object.assign(S, { levels: DEFAULT_LEVELS.slice(), entity: "", limit: PAGE });
      return load(false, "input[data-level]");
    }
    if (act === "paste") { if (PR.openIngest) PR.openIngest(""); return; }
    if (act === "more" && !S.busy) {
      const first = S.items.length;  // 新載入的第一則：焦點放在它的標題
      S.limit = nextLimit(S.limit);
      return load(true, [`.story[data-i="${first}"] .t a`, "[data-act=more]", "[data-act=retry]", "input[data-level]"]);
    }
  }

  PR.today = { params, toggleLevel, nextLimit, readerHref, errorKind, rowHtml, detailHtml, viewHtml, focusFor,
               load, onChange, onClick, state: S, timeoutMs: TIMEOUT_MS, DEFAULT_LEVELS, PAGE, MAX_LIMIT };

  document.addEventListener("DOMContentLoaded", () => {
    const view = PR.$("#view");
    if (!view) return;
    view.addEventListener("change", onChange);
    view.addEventListener("click", onClick);
    load();
  });
})(window.PR);
