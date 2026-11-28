/* 貼新聞連結匯入（ticket 11）。入口：每一頁右上角的「＋ 貼網址」、不在輸入框時按 Ctrl+V 貼上網址；
   全部走同一個對話框、呼叫同一個 POST /api/ingest。arXiv、DOI、PDF 連結照舊交給論文匯入（library/import.js）。

   對話框分成四塊：網址列、進度（#ingestSteps）、訊息（#ingestMsg，錯誤和提示）、結果（#ingestOut）、手動貼全文（#ingestManual）。
   送出時只清訊息和結果，手動貼的全文不會因為送出失敗而不見；「重試」重送上一次的內容（網址或全文）。
   每次送出拿一個序號，晚到的舊回應不蓋掉新畫面。關閉時對話框整個藏起來（hidden + inert），焦點還給打開前的元素。 */
(function (PR) {
  "use strict";

  const MAX_URL = 2000;
  const PAPER_HOSTS = /(^|\.)(arxiv\.org|doi\.org|openreview\.net)$/i;
  const RETRY_KINDS = ["timeout", "network", "upstream", "over_limit", "internal"];
  const FETCH_KINDS = ["timeout", "blocked", "paywall", "not_found", "unsupported", "over_limit", "network", "upstream", "redirect", "no_text"];
  const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])";

  /* 貼上的文字是不是一則新聞網址：http(s)、沒有空白、不是 PDF / arXiv / DOI */
  PR.isNewsUrl = function (text) {
    const t = String(text == null ? "" : text).trim();
    if (!t || t.length > MAX_URL || !/^https?:\/\/\S+$/i.test(t)) return false;
    let u;
    try { u = new URL(t); } catch (_) { return false; }
    if (/\.pdf$/i.test(u.pathname) || PAPER_HOSTS.test(u.hostname)) return false;
    return true;
  };

  const inEditor = (el) => !!(el && el.closest && el.closest("input, textarea, select, [contenteditable]:not([contenteditable=false])"));

  let box = null;
  let seq = 0;          // 每次送出加一；回應回來時序號不同就丟掉
  let last = null;      // 上一次送出的內容，給「重試」用
  let returnFocus = null;

  function dialog() {
    if (box) return box;
    box = document.createElement("div");
    box.className = "dialog-backdrop ingest-backdrop";  // 各頁靠 .dialog-backdrop.open 判斷有對話框開著（快捷鍵、Enter 打開論文…）
    box.id = "ingestDlg";
    box.hidden = true;
    box.inert = true;
    box.innerHTML = '<div class="dialog ingest-dialog" role="dialog" aria-modal="true" aria-labelledby="ingestTitle" tabindex="-1"></div>';
    document.body.appendChild(box);
    box.addEventListener("mousedown", (e) => { if (e.target === box) close(); });
    box.addEventListener("click", onClick);
    box.addEventListener("submit", onSubmit);
    return box;
  }
  const inner = () => dialog().querySelector(".ingest-dialog");
  const $ = (sel) => inner().querySelector(sel);
  const isOpen = () => !!(box && !box.hidden);

  function close() {
    if (!isOpen()) return;
    const active = document.activeElement;
    if (active && box.contains(active) && active.blur) active.blur();
    box.classList.remove("open");
    box.hidden = true;
    box.inert = true;
    const back = returnFocus;
    returnFocus = null;
    if (back && back.isConnected && back.focus) back.focus();
  }
  PR.closeIngest = close;

  function shell(url) {
    inner().innerHTML =
      '<h2 id="ingestTitle">' + PR.t("貼連結匯入") + "</h2>" +
      '<form class="ingest-paste" data-form="url"><input class="input" id="ingestUrl" type="url" autocomplete="off" maxlength="' + MAX_URL + '" placeholder="' + PR.t("貼上新聞網址") + '" value="' + PR.esc(url || "") + '">' +
      '<button class="btn accent" type="submit">' + PR.t("匯入") + "</button></form>" +
      '<p class="hint">' + PR.t("任何頁面右上角的「＋ 貼網址」都會打開這裡；不在輸入框時直接按 Ctrl+V 也可以。") + "</p>" +
      '<div class="ingest-steps" id="ingestSteps" hidden></div>' +
      '<div id="ingestMsg" aria-live="polite"></div>' +
      '<div id="ingestOut" aria-live="polite"></div>' +
      '<div id="ingestManual"></div>' +
      '<p class="ingest-foot"><button class="linkish" type="button" data-act="manual">' + PR.t("改成手動貼全文") + "</button>" +
      ' <button class="linkish" type="button" data-act="close">' + PR.t("關閉") + "</button></p>";
  }

  function steps(stage) {
    const el = $("#ingestSteps");
    if (!stage) { el.hidden = true; el.innerHTML = ""; return; }
    const manual = stage === "save" || !!(last && "text" in last.body);  // 手動貼全文沒有網址正規化和抓取這幾步
    const list = manual ? [["save", PR.t("建立資料")]]
      : [["fetch", PR.t("抓取頁面")], ["extract", PR.t("抽出正文")], ["save", PR.t("建立資料")]];
    const at = list.findIndex(([k]) => k === stage);
    el.hidden = false;
    el.innerHTML = (manual ? "" : '<span class="done">✓ ' + PR.t("網址正規化") + "</span>") + list.map(([k, label], i) =>
      '<span class="' + (stage === "done" || i < at ? "done" : i === at ? "now" : "") + '">' + (stage === "done" || i < at ? "✓ " : i === at ? "… " : "") + label + "</span>").join("");
  }

  const when = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? PR.esc(iso) : PR.esc(d.toLocaleString(PR.lang === "en" ? "en" : "zh-TW", { dateStyle: "medium", timeStyle: "short" }));
  };
  const TIME_SOURCE = { metadata: () => PR.t("頁面 metadata"), user: () => PR.t("使用者輸入"), unknown: () => PR.t("時間不明") };
  const readHref = (id) => "/read/" + encodeURIComponent(id);

  function resultHtml(r) {
    const time = r.published_at
      ? when(r.published_at) + ' <span class="muted">' + PR.t("來源：{src}", { src: (TIME_SOURCE[r.time_source] || TIME_SOURCE.unknown)() }) + "</span>"
      : '<span class="chip warn">' + PR.t("時間不明") + "</span>" + (r.published_raw ? ' <span class="muted">' + PR.t("頁面上寫的是「{raw}」，沒有時區", { raw: PR.esc(r.published_raw) }) + "</span>" : "") +
        ' <span class="muted">' + PR.t("不納入事件驗證") + "</span>";
    const head = r.status === "exists"
      ? '<div class="ingest-note">↺ ' + PR.t("這篇已經匯入過（{time}）。", { time: when(r.added) }) +
        (r.refetch ? " " + PR.t("這次重抓沒有更新，保留原本的內容：{reason}", { reason: PR.esc(r.refetch.message || "") }) : "") + "</div>"
      : r.status === "unchanged" ? '<div class="ingest-note">↺ ' + PR.t("內容和上次匯入的一樣，沒有建立新版本。") + "</div>"
      : r.status === "updated" ? '<div class="ingest-note">' + PR.t("原文和上次不同，存成新版本；舊版本保留。") + "</div>" : "";
    const preview = r.preview_only
      ? '<div class="ingest-warn">⚠ <b>' + PR.t("只有預覽") + "</b>" + PR.t("：") + PR.t("這篇在付費牆後面，只抓到前面幾段。已匯入並標示「只有預覽」。") +
        '<div class="ingest-actions"><a class="btn line" href="' + readHref(r.id) + '">' + PR.t("先讀預覽") + "</a>" +
        ' <button class="btn line" type="button" data-act="manual">' + PR.t("貼上全文") + "</button></div></div>" : "";
    const next = r.hant_converted ? PR.t("原文是簡體，已轉成繁體（不用 AI，原文保留）") : r.same_language ? PR.t("原文是中文，不用翻譯") : r.translate ? PR.t("翻譯中（可以先讀）") : PR.t("沒有自動翻譯");
    return head + preview +
      '<section class="ingest-result"><div class="kind">' + PR.t("新聞 · 自成一個 Story") + "</div><h3>" + PR.esc(r.title || r.url || "") + "</h3>" +
      '<dl class="kv"><dt>' + PR.t("媒體") + "</dt><dd>" + PR.esc(r.publisher || "") + "</dd>" +
      "<dt>" + PR.t("發布時間") + "</dt><dd>" + time + "</dd>" +
      "<dt>" + PR.t("抓取時間") + "</dt><dd>" + when(r.fetched_at) + "</dd>" +
      "<dt>" + PR.t("正文") + "</dt><dd>" + PR.t("{n} 段 · 約 {chars} 字", { n: r.paragraphs || 0, chars: (r.chars || 0).toLocaleString() }) + "</dd>" +
      "<dt>" + PR.t("翻譯") + "</dt><dd>" + next + "</dd></dl>" +
      '<div class="ingest-actions"><a class="btn accent" href="' + readHref(r.id) + '">' + PR.t("打開閱讀") + "</a></div></section>";
  }

  /* 錯誤標題看類別：網址不能抓、抓不到這頁（抓取失敗、抽不到正文）、其他（輸入不對、正在翻譯、內部錯誤）是「沒有匯入」 */
  function errorHtml(kind, message, manual) {
    if (kind === "invalid_url") {
      return '<div class="ingest-error">⛔ <b>' + PR.t("這個網址不能抓") + "</b>" + PR.t("：") + PR.esc(message) +
        '<p class="hint">' + PR.t("指向本機或內部網路的網址（例如 localhost、192.168.x.x）NewsRead 不會去抓，避免被貼進來的連結拿來存取你電腦或內網上的服務。") + "</p></div>";
    }
    const title = !manual && FETCH_KINDS.includes(kind) ? PR.t("抓不到這頁") : PR.t("沒有匯入");
    const retry = RETRY_KINDS.includes(kind) ? '<button class="btn line" type="button" data-act="retry">' + PR.t("稍後重試") + "</button> " : "";
    const toManual = manual ? "" : '<button class="btn line" type="button" data-act="manual">' + PR.t("改成手動貼全文") + "</button>";
    return '<div class="ingest-error">! <b>' + title + "</b>" + PR.t("：") + PR.esc(message) +
      (retry || toManual ? '<div class="ingest-actions">' + retry + toManual + "</div>" : "") + "</div>";
  }

  function manualHtml(url) {
    return '<form class="ingest-manual" data-form="manual">' +
      '<label class="field"><span>' + PR.t("標題") + '</span><input class="input" name="title" maxlength="300"></label>' +
      '<label class="field"><span>' + PR.t("媒體 / 作者") + '</span><input class="input" name="publisher" maxlength="300"></label>' +
      '<label class="field"><span>' + PR.t("發布時間") + '</span><input class="input" name="published_at" maxlength="64" placeholder="2026-11-10T13:30+08:00">' +
      '<small class="hint">' + PR.t("頁面上抓不到時間，請自己填（要有時區）；不知道就留空，會標「時間不明」，不納入事件驗證。") + "</small></label>" +
      '<label class="field"><span>' + PR.t("原始連結") + '</span><input class="input" name="url" type="url" maxlength="' + MAX_URL + '" value="' + PR.esc(url || "") + '"></label>' +
      '<label class="field"><span>' + PR.t("新聞全文") + '</span><textarea class="input" name="text" rows="8" required></textarea></label>' +
      '<div class="ingest-actions"><button class="btn accent" type="submit">' + PR.t("匯入") + '</button> <span class="hint">' + PR.t("時間來源會記為「使用者輸入」。") + "</span></div></form>";
  }

  function setBusy(on) {
    inner().setAttribute("aria-busy", on ? "true" : "false");
    inner().querySelectorAll("button[type=submit], [data-act=retry]").forEach((b) => { b.disabled = on; });
  }

  async function send(body, stage) {
    const my = ++seq;
    last = { body, stage };
    const manual = "text" in body;
    $("#ingestMsg").innerHTML = "";
    $("#ingestOut").innerHTML = "";
    steps(stage);
    setBusy(true);
    try {
      const r = await PR.api("/api/ingest", { method: "POST", body });
      if (my !== seq) return;  // 已經有更新的送出，這個回應作廢
      steps("done");
      if (manual) $("#ingestManual").innerHTML = "";  // 匯入成功才收起手動表單
      $("#ingestOut").innerHTML = resultHtml(r);
      PR.emit("ingested", r);
    } catch (e) {
      if (my !== seq) return;
      const data = (e && e.data) || {};
      steps("");
      $("#ingestMsg").innerHTML = errorHtml(data.kind || "network", data.error || (e && e.message) || "", manual);
    } finally {
      if (my === seq) setBusy(false);
    }
  }

  function showManual() {
    steps("");
    $("#ingestMsg").innerHTML = "";
    const slot = $("#ingestManual");
    if (!slot.querySelector("form")) slot.innerHTML = manualHtml($("#ingestUrl").value.trim());
    const t = slot.querySelector("textarea[name=text]");
    if (t) t.focus();
  }

  function onSubmit(e) {
    const form = e.target.closest("form[data-form]");
    if (!form) return;
    e.preventDefault();
    if (inner().getAttribute("aria-busy") === "true") return;
    if (form.dataset.form === "url") {
      const url = $("#ingestUrl").value.trim();
      if (url) send({ url }, "fetch");
      return;
    }
    const f = Object.fromEntries(["title", "publisher", "published_at", "url", "text"].map((k) => [k, (form.elements[k].value || "").trim()]));
    if (f.text) send(f, "save");
  }

  function onClick(e) {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const act = b.dataset.act;
    if (act === "close") close();
    else if (act === "retry") { if (last) send(last.body, last.stage); }
    else if (act === "manual") showManual();
  }

  /* 打開對話框；給了網址就直接開始匯入。焦點移進對話框（網址列或對話框本身），關閉時還回去 */
  PR.openIngest = function (url) {
    const d = dialog();
    const active = document.activeElement;
    if (!isOpen()) returnFocus = active && active !== document.body && !d.contains(active) ? active : null;
    seq++;  // 前一次還沒回來的請求作廢
    last = null;
    shell(url);
    setBusy(false);  // 作廢的請求不會再回來解除忙碌，這裡重設
    d.hidden = false;
    d.inert = false;
    d.classList.add("open");
    if (url) {
      inner().focus();
      send({ url: String(url).trim() }, "fetch");
    } else {
      const input = $("#ingestUrl");
      if (input) input.focus();
    }
  };

  /* Tab 只在對話框裡面繞 */
  function trapTab(e) {
    const items = Array.from(inner().querySelectorAll(FOCUSABLE)).filter((el) => !el.closest("[hidden]"));
    if (!items.length) { e.preventDefault(); inner().focus(); return; }
    const first = items[0], lastItem = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === inner())) { e.preventDefault(); lastItem.focus(); }
    else if (!e.shiftKey && active === lastItem) { e.preventDefault(); first.focus(); }
    else if (!inner().contains(active)) { e.preventDefault(); first.focus(); }
  }

  /* 每一頁右上角的「＋ 貼網址」：放在「導入論文」前面；沒有那個按鈕就放在空白欄後面 */
  function addButton() {
    const bar = document.querySelector("header.topbar, header.appbar");
    if (!bar || bar.querySelector("[data-ingest-open]")) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn line ingest-open";
    b.dataset.ingestOpen = "";
    b.textContent = PR.t("＋ 貼網址");
    b.title = PR.t("貼新聞連結匯入（不在輸入框時也可以直接 Ctrl+V）");
    b.addEventListener("click", () => PR.openIngest(""));
    const importBtn = bar.querySelector("#importBtn");
    const spacer = importBtn ? null : bar.querySelector(".spacer, .grow");
    if (importBtn) bar.insertBefore(b, importBtn);
    else if (spacer) spacer.after(b);
    else bar.appendChild(b);
  }

  /* 焦點不在輸入框、剪貼簿是新聞網址時，Ctrl+V 打開匯入；在輸入框裡照常貼上 */
  PR.ingestPaste = function (e) {
    if (inEditor(e.target) || inEditor(document.activeElement)) return false;
    if (isOpen()) return false;
    const text = ((e.clipboardData && e.clipboardData.getData("text")) || "").trim();
    if (!PR.isNewsUrl(text)) return false;
    e.preventDefault();
    PR.openIngest(text);
    return true;
  };
  document.addEventListener("paste", PR.ingestPaste);
  /* 對話框開著時，按鍵在 window 的捕獲階段就攔下：Esc 關閉、Tab 繞圈，其他鍵照常作用在對話框裡（打字、Enter 送出），
     但不再傳給後面頁面的快捷鍵（閱讀器的單鍵快捷鍵、文獻庫的 Enter 打開論文、Esc 清掉選取） */
  window.addEventListener("keydown", (e) => {
    if (!isOpen()) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === "Tab" || e.key.toLowerCase() === "w")) return;  // 桌面版換分頁、關分頁照常
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "Tab") trapTab(e);
    e.stopPropagation();
  }, true);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addButton);
  else addButton();
})(window.PR);
