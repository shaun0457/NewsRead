/* 額度保護（ticket 68）和用量頁入口（ticket 29）：每一頁右上角顯示 Claude 5 小時額度（「Claude 5h 42%」），
   背景工作暫停時改顯示「背景工作暫停 · …」；兩種都點了到用量頁（/usage）。額度還沒有數字、或已經過了重置時間就不顯示。
   GET /api/ai/guard 每 POLL_MS 問一次；頁面看不到時不問，回到頁面馬上問一次；失敗時間隔加倍，最多 MAX_BACKOFF_MS；
   離開頁面（pagehide）就停。同一時間只有一個請求。
   每個手動 AI 入口（問 AI、筆記幫手、智慧標註、心智圖、重譯這段、按了才開始的翻譯和整理）送出前呼叫 PR.quotaGuard.remind()：額度超過門檻、或 API 到上限時提醒（同一段只提醒一次），照樣送出。 */
(function (PR) {
  "use strict";

  const POLL_MS = 60000;
  const MAX_BACKOFF_MS = 600000;
  let status = null;
  let timer = 0;
  let delay = POLL_MS;
  let busy = false;
  let stopped = false;
  let el = null;
  let reminded = "";

  const pct = (v) => Math.round((Number(v) || 0) * 100) + "%";

  /* 額度數字還能用：有數字、重置時間還沒到（過了就當作已經重置，下一次呼叫才有新數字） */
  function quotaLive(s) {
    const q = (s && s.quota) || {};
    if (typeof q.used !== "number" || !isFinite(q.used)) return false;
    // 跟後端 quota_guard.quota_state 一樣：沒有記下時間就判斷不了多舊，不顯示；重置時間和記下時間 + 5 小時取早的
    if (typeof q.at !== "number" || !isFinite(q.at)) return false;
    const ends = [q.at + 5 * 3600];
    if (typeof q.resets_at === "number" && isFinite(q.resets_at)) ends.push(q.resets_at);
    return Math.min(...ends) * 1000 > Date.now();
  }

  function text(s) {
    const b = (s && s.background) || {};
    if (!b.paused) return quotaLive(s) ? PR.t("Claude 5h {pct}", { pct: pct(s.quota.used) }) : "";
    if (b.reason === "quota") return PR.t("背景工作暫停 · Claude 5h {pct}", { pct: pct(s.quota && s.quota.used) });
    if (b.reason === "api_cap") return PR.t("背景工作暫停 · API 到上限");
    if (b.reason === "no_api") return PR.t("背景工作暫停 · 沒有 API key");
    return PR.t("背景工作暫停");
  }

  function why(s) {
    const r = ((s && s.background) || {}).reason;
    if (r === "quota") return PR.t("Claude Code 5 小時額度超過你設的門檻，背景的分類和匯入後的自動翻譯先等額度重置。你手動按的照跑。");
    if (r === "api_cap") return PR.t("API 這個月的花費到了上限，匯入後的自動翻譯和背景的起草先停下。");
    if (r === "no_api") return PR.t("背景工作預設不用訂閱，也還沒有 API key 或本機模型，新資料先排在待分類。");
    return PR.t("Claude Code 5 小時額度（整個帳號的用量）。點開看用量。");
  }

  function render() {
    const label = text(status);
    if (!label) { if (el) el.hidden = true; return; }
    if (!el) {
      const bar = document.querySelector("header.topbar, header.appbar");
      if (!bar) return;
      el = document.createElement("a");
      el.className = "quota-paused";
      el.href = "/usage";
      const slot = bar.querySelector("#themeSlot");
      if (slot) bar.insertBefore(el, slot); else bar.appendChild(el);
    }
    el.textContent = label;
    el.className = "quota-paused" + ((status.background || {}).paused ? "" : " calm");  // calm：額度正常，不用紅字
    el.title = why(status);
    el.hidden = false;
  }

  function schedule() {
    if (stopped || timer || document.hidden) return;
    timer = setTimeout(poll, delay);
  }

  async function poll() {
    clearTimeout(timer);
    timer = 0;
    if (stopped || busy || document.hidden) return;
    busy = true;
    try {
      status = await PR.api("/api/ai/guard");
      delay = POLL_MS;
      render();
    } catch (_) {
      delay = Math.min(delay * 2, MAX_BACKOFF_MS);  // 服務在重開或關了：慢慢再問，不洗版
    } finally {
      busy = false;
    }
    schedule();
  }

  function stop() {
    stopped = true;
    clearTimeout(timer);
    timer = 0;
  }

  /* 這次手動按的 AI 用哪一種引擎（後端 status.engines，見 ai_engines.Engines.manual_kinds；#97）：
     claude（Claude Code 訂閱）/ subscription（Codex、Antigravity）/ api / local / none；不知道是 undefined。
     use：不帶 = 翻譯、重譯（閱讀器的翻譯引擎）；{ model: id } = 問 AI 名單的模型（空的 = 名單的預設）；字串 = 直接給種類。 */
  function kindOf(use) {
    if (typeof use === "string") return use;
    const e = (status && status.engines) || {};
    if (use && typeof use === "object") return (e.chat || {})[use.model] || e.chat_default;
    return e.translate;
  }

  /* 手動按 AI 之前：這次用的引擎碰到的限制提醒一次（不擋），同時碰到的一起說。回傳有沒有提醒。
     Claude Code 訂閱只看 5 小時額度、API 只看每月上限，本機模型和看不到額度的訂閱不提醒；不知道種類時兩個都看。 */
  function remind(use) {
    const kind = kindOf(use);
    const q = (status && status.quota) || {};
    const a = (status && status.api) || {};
    const quota = q.over && (kind === "claude" || kind === undefined);
    const cap = a.reached && (kind === "api" || kind === undefined);
    if (!quota && !cap) return false;
    const key = (quota ? "q" + q.until : "") + "|" + (cap ? "a" + a.month : "");
    if (key === reminded) return false;
    reminded = key;
    const vars = { pct: pct(q.used), limit: (status.settings || {}).threshold };
    PR.toast(PR.esc(quota && cap ? PR.t("提醒：Claude Code 5 小時額度已用 {pct}，超過你設的 {limit}%；API 這個月的花費也到上限了。這次照樣送出。", vars)
      : quota ? PR.t("提醒：Claude Code 5 小時額度已用 {pct}，超過你設的 {limit}%。這次照樣送出。", vars)
        : PR.t("提醒：API 這個月的花費到上限了。這次照樣送出。")));
    return true;
  }

  /* 匯入後的自動翻譯在等（job.state === "waiting"，原因在 job.wait.reason；ticket 68）：清單和閱讀器的短標籤、詳情的說明 */
  function clock(sec) {
    if (typeof sec !== "number" || !isFinite(sec)) return "";
    const d = new Date(sec * 1000);
    return isNaN(d.getTime()) ? "" : String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  function waitLabel(job) {
    const r = ((job && job.wait) || {}).reason;
    if (r === "subscription" || r === "api_off" || r === "auto_off") return PR.t("等你按翻譯");
    if (r === "api_cap") return PR.t("API 到上限");
    if (r === "check") return PR.t("稍後自動翻譯");
    return PR.t("等額度重置");
  }

  function waitText(job) {
    const w = (job && job.wait) || {};
    const what = job && job.read ? PR.t("整理") : PR.t("翻譯");
    if (w.reason === "subscription") return PR.t("用 Claude Code、Codex 訂閱時，匯入後不會自動{what}，要你按了才開始。", { what });
    if (w.reason === "api_off") return PR.t("API 每月上限設成 0（背景不用 API），匯入後不會自動{what}，要你按了才開始。", { what });
    if (w.reason === "auto_off") return PR.t("你關掉了「匯入後自動翻譯」，這篇不會自動{what}，要你按了才開始。", { what });
    if (w.reason === "check") return PR.t("匯入後的自動{what}在等額度保護確認，幾分鐘內自動接著做。", { what });
    if (w.reason === "api_cap") return PR.t("API 這個月的花費到了上限，匯入後的自動{what}先等，下個月或調高上限後自動接著做。", { what });
    const time = clock(w.until);
    return time ? PR.t("Claude Code 5 小時額度超過你設的門檻，匯入後的自動{what}先等，{time} 額度重置後自動接著做。", { what, time })
      : PR.t("Claude Code 5 小時額度超過你設的門檻，匯入後的自動{what}先等，額度重置後自動接著做。", { what });
  }

  function waitCanWait(job) {  // 會自己接著做的（等額度），另外提示可以現在開始
    const r = ((job && job.wait) || {}).reason;
    return r !== "subscription" && r !== "api_off" && r !== "auto_off";
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { clearTimeout(timer); timer = 0; } else poll();
  });
  window.addEventListener("pagehide", stop);
  window.addEventListener("pageshow", (e) => { if (e.persisted) { stopped = false; poll(); } });  // 從上一頁快取回來

  PR.quotaGuard = { poll, stop, remind, kindOf, waitLabel, waitText, waitCanWait, get status() { return status; },
    _state: () => ({ timer, delay, busy, stopped }) };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", poll);
  else poll();
})(window.PR);
