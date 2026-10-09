/* API 服務表單，設定 → 模型頁新增或修改模型時使用：
   服務下拉選單 → API Key → 模型 → 進階設定（API 位址、API 格式）。
   自定义地址时，接口地址和格式直接放在最上面。
   表单的值放在调用方给的对象 a 里：{preset, base_url, api, model, vision, [keyProp]}；
   翻译设置用 keyProp api_key（存过的显示成 ••••），模型卡片的表单用 key。 */
(function (PR) {
  "use strict";
  const API_KINDS = [["chat", PR.t("Chat Completions（通用）")], ["responses", PR.t("Responses（OpenAI 新版 API）")]];
  const found = {};  // 接口地址 → 点“获取模型列表”拉到的模型名
  const masked = (v) => String(v || "").startsWith("••••");
  const preset = (s, id) => s.presets.find((p) => p.id === id);
  const hasKey = (s, id) => (s.cfg.openai.saved_keys || []).includes(id) || !!(s.chatKeys || {})[id];
  PR.apiHasKey = hasKey;
  /* 模型的显示名：推荐名单里有就用“DeepSeek V4.1 Flash”，没有就是模型名本身 */
  PR.apiModelName = (s, presetId, model) => {
    const name = ((((preset(s, presetId) || {}).models) || []).find((m) => m.id === model) || {}).name || model;
    return PR.t(name);
  };

  function tiles(s, a) {
    const choices = (s.api_choices || ["openai", "anthropic", "gemini", "deepseek", "dashscope", "openrouter", "ollama", "lmstudio"]).slice();
    const legacy = a.preset && !choices.includes(a.preset) ? a.preset : "";
    if (legacy) choices.push(legacy);
    const option = (id) => {
      const p = preset(s, id);
      if (!p) return "";
      const suffix = (p.free ? " · " + PR.t("免费") : "") + (hasKey(s, id) ? " · ✓" : "");
      return '<option value="' + PR.esc(id) + '"' + (a.preset === id ? " selected" : "") + ">" + PR.esc(PR.t(p.name) + suffix) + "</option>";
    };
    const cloud = choices.filter((id) => id !== "ollama" && id !== "lmstudio");
    const local = choices.filter((id) => id === "ollama" || id === "lmstudio");
    return '<label class="field"><span>' + PR.t("服務") + '</span><select class="input" data-af="preset">' +
      '<option value=""' + (!a.preset ? " selected" : "") + ">" + PR.t("自訂 OpenAI 相容 API") + "</option>" +
      (cloud.length ? '<optgroup label="' + PR.t("雲端 API") + '">' + cloud.map(option).join("") + "</optgroup>" : "") +
      (local.length ? '<optgroup label="' + PR.t("本機模型") + '">' + local.map(option).join("") + "</optgroup>" : "") +
      (legacy ? '<optgroup label="' + PR.t("既有設定") + '">' + option(legacy) + "</optgroup>" : "") +
      "</select><span class=\"hint\">" + PR.t("支援 OpenAI 相容 API 的服務") + "</span></label>";
  }

  /* 模型：雲端推薦清單與即時載入清單合併；Ollama 只顯示本機實際安裝的模型。 */
  function modelField(s, a, p) {
    const rec = a.preset === "ollama" ? [] : (p && p.models) || [];
    let got = found[(a.base_url || "").trim()] || [];
    if (!got.length && a.preset === "ollama" && s.found && s.found.ollama) got = s.found.ollama.models;
    if (s.apiTyping || (!rec.length && !got.length)) {
      return '<input class="input" data-af="model" value="' + PR.esc(a.model) + '" placeholder="' + PR.t("模型名，比如 deepseek-flash") + '">';
    }
    const recIds = rec.map((m) => m.id);
    let h = PR.opt(rec.map((m) => [m.id, PR.t(m.name) + (m.tag ? " · " + PR.t(m.tag) : "")]), a.model);
    const rest = got.filter((m) => !recIds.includes(m));
    if (rest.length) h += '<optgroup label="' + (a.preset === "ollama" && !found[(a.base_url || "").trim()] ? PR.t("本机已下载") : PR.t("接口里的全部模型")) + '">' + PR.opt(rest.map((m) => [m, m]), a.model) + "</optgroup>";
    if (a.model && !recIds.includes(a.model) && !got.includes(a.model)) h = PR.opt([[a.model, a.model]], a.model) + h;
    if (!a.model) h = '<option value="" selected>' + PR.t("选一个模型") + "</option>" + h;
    return '<select class="input" data-af="model">' + h + '<option value="__type">' + PR.t("手填模型名…") + "</option></select>";
  }

  function html(s, a, opt) {
    const p = preset(s, a.preset);
    const kp = opt.keyProp, saved = hasKey(s, a.preset) || masked(a[kp]);
    const addr = '<div class="grid2"><label class="field"><span>' + PR.t("接口地址（base URL）") + '</span><input class="input" data-af="base_url" value="' + PR.esc(a.base_url) + '" placeholder="https://…/v1"></label>' +
      '<label class="field"><span>' + PR.t("接口格式") + '</span><select class="input" data-af="api">' + PR.opt(API_KINDS, a.api || "chat") + "</select></label></div>";
    let note = p ? PR.esc(PR.t(p.note || "")) : PR.t("填服务商给的接口地址（一般以 /v1 结尾）。不知道选哪种接口格式就用 Chat Completions；只支持 Responses 的才换。");
    if (a.preset === "ollama" && s.found) {
      const ol = s.found.ollama;
      note = (ol && ol.running ? PR.t("Ollama 在运行，已下载 {n} 个模型。", { n: ol.models.length }) : '<span class="bad">' + PR.t("没检测到 Ollama（127.0.0.1:11434）。") + "</span>") + note;
    }
    const link = p && p.key_url ? ' <a href="' + p.key_url + '" target="_blank" rel="noopener">' + (p.key ? PR.t("获取 Key ↗") : PR.t("下载 ↗")) + "</a>" : "";
    const fetchMsg = s.fetchMsg || {};
    return tiles(s, a) + '<p class="hint preset-note">' + note + link + "</p>" + (p ? "" : addr) +
      (p && !p.key ? "" : '<label class="field"><span>API Key</span><input class="input" type="password" data-af="key" value="' + (masked(a[kp]) ? "" : PR.esc(a[kp] || "")) +
        '" placeholder="' + (saved ? PR.t("已保存，留空不改") : "sk-…") + '" autocomplete="off"></label>') +
      '<label class="field"><span>' + PR.t("模型") + '</span><div class="model-row">' + modelField(s, a, p) +
      '<button class="btn sm line" data-fetch-models title="' + PR.t("从接口读出它支持的全部模型") + '">' + PR.t("获取模型列表") + "</button></div>" +
      (fetchMsg.text ? '<span class="test-result ' + (fetchMsg.cls || "") + '">' + PR.esc(fetchMsg.text) + "</span>" : "") + "</label>" +
      (opt.vision ? '<label class="check" style="margin:0 0 10px"><input type="checkbox" data-af="vision"' + (a.vision ? " checked" : "") + ">" + PR.t("模型能看图（把原页图一起发过去，公式和表格更准）") + "</label>" : "") +
      (p ? '<details class="api-adv"' + (s.advOpen ? " open" : "") + "><summary>" + PR.t("高级：接口地址、接口格式") + "</summary>" + addr + "</details>" : "");
  }

  function read(root, a, kp) {
    PR.$$("[data-af]", root).forEach((el) => {
      const k = el.dataset.af, v = el.type === "checkbox" ? el.checked : el.value.trim();
      if (k === "key") { if (v) a[kp] = v; }
      else if (!(k === "model" && v === "__type")) a[k] = v;
    });
    const adv = PR.$(".api-adv", root);
    PR.settingsState.advOpen = !!(adv && adv.open);
  }

  /* 换服务商：地址、格式、默认模型跟着换；换到自定义时清空让用户填 */
  function pick(s, a, id, kp) {
    const p = preset(s, id), prev = a.preset;
    a.preset = id;
    s.fetchMsg = null; s.apiTyping = false;
    if (p) {
      const om = id === "ollama" && s.found && s.found.ollama && s.found.ollama.models;
      Object.assign(a, { base_url: p.base_url, api: p.api || "chat", model: id === "ollama" ? (om && om.length ? om[0] : "") : p.model });
      const m = p.models.find((x) => x.id === a.model);
      a.vision = !!(m && m.vision);
    } else if (prev) Object.assign(a, { base_url: "", api: "chat", model: "", vision: false });
    a[kp] = hasKey(s, id) ? "••••" : "";
  }

  PR.apiForm = {
    html, read,
    pick(s, a, id, kp) { pick(s, a, id, kp); },
    /* 点击：服务商、获取模型列表。处理了返回 true（要重画），没处理返回 false */
    async click(e, s, a, kp, root) {
      if (e.target.closest("[data-fetch-models]")) {
        e.preventDefault();
        read(root, a, kp);
        const key = masked(a[kp]) ? (s.chatKeys || {})[a.preset] || "" : a[kp] || "";
        s.fetchMsg = { text: PR.t("正在获取…") };
        PR.settingsRender();
        try {
          const r = await PR.api("/api/models/list", { method: "POST", body: { base_url: a.base_url, preset: a.preset, api_key: key } });
          if (r.ok && r.models.length) { found[(a.base_url || "").trim()] = r.models; s.apiTyping = false; s.fetchMsg = { cls: "ok", text: PR.t("✓ 接口里有 {n} 个模型，都放进下拉框了", { n: r.models.length }) }; }
          else s.fetchMsg = { cls: "bad", text: r.ok ? PR.t("接口没返回模型，手填模型名") : "✗ " + r.message };
        } catch (err) { s.fetchMsg = { cls: "bad", text: err.message }; }
        return true;
      }
      return false;
    },
    /* 改动：下拉框选“手填”换成输入框；换了推荐模型，“能看图”跟着它勾上或去掉 */
    change(e, s, a, kp, root) {
      if (e.target.dataset.af === "preset") {
        pick(s, a, e.target.value, kp);
        return true;
      }
      if (e.target.dataset.af !== "model") return false;
      if (e.target.value === "__type") { e.target.value = a.model; read(root, a, kp); s.apiTyping = true; return true; }
      read(root, a, kp);
      const m = (((preset(s, a.preset) || {}).models) || []).find((x) => x.id === a.model);
      if (m) a.vision = !!m.vision;
      return true;
    },
  };
})(window.PR);
