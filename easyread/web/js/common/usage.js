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

  function limitsText(limits) {
    return Object.keys(WINDOWS).filter((k) => limits && limits[k] && limits[k].used != null)
      .map((k) => WINDOWS[k] + " " + Math.round(limits[k].used * 100) + "%").join("、");
  }

  /* 简短：进度条旁边用。“已用 12.3 万 token · 5 小时额度 24%” */
  PR.usageShort = function (u) {
    if (!u || !u.calls) return "";
    const lim = limitsText(u.limits);
    return "已用 " + tokens(u.input + u.output) + " token" + (lim ? " · " + lim.split("、")[0] : "");
  };

  /* 完整：论文详情里用 */
  PR.usageLong = function (u, total) {
    if (!u || !u.calls) return "";
    const lim = limitsText(u.limits);
    let s = "上次翻译用了 " + tokens(u.input + u.output) + " token（输入 " + tokens(u.input) +
      (u.cached ? "，其中缓存命中 " + tokens(u.cached) : "") + "；输出 " + tokens(u.output) + "）";
    if (lim) s += "。用完后 Claude 订阅 " + lim;
    else if (u.cost_usd != null) s += "，按官方价约 $" + u.cost_usd.toFixed(2);
    if (total && total.calls > u.calls) s += "。这篇累计 " + tokens(total.input + total.output) + " token";
    return s;
  };
})(window.PR);
