/* 翻译用量（job.json 里的 usage / usage_total）显示成一句话 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  function tokens(n) {
    n = Number(n) || 0;
    if (n < 10000) return n.toLocaleString();
    return (n / 10000).toFixed(n < 1e6 ? 1 : 0).replace(/\.0$/, "") + " 万";
  }
  PR.fmtTokens = tokens;

  const WINDOWS = { five_hour: "5 小时额度", seven_day: "7 天额度" };

  const pct = (x) => Math.round(x * 100) + "%";

  /* “5 小时额度用到 25%、7 天额度用到 86%”。额度是整个账号的，同时用 Claude Code 干别的也算在里面，
     所以不拿前后相减去算翻译用了多少，翻译本身的量看 token 数 */
  function limitsText(u) {
    const now = u.limits || {};
    return Object.keys(WINDOWS).filter((k) => now[k] && now[k].used != null)
      .map((k) => WINDOWS[k] + "用到 " + pct(now[k].used)).join("、");
  }

  /* 简短：进度条旁边用。“已用 12.3 万 token · 5 小时额度用到 24%” */
  PR.usageShort = function (u) {
    if (!u || !u.calls) return "";
    const five = u.limits && u.limits.five_hour;
    return "已用 " + tokens(u.input + u.output) + " token" + (five && five.used != null ? " · 5 小时额度用到 " + pct(five.used) : "");
  };

  /* 完整：论文详情里用 */
  PR.usageLong = function (u, total) {
    if (!u || !u.calls) return "";
    const lim = limitsText(u);
    let s = "上次翻译用了 " + tokens(u.input + u.output) + " token（输入 " + tokens(u.input) +
      (u.cached ? "，其中缓存命中 " + tokens(u.cached) : "") + "；输出 " + tokens(u.output) + "）";
    if (lim) s += "。译完时 Claude 订阅" + lim + "（整个账号的，含其他用途）";
    else if (u.cost_usd != null) s += "，按官方价约 $" + u.cost_usd.toFixed(2);
    if (total && total.calls > u.calls) s += "。这篇累计 " + tokens(total.input + total.output) + " token";
    return s;
  };
})(window.PR);
