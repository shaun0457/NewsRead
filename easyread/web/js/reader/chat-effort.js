/* 思考强度：不单独占按钮，放进模型菜单里一排小按钮；选了以后模型按钮上显示“Opus 5.5 · 高”。只对当前对话生效。 */
(function (PR) {
  "use strict";
  const names = () => ({ none: PR.t("不思考"), minimal: PR.t("最少"), low: PR.t("低"), medium: PR.t("中"), high: PR.t("高"), xhigh: PR.t("很高"), max: PR.t("最高"), ultra: PR.t("极限") });
  const name = (v) => names()[v] || PR.t("默认");
  PR.chatEffort = {
    levels(m, catalog) {
      if (m.engine === "claude") return /haiku/i.test(m.model || "") ? [] : ["low", "medium", "high", "xhigh", "max"];
      const source = catalog && catalog.codex;
      const hit = source && (source.models || []).find((x) => x.id === (m.model || source.default));
      if (m.engine === "codex" && hit && hit.reasoning_levels && hit.reasoning_levels.length) return hit.reasoning_levels;
      return ["low", "medium", "high", "xhigh", "max"];
    },
    value(st, m) { return st.chatOptions.reasoning_effort == null ? m.reasoning_effort || "" : st.chatOptions.reasoning_effort; },
    /* 模型按钮上的后缀：没改过就不显示 */
    suffix(st, m) {
      const v = this.levels(m, st.catalog).length ? this.value(st, m) : "";
      return v ? '<span class="ch-model-effort"> · ' + PR.esc(name(v)) + "</span>" : "";
    },
    /* 模型菜单最下面的一段 */
    section(st, m) {
      const levels = this.levels(m, st.catalog);
      if (!levels.length) return "";
      const cur = this.value(st, m);
      return '<div class="ch-effort-sec"><div class="ch-effort-title"><span>' + PR.t("思考强度") + "</span><small>" + PR.t("越高想得越久，只对这个对话生效") + "</small></div>" +
        '<div class="ch-effort-seg" role="radiogroup" aria-label="' + PR.t("思考强度") + '">' + ["", ...levels].map((v) =>
          '<button data-c="effort-level" data-effort="' + v + '" role="radio" aria-checked="' + (v === cur) + '" class="' + (v === cur ? "on" : "") + '"' + (st.streaming ? " disabled" : "") + ">" + PR.esc(name(v)) + "</button>").join("") +
        "</div></div>";
    },
    label: name,
  };
})(window.PR);
