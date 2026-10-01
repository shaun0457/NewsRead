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

  /* “5 小时额度这次用了约 1%，现在用到 25%；7 天额度用到 86%” */
  function limitsText(u) {
    const now = u.limits || {}, start = u.limits_start || {};
    return Object.keys(WINDOWS).filter((k) => now[k] && now[k].used != null).map((k) => {
      const d = start[k] && start[k].used != null ? now[k].used - start[k].used : null;
      const spent = d == null ? "" : d < 0.01 ? "这次用了不到 1%，" : "这次用了约 " + pct(d) + "，";
      return WINDOWS[k] + spent + "现在用到 " + pct(now[k].used);
    }).join("；");
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
    if (lim) s += "。Claude 订阅：" + lim;
    else if (u.cost_usd != null) s += "，按官方价约 $" + u.cost_usd.toFixed(2);
    if (total && total.calls > u.calls) s += "。这篇累计 " + tokens(total.input + total.output) + " token";
    return s;
  };
})(window.PR);
