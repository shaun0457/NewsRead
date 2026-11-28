/* 用量頁（ticket 29）：訂閱額度、各引擎的 token、API key 花費，依工作和來源分開看，最近 14 天，額度保護的事件。
   畫面照核准的 Mockup A（docs/mockups/v1-a/usage.html）。資料來自 GET /api/usage（用量報表）、GET /api/ai/guard（額度保護狀態、
   保護線和 API 月上限）、GET /api/ai/guard/events（事件）；三個都是唯讀。後兩個失敗時只少那一塊，用量報表失敗才算整頁失敗。
   伺服器回來的文字（事件說明、模型名稱、來源）一律過 PR.esc；錯誤只顯示固定文案，不顯示伺服器或例外的原文。
   每個清單都有上限：事件最多畫 MAX_EVENTS 筆，等伺服器最多 TIMEOUT_MS。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  const TIMEOUT_MS = 15000;  // 等伺服器最多這麼久，超過就當失敗、可以重試
  const MAX_EVENTS = 20;     // 事件清單最多畫幾筆（伺服器最多回 200 筆）
  const DAYS = 14;
  const PERIODS = ["month", "day"];
  const SUBSCRIPTION = ["claude", "codex", "antigravity"];
  const LABEL_DAYS = [0, 3, 6, 9, 13];  // 每日長條圖底下標日期的位置
  const WINDOW_SEC = { five_hour: 5 * 3600, seven_day: 7 * 86400 };  // 額度視窗多長：記下之後過了這麼久，數字一定已經重置
  const esc = (s) => PR.esc(s);

  /* 畫面文字集中在這裡（i18n_check 看得到 PR.t，看不到 template 裡的中文） */
  const T = () => ({
    month: PR.t("每月"), day: PR.t("每天"), periodLabel: PR.t("統計區間"), refresh: PR.t("重新整理"),
    thisMonth: PR.t("本月"), today: PR.t("今天"),
    updatedAt: (time) => PR.t("更新於 {time}", { time }),
    back: PR.t("← AI 模型設定"),
    subscription: PR.t("訂閱"), local: PR.t("本機"),
    // 額度保護
    guardTitle: PR.t("額度保護中："),
    guardQuota: (pct, limit) => PR.t("Claude Code 5 小時額度到 {pct}，超過你設的 {limit}%。背景的分類和匯入後的自動翻譯暫停，你手動按的照跑。", { pct, limit }),
    guardQuotaUntil: (time) => PR.t("{time} 額度重置後自動接著跑。", { time }),
    guardApiCap: PR.t("API 這個月的花費到了上限，匯入後的自動翻譯和背景的起草先停下。"),
    guardNoApi: PR.t("背景工作預設不用訂閱，也還沒有 API key 或本機模型，新資料先排在待分類。"),
    guardPaused: PR.t("背景工作暫停。"),
    changeSettings: PR.t("改設定"),
    // 空狀態
    emptyTitle: PR.t("還沒有任何 AI 呼叫"),
    emptyBody: PR.t("第一次分類、翻譯或問 AI 之後，這裡會開始記錄。"),
    emptyBody2: PR.t("每一次呼叫都會記下日期、來源、工作、引擎、模型和 token。"),
    // 錯誤
    loadFailed: PR.t("讀不到用量"), retry: PR.t("重試"),
    failedBody: PR.t("本機服務暫時沒有回應。資料沒有遺失。"), timeoutBody: PR.t("等太久了，請稍後再試。"),
    // 卡片
    claudeTitle: "Claude Code", codexTitle: "Codex CLI", antigravityTitle: "Antigravity CLI",
    apiTitle: PR.t("API key 花費"),
    fiveHour: PR.t("5 小時額度"), sevenDay: PR.t("7 天額度"),
    resetsAt: (time) => PR.t("{time} 重置", { time }),
    resetDone: PR.t("已過重置時間，下次呼叫後更新"),
    guardLine: (pct) => PR.t("直線 = 你設的保護線 {pct}%", { pct }),
    noQuota: PR.t("還沒有收到額度數字。Claude Code 有回應之後才會出現。"),
    wholeAccount: PR.t("這是整個帳號的用量，包含你自己用 Claude Code 寫程式。數字在呼叫時更新，沒有呼叫就不會變。"),
    quotaAt: (time) => PR.t("上次更新：{time}", { time }),
    window: (calls, tokens) => PR.t("NewsRead 這 5 小時：{calls} 次 · {tokens} token", { calls, tokens }),
    windowNote: PR.t("（看不到占額度幾 %，只能看 token）"),
    cliUsage: (when, calls, tokens) => PR.t("{when} {calls} 次 · {tokens} token", { when, calls, tokens }),
    cliNote: PR.t("只回報 token 數，看不到額度用了多少。被限流時會顯示在下面的事件裡。"),
    apiSpent: (spent, cap) => `${spent} / ${cap}`,
    apiSpentOnly: (spent) => spent,
    apiWarnLine: PR.t("直線 = 80% 時通知"),
    apiNoCap: PR.t("月上限設成 0：背景不用 API。"),
    apiNone: PR.t("這段期間沒有 API 花費。"),
    apiNote: PR.t("依供應商回傳的用量和價目表計算；訂閱不折算成金額。"),
    openai: PR.t("OpenAI 相容"), ollama: PR.t("本機模型（Ollama）"), other: PR.t("其他"),
    // 區塊
    daysTitle: PR.t("最近 14 天"), daysNote: PR.t("每天的 token 數（訂閱和 API 合計）。"),
    daysLabel: (list) => PR.t("每日 token 長條圖：{list}", { list }),
    todayLabel: PR.t("今天"),
    tasksTitle: (when) => PR.t("哪個工作用最多（{when}）", { when }),
    sourcesTitle: (when) => PR.t("哪個來源用最多（{when}）", { when }),
    sourcesNote: PR.t("來源是呼叫 AI 的功能入口。要依個別媒體分開看，得等資料來源接上、帳本記下每次呼叫用的是哪一則資料之後才做得到；掛到論點的比例目前只有分類算得出來。"),
    colTask: PR.t("工作"), colEngine: PR.t("引擎 · 模型"), colCalls: PR.t("次數"), colCost: PR.t("花費"),
    colSource: PR.t("來源"), colItems: PR.t("資料"), colLinked: PR.t("掛到論點的"),
    noRows: PR.t("這段期間還沒有。"),
    updated: PR.t("用量已更新"), eventsFailed: PR.t("事件暫時讀不到。"),
    truncated: (n) => PR.t("只列用最多的前 {n} 列。", { n }),
    eventsTitle: PR.t("事件"), noEvents: PR.t("還沒有額度保護、限流或上限的事件。"),
    eventsNote: PR.t("只記錯誤代碼和固定說明，不記上游回傳的原文。"),
    eventsShown: (n) => PR.t("只顯示最近 {n} 筆。", { n }),
    tasks: { triage: PR.t("分類"), translate: PR.t("翻譯"), draft: PR.t("題材頁 / 概念卡起草"), thesis_change: PR.t("論點變化偵測"), ask: PR.t("問 AI") },
    sources: { triage: PR.t("AI 分類"), newsread: PR.t("閱讀器（翻譯、問 AI）") },
  });

  /* ---------- 純函式（測試直接呼叫） ---------- */
  function fmtTokens(n) {
    n = Number(n) || 0;
    if (n < 1000) return n.toLocaleString("en-US");
    const unit = n >= 1e9 ? [1e9, "B"] : n >= 1e6 ? [1e6, "M"] : [1e3, "K"];
    return (n / unit[0]).toFixed(1).replace(/\.0$/, "") + unit[1];
  }

  function money(n) {
    n = Number(n) || 0;
    if (n > 0 && n < 0.01) return "<$0.01";
    return "$" + n.toFixed(2);
  }

  const pctOf = (x) => Math.round((Number(x) || 0) * 100);
  const clampPct = (x) => Math.max(0, Math.min(100, pctOf(x)));
  const two = (n) => String(n).padStart(2, "0");

  /* 秒（Unix）→ 本機時間。同一天只顯示時間，不同天加月 / 日 */
  function clock(sec, nowSec) {
    if (typeof sec !== "number" || !isFinite(sec)) return "";
    const d = new Date(sec * 1000), n = new Date((nowSec || Date.now() / 1000) * 1000);
    const hm = `${two(d.getHours())}:${two(d.getMinutes())}`;
    const same = d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
    return same ? hm : `${two(d.getMonth() + 1)}/${two(d.getDate())} ${hm}`;
  }

  function isoClock(iso, nowSec) {
    const ms = Date.parse(iso);
    return Number.isFinite(ms) ? clock(ms / 1000, nowSec) : "";
  }

  const periodWord = (period, tx) => (period === "day" ? tx.today : tx.thisMonth);

  /* 這個額度數字什麼時候失效（Unix 秒）：重置時間和「記下時間 + 視窗長度」取早的；都沒有就是 null */
  function quotaUntil(win, at, key) {
    const ends = [];
    if (typeof win.resets_at === "number" && isFinite(win.resets_at)) ends.push(win.resets_at);
    if (typeof at === "number" && isFinite(at) && WINDOW_SEC[key]) ends.push(at + WINDOW_SEC[key]);
    return ends.length ? Math.min(...ends) : null;
  }

  function engineName(engine, tx) {
    return { claude: tx.claudeTitle, codex: tx.codexTitle, antigravity: tx.antigravityTitle, anthropic: "Anthropic API",
             openai: tx.openai, ollama: tx.ollama }[engine] || tx.other;
  }

  function costText(row, tx) {
    if (typeof row.cost_usd === "number") return money(row.cost_usd);
    if (SUBSCRIPTION.includes(row.engine)) return tx.subscription;
    return row.engine === "ollama" ? tx.local : "—";
  }

  function ratioText(items, linked) {
    return items > 0 && typeof linked === "number" ? Math.round((linked / items) * 100) + "%" : "—";
  }

  /* ---------- 區塊 ---------- */
  function meterHtml(label, used, note, opts) {
    opts = opts || {};
    const w = clampPct(used);
    const mark = opts.mark == null ? "" : `<b style="left:${clampPct(opts.mark / 100)}%" aria-hidden="true"></b>`;
    return `<div class="meter${opts.stale ? " stale" : ""}"><div class="top"><span>${esc(label)}</span><b${opts.hot ? ' style="color:var(--danger)"' : ""}>${esc(opts.text || pctOf(used) + "%")}</b></div>`
      + `<div class="bar" role="meter" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${w}">`
      + `<i${opts.hot ? ' class="hot"' : ""} style="width:${w}%"></i>${mark}</div><small>${esc(note)}</small></div>`;
  }

  function claudeCardHtml(D, G, tx) {
    const c = D.claude || {}, limits = c.limits || {};
    const threshold = G && G.settings && Number.isFinite(G.settings.threshold) ? G.settings.threshold : null;
    let h = `<section class="card qc"><h2>${esc(tx.claudeTitle)} <span class="chip ok">${esc(tx.subscription)}</span></h2>`;
    const rows = [["five_hour", tx.fiveHour, threshold], ["seven_day", tx.sevenDay, null]].filter(([k]) => limits[k] && typeof limits[k].used === "number");
    if (!rows.length) {
      h += `<p class="muted small">${esc(tx.noQuota)}</p>`;
    } else {
      for (const [key, label, line] of rows) {
        const w = limits[key];
        const until = quotaUntil(w, c.at, key);
        const done = until != null && until <= D.now;
        const note = (done ? tx.resetDone : (typeof w.resets_at === "number" ? tx.resetsAt(clock(w.resets_at, D.now)) : ""))
          + (line != null && !done ? " · " + tx.guardLine(line) : "");
        h += meterHtml(label, w.used, note, { stale: done, hot: line != null && !done && pctOf(w.used) >= line, mark: line != null && !done ? line : null });
      }
      h += `<p class="muted small">${esc(tx.wholeAccount)}`
        + (typeof c.at === "number" ? " " + esc(tx.quotaAt(clock(c.at, D.now))) : "") + `</p>`;
    }
    const w = c.window || { calls: 0, tokens: 0 };
    h += `<p class="small"><b>${esc(tx.window(w.calls.toLocaleString("en-US"), fmtTokens(w.tokens)))}</b> <span class="muted">${esc(tx.windowNote)}</span></p>`;
    return h + `</section>`;
  }

  function cliCardHtml(D, engine, title, tx) {
    const u = (D.cli && D.cli[engine]) || { calls: 0, tokens: 0 };
    return `<section class="card qc"><h2>${esc(title)} <span class="chip ok">${esc(tx.subscription)}</span></h2>`
      + `<p>${esc(tx.cliUsage(periodWord(D.period, tx), u.calls.toLocaleString("en-US"), fmtTokens(u.tokens)))}</p>`
      + `<p class="muted small">${esc(tx.cliNote)}</p></section>`;
  }

  function apiCardHtml(D, G, tx) {
    const api = D.api || {}, spent = Number(api.spent_usd) || 0;
    const cap = G && G.api && typeof G.api.cap_usd === "number" ? G.api.cap_usd : null;
    let h = `<section class="card qc"><h2>${esc(tx.apiTitle)} <span class="chip">${esc(tx.thisMonth)}</span></h2>`;
    if (cap) {
      h += meterHtml(tx.apiSpent(money(spent), money(cap)), spent / cap, tx.apiWarnLine, { text: pctOf(spent / cap) + "%", hot: spent >= cap, mark: 80 });
    } else {
      h += `<p>${esc(tx.apiSpentOnly(money(spent)))}</p>` + (cap === 0 ? `<p class="muted small">${esc(tx.apiNoCap)}</p>` : "");
    }
    const by = Array.isArray(api.by_engine) ? api.by_engine : [];
    h += `<p class="muted small" data-no-i18n>${by.length ? esc(by.map((e) => `${engineName(e.engine, tx)} ${money(e.spent_usd)}`).join(" · ")) : esc(tx.apiNone)}</p>`;
    return h + `<p class="muted small">${esc(tx.apiNote)}</p></section>`;
  }

  function daysHtml(D, tx) {
    const days = Array.isArray(D.daily) ? D.daily.slice(-DAYS) : [];
    const max = Math.max(0, ...days.map((d) => Number(d.tokens) || 0));
    const mdLabel = (date) => date.slice(5).replace(/^0/, "").replace("-0", "-").replace("-", "/");
    const bars = days.map((d) => {
      const n = Number(d.tokens) || 0;
      return `<span${n ? "" : ' class="zero"'} style="height:${max && n ? Math.max(2, Math.round((n / max) * 100)) : 0}%" title="${esc(`${d.date} · ${fmtTokens(n)}`)}"></span>`;
    }).join("");
    const labels = days.map((d, i) => `<span>${LABEL_DAYS.includes(i) ? esc(i === days.length - 1 ? tx.todayLabel : mdLabel(String(d.date))) : ""}</span>`).join("");
    const summary = tx.daysLabel(days.map((d) => `${mdLabel(String(d.date))} ${fmtTokens(d.tokens)}`).join(PR.lang === "en" ? ", " : "、"));  // i18n-ok：列表分隔符號
    return `<section class="card sec"><h2>${esc(tx.daysTitle)}</h2><p class="muted">${esc(tx.daysNote)}</p>`
      + `<div class="days" role="img" aria-label="${esc(summary)}">${bars}</div><div class="dlab" aria-hidden="true">${labels}</div></section>`;
  }

  function tableHtml(title, note, head, rows, empty, truncated, tx) {
    return `<section class="card sec"><h2>${esc(title)}</h2>` + (note ? `<p class="muted">${esc(note)}</p>` : "")
      + (rows.length
        ? `<div class="scroll-x"><table class="tbl"><thead><tr>${head.map(([label, right]) => `<th${right ? ' class="r"' : ""}>${esc(label)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
        : `<p class="muted">${esc(empty)}</p>`)
      + (truncated ? `<p class="muted small">${esc(tx.truncated(rows.length))}</p>` : "") + `</section>`;
  }

  function tasksHtml(D, tx) {
    const rows = (D.tasks || []).map((r) => {
      const label = tx.tasks[r.task] || r.task;
      const engine = engineName(r.engine, tx) + (r.model ? " · " + r.model : "");
      return `<tr><td data-no-i18n>${esc(label)}</td><td data-no-i18n>${esc(engine)}</td><td class="r num">${esc((r.calls || 0).toLocaleString("en-US"))}</td>`
        + `<td class="r num">${esc(fmtTokens(r.tokens))}</td><td class="r${typeof r.cost_usd === "number" ? " num" : " muted"}" data-no-i18n>${esc(costText(r, tx))}</td></tr>`;
    });
    return tableHtml(tx.tasksTitle(periodWord(D.period, tx)), "", [[tx.colTask], [tx.colEngine], [tx.colCalls, 1], ["token", 1], [tx.colCost, 1]],
      rows, tx.noRows, !!D.tasks_truncated, tx);
  }

  function sourcesHtml(D, tx) {
    const rows = (D.sources || []).map((r) => {
      const label = tx.sources[r.source] || r.source;
      return `<tr><td data-no-i18n>${esc(label)}</td><td class="r num">${esc((r.calls || 0).toLocaleString("en-US"))}</td>`
        + `<td class="r num">${r.items == null ? "—" : esc(r.items.toLocaleString("en-US"))}</td><td class="r num">${esc(fmtTokens(r.tokens))}</td>`
        + `<td class="r num">${esc(ratioText(r.items, r.linked))}</td></tr>`;
    });
    return tableHtml(tx.sourcesTitle(periodWord(D.period, tx)), tx.sourcesNote,
      [[tx.colSource], [tx.colCalls, 1], [tx.colItems, 1], ["token", 1], [tx.colLinked, 1]], rows, tx.noRows, !!D.sources_truncated, tx);
  }

  function eventsHtml(E, nowSec, tx) {
    if (!Array.isArray(E)) {  // 事件清單讀不到：不能說成「還沒有事件」
      return `<section class="card sec"><h2>${esc(tx.eventsTitle)}</h2><p class="muted">${esc(tx.eventsFailed)}</p></section>`;
    }
    const list = E;
    const shown = list.slice(0, MAX_EVENTS);
    const items = shown.map((e) => {
      const d = e.data || {};
      const extra = typeof d.used === "number" ? ` · ${pctOf(d.used)}%`
        : (typeof d.spent_usd === "number" && typeof d.cap_usd === "number" ? ` · ${money(d.spent_usd)} / ${money(d.cap_usd)}` : "");
      return `<li data-no-i18n><span class="num">${esc(isoClock(e.at, nowSec))}</span> ${esc(e.message || "")}${esc(extra)}</li>`;
    }).join("");
    return `<section class="card sec"><h2>${esc(tx.eventsTitle)}</h2>`
      + (shown.length ? `<ul class="events">${items}</ul>` : `<p class="muted">${esc(tx.noEvents)}</p>`)
      + (list.length > MAX_EVENTS ? `<p class="muted small">${esc(tx.eventsShown(MAX_EVENTS))}</p>` : "")
      + `<p class="muted small">${esc(tx.eventsNote)}</p></section>`;
  }

  function guardBannerHtml(G, nowSec, tx) {
    const b = G && G.background;
    if (!b || !b.paused) return "";
    let body;
    if (b.reason === "quota") {
      const q = G.quota || {}, s = G.settings || {};
      body = tx.guardQuota(pctOf(q.used) + "%", s.threshold) + (typeof b.until === "number" ? " " + tx.guardQuotaUntil(clock(b.until, nowSec)) : "");
    } else {
      body = b.reason === "api_cap" ? tx.guardApiCap : b.reason === "no_api" ? tx.guardNoApi : tx.guardPaused;
    }
    return `<div class="banner warn" role="status"><span class="ico" aria-hidden="true">⏸</span><div><b>${esc(tx.guardTitle)}</b>${esc(body)} <a href="/settings#models">${esc(tx.changeSettings)}</a></div></div>`;
  }

  function controlsHtml(S, tx) {
    return `<span role="group" aria-label="${esc(tx.periodLabel)}" class="row">`
      + PERIODS.map((p) => `<button type="button" class="btn sm" data-period="${p}" aria-pressed="${S.period === p}">${esc(p === "day" ? tx.day : tx.month)}</button>`).join("")
      + `</span><button type="button" class="btn sm" data-act="refresh"${S.status === "loading" || S.busy ? ' aria-disabled="true"' : ""}>${esc(tx.refresh)}</button>`;
  }

  function viewHtml(S) {
    const tx = T();
    if (S.status === "loading") {
      return `<div style="display:grid;gap:10px" aria-busy="true"><div class="skel" style="width:40%"></div><div class="skel"></div><div class="skel" style="width:80%"></div></div>`;
    }
    if (S.status === "error") {
      return `<div class="empty"><h2>${esc(tx.loadFailed)}</h2><p>${esc(S.error === "timeout" ? tx.timeoutBody : tx.failedBody)} `
        + `<button type="button" class="btn sm" data-act="retry">${esc(tx.retry)}</button></p></div>`;
    }
    const D = S.data || {};
    const banner = guardBannerHtml(S.guard, D.now, tx);
    if (D.empty) {
      return banner + `<div class="empty"><h2>${esc(tx.emptyTitle)}</h2><p>${esc(tx.emptyBody)}<br>${esc(tx.emptyBody2)}</p></div>`;
    }
    const cli = ["codex", "antigravity"].filter((e) => e === "codex" || (D.cli && D.cli[e] && D.cli[e].calls > 0));
    return banner + `<div class="quota">${claudeCardHtml(D, S.guard, tx)}`
      + cli.map((e) => cliCardHtml(D, e, e === "codex" ? tx.codexTitle : tx.antigravityTitle, tx)).join("")
      + apiCardHtml(D, S.guard, tx) + `</div>`
      + daysHtml(D, tx) + tasksHtml(D, tx) + sourcesHtml(D, tx) + eventsHtml(S.events, D.now, tx);
  }

  /* ---------- 頁面 ---------- */
  const S = { status: "loading", period: "month", data: null, guard: null, events: null, error: null, busy: false, said: "" };
  let seq = 0;
  let current = null;  // 進行中的請求：新的一次開始時取消舊的

  function errorKind(error, timedOut) {
    return timedOut || (error && error.name === "AbortError") ? "timeout" : "failed";
  }

  function render(focus) {
    const view = PR.$("#view");
    if (!view) return;
    const tx = T();
    view.innerHTML = viewHtml(S);
    view.setAttribute("aria-busy", S.status === "loading" || S.busy ? "true" : "false");
    const controls = PR.$("#controls");
    if (controls) controls.innerHTML = controlsHtml(S, tx);
    const stamp = PR.$("#stamp");
    if (stamp) stamp.innerHTML = S.status === "ready" && S.data
      ? `${esc(tx.updatedAt(clock(S.data.now, S.data.now)))} · <a href="/settings#models">${esc(tx.back)}</a>` : `<a href="/settings#models">${esc(tx.back)}</a>`;
    const live = PR.$("#usageStatus");
    if (live) live.textContent = S.status === "error" ? tx.loadFailed : S.said;
    if (!focus) return;
    for (const sel of [].concat(focus)) {
      const el = document.querySelector(sel);
      if (el && !el.disabled) { el.focus(); return; }
    }
  }

  async function load(quiet, focus) {
    const mine = ++seq;
    if (current) current.abort();  // 舊的那次結果用不到了
    if (!quiet || !S.data) S.status = "loading";
    S.busy = true;
    S.said = "";
    render(focus);
    const ctrl = new AbortController();
    current = ctrl;
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, PR.usagePage.timeoutMs);
    const get = (path) => PR.api(path, { signal: ctrl.signal });
    try {
      const [data, guard, events] = await Promise.all([
        get("/api/usage?period=" + encodeURIComponent(S.period)),
        get("/api/ai/guard").catch(() => null),         // 少了保護線和月上限，其他照常顯示
        get("/api/ai/guard/events").catch(() => null),  // 少了事件清單
      ]);
      if (mine !== seq) return;  // 後面又發了一次，這次的結果過期了
      if (ctrl.signal.aborted || !data || typeof data !== "object" || !("empty" in data)) throw new Error("bad");  // 讀 body 時才逾時，或回傳的不是用量報表
      // 事件讀不到時留 null，畫面顯示「讀不到」，不說成沒有事件
      Object.assign(S, { data, guard, events: events && Array.isArray(events.events) ? events.events : null, status: "ready", error: null });
      if (quiet) S.said = T().updated;
    } catch (e) {
      if (mine !== seq) return;
      S.status = "error";
      S.error = errorKind(e, timedOut);
    } finally {
      clearTimeout(timer);
      if (current === ctrl) current = null;
    }
    if (mine !== seq) return;
    S.busy = false;
    render(focus);
  }

  function onClick(ev) {
    const t = ev.target.closest ? ev.target.closest("[data-period], [data-act]") : null;
    if (!t) return;
    if (t.dataset.period) {
      if (!PERIODS.includes(t.dataset.period) || t.dataset.period === S.period) return;
      S.period = t.dataset.period;
      return load(true, `#controls [data-period="${S.period}"]`);
    }
    if (t.dataset.act === "retry") return load(false, ["[data-act=retry]", "#controls [data-period]"]);
    if (t.dataset.act === "refresh") {
      if (S.busy) return;  // 正在讀：按鈕標了 aria-disabled，不重複發
      return load(true, "#controls [data-act=refresh]");
    }
  }

  PR.usagePage = { tx: T, fmtTokens, money, clock, ratioText, costText, claudeCardHtml, cliCardHtml, apiCardHtml, daysHtml, tasksHtml, sourcesHtml,
                   eventsHtml, guardBannerHtml, controlsHtml, viewHtml, errorKind, quotaUntil, load, onClick, state: S, timeoutMs: TIMEOUT_MS,
                   MAX_EVENTS, DAYS };

  document.addEventListener("DOMContentLoaded", () => {
    const view = PR.$("#view"), controls = PR.$("#controls");
    if (!view) return;
    view.addEventListener("click", onClick);
    if (controls) controls.addEventListener("click", onClick);
    load();
  });
})(window.PR);
