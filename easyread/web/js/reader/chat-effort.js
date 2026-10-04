/* 思考强度：不单独占按钮，放进模型菜单里一排小按钮；选了以后模型按钮上显示“Opus 5.5 · 高”。只对当前对话生效。 */
(function (PR) {
  "use strict";
  const names = () => ({ none: PR.t("不思考"), minimal: PR.t("最少"), low: PR.t("低"), medium: PR.t("中"), high: PR.t("高"), xhigh: PR.t("很高"), max: PR.t("最高"), ultra: PR.t("极限") });
  const name = (v) => names()[v] || v;
  PR.chatEffort = {
    levels(m, catalog) {
      if (m.engine === "claude") return /haiku/i.test(m.model || "") ? [] : ["low", "medium", "high", "xhigh", "max"];
      const source = catalog && catalog.codex;
      const hit = source && (source.models || []).find((x) => x.id === (m.model || source.default));
      if (m.engine === "codex" && hit && hit.reasoning_levels && hit.reasoning_levels.length) return hit.reasoning_levels;
      return ["low", "medium", "high", "xhigh", "max"];
    },
    value(st, m) { return st.chatOptions.reasoning_effort || m.reasoning_effort || ""; },
    /* 不传 --effort 时模型实际用的档位：Codex 看 config.toml / 模型自带默认；Claude Code 看 effortLevel，
       没设就按官方文档（Opus / Sonnet 5.5 是中，Opus 4.7 是很高，其余是高）。API 模型由服务方决定，不知道就空 */
    fallback(st, m) {
      const cat = (st.catalog || {})[m.engine] || {};
      if (cat.configured_reasoning) return cat.configured_reasoning;
      if (m.engine === "codex") { const hit = (cat.models || []).find((x) => x.id === (m.model || cat.default)); return (hit && hit.default_reasoning) || ""; }
      if (m.engine !== "claude") return "";
      const hit = (cat.models || []).find((x) => x.id === m.model);
      const actual = (hit && hit.actual) || (m.model ? "" : cat.default) || m.label || "";
      return /(opus|sonnet) 5\.5/i.test(actual) ? "medium" : /opus 4\.7/i.test(actual) ? "xhigh" : "high";
    },
    effective(st, m) { return this.value(st, m) || this.fallback(st, m); },
    /* 模型按钮上的后缀：显示实际生效的档位 */
    suffix(st, m) {
      const v = this.levels(m, st.catalog).length ? this.effective(st, m) : "";
      return v ? '<span class="ch-model-effort"> · ' + PR.esc(name(v)) + "</span>" : "";
    },
    /* 模型菜单最下面的一段 */
    section(st, m) {
      const levels = this.levels(m, st.catalog);
      if (!levels.length) return "";
      const cur = this.effective(st, m);
      return '<div class="ch-effort-sec"><div class="ch-effort-title"><span>' + PR.t("思考强度") + "</span><small>" + PR.t("越高想得越久，只对这个对话生效") + "</small></div>" +
        '<div class="ch-effort-seg" role="radiogroup" aria-label="' + PR.t("思考强度") + '">' + levels.map((v) =>
          '<button data-c="effort-level" data-effort="' + v + '" role="radio" aria-checked="' + (v === cur) + '" class="' + (v === cur ? "on" : "") + '"' + (st.streaming ? " disabled" : "") + ">" + PR.esc(name(v)) + "</button>").join("") +
        "</div></div>";
    },
    label: name,
  };
})(window.PR);
