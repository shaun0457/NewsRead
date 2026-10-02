/* Compact conversation-only effort picker, beside the model selector. */
(function (PR) {
  "use strict";
  const names = { none: "None", minimal: "Minimal", low: "Low", medium: "Medium", high: "High", xhigh: "XHigh", max: "Max", ultra: "Ultra" };
  PR.chatEffort = {
    levels(m, catalog) {
      if (m.engine === "claude") return /haiku/i.test(m.model || "") ? [] : ["low", "medium", "high", "xhigh", "max"];
      const source = catalog && catalog.codex;
      const hit = source && (source.models || []).find((x) => x.id === (m.model || source.default));
      if (m.engine === "codex" && hit && hit.reasoning_levels && hit.reasoning_levels.length) return hit.reasoning_levels;
      return ["low", "medium", "high", "xhigh", "max"];
    },
    value(st, m) { return st.chatOptions.reasoning_effort == null ? m.reasoning_effort || "" : st.chatOptions.reasoning_effort; },
    html(st, m) {
      const levels = this.levels(m, st.catalog), value = this.value(st, m);
      if (!levels.length) return "";
      const label = names[value] || PR.t("默认强度");
      const choices = ["", ...levels], idx = Math.max(0, choices.indexOf(value));
      return '<button class="ch-effort" data-c="effort" aria-expanded="' + !!st.effortOpen + '" title="' + PR.t("调整推理强度") + '"' + (st.streaming ? ' disabled' : '') + '>' + PR.esc(label) + '</button>' +
        (st.effortOpen ? '<div class="ch-effort-pop" role="dialog" aria-label="' + PR.t("推理强度") + '"><div class="ch-effort-head"><span>Effort</span><b id="chatEffortValue">' + PR.esc(label) + '</b></div>' +
          '<div class="ch-effort-scale"><span>' + PR.t("更快") + '</span><span>' + PR.t("更深入") + '</span></div>' +
          '<input id="chatEffortRange" type="range" min="0" max="' + (choices.length - 1) + '" step="1" value="' + idx + '" aria-label="' + PR.t("推理强度") + '" aria-valuetext="' + PR.esc(label) + '">' +
          '<div class="ch-effort-ticks">' + choices.map((v, i) => '<button data-c="effort-level" data-effort="' + v + '" title="' + PR.esc(names[v] || PR.t("默认强度")) + '" aria-label="' + PR.esc(names[v] || PR.t("默认强度")) + '" class="' + (i === idx ? 'on' : '') + '">•</button>').join('') + '</div>' +
          '<p>' + PR.t("仅当前对话，下一条消息生效") + '</p></div>' : '');
    },
    label(value) { return names[value] || PR.t("默认强度"); },
  };
})(window.PR);
