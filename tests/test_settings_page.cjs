/* Ticket 67：設定頁 AI 模型區的畫面邏輯（偵測表、自帶 key、每種工作、各種提示、跳脫）。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function load() {
  const PR = {
    lang: "zh-TW",
    t: (s, values = {}) => s.replace(/\{(\w+)\}/g, (m, key) => values[key] ?? m),
    esc: (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"),
    $: () => null,
  };
  const context = { window: { PR }, document: { addEventListener() {} } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/settings/app.js"), "utf8"), context);
  return PR.settings;
}
const P = load();
const NOW = Date.UTC(2026, 10, 11, 2, 0);

const choice = (engine, model, extra = {}) => Object.assign({ id: engine + "|" + (extra.entry || "") + "|" + model, engine, model, entry: "",
  model_label: { "claude-haiku-5-5": "Haiku", "claude-sonnet-5-5": "Sonnet", "claude-opus-5-5": "Opus" }[model] || model, name: "",
  kind: { claude: "subscription", codex: "subscription", anthropic: "api", openai: "api", ollama: "local" }[engine], usable: true }, extra);
const task = (using, extra = {}) => Object.assign({ primary: null, fallback: null, resolved: using, using, state: "ready", reason: null, today: 0, month_cost: null }, extra);

function view(over = {}) {
  return Object.assign({
    detected: { claude: { found: true, version: "9.9.9 (Claude Code)", auth: "ok", billing: "subscription" },
                codex: { found: true, version: "codex 1", auth: null }, antigravity: { found: false, version: "" },
                ollama: { running: false, models: [] } },
    detected_at: NOW / 1000 - 60,
    claude_quota: { five_hour: { used: 0.42, resets_at: NOW / 1000 + 3600 }, seven_day: { used: 0.61, resets_at: NOW / 1000 + 86400 } },
    anthropic: { last4: "a9Fw", status: "ok", tested_at: "2026-11-10T02:00:00+00:00", code: null }, anthropic_sdk: true,
    openai: [],
    tasks: { triage: task("claude||claude-haiku-5-5", { today: 182 }), translate: task("codex||"), draft: task("claude||claude-opus-5-5"),
             thesis_change: task("anthropic||claude-sonnet-5-5", { primary: "anthropic||claude-sonnet-5-5", month_cost: 2.4 }),
             ask: task("claude||claude-sonnet-5-5") },
    choices: [choice("claude", "claude-haiku-5-5"), choice("claude", "claude-sonnet-5-5"), choice("claude", "claude-opus-5-5"),
              choice("codex", ""), choice("anthropic", "claude-sonnet-5-5")],
    any_ai: true,
  }, over);
}
const S = (v, over = {}) => Object.assign({ status: "ready", data: v, busy: false, editing: null, draft: P.blankOpenai(), errors: {} }, over);

test("choice labels say which engine, which model and how it is paid", () => {
  const tx = { openai: "OpenAI 相容", subscription: "（訂閱）", local: "（本機）", unusable: "（現在不能用）" };
  assert.equal(P.choiceLabel(choice("claude", "claude-haiku-5-5"), tx), "Claude Code · Haiku（訂閱）");
  assert.equal(P.choiceLabel(choice("codex", ""), tx), "Codex CLI（訂閱）");
  assert.equal(P.choiceLabel(choice("anthropic", "claude-sonnet-5-5"), tx), "Anthropic API · Sonnet");
  assert.equal(P.choiceLabel(choice("openai", "m-1", { name: "範例服務", entry: "o1" }), tx), "範例服務 · m-1");
  assert.equal(P.choiceLabel(choice("ollama", "qwen3:8b", { usable: false }), tx), "Ollama · qwen3:8b（本機）（現在不能用）");
});

test("the detection table shows login, billing, version and Claude quota", () => {
  const html = P.viewHtml(S(view()), NOW);
  assert.match(html, /本機訂閱（自動偵測 · \d+\/\d+ \d\d:\d\d）/);
  assert.match(html, /data-act="detect"/);
  assert.match(html, /Claude Code<\/td><td><span class="chip ok">已登入 · 訂閱/);
  assert.match(html, /5 小時 42% · 7 天 61%/);
  assert.match(html, /Codex CLI<\/td><td><span class="chip">找到了 · 還沒用過/);
  assert.match(html, /只回報 token 數，看不到額度/);
  assert.match(html, /Antigravity CLI<\/td><td><span class="chip">沒找到/);
  assert.match(html, /沒在執行/);
  const stale = view({ claude_quota: { five_hour: { used: 0.9, resets_at: NOW / 1000 - 10 }, seven_day: { used: 0.2, resets_at: NOW / 1000 + 10 } } });
  assert.match(P.viewHtml(S(stale), NOW), /5 小時 已重置 · 7 天 20%/);  // 重置過的數字不準了
  const bad = view();
  bad.detected.claude = { found: true, auth: "invalid" };
  assert.match(P.viewHtml(S(bad), NOW), /chip bad">沒登入或登入過期/);
});

test("keys show only the last four characters and their test status", () => {
  const html = P.viewHtml(S(view()), NOW);
  assert.match(html, /•••• 末四碼 a9Fw/);
  assert.match(html, /chip ok">測試通過 11\/10/);
  assert.match(html, /data-act="edit-anthropic">更換/);
  const invalid = view({ anthropic: { last4: "a9Fw", status: "invalid", tested_at: "2026-11-11T02:02:00+00:00", code: "AUTH_INVALID" } });
  const ih = P.viewHtml(S(invalid), NOW);
  assert.match(ih, /chip bad">key 無效<\/span><span class="sub">AUTH_INVALID · 11\/11 \d\d:02/);
  assert.match(ih, /class="btn sm" type="button" data-act="edit-anthropic"/);  // 失效時「更換」是一般按鈕，比較顯眼
  const none = P.viewHtml(S(view({ anthropic: null })), NOW);
  assert.match(none, /id="f-anthropic-key" type="password"/);
  assert.match(none, /placeholder="sk-ant-…"/);
  assert.match(none, /data-act="save-anthropic">儲存並測試/);
  assert.ok(!none.includes('data-act="cancel"'));
  const editing = P.viewHtml(S(view(), { editing: "anthropic", errors: { "anthropic.key": "key 的格式不對。" } }), NOW);
  assert.match(editing, /class="input num invalid" id="f-anthropic-key"/);
  assert.match(editing, /role="alert">key 的格式不對。/);
  assert.match(editing, /data-act="cancel"/);
  assert.match(P.viewHtml(S(view({ anthropic_sdk: false })), NOW), /沒裝 anthropic 套件/);
  assert.match(P.viewHtml(S(view({ anthropic: { last4: "", status: "untested" } })), NOW), /••••（已存）/);
});

test("OpenAI-compatible entries: list, add form, edit form keeps the key blank, errors land on the right field", () => {
  const o = { id: "o1", name: "範例<服務>", base_url: "https://api.example.com/v1", api: "chat", model: "m-1", last4: "9zZ9", has_key: true,
              status: "unverified", tested_at: "2026-11-11T02:02:00+00:00", code: "NETWORK" };
  const v = view({ openai: [o] });
  const html = P.viewHtml(S(v), NOW);
  assert.match(html, /範例&lt;服務&gt;/);
  assert.ok(!html.includes("範例<服務>"));
  assert.match(html, /chip warn">沒驗證到<\/span><span class="sub">NETWORK/);
  assert.match(html, /data-act="add-openai">＋ 新增/);
  const adding = P.viewHtml(S(v, { editing: "new", errors: { "openai.base_url": "base URL 的格式不對。", "anthropic.key": "x" } }), NOW);
  assert.match(adding, /class="input num invalid" id="f-o-base"/);
  assert.match(adding, /role="alert">base URL 的格式不對。/);
  assert.match(adding, /data-act="add-openai" disabled/);
  assert.match(adding, /id="f-o-key" type="password"[^>]*placeholder="sk-…"/);
  assert.ok(!/class="input num invalid" id="f-anthropic-key"/.test(adding));  // 別的表單的錯誤不會跑到這裡
  const editing = P.viewHtml(S(v, { editing: "o1", draft: { name: o.name, base_url: o.base_url, api: "responses", model: o.model } }), NOW);
  assert.match(editing, /placeholder="不換就留空"/);
  assert.match(editing, /<option value="responses" selected>/);
  assert.match(editing, /id="f-o-name" data-o="name" maxlength="40" value="範例&lt;服務&gt;" data-no-i18n/);
  assert.ok(!/value="[^"]*9zZ9/.test(editing));  // 編輯時不把 key 填回去
  assert.match(P.viewHtml(S(view({ openai: [Object.assign({}, o, { has_key: false, last4: "" })] })), NOW), /沒填 key/);
});

test("per-task selects: auto shows what it picked, fallback select, counts and monthly cost", () => {
  const html = P.viewHtml(S(view()), NOW);
  assert.match(html, /<option value="" selected>自動（目前：Claude Code · Haiku（訂閱））<\/option>/);
  assert.match(html, /id="f-task-thesis_change"[^>]*>[^]*?<option value="anthropic\|\|claude-sonnet-5-5" selected>Anthropic API · Sonnet/);
  assert.match(html, /id="f-fb-triage" data-task="triage" data-slot="fallback"/);
  assert.match(html, /不用備用/);
  assert.match(html, /今天 182 次/);
  assert.match(html, /本月 \$2\.40/);
  assert.match(html, /換引擎或模型會記進 prompt 版本/);
  for (const t of ["triage", "translate", "draft", "thesis_change", "ask"]) assert.match(html, new RegExp(`id="f-task-${t}"`));
});

test("an invalid key switches its tasks to the fallback with a banner, or pauses them", () => {
  const v = view({ anthropic: { last4: "a9Fw", status: "invalid", code: "AUTH_INVALID" } });
  v.tasks.thesis_change = task("claude||claude-sonnet-5-5", { primary: "anthropic||claude-sonnet-5-5", resolved: "anthropic||claude-sonnet-5-5",
                                                             fallback: "claude||claude-sonnet-5-5", state: "fallback", reason: "auth_invalid" });
  v.tasks.ask = task(null, { primary: "anthropic||claude-sonnet-5-5", resolved: "anthropic||claude-sonnet-5-5", state: "paused", reason: "auth_invalid" });
  const html = P.viewHtml(S(v), NOW);
  assert.match(html, /用 Anthropic key 的工作（論點變化偵測）已改用 Claude Code · Sonnet（訂閱）代跑；換好 key 之前不會再用這把。/);
  assert.match(html, /這些工作暫停了：問 AI。Anthropic key 失效/);
  assert.match(html, /改用備用：Claude Code · Sonnet（訂閱）/);
  assert.match(html, /chip bad">暫停中/);
  const cli = view();
  cli.tasks.ask = task("anthropic||claude-sonnet-5-5", { primary: "claude||claude-sonnet-5-5", resolved: "claude||claude-sonnet-5-5",
                                                        state: "fallback", reason: "auth_invalid" });
  assert.match(P.viewHtml(S(cli), NOW), /用 Claude Code 的工作（問 AI）已改用 Anthropic API · Sonnet代跑；重新登入並按「重新偵測」之前不會再用它。/);
});

test("no AI at all: banner and every task labelled", () => {
  const v = view({ any_ai: false, anthropic: null, choices: [] });
  v.detected.claude = { found: false }; v.detected.codex = { found: false };
  for (const t of Object.keys(v.tasks)) v.tasks[t] = task(null, { state: "no_ai" });
  const html = P.viewHtml(S(v), NOW);
  assert.match(html, /沒找到可以用的 AI。/);
  assert.match(html, /裝好 Claude Code 並登入後按「重新偵測」/);
  assert.equal((html.match(/<span class="chip">沒有 AI<\/span>/g) || []).length, 5);
  assert.ok(!P.viewHtml(S(view()), NOW).includes("沒找到可以用的 AI"));
});

test("page states and busy form", () => {
  assert.match(P.viewHtml(S(null, { status: "loading" }), NOW), /class="skel"/);
  assert.match(P.viewHtml(S(null, { status: "error" }), NOW), /data-act="retry"/);
  assert.match(P.viewHtml(S(view(), { busy: true }), NOW), /<fieldset class="plain" disabled>/);
  assert.match(P.viewHtml(S(view({ detected_at: null })), NOW), /偵測中…/);
});

test("user and upstream text is escaped and kept away from the DOM translator", () => {
  const v = view();
  v.detected.claude.version = '<img src=x onerror="alert(1)">';
  v.choices.push(choice("ollama", '<script>"x"</script>'));
  const html = P.viewHtml(S(v), NOW);
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script>"));
  assert.match(html, /class="sub num" data-no-i18n>&lt;img/);
  assert.match(html, /data-slot="primary" data-no-i18n>/);
});

test("short times", () => {
  assert.equal(P.shortTime(null), "");
  assert.equal(P.shortTime("garbage"), "");
  assert.match(P.shortTime(NOW / 1000), /^11\/11 \d\d:00$/);
  assert.match(P.shortTime("2026-11-10T02:00:00+00:00", false), /^11\/10$/);
});

test("a half-typed key only comes back into the same form", () => {
  const typed = { "#f-anthropic-key": "sk-ant-typed-1234", "#f-o-key": "sk-typed-for-A" };
  assert.equal(JSON.stringify(P.carryKeys(typed, "oA", "oA")), JSON.stringify(typed));  // 同一個服務重畫（偵測、改下拉選單、存檔失敗）
  assert.equal(JSON.stringify(P.carryKeys(typed, "oA", "oB")), JSON.stringify({ "#f-anthropic-key": "sk-ant-typed-1234" }));  // 換成 B 服務：不帶過去
  assert.equal(JSON.stringify(P.carryKeys(typed, "oA", "new")), JSON.stringify({ "#f-anthropic-key": "sk-ant-typed-1234" }));
  assert.equal(JSON.stringify(P.carryKeys(typed, null, "new")), JSON.stringify({ "#f-anthropic-key": "sk-ant-typed-1234" }));
  assert.equal(JSON.stringify(P.carryKeys(typed, "oA", "oA", false)), JSON.stringify({}));  // 存檔成功、取消：清掉
});
