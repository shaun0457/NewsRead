/* API 接口的表单，设置 → 模型页里添加、修改模型时用：
   服务商（按 国内直连 / 海外 / 本机 分组，有免费模型的带“免费”）→ 说明和获取 Key → API Key → 模型 → 高级（接口地址、接口格式）。
   自定义地址时，接口地址和格式直接放在最上面。
   表单的值放在调用方给的对象 a 里：{preset, base_url, api, model, vision, [keyProp]}；
   翻译设置用 keyProp api_key（存过的显示成 ••••），模型卡片的表单用 key。 */
(function (PR) {
  "use strict";
  const API_KINDS = [["chat", "Chat Completions（通用）"], ["responses", "Responses（OpenAI 新接口）"]];
  const found = {};  // 接口地址 → 点“获取模型列表”拉到的模型名
  const masked = (v) => String(v || "").startsWith("••••");
  const preset = (s, id) => s.presets.find((p) => p.id === id);
  const hasKey = (s, id) => (s.cfg.openai.saved_keys || []).includes(id) || !!(s.chatKeys || {})[id];
  PR.apiHasKey = hasKey;
  /* 模型的显示名：推荐名单里有就用“DeepSeek V4.1 Flash”，没有就是模型名本身 */
  PR.apiModelName = (s, presetId, model) => ((((preset(s, presetId) || {}).models) || []).find((m) => m.id === model) || {}).name || model;

  function tiles(s, a) {
    const tile = (p) => '<button data-af-preset="' + p.id + '" class="' + (a.preset === p.id ? "on" : "") + '">' + PR.esc(p.name) +
      (p.free ? '<i class="free-tag">免费</i>' : "") + (hasKey(s, p.id) ? ' <span class="ok-dot" title="已存 Key"></span>' : "") + "</button>";
    return '<div class="preset-tiles grouped">' + s.groups.map(([g, label]) => {
      const ps = s.presets.filter((p) => p.region === g);
      return ps.length ? '<div class="preset-group"><span>' + PR.esc(label) + "</span>" + ps.map(tile).join("") + "</div>" : "";
    }).join("") + '<div class="preset-group"><span>其他</span><button data-af-preset="" class="' + (!a.preset ? "on" : "") + '">自定义地址</button>' +
      '<em class="hint">任意 OpenAI 兼容接口、中转站</em></div></div>';
  }

  /* 模型：推荐的 + 接口里拉到的，做成下拉框，最后一项“手填”；都没有（自定义、LM Studio）或选了手填时是输入框 */
  function modelField(s, a, p) {
    const rec = (p && p.models) || [];
    let got = found[(a.base_url || "").trim()] || [];
    if (!got.length && a.preset === "ollama" && s.found && s.found.ollama) got = s.found.ollama.models;
    if (s.apiTyping || (!rec.length && !got.length)) {
      return '<input class="input" data-af="model" value="' + PR.esc(a.model) + '" placeholder="模型名，比如 deepseek-flash">';
    }
    const recIds = rec.map((m) => m.id);
    let h = PR.opt(rec.map((m) => [m.id, m.name + (m.tag ? " · " + m.tag : "")]), a.model);
    const rest = got.filter((m) => !recIds.includes(m));
    if (rest.length) h += '<optgroup label="' + (a.preset === "ollama" && !found[(a.base_url || "").trim()] ? "本机已下载" : "接口里的全部模型") + '">' + PR.opt(rest.map((m) => [m, m]), a.model) + "</optgroup>";
    if (a.model && !recIds.includes(a.model) && !got.includes(a.model)) h = PR.opt([[a.model, a.model]], a.model) + h;
    if (!a.model) h = '<option value="" selected>选一个模型</option>' + h;
    return '<select class="input" data-af="model">' + h + '<option value="__type">手填模型名…</option></select>';
  }

  function html(s, a, opt) {
    const p = preset(s, a.preset);
    const kp = opt.keyProp, saved = hasKey(s, a.preset) || masked(a[kp]);
    const addr = '<div class="grid2"><label class="field"><span>接口地址（base URL）</span><input class="input" data-af="base_url" value="' + PR.esc(a.base_url) + '" placeholder="https://…/v1"></label>' +
      '<label class="field"><span>接口格式</span><select class="input" data-af="api">' + PR.opt(API_KINDS, a.api || "chat") + "</select></label></div>";
    let note = p ? PR.esc(p.note || "") : "填服务商给的接口地址（一般以 /v1 结尾）。不知道选哪种接口格式就用 Chat Completions；只支持 Responses 的才换。";
    if (a.preset === "ollama" && s.found) {
      const ol = s.found.ollama;
      note = (ol && ol.running ? "Ollama 在运行，已下载 " + ol.models.length + " 个模型。" : '<span class="bad">没检测到 Ollama（127.0.0.1:11434）。</span>') + note;
    }
    const link = p && p.key_url ? ' <a href="' + p.key_url + '" target="_blank" rel="noopener">' + (p.key ? "获取 Key ↗" : "下载 ↗") + "</a>" : "";
    const fetchMsg = s.fetchMsg || {};
    return tiles(s, a) + '<p class="hint preset-note">' + note + link + "</p>" + (p ? "" : addr) +
      (p && !p.key ? "" : '<label class="field"><span>API Key</span><input class="input" type="password" data-af="key" value="' + (masked(a[kp]) ? "" : PR.esc(a[kp] || "")) +
        '" placeholder="' + (saved ? "已保存，留空不改" : "sk-…") + '" autocomplete="off"></label>') +
      '<label class="field"><span>模型</span><div class="model-row">' + modelField(s, a, p) +
      '<button class="btn sm line" data-fetch-models title="从接口读出它支持的全部模型">获取模型列表</button></div>' +
      (fetchMsg.text ? '<span class="test-result ' + (fetchMsg.cls || "") + '">' + PR.esc(fetchMsg.text) + "</span>" : "") + "</label>" +
      (opt.vision ? '<label class="check" style="margin:0 0 10px"><input type="checkbox" data-af="vision"' + (a.vision ? " checked" : "") + ">模型能看图（把原页图一起发过去，公式和表格更准）</label>" : "") +
      (p ? '<details class="api-adv"' + (s.advOpen ? " open" : "") + "><summary>高级：接口地址、接口格式</summary>" + addr + "</details>" : "");
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
      Object.assign(a, { base_url: p.base_url, api: p.api || "chat", model: om && om.length && !om.includes(p.model) ? om[0] : p.model });
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
      const b = e.target.closest("[data-af-preset]");
      if (b) { read(root, a, kp); pick(s, a, b.dataset.afPreset, kp); return true; }
      if (e.target.closest("[data-fetch-models]")) {
        e.preventDefault();
        read(root, a, kp);
        const key = masked(a[kp]) ? (s.chatKeys || {})[a.preset] || "" : a[kp] || "";
        s.fetchMsg = { text: "正在获取…" };
        PR.settingsRender();
        try {
          const r = await PR.api("/api/models/list", { method: "POST", body: { base_url: a.base_url, preset: a.preset, api_key: key } });
          if (r.ok && r.models.length) { found[(a.base_url || "").trim()] = r.models; s.apiTyping = false; s.fetchMsg = { cls: "ok", text: "✓ 接口里有 " + r.models.length + " 个模型，都放进下拉框了" }; }
          else s.fetchMsg = { cls: "bad", text: r.ok ? "接口没返回模型，手填模型名" : "✗ " + r.message };
        } catch (err) { s.fetchMsg = { cls: "bad", text: err.message }; }
        return true;
      }
      return false;
    },
    /* 改动：下拉框选“手填”换成输入框；换了推荐模型，“能看图”跟着它勾上或去掉 */
    change(e, s, a, kp, root) {
      if (e.target.dataset.af !== "model") return false;
      if (e.target.value === "__type") { e.target.value = a.model; read(root, a, kp); s.apiTyping = true; return true; }
      read(root, a, kp);
      const m = (((preset(s, a.preset) || {}).models) || []).find((x) => x.id === a.model);
      if (m) a.vision = !!m.vision;
      return true;
    },
  };
})(window.PR);
