/* 翻译和问 AI 的用量（job.json 的 usage / usage_total，对话里每条回答的 usage）。
   样子学 Claude 桌面端：订阅额度用进度条 + 什么时候重置；token 数做成小号的明细。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  function tokens(n) {
    n = Number(n) || 0;
    if (n < 10000) return n.toLocaleString();
    return (n / 10000).toFixed(n < 1e6 ? 1 : 0).replace(/\.0$/, "") + PR.t(" 万");
  }
  PR.fmtTokens = tokens;

  const WINDOWS = [["five_hour", PR.t("5 小时额度")], ["seven_day", PR.t("本周额度")]];
  const pct = (x) => Math.round(x * 100) + "%";
  const level = (x) => (x >= 0.95 ? "full" : x >= 0.8 ? "high" : "");

  function resetText(ts) {
    if (!ts) return "";
    const ms = ts * 1000 - Date.now();
    if (ms <= 0) return PR.t("已重置");
    const h = Math.floor(ms / 3.6e6), m = Math.round((ms % 3.6e6) / 6e4);
    if (h < 24) return h ? PR.t("{h} 小时 {m} 分钟后重置", { h, m }) : PR.t("{m} 分钟后重置", { m });
    const d = new Date(ts * 1000);
    const time = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    if (PR.lang === "en") return "Resets " + ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()] + ", " + ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()] + " " + d.getDate() + " " + time;
    return (d.getMonth() + 1) + " 月 " + d.getDate() + " 日 周" + "日一二三四五六"[d.getDay()] + " " + time + " 重置";  // i18n-ok
  }

  /* 额度进度条（Claude 订阅才有），排版学 Claude 桌面端：名字在左，“几小时后重置 + 百分比”在右，下面一根细条。
     额度是整个账号共用的，同时用 Claude Code 干别的也算在里面，所以不拿前后相减去算翻译用了多少 */
  PR.usageBars = function (limits, title) {
    const rows = WINDOWS.filter(([k]) => limits && limits[k] && limits[k].used != null).map(([k, name]) => {
      const w = limits[k];
      const stale = w.resets_at && w.resets_at * 1000 <= Date.now();  // 记下的是重置前的数，已经不准了
      return '<div class="us-limit ' + (stale ? "stale" : level(w.used)) + '"><div class="us-row"><span>' + name + "</span>" +
        "<em>" + (stale ? PR.t("已重置，当时 {pct}", { pct: pct(w.used) }) : resetText(w.resets_at) + "<b>" + pct(w.used) + "</b>") + "</em></div>" +
        '<div class="us-bar"><i style="width:' + (stale ? 0 : Math.min(100, w.used * 100)) + '%"></i></div></div>';
    });
    return rows.length ? '<div class="us-limits">' + (title ? '<div class="us-head">' + title + "</div>" : "") + rows.join("") + "</div>" : "";
  };

  function ago(at) {
    const m = Math.round((Date.now() / 1000 - at) / 60);
    return m < 1 ? PR.t("刚刚") : m < 60 ? PR.t("{n} 分钟前", { n: m }) : m < 1440 ? PR.t("{n} 小时前", { n: Math.round(m / 60) }) : PR.t("{n} 天前", { n: Math.round(m / 1440) });
  }

  /* token 明细：右边大数字，下面一行小字 */
  PR.usageTokens = function (label, u) {
    if (!u || !u.calls) return "";
    return '<div class="us-tokens"><div class="us-row"><span>' + label + "</span><b>" + tokens(u.input + u.output) + " token</b></div>" +
      '<div class="us-split">' + PR.t("输入 {n}", { n: tokens(u.input) }) + (u.cached ? PR.t("（缓存命中 {n}）", { n: tokens(u.cached) }) : "") + " · " + PR.t("输出 {n}", { n: tokens(u.output) }) +
      (u.cost_usd != null && !u.limits ? " · " + PR.t("按官方价约 ${n}", { n: u.cost_usd.toFixed(2) }) : "") + "</div></div>";
  };

  /* 翻译进度旁边的一句话：“已用 12.3 万 token · 5 小时额度用到 24%” */
  PR.usageShort = function (u) {
    if (!u || !u.calls) return "";
    const five = u.limits && u.limits.five_hour;
    return PR.t("已用 {n} token", { n: tokens(u.input + u.output) }) + (five && five.used != null ? " · " + PR.t("5 小时额度用到 {pct}", { pct: pct(five.used) }) : "");
  };

  /* 论文详情里的用量卡片：上次翻译、这篇累计、译完时的额度 */
  PR.usageCard = function (u, total) {
    if (!u || !u.calls) return "";
    return '<div class="us-card">' + PR.usageTokens(PR.t("上次翻译"), u) +
      (total && total.calls > u.calls ? PR.usageTokens(PR.t("这篇累计"), total) : "") +
      PR.usageBars(u.limits, PR.t("Claude 订阅用量（译完时，整个账号共用）")) + "</div>";
  };

  /* 问 AI：整个对话的合计 */
  function threadSum(msgs) {
    const used = (msgs || []).map((m) => m.usage).filter((u) => u && u.calls);
    if (!used.length) return null;
    const sum = { calls: 0, input: 0, cached: 0, output: 0 };
    used.forEach((u) => { sum.calls += u.calls; sum.input += u.input; sum.cached += u.cached; sum.output += u.output; });
    return sum;
  }

  /* 对话输入框底部的小圆环。latest：服务端记下的最近一次额度 {limits, at}，新对话也有；
     没用过 Claude 订阅时只写这个对话的 token 数 */
  PR.usageChip = function (latest, msgs, open) {
    const five = latest && latest.limits && latest.limits.five_hour;
    const live = five && five.used != null && !(five.resets_at && five.resets_at * 1000 <= Date.now());
    const cls = "us-chip" + (open ? " on" : "");
    if (live) {
      const r = 6, c = 2 * Math.PI * r, v = Math.min(1, five.used);
      return '<button class="' + cls + " " + level(v) + '" data-c="usage" title="' + PR.t("用量") + '">' +
        '<svg viewBox="0 0 16 16" width="16" height="16"><circle cx="8" cy="8" r="' + r + '" class="track"/>' +
        '<circle cx="8" cy="8" r="' + r + '" class="fill" stroke-dasharray="' + (c * v).toFixed(2) + " " + c.toFixed(2) + '" transform="rotate(-90 8 8)"/></svg>' +
        "<span>" + pct(v) + "</span></button>";
    }
    const sum = threadSum(msgs);
    if (sum) return '<button class="' + cls + '" data-c="usage" title="' + PR.t("用量") + '"><span>' + tokens(sum.input + sum.output) + " token</span></button>";
    return latest && latest.limits ? '<button class="' + cls + '" data-c="usage" title="' + PR.t("用量") + '"><span>' + PR.t("用量") + "</span></button>" : "";
  };

  /* 上下文条（学 Claude 的 Context window）：最近一次回答时发给模型的全部内容。每次提问都会连同之前的对话一起发，
     所以看的是“当前对话多大”，不是累计。分三段：缓存命中的（系统提示、之前的对话）、这次新发的、模型的回答。
     不知道模型上下文多大时（API、Codex），条按 20 万算，右边只写 token 数 */
  function contextHtml(msgs) {
    const last = (msgs || []).map((m) => m.usage).filter((u) => u && u.calls && u.context).pop();
    if (!last) return '<div class="us-ctx"><div class="us-row"><span>' + PR.t("上下文") + "</span><em>" + PR.t("还没提问") + '</em></div><div class="us-bar"></div></div>';
    const c = last.context, total = c.cached + c.fresh + c.output, win = last.context_window;
    const scale = win || Math.max(200000, total);
    const seg = (n, cls, name) => n > 0 ? '<i class="' + cls + '" style="width:' + Math.max(0.6, (n / scale) * 100) + '%" title="' + name + " " + tokens(n) + '"></i>' : "";
    return '<div class="us-ctx"><div class="us-row"><span>' + PR.t("上下文") + "</span><em>" + tokens(total) + (win ? " / " + tokens(win) + PR.t("（{pct}%）", { pct: Math.max(1, Math.round((total / win) * 100)) }) : " token") + "</em></div>" +
      '<div class="us-bar us-stack">' + seg(c.cached, "cached", PR.t("缓存命中（系统提示、之前的对话）")) + seg(c.fresh, "fresh", PR.t("这次新发的（问题、引用的段落）")) + seg(c.output, "out", PR.t("回答")) + "</div>" +
      '<div class="us-legend"><span><i class="cached"></i>' + PR.t("缓存命中") + '</span><span><i class="fresh"></i>' + PR.t("新发送") + '</span><span><i class="out"></i>' + PR.t("回答") + "</span></div></div>";
  }

  /* 点圆环弹出的用量面板 */
  PR.usagePop = function (latest, msgs) {
    const bars = latest && latest.limits ? PR.usageBars(latest.limits, PR.t("Claude 订阅用量")) : "";
    return '<div class="us-pop">' + contextHtml(msgs) + bars +
      (bars ? '<div class="us-foot">' + PR.t("整个账号共用，含其他用途 · 更新于 {ago}", { ago: ago(latest.at) }) + "</div>" : "") + "</div>";
  };
})(window.PR);
