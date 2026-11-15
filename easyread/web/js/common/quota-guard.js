/* 額度保護（ticket 68）：背景工作暫停時，每一頁右上角顯示「背景工作暫停」，點了到設定頁的 AI 模型。
   GET /api/ai/guard 每 POLL_MS 問一次；頁面看不到時不問，回到頁面馬上問一次；失敗時間隔加倍，最多 MAX_BACKOFF_MS；
   離開頁面（pagehide）就停。同一時間只有一個請求。
   手動按的 AI（問 AI）送出前呼叫 PR.quotaGuard.remind()：額度超過門檻、或 API 到上限時提醒（同一段只提醒一次），照樣送出。 */
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

  function text(s) {
    const b = (s && s.background) || {};
    if (!b.paused) return "";
    if (b.reason === "quota") return PR.t("背景工作暫停 · Claude 5h {pct}", { pct: pct(s.quota && s.quota.used) });
    if (b.reason === "api_cap") return PR.t("背景工作暫停 · API 到上限");
    if (b.reason === "no_api") return PR.t("背景工作暫停 · 沒有 API key");
    return PR.t("背景工作暫停");
  }

  function why(s) {
    const r = ((s && s.background) || {}).reason;
    if (r === "quota") return PR.t("Claude Code 5 小時額度超過你設的門檻，背景的分類、翻譯先等額度重置。你手動按的照跑。");
    if (r === "api_cap") return PR.t("API 這個月的花費到了上限，背景的翻譯和起草先停下。");
    if (r === "no_api") return PR.t("背景工作預設不用訂閱，也還沒有 API key 或本機模型，新資料先排在待分類。");
    return "";
  }

  function render() {
    const label = text(status);
    if (!label) { if (el) el.hidden = true; return; }
    if (!el) {
      const bar = document.querySelector("header.topbar, header.appbar");
      if (!bar) return;
      el = document.createElement("a");
      el.className = "quota-paused";
      el.href = "/settings#models";
      const slot = bar.querySelector("#themeSlot");
      if (slot) bar.insertBefore(el, slot); else bar.appendChild(el);
    }
    el.textContent = label;
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

  /* 手動按 AI 之前：超過門檻就提醒一次（不擋）。回傳有沒有提醒。
     kind：這次用的引擎計費方式。subscription 只提醒訂閱額度，api 只提醒 API 上限；不知道（undefined）兩個都看。 */
  function remind(kind) {
    const q = (status && status.quota) || {};
    const a = (status && status.api) || {};
    let key = "", msg = "";
    if (q.over && kind !== "api") {
      key = "q" + q.until;
      msg = PR.t("提醒：Claude Code 5 小時額度已用 {pct}，超過你設的 {limit}%。這次照樣送出。",
        { pct: pct(q.used), limit: (status.settings || {}).threshold });
    } else if (a.reached && kind !== "subscription") {
      key = "a" + a.month;
      msg = PR.t("提醒：API 這個月的花費到上限了。這次照樣送出。");
    }
    if (!msg || key === reminded) return false;
    reminded = key;
    PR.toast(PR.esc(msg));
    return true;
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { clearTimeout(timer); timer = 0; } else poll();
  });
  window.addEventListener("pagehide", stop);
  window.addEventListener("pageshow", (e) => { if (e.persisted) { stopped = false; poll(); } });  // 從上一頁快取回來

  PR.quotaGuard = { poll, stop, remind, get status() { return status; }, _state: () => ({ timer, delay, busy, stopped }) };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", poll);
  else poll();
})(window.PR);
