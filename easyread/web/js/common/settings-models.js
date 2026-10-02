/* Claude Code / Codex 的模型下拉框，“翻译”和“问 AI”两页共用（API 的表单在 settings-api.js）。
   名单来自 /api/engines 的 models（后端 cli_models.py）：Codex 就是它 /model 里列的那些；Claude 的别名带上实际版本。 */
(function (PR) {
  "use strict";
  const FALLBACK = { claude: { models: [{ id: "opus", name: "Opus", desc: PR.t("最强") }, { id: "sonnet", name: "Sonnet", desc: PR.t("快、省") }, { id: "haiku", name: "Haiku", desc: PR.t("最快最省") }] },
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
      if (!opts.length) opts.unshift(["", PR.t("Codex 默认")]);
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

  PR.modelReasoningFields = function (s, f) {
    const L = lists(s)[f.kind] || {};
    const model = (L.models || []).find((m) => m.id === (f.model || L.default));
    let levels = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];
    if (f.kind === "codex") levels = model && model.reasoning_levels && model.reasoning_levels.length ? model.reasoning_levels : ["low", "medium", "high", "xhigh", "max"];
    if (f.kind === "claude") levels = /haiku/i.test(f.model) ? [] : ["low", "medium", "high", "xhigh", "max"];
    const opts = [["", PR.t("跟随默认")], ...levels.map((v) => [v, v])];
    if (f.reasoning_effort && !levels.includes(f.reasoning_effort)) opts.push([f.reasoning_effort, f.reasoning_effort]);
    const field = (key, label, options) => '<label class="field"><span>' + label + '</span><select class="input" data-reasoning="' + key + '">' + PR.opt(options, f[key] || "") + '</select></label>';
    return '<div class="grid2">' + field("reasoning_effort", PR.t("推理强度"), opts) +
      (f.kind === "claude" ? "" : field("service_tier", "Fast", [["", PR.t("跟随默认")], ["fast", PR.t("开启 Fast")], ["default", PR.t("标准速度")]])) + '</div>' +
      '<p class="hint">' + PR.t("可显式选择并保存在 EasyRead，不修改本机 CLI 默认配置；low 通常更快，高强度通常更慢。") + '</p>' +
      '<p class="hint">' + (f.kind === "api" ? PR.t("API 选项需模型和服务商支持；不确定时保留默认，不额外发送参数。Fast 可能增加费用。") :
        f.kind === "claude" ? PR.t("Haiku 不支持 effort；其他模型的可用档位取决于 Claude Code 版本与账户。") :
          PR.t("Fast 的可用性及额度消耗取决于模型和账户；未读到模型档位时请按 CLI 支持情况选择。")) + '</p>';
  };

})(window.PR);
