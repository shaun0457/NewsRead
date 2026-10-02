/* Claude Code / Codex 的模型下拉框，“翻译”和“问 AI”两页共用（API 的表单在 settings-api.js）。
   名单来自 /api/engines 的 models（后端 cli_models.py）：Codex 就是它 /model 里列的那些；Claude 的别名带上实际版本。 */
(function (PR) {
  "use strict";
  const FALLBACK = { claude: { models: [{ id: "opus", name: "Opus", desc: "最强" }, { id: "sonnet", name: "Sonnet", desc: "快、省" }, { id: "haiku", name: "Haiku", desc: "最快最省" }] },
    codex: { default: "", models: [] } };
  const lists = (s) => (s.models || FALLBACK);

  /* 下拉框的选项：[[value, label]]，选项就写模型名。Codex 一个模型都没查到时才留一项“Codex 默认” */
  PR.cliModelOptions = function (s, engine, value) {
    const L = lists(s)[engine] || FALLBACK[engine];
    let opts;
    if (engine === "claude") {
      opts = L.models.map((m) => [m.id, m.actual || "Claude " + m.name]);
    } else {
      opts = L.models.map((m) => [m.id, m.name]);
      if (!opts.length) opts.unshift(["", "Codex 默认"]);
    }
    if (value && !opts.some(([v]) => v === value)) opts.push([value, value]);
    return opts;
  };
  PR.cliModelSelect = (s, engine, value, attrs) =>
    "<select class=\"input\" " + attrs + ">" + PR.opt(PR.cliModelOptions(s, engine, value), value) + "</select>";
  /* 以前存的“跟随 CLI 默认”（模型空着）→ 换成它现在实际用的那个，翻译固定用一个模型，不随 CLI 设置变 */
  PR.cliPin = function (s, engine, model) {
    if (model || (engine !== "claude" && engine !== "codex") || !s.models) return model;
    const L = s.models[engine] || {};
    if (engine === "codex") return L.default || "";
    const hit = (L.models || []).find((m) => m.actual && m.actual === L.default);
    return hit ? hit.id : "opus";
  };

})(window.PR);
