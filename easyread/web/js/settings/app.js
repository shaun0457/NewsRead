/* 設定頁的 AI 模型區（ticket 67）：本機訂閱偵測、自帶 key、每種工作用哪個引擎。
   畫面照核准的 Mockup A（docs/mockups/v1-a/settings.html 的 #models）。額度保護是 ticket 68，還沒做。
   key 只在輸入框裡出現；送出後伺服器只回末四碼，這裡也不留著。 */
window.PR = window.PR || {};
(function (PR) {
  "use strict";

  const TASKS = ["triage", "translate", "draft", "thesis_change", "ask"];
  const CLI = ["claude", "codex", "antigravity"];
  // 產品名不翻
  const ENGINE = { claude: "Claude Code", codex: "Codex CLI", antigravity: "Antigravity CLI", ollama: "Ollama", anthropic: "Anthropic API" };  // i18n-ok

  /* 畫面文字集中在這裡（i18n_check 只看得到一般字串裡的 PR.t，看不到 template 裡的） */
  const T = () => ({
    triage: PR.t("分類（重要度、證據、對象）"), translate: PR.t("翻譯"), draft: PR.t("題材頁 / 概念卡起草"),
    thesis_change: PR.t("論點變化偵測"), ask: PR.t("問 AI"),
    openai: PR.t("OpenAI 相容"), subscription: PR.t("（訂閱）"), local: PR.t("（本機）"), unusable: PR.t("（現在不能用）"),
    noAiTitle: PR.t("沒找到可以用的 AI。"),
    noAiBody: PR.t("這台電腦沒有已登入的 Claude Code / Codex CLI，也沒有填 API key。"),
    noAiHow: PR.t("選一個：裝好 Claude Code 並登入後按「重新偵測」，或在下面填一把 API key。"),
    detected: (when) => PR.t("本機訂閱（自動偵測 · {when}）", { when }), detecting: PR.t("本機訂閱（偵測中…）"),
    redetect: PR.t("重新偵測"),
    engineCol: PR.t("引擎"), statusCol: PR.t("狀態"), quotaCol: PR.t("額度回報"),
    ollamaName: PR.t("Ollama（本地模型）"),
    loggedIn: PR.t("已登入 · 訂閱"), loggedInApi: PR.t("已登入 · API 計費"), authBad: PR.t("沒登入或登入過期"),
    foundUnused: PR.t("找到了 · 還沒用過"), notFound: PR.t("沒找到"),
    running: (n) => PR.t("執行中 · {n} 個模型", { n }), notRunning: PR.t("沒在執行"),
    quota: (five, seven) => PR.t("5 小時 {five} · 7 天 {seven}", { five, seven }), quotaReset: PR.t("已重置"),
    noQuotaYet: PR.t("用過一次才看得到額度"), codexQuota: PR.t("只回報 token 數，看不到額度"),
    ollamaQuota: PR.t("不用額度，速度看你的電腦"),
    byok: PR.t("自帶 API key（BYOK）"), providerCol: PR.t("供應商"), keyCol: PR.t("Key"),
    masked: (tail) => PR.t("•••• 末四碼 {tail}", { tail }), maskedShort: PR.t("••••（已存）"), noKey: PR.t("沒填 key"),
    tested: (when) => PR.t("測試通過 {when}", { when }), invalid: PR.t("key 無效"), unverified: PR.t("沒驗證到"),
    untested: PR.t("還沒測試"),
    change: PR.t("更換"), remove: PR.t("移除"), edit: PR.t("編輯"), cancel: PR.t("取消"), saveTest: PR.t("儲存並測試"),
    add: PR.t("＋ 新增"), keyLabel: PR.t("Anthropic API key"),
    noSdk: PR.t("這台電腦沒裝 anthropic 套件，Anthropic key 存得起來但還不能用。"),
    openaiSub: PR.t("OpenAI、Gemini、DeepSeek、LM Studio…填 base URL"),
    name: PR.t("名稱"), baseUrl: PR.t("Base URL"), api: PR.t("接口格式"), model: PR.t("模型"), key: PR.t("Key"),
    apiChat: PR.t("Chat Completions（通用）"), apiResponses: PR.t("Responses（OpenAI 新接口）"),
    keepKey: PR.t("不換就留空"), baseHint: PR.t("例如 https://api.openai.com/v1。不是這台電腦上的服務要用 https。"),
    keyHint: PR.t("Key 只存在這台電腦，畫面上只顯示末四碼，不寫進 log、不出現在任何回應裡。"),
    keyFallback: (who, tasks, using) => PR.t("用 {who} 的工作（{tasks}）已改用 {using}代跑；換好 key 之前不會再用這把。", { who, tasks, using }),
    cliFallback: (who, tasks, using) => PR.t("用 {who} 的工作（{tasks}）已改用 {using}代跑；重新登入並按「重新偵測」之前不會再用它。", { who, tasks, using }),
    paused: (who, tasks) => PR.t("這些工作暫停了：{tasks}。{who} 失效，也沒有可以用的備用引擎。換好 key，或在下面改選別的引擎。", { who, tasks }),
    anthropicKey: PR.t("Anthropic key"), entryKey: (name) => PR.t("{name} 的 key", { name }),
    perTask: PR.t("每種工作用哪個"), auto: PR.t("自動"), autoNow: (label) => PR.t("自動（目前：{label}）", { label }),
    fallbackLabel: PR.t("備用"), noFallback: PR.t("不用備用"),
    noAi: PR.t("沒有 AI"), pausedChip: PR.t("暫停中"), usingFallback: (label) => PR.t("改用備用：{label}", { label }),
    today: (n) => PR.t("今天 {n} 次", { n }), month: (cost) => PR.t("本月 ${cost}", { cost }),
    versionNote: PR.t("換引擎或模型會記進 prompt 版本；golden set 比較準確度時分開算。"),
    loadFailed: PR.t("讀不到 AI 設定。"), retry: PR.t("重試"),
  });
  const esc = (s) => PR.esc(s);
  const joinList = (xs) => xs.join(PR.lang === "en" ? ", " : "、");  // i18n-ok：列表分隔符號

  /* ---------- 純函式（測試直接呼叫） ---------- */
  function pad(n) { return String(n).padStart(2, "0"); }

  /* ISO 字串或 Unix 秒 → 「11/11 08:58」（withTime=false 時只有日期） */
  function shortTime(value, withTime) {
    if (value == null || value === "") return "";
    const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    if (isNaN(d.getTime())) return "";
    const day = (d.getMonth() + 1) + "/" + d.getDate();
    return withTime === false ? day : day + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function choiceLabel(c, tx) {
    if (!c) return "";
    let label;
    if (c.engine === "openai") label = (c.name || tx.openai) + (c.model ? " · " + c.model : "");
    else label = (ENGINE[c.engine] || c.engine) + (c.model_label || c.model ? " · " + (c.model_label || c.model) : "");
    if (c.kind === "subscription") label += tx.subscription;
    if (c.kind === "local") label += tx.local;
    if (c.usable === false) label += tx.unusable;
    return label;
  }

  function findChoice(view, id) {
    return (view.choices || []).find((c) => c.id === id) || null;
  }

  function quotaText(q, tx, now) {
    const five = q && q.five_hour, seven = q && q.seven_day;
    if (!five && !seven) return "";
    const pct = (w) => {
      if (!w || w.used == null) return "—";
      if (w.resets_at && w.resets_at * 1000 <= now) return tx.quotaReset;  // 記下的是重置前的數，已經不準了
      return Math.round(Number(w.used) * 100) + "%";
    };
    return tx.quota(pct(five), pct(seven));
  }

  function engineRowsHtml(view, tx, now) {
    const det = view.detected || {};
    const rows = CLI.map((e) => {
      const d = det[e] || {};
      let chip;
      if (!d.found) chip = `<span class="chip">${esc(tx.notFound)}</span>`;
      else if (d.auth === "invalid") chip = `<span class="chip bad">${esc(tx.authBad)}</span>`;
      else if (d.auth === "ok") chip = `<span class="chip ok">${esc(d.billing === "api" ? tx.loggedInApi : tx.loggedIn)}</span>`;
      else chip = `<span class="chip">${esc(tx.foundUnused)}</span>`;
      const version = d.found && d.version ? `<span class="sub num" data-no-i18n>${esc(d.version)}</span>` : "";
      let quota = `<span class="muted">—</span>`;
      if (e === "claude" && d.found) quota = quotaText(view.claude_quota, tx, now) ? `<span>${esc(quotaText(view.claude_quota, tx, now))}</span>` : `<span class="muted">${esc(tx.noQuotaYet)}</span>`;
      if (e === "codex" && d.found) quota = `<span class="muted">${esc(tx.codexQuota)}</span>`;
      return `<tr><td>${esc(ENGINE[e])}</td><td>${chip}${version}</td><td>${quota}</td></tr>`;
    });
    const o = det.ollama || {};
    const ochip = o.running ? `<span class="chip ok">${esc(tx.running((o.models || []).length))}</span>` : `<span class="chip">${esc(tx.notRunning)}</span>`;
    rows.push(`<tr><td>${esc(tx.ollamaName)}</td><td>${ochip}</td><td class="muted">${esc(tx.ollamaQuota)}</td></tr>`);
    return rows.join("");
  }

  function statusHtml(k, tx) {
    if (!k) return "";
    const sub = (code, at) => `<span class="sub">${esc(code || "")}${code && at ? " · " : ""}${esc(shortTime(at))}</span>`;
    if (k.status === "ok") return `<span class="chip ok">${esc(tx.tested(shortTime(k.tested_at, false)))}</span>`;
    if (k.status === "invalid") return `<span class="chip bad">${esc(tx.invalid)}</span>${sub(k.code, k.tested_at)}`;
    if (k.status === "unverified") return `<span class="chip warn">${esc(tx.unverified)}</span>${sub(k.code, k.tested_at)}`;
    return `<span class="chip">${esc(tx.untested)}</span>`;
  }

  function maskedHtml(k, tx) {
    if (!k) return "";
    if (k.has_key === false) return `<span class="muted">${esc(tx.noKey)}</span>`;
    return esc(k.last4 ? tx.masked(k.last4) : tx.maskedShort);
  }

  function fieldErr(errors, key) {
    return errors && errors[key] ? `<span class="err" role="alert">${esc(errors[key])}</span>` : "";
  }

  function anthropicRowHtml(view, ui, tx) {
    const a = view.anthropic, errors = ui.errors || {};
    const sdk = view.anthropic_sdk === false ? `<span class="sub">${esc(tx.noSdk)}</span>` : "";
    if (!a || ui.editing === "anthropic") {
      const bad = errors["anthropic.key"] ? " invalid" : "";
      return `<tr><td>Anthropic${sdk}</td>` +
        `<td colspan="2"><input class="input num${bad}" id="f-anthropic-key" type="password" autocomplete="new-password" spellcheck="false" ` +
        `placeholder="sk-ant-…" aria-label="${esc(tx.keyLabel)}">${fieldErr(errors, "anthropic.key")}${fieldErr(errors, "anthropic.form")}</td>` +
        `<td class="acts"><button class="btn sm primary" type="button" data-act="save-anthropic">${esc(tx.saveTest)}</button>` +
        (a ? `<button class="btn sm ghost" type="button" data-act="cancel">${esc(tx.cancel)}</button>` : "") + `</td></tr>`;
    }
    return `<tr><td>Anthropic${sdk}</td><td class="num">${maskedHtml(a, tx)}</td><td>${statusHtml(a, tx)}</td>` +
      `<td class="acts"><button class="btn sm${a.status === "invalid" ? "" : " ghost"}" type="button" data-act="edit-anthropic">${esc(tx.change)}</button>` +
      `<button class="btn sm ghost danger" type="button" data-act="remove-anthropic">${esc(tx.remove)}</button></td></tr>`;
  }

  function openaiFormHtml(draft, ui, tx) {
    const all = ui.errors || {};
    const errors = {};
    Object.keys(all).forEach((k) => { if (k.startsWith("openai.")) errors[k.slice(7)] = all[k]; });
    const bad = (k) => (errors[k] ? " invalid" : "");
    const editing = ui.editing && ui.editing !== "new";
    return `<tr class="form-row"><td colspan="4"><div class="grid2">` +
      `<div class="field"><label for="f-o-name">${esc(tx.name)}</label><input class="input${bad("name")}" id="f-o-name" data-o="name" maxlength="40" value="${esc(draft.name)}" data-no-i18n>${fieldErr(errors, "name")}</div>` +
      `<div class="field"><label for="f-o-model">${esc(tx.model)}</label><input class="input num${bad("model")}" id="f-o-model" data-o="model" maxlength="100" value="${esc(draft.model)}" data-no-i18n>${fieldErr(errors, "model")}</div>` +
      `<div class="field"><label for="f-o-base">${esc(tx.baseUrl)}</label><input class="input num${bad("base_url")}" id="f-o-base" data-o="base_url" maxlength="300" spellcheck="false" value="${esc(draft.base_url)}" placeholder="https://…" data-no-i18n><span class="hint">${esc(tx.baseHint)}</span>${fieldErr(errors, "base_url")}</div>` +
      `<div class="field"><label for="f-o-api">${esc(tx.api)}</label><select class="input" id="f-o-api" data-o="api">` +
      `<option value="chat"${draft.api !== "responses" ? " selected" : ""}>${esc(tx.apiChat)}</option>` +
      `<option value="responses"${draft.api === "responses" ? " selected" : ""}>${esc(tx.apiResponses)}</option></select></div>` +
      `<div class="field"><label for="f-o-key">${esc(tx.key)}</label><input class="input num${bad("key")}" id="f-o-key" type="password" autocomplete="new-password" spellcheck="false" ` +
      `placeholder="${esc(editing ? tx.keepKey : "sk-…")}">${fieldErr(errors, "key")}</div>` +
      `</div>${fieldErr(errors, "form")}<div class="row"><button class="btn sm primary" type="button" data-act="save-openai">${esc(tx.saveTest)}</button>` +
      `<button class="btn sm ghost" type="button" data-act="cancel">${esc(tx.cancel)}</button></div></td></tr>`;
  }

  function openaiRowsHtml(view, ui, tx) {
    const rows = (view.openai || []).map((o) => {
      if (ui.editing === o.id) return openaiFormHtml(ui.draft, ui, tx);
      return `<tr><td><span data-no-i18n>${esc(o.name)}</span><span class="sub num" data-no-i18n>${esc(o.base_url)} · ${esc(o.model)}</span></td>` +
        `<td class="num">${maskedHtml(o, tx)}</td><td>${statusHtml(o, tx)}</td>` +
        `<td class="acts"><button class="btn sm ghost" type="button" data-act="edit-openai" data-id="${esc(o.id)}">${esc(tx.edit)}</button>` +
        `<button class="btn sm ghost danger" type="button" data-act="remove-openai" data-id="${esc(o.id)}">${esc(tx.remove)}</button></td></tr>`;
    });
    rows.push(`<tr><td>${esc(tx.openai)}<span class="sub">${esc(tx.openaiSub)}</span></td>` +
      `<td><button class="btn sm" type="button" data-act="add-openai"${ui.editing === "new" ? " disabled" : ""}>${esc(tx.add)}</button></td><td></td><td></td></tr>`);
    if (ui.editing === "new") rows.push(openaiFormHtml(ui.draft, ui, tx));
    return rows.join("");
  }

  /* 主要引擎不能用時的提示：改用備用的、暫停的，依失效的那個引擎分組 */
  function bannersHtml(view, tx) {
    const groups = new Map();
    TASKS.forEach((t) => {
      const s = (view.tasks || {})[t];
      if (!s || s.reason !== "auth_invalid" || (s.state !== "fallback" && s.state !== "paused")) return;
      const primary = findChoice(view, s.resolved);
      const who = !primary ? tx.anthropicKey : primary.engine === "anthropic" ? tx.anthropicKey
        : primary.engine === "openai" ? tx.entryKey(primary.name || tx.openai) : ENGINE[primary.engine];
      const using = s.state === "fallback" ? choiceLabel(Object.assign({}, findChoice(view, s.using), { usable: true }), tx) : "";
      const key = s.state + "|" + who + "|" + using + "|" + (primary && CLI.includes(primary.engine) ? "cli" : "key");
      if (!groups.has(key)) groups.set(key, { state: s.state, who, using, cli: !!(primary && CLI.includes(primary.engine)), tasks: [] });
      groups.get(key).tasks.push(tx[t]);
    });
    return Array.from(groups.values()).map((g) => {
      const text = g.state === "paused" ? tx.paused(g.who, joinList(g.tasks))
        : (g.cli ? tx.cliFallback : tx.keyFallback)(g.who, joinList(g.tasks), g.using);
      return `<div class="banner bad"><span class="ico">!</span><div>${esc(text)}</div></div>`;  // 常駐的提示不用 alert，免得每次重畫都重念
    }).join("");
  }

  function optionsHtml(view, selected, tx, first) {
    return first + (view.choices || []).map((c) =>
      `<option value="${esc(c.id)}"${c.id === selected ? " selected" : ""}>${esc(choiceLabel(c, tx))}</option>`).join("");
  }

  function taskHint(s, view, tx) {
    const parts = [];
    if (s.state === "no_ai") parts.push(`<span class="chip">${esc(tx.noAi)}</span>`);
    if (s.state === "paused") parts.push(`<span class="chip bad">${esc(tx.pausedChip)}</span>`);
    if (s.state === "fallback") parts.push(esc(tx.usingFallback(choiceLabel(Object.assign({}, findChoice(view, s.using), { usable: true }), tx))));
    parts.push(esc(tx.today(s.today || 0)));
    if (s.month_cost != null && s.month_cost > 0) parts.push(esc(tx.month(Number(s.month_cost).toFixed(2))));
    return parts.join(" · ");
  }

  function tasksHtml(view, tx) {
    return TASKS.map((t) => {
      const s = (view.tasks || {})[t] || {};
      const using = s.state === "ready" ? findChoice(view, s.using) : null;
      const auto = `<option value=""${s.primary ? "" : " selected"}>${esc(!s.primary && using ? tx.autoNow(choiceLabel(using, tx)) : tx.auto)}</option>`;
      return `<div class="field"><label for="f-task-${t}">${esc(tx[t])}</label>` +
        `<select class="input" id="f-task-${t}" data-task="${t}" data-slot="primary" data-no-i18n>${optionsHtml(view, s.primary, tx, auto)}</select>` +
        `<div class="row fallback"><label class="hint" for="f-fb-${t}">${esc(tx.fallbackLabel)}</label>` +
        `<select class="input" id="f-fb-${t}" data-task="${t}" data-slot="fallback" data-no-i18n>` +
        `${optionsHtml(view, s.fallback, tx, `<option value=""${s.fallback ? "" : " selected"}>${esc(tx.noFallback)}</option>`)}</select></div>` +
        `<span class="hint">${taskHint(s, view, tx)}</span></div>`;
    }).join("");
  }

  function viewHtml(S, now) {
    const tx = T();
    if (S.status === "loading") return `<div class="skel" style="width:60%"></div><div class="skel" style="width:40%;margin-top:10px"></div>`;
    if (S.status === "error") return `<div class="banner bad" role="alert"><span class="ico">!</span><div>${esc(tx.loadFailed)} ` +
      `<button class="btn sm" type="button" data-act="retry">${esc(tx.retry)}</button></div></div>`;
    const v = S.data || {}, ui = S;
    const noai = v.any_ai ? "" : `<div class="banner bad"><span class="ico">!</span><div><b>${esc(tx.noAiTitle)}</b>` +
      `${esc(tx.noAiBody)}<br>${esc(tx.noAiHow)}</div></div>`;
    const when = shortTime(v.detected_at);
    return `<fieldset class="plain"${S.busy ? " disabled" : ""}>` + noai +
      `<div class="label">${esc(when ? tx.detected(when) : tx.detecting)}<button class="btn sm ghost" type="button" data-act="detect">${esc(tx.redetect)}</button></div>` +
      `<div class="scroll-x"><table class="tbl"><thead><tr><th>${esc(tx.engineCol)}</th><th>${esc(tx.statusCol)}</th><th>${esc(tx.quotaCol)}</th></tr></thead>` +
      `<tbody>${engineRowsHtml(v, tx, now == null ? Date.now() : now)}</tbody></table></div>` +
      `<div class="label">${esc(tx.byok)}</div>` +
      `<div class="scroll-x"><table class="tbl keys"><thead><tr><th>${esc(tx.providerCol)}</th><th>${esc(tx.keyCol)}</th><th>${esc(tx.statusCol)}</th><th></th></tr></thead>` +
      `<tbody>${anthropicRowHtml(v, ui, tx)}${openaiRowsHtml(v, ui, tx)}</tbody></table></div>` +
      `<p class="hint">${esc(tx.keyHint)}</p>` + bannersHtml(v, tx) +
      `<div class="label">${esc(tx.perTask)}</div><div class="grid2">${tasksHtml(v, tx)}</div>` +
      `<p class="muted note">${esc(tx.versionNote)}</p></fieldset>`;
  }

  function blankOpenai() { return { name: "", base_url: "", api: "chat", model: "" }; }

  PR.settings = { carryKeys, shortTime, choiceLabel, quotaText, engineRowsHtml, anthropicRowHtml, openaiRowsHtml, bannersHtml, tasksHtml, viewHtml, blankOpenai };

  /* ---------- 畫面狀態和事件 ---------- */
  const S = { status: "loading", data: null, busy: false, editing: null, draft: blankOpenai(), errors: {} };
  let loadSeq = 0;

  const KEY_INPUTS = ["#f-anthropic-key", "#f-o-key"];

  /* 重畫時哪些還沒送出的 key 要放回輸入框。只放回同一個表單：Anthropic 的輸入框只有一個；
     OpenAI 相容的要重畫前後編輯的是同一個服務，不然 A 服務打到一半的 key 會帶到 B 服務、送到 B 的地址 */
  function carryKeys(typed, before, after, keepKeys) {
    if (keepKeys === false) return {};
    const out = {};
    if (typed["#f-anthropic-key"]) out["#f-anthropic-key"] = typed["#f-anthropic-key"];
    if (typed["#f-o-key"] && before != null && before === after) out["#f-o-key"] = typed["#f-o-key"];
    return out;
  }

  let renderedEditing = null;  // 上一次畫面上開著的是哪個表單

  /* keepKeys：重畫時把還沒送出的 key 留在輸入框裡（只在 DOM，不放進 S）；存檔成功後傳 false 清掉 */
  function render(focus, keepKeys) {
    const view = PR.$("#view");
    if (!view) return;
    const now = Object.fromEntries(KEY_INPUTS.map((sel) => [sel, (PR.$(sel, view) || {}).value || ""]));
    const typed = carryKeys(now, renderedEditing, S.editing, keepKeys);
    view.innerHTML = viewHtml(S);
    renderedEditing = S.editing;
    KEY_INPUTS.forEach((sel) => { const el = PR.$(sel, view); if (el && typed[sel]) el.value = typed[sel]; });
    if (focus) {
      const el = PR.$(focus, view);
      if (el) el.focus();
    }
  }

  function errorMessage(e, fallback) {
    const data = (e && e.data) || {};
    return e && e.status && e.status < 500 && typeof data.error === "string" ? data.error : fallback;
  }

  async function token() {
    if (PR.token) return;
    try {  // 先拿寫入用的 token，第一次存 key 才不會先被 403 擋一次
      const lib = await PR.api("/api/library");
      if (lib && lib.token) PR.token = lib.token;
    } catch (_) { /* 拿不到就讓 PR.api 在 403 時再拿 */ }
  }

  async function load(quiet) {
    const seq = ++loadSeq;
    if (!quiet) { S.status = "loading"; render(); }
    try {
      await token();
      const data = await PR.api("/api/ai");
      if (seq !== loadSeq) return;
      S.data = data;
      S.status = "ready";
    } catch (e) {
      if (seq !== loadSeq) return;
      S.status = "error";
    }
    render();
  }

  /* 寫入：成功時伺服器回整份新狀態。test 是「儲存並測試」的結果 */
  async function send(path, body, failText, scope) {
    if (S.busy) return null;
    S.busy = true;
    loadSeq++;  // 進行中的讀取結果作廢，免得蓋掉這次寫入
    render();
    let res = null;
    try {
      res = await PR.api(path, { method: "POST", body: body || {} });
      S.data = res;
      S.status = "ready";
      S.errors = {};
    } catch (e) {
      const f = (e && e.data && e.data.field) || "form";
      S.errors = { [(scope || "page") + "." + f]: errorMessage(e, failText) };
    }
    S.busy = false;
    return res;
  }

  function testToast(test) {
    if (!test) return;
    PR.toast(esc(test.ok ? PR.t("測試通過。") : test.status === "invalid" ? PR.t("key 無效（{code}）。", { code: test.code || "" })
      : test.message || PR.t("已儲存，但沒驗證到這把 key。")));
  }

  async function saveAnthropic() {
    const input = PR.$("#f-anthropic-key");
    const key = input ? input.value : "";
    const res = await send("/api/ai/keys/anthropic", { key }, PR.t("儲存失敗，請再試一次。"), "anthropic");
    if (res) { S.editing = null; testToast(res.test); }
    render(res ? '[data-act="edit-anthropic"]' : "#f-anthropic-key", !res);
  }

  async function saveOpenai() {
    const input = PR.$("#f-o-key");
    const body = Object.assign({}, S.draft, { key: input ? input.value : "" });
    const path = "/api/ai/keys/openai" + (S.editing && S.editing !== "new" ? "/" + encodeURIComponent(S.editing) : "");
    const res = await send(path, body, PR.t("儲存失敗，請再試一次。"), "openai");
    if (res) { S.editing = null; S.draft = blankOpenai(); testToast(res.test); }
    render(res ? '[data-act="add-openai"]' : "#view .invalid", !res);
  }

  async function act(name, el) {
    switch (name) {
      case "retry": return void load();
      case "detect": {
        const res = await send("/api/ai/detect", {}, PR.t("偵測失敗，請再試一次。"));
        if (!res) PR.toast(esc(S.errors["page.form"] || PR.t("偵測失敗，請再試一次。")));
        return void render('[data-act="detect"]');
      }
      case "edit-anthropic": S.editing = "anthropic"; S.errors = {}; return void render("#f-anthropic-key");
      case "save-anthropic": return void saveAnthropic();
      case "remove-anthropic": {
        const ok = await send("/api/ai/keys/anthropic/remove", {}, PR.t("移除失敗，請再試一次。"), "anthropic");
        if (!ok) PR.toast(esc(S.errors["anthropic.form"] || PR.t("移除失敗，請再試一次。")));
        return void render(ok ? "#f-anthropic-key" : '[data-act="remove-anthropic"]');
      }
      case "add-openai": S.editing = "new"; S.draft = blankOpenai(); S.errors = {}; return void render("#f-o-name");
      case "edit-openai": {
        const o = ((S.data && S.data.openai) || []).find((x) => x.id === el.dataset.id);
        if (!o) return;
        S.editing = o.id;
        S.draft = { name: o.name, base_url: o.base_url, api: o.api, model: o.model };
        S.errors = {};
        return void render("#f-o-name");
      }
      case "save-openai": return void saveOpenai();
      case "remove-openai": {
        const ok = await send("/api/ai/keys/openai/" + encodeURIComponent(el.dataset.id) + "/remove", {}, PR.t("移除失敗，請再試一次。"), "openai");
        if (!ok) PR.toast(esc(S.errors["openai.form"] || PR.t("移除失敗，請再試一次。")));
        return void render('[data-act="add-openai"]');
      }
      case "cancel": {
        const back = S.editing === "anthropic" ? '[data-act="edit-anthropic"]' : '[data-act="add-openai"]';
        S.editing = null; S.errors = {}; S.draft = blankOpenai();
        return void render(back, false);
      }
    }
  }

  function onClick(ev) {
    const target = ev.target.closest("[data-act]");
    if (!target || (S.busy && target.dataset.act !== "retry")) return;
    act(target.dataset.act, target);
  }

  function onInput(ev) {
    const el = ev.target;
    if (el.dataset.o && el.dataset.o in S.draft) S.draft[el.dataset.o] = el.value;
  }

  async function onChange(ev) {
    const el = ev.target;
    if (el.dataset.o === "api") { S.draft.api = el.value; return; }
    const task = el.dataset.task;
    if (!task || !S.data) return;
    const cur = (S.data.tasks || {})[task] || {};
    const body = { task, primary: cur.primary || "", fallback: cur.fallback || "" };
    body[el.dataset.slot] = el.value;
    const res = await send("/api/ai/tasks", body, PR.t("沒有改成功，請再試一次。"));
    if (!res) PR.toast(esc(S.errors["page.task"] || S.errors["page.form"] || PR.t("沒有改成功，請再試一次。")));
    render("#" + el.id);
  }

  function onKey(ev) {
    if (ev.key !== "Enter" || ev.isComposing) return;
    if (ev.target.id === "f-anthropic-key") { ev.preventDefault(); if (!S.busy) saveAnthropic(); }
    else if (ev.target.dataset && ev.target.dataset.o && ev.target.tagName === "INPUT") { ev.preventDefault(); if (!S.busy) saveOpenai(); }
    else if (ev.target.id === "f-o-key") { ev.preventDefault(); if (!S.busy) saveOpenai(); }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const view = PR.$("#view");
    if (!view) return;
    view.addEventListener("click", onClick);
    view.addEventListener("input", onInput);
    view.addEventListener("change", onChange);
    view.addEventListener("keydown", onKey);
    load();
  });
})(window.PR);
