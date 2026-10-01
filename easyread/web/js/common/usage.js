/* 翻译和问 AI 的用量（job.json 的 usage / usage_total，对话里每条回答的 usage）。
   样子学 Claude 桌面端：订阅额度用进度条 + 什么时候重置；token 数做成小号的明细。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  function tokens(n) {
    n = Number(n) || 0;
    if (n < 10000) return n.toLocaleString();
    return (n / 10000).toFixed(n < 1e6 ? 1 : 0).replace(/\.0$/, "") + " 万";
  }
  PR.fmtTokens = tokens;

  const WINDOWS = [["five_hour", "5 小时额度"], ["seven_day", "本周额度"]];
  const pct = (x) => Math.round(x * 100) + "%";
  const level = (x) => (x >= 0.95 ? "full" : x >= 0.8 ? "high" : "");

  function resetText(ts) {
    if (!ts) return "";
    const ms = ts * 1000 - Date.now();
    if (ms <= 0) return "已重置";
    const h = Math.floor(ms / 3.6e6), m = Math.round((ms % 3.6e6) / 6e4);
    if (h < 24) return (h ? h + " 小时 " : "") + m + " 分钟后重置";
    const d = new Date(ts * 1000);
    return (d.getMonth() + 1) + " 月 " + d.getDate() + " 日 周" + "日一二三四五六"[d.getDay()] + " " +
      String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0") + " 重置";
  }

  /* 额度进度条（Claude 订阅才有）。额度是整个账号共用的，同时用 Claude Code 干别的也算在里面，
     所以不拿前后相减去算翻译用了多少，翻译本身的量看 token 数 */
  PR.usageBars = function (limits, when) {
    const rows = WINDOWS.filter(([k]) => limits && limits[k] && limits[k].used != null).map(([k, name]) => {
      const w = limits[k];
      if (w.resets_at && w.resets_at * 1000 <= Date.now()) {  // 记下的是重置前的数，已经不准了
        return '<div class="us-limit stale"><div class="us-row"><span>' + name + "</span><b>—</b></div>" +
          '<div class="us-bar"><i style="width:0"></i></div><div class="us-reset">已重置（当时用到 ' + pct(w.used) + "）</div></div>";
      }
      return '<div class="us-limit ' + level(w.used) + '"><div class="us-row"><span>' + name + "</span><b>" + pct(w.used) + "</b></div>" +
        '<div class="us-bar"><i style="width:' + Math.min(100, w.used * 100) + '%"></i></div>' +
        '<div class="us-reset">' + resetText(w.resets_at) + "</div></div>";
    });
    return rows.length ? '<div class="us-limits">' + rows.join("") + '<div class="us-note">Claude 订阅额度（' + when + "），整个账号共用</div></div>" : "";
  };

  /* token 明细：右边大数字，下面一行小字 */
  PR.usageTokens = function (label, u) {
    if (!u || !u.calls) return "";
    return '<div class="us-tokens"><div class="us-row"><span>' + label + "</span><b>" + tokens(u.input + u.output) + " token</b></div>" +
      '<div class="us-split">输入 ' + tokens(u.input) + (u.cached ? "（缓存命中 " + tokens(u.cached) + "）" : "") + " · 输出 " + tokens(u.output) +
      (u.cost_usd != null && !u.limits ? " · 按官方价约 $" + u.cost_usd.toFixed(2) : "") + "</div></div>";
  };

  /* 翻译进度旁边的一句话：“已用 12.3 万 token · 5 小时额度用到 24%” */
  PR.usageShort = function (u) {
    if (!u || !u.calls) return "";
    const five = u.limits && u.limits.five_hour;
    return "已用 " + tokens(u.input + u.output) + " token" + (five && five.used != null ? " · 5 小时额度用到 " + pct(five.used) : "");
  };

  /* 论文详情里的用量卡片：上次翻译、这篇累计、额度 */
  PR.usageCard = function (u, total) {
    if (!u || !u.calls) return "";
    return '<div class="us-card">' + PR.usageTokens("上次翻译", u) +
      (total && total.calls > u.calls ? PR.usageTokens("这篇累计", total) : "") + PR.usageBars(u.limits, "译完时") + "</div>";
  };

  /* 问 AI：整个对话的合计，额度取最近一条回答时的 */
  function threadSum(msgs) {
    const used = (msgs || []).map((m) => m.usage).filter((u) => u && u.calls);
    if (!used.length) return null;
    const sum = { calls: 0, input: 0, cached: 0, output: 0 };
    used.forEach((u) => { sum.calls += u.calls; sum.input += u.input; sum.cached += u.cached; sum.output += u.output; });
    sum.limits = used[used.length - 1].limits;
    return sum;
  }

  /* 对话输入框底部的小圆环：有订阅额度时画 5 小时额度，没有时只写这个对话的 token 数 */
  PR.usageChip = function (msgs) {
    const sum = threadSum(msgs);
    if (!sum) return "";
    const five = sum.limits && sum.limits.five_hour;
    if (five && five.used != null) {
      const r = 6, c = 2 * Math.PI * r, v = Math.min(1, five.used);
      return '<button class="us-chip ' + level(v) + '" data-c="usage" title="用量">' +
        '<svg viewBox="0 0 16 16" width="16" height="16"><circle cx="8" cy="8" r="' + r + '" class="track"/>' +
        '<circle cx="8" cy="8" r="' + r + '" class="fill" stroke-dasharray="' + (c * v).toFixed(2) + " " + c.toFixed(2) + '" transform="rotate(-90 8 8)"/></svg>' +
        "<span>" + pct(v) + "</span></button>";
    }
    return '<button class="us-chip" data-c="usage" title="用量"><span>' + tokens(sum.input + sum.output) + " token</span></button>";
  };

  /* 点圆环弹出的用量面板 */
  PR.usagePop = function (msgs) {
    const sum = threadSum(msgs);
    if (!sum) return "";
    const last = (msgs || []).map((m) => m.usage).filter((u) => u && u.calls).pop();
    return '<div class="us-pop"><div class="us-title">用量</div>' + PR.usageBars(sum.limits, "最近一次回答时") +
      PR.usageTokens("这个对话", sum) + (sum.calls > 1 ? PR.usageTokens("上一条回答", last) : "") + "</div>";
  };
})(window.PR);
