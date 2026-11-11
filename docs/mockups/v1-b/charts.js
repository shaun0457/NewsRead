/* Mockup B 的靜態圖：外觀接近 lightweight-charts（K 線）和 ECharts（輪動圖、折線），
   資料是用固定種子產生的假資料，不是真實行情。只給 mockup 用，正式版直接用那兩個元件。

   <div data-chart="kline" data-seed="3" data-n="90" data-marks="60:news:A 級公告,72:me:你 加強·中" ...>
   <div data-chart="rrg" data-series='[{"n":"800V DC","pts":[[99,101],[101,102]]}]'>
   <div data-chart="line" data-labels='["Q1","Q2"]' data-series='[{"n":"champion","c":"ai","v":[0.21,0.24]}]'>
*/
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  let uid = 0;

  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function svg(w, h, label) {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", `0 0 ${w} ${h}`);
    s.setAttribute("role", "img");
    s.setAttribute("aria-label", label || "範例圖表");
    s.setAttribute("class", "chart-svg");
    return s;
  }
  function add(parent, tag, attrs, text) {
    const e = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
    if (text != null) e.textContent = text;
    parent.appendChild(e);
    return e;
  }
  function tip(e, text) { add(e, "title", {}, text); return e; }
  function json(s, fallback) { try { return s ? JSON.parse(s) : fallback; } catch (_) { return fallback; } }
  function fmt(v) { return v >= 1000 ? Math.round(v).toLocaleString("en-US") : v >= 100 ? v.toFixed(1) : v.toFixed(2); }

  /* 交易日：從 2026-11-10 往回數，跳過週末（mockup 不管假日） */
  function days(n, end) {
    const out = [];
    const d = new Date(end || "2026-11-10T00:00:00Z");
    while (out.length < n) {
      const w = d.getUTCDay();
      if (w !== 0 && w !== 6) out.unshift(`${d.getUTCMonth() + 1}/${d.getUTCDate()}`);
      d.setUTCDate(d.getUTCDate() - 1);
    }
    return out;
  }

  function marks(s) {
    return (s || "").split(",").map((x) => x.trim()).filter(Boolean).map((x) => {
      const [i, type, ...rest] = x.split(":");
      return { i: +i, type, label: rest.join(":") };
    });
  }

  /* ---------- K 線（lightweight-charts 外觀） ---------- */
  function kline(el) {
    const n = +el.dataset.n || 90;
    const r = rng(+el.dataset.seed || 7);
    const drift = +(el.dataset.drift || 0.002);
    let p = +el.dataset.p || 100;
    const bars = [];
    for (let i = 0; i < n; i++) {
      const o = p;
      const ch = (r() - 0.5) * 0.045 + drift;
      const c = Math.max(1, o * (1 + ch));
      bars.push({ o, c, hi: Math.max(o, c) * (1 + r() * 0.015), lo: Math.min(o, c) * (1 - r() * 0.015), v: 0.5 + r() + (Math.abs(ch) > 0.025 ? 1.1 : 0) });
      p = c;
    }
    const ms = marks(el.dataset.marks);
    ms.forEach((m) => { if (bars[m.i] && m.type === "news") bars[m.i].v *= 1.7; });
    const gap = (el.dataset.gap || "").split("-").map(Number);
    const mask = el.dataset.mask != null ? +el.dataset.mask : null;
    const labels = days(n, el.dataset.end);

    const W = 720, H = 300, PR = 58, L = 6, top = 22, ph = 190, vt = 226, vh = 50;
    const step = (W - PR - L) / n, bw = Math.max(2, step * 0.62);
    const hi = Math.max(...bars.map((b) => b.hi)) * 1.01, lo = Math.min(...bars.map((b) => b.lo)) * 0.99;
    const x = (i) => L + i * step + step / 2;
    const y = (v) => top + ((hi - v) / (hi - lo)) * ph;
    const vmax = Math.max(...bars.map((b) => b.v));
    const s = svg(W, H, el.getAttribute("aria-label") || "範例 K 線");
    const id = `m${++uid}`;
    const defs = add(s, "defs");
    const pat = add(defs, "pattern", { id: `${id}h`, width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    add(pat, "rect", { width: 8, height: 8, class: "k-mask-bg" });
    add(pat, "line", { x1: 0, y1: 0, x2: 0, y2: 8, class: "k-mask-ln" });

    for (let g = 0; g <= 4; g++) {
      const v = lo + ((hi - lo) * g) / 4;
      add(s, "line", { x1: L, x2: W - PR, y1: y(v), y2: y(v), class: "k-grid" });
      add(s, "text", { x: W - PR + 6, y: y(v) + 4, class: "k-ax" }, fmt(v));
    }
    const every = Math.ceil(n / 6);
    labels.forEach((t, i) => { if (i % every === 0) add(s, "text", { x: x(i), y: H - 4, class: "k-ax", "text-anchor": "middle" }, t); });

    if (el.dataset.bench) {  // 基準指數（換算到同一個起點）
      const rb = rng(+el.dataset.seed + 99);
      let b = bars[0].o; const pts = [];
      for (let i = 0; i < n; i++) { b *= 1 + (rb() - 0.5) * 0.02 + 0.0006; pts.push(`${x(i)},${y(Math.min(hi, Math.max(lo, b)))}`); }
      add(s, "polyline", { points: pts.join(" "), class: "k-bench" });
    }

    bars.forEach((b, i) => {
      const up = b.c >= b.o;
      const cls = up ? "k-up" : "k-dn";
      add(s, "line", { x1: x(i), x2: x(i), y1: y(b.hi), y2: y(b.lo), class: `${cls} k-wick` });
      add(s, "rect", { x: x(i) - bw / 2, y: y(Math.max(b.o, b.c)), width: bw, height: Math.max(1, Math.abs(y(b.o) - y(b.c))), class: cls });
      add(s, "rect", { x: x(i) - bw / 2, y: vt + vh - (b.v / vmax) * vh, width: bw, height: (b.v / vmax) * vh, class: `${cls} k-vol` });
    });

    if (gap.length === 2 && !isNaN(gap[0])) {
      const gx = x(gap[0]) - step / 2, gw = (gap[1] - gap[0] + 1) * step;
      add(s, "rect", { x: gx, y: top, width: gw, height: vt + vh - top, fill: `url(#${id}h)`, class: "k-gap" });
      add(s, "text", { x: gx + gw / 2, y: top + 14, class: "k-note", "text-anchor": "middle" }, el.dataset.gapLabel || "停牌 · 無法打分");
    }
    if (mask != null) {
      const mx = x(mask) + step / 2;
      add(s, "rect", { x: mx, y: top - 6, width: W - PR - mx, height: vt + vh - top + 6, fill: `url(#${id}h)`, class: "k-mask" });
      add(s, "text", { x: (mx + W - PR) / 2, y: top + ph / 2, class: "k-note", "text-anchor": "middle" }, el.dataset.maskLabel || "發布之後的價格先遮住");
      add(s, "text", { x: (mx + W - PR) / 2, y: top + ph / 2 + 16, class: "k-note sm", "text-anchor": "middle" }, "判斷完再顯示");
    }

    ms.forEach((m) => {
      const b = bars[m.i];
      if (!b) return;
      const cx = x(m.i);
      let e;
      if (m.type === "news") { e = add(s, "circle", { cx, cy: y(b.hi) - 9, r: 5, class: "mk-news" }); }
      else if (m.type === "me") { const yy = y(b.lo) + 8; e = add(s, "path", { d: `M${cx} ${yy} l6 10 h-12 z`, class: "mk-me" }); }
      else if (m.type === "ai") { const yy = y(b.lo) + 13; e = add(s, "path", { d: `M${cx} ${yy - 5} l5 5 l-5 5 l-5 -5 z`, class: "mk-ai" }); }
      else if (m.type === "kol") { e = add(s, "rect", { x: cx - 4.5, y: y(b.hi) - 22, width: 9, height: 9, class: "mk-kol" }); }
      else if (m.type === "pred") {
        add(s, "line", { x1: cx, x2: cx, y1: top - 8, y2: vt + vh, class: "mk-pred-ln" });
        e = add(s, "path", { d: `M${cx} ${top - 12} h16 l-4 5 l4 5 h-16 z`, class: "mk-pred" });
      } else if (m.type === "due") {
        add(s, "line", { x1: cx, x2: cx, y1: top - 8, y2: vt + vh, class: "mk-due-ln" });
        e = add(s, "text", { x: cx + 3, y: top - 2, class: "k-note sm" }, "到期");
      } else if (m.type === "pub") {
        add(s, "line", { x1: cx, x2: cx, y1: top - 8, y2: vt + vh, class: "mk-pub-ln" });
        e = add(s, "text", { x: cx - 3, y: top - 10, class: "k-note sm", "text-anchor": "end" }, "這則發布");
      }
      if (e && m.label) tip(e, `${labels[m.i]} · ${m.label}`);
    });

    const last = bars[mask != null ? Math.min(mask, n - 1) : n - 1];
    const ly = y(last.c);
    add(s, "rect", { x: W - PR + 2, y: ly - 9, width: PR - 4, height: 18, rx: 2, class: last.c >= last.o ? "k-up" : "k-dn" });
    add(s, "text", { x: W - PR + 6, y: ly + 4, class: "k-last" }, fmt(last.c));
    add(s, "text", { x: L + 4, y: vt - 6, class: "k-tv" }, "TradingView Lightweight Charts™");
    el.replaceChildren(s);
  }

  /* ---------- 相對輪動圖（ECharts scatter 外觀） ---------- */
  function rrg(el) {
    const series = json(el.dataset.series, []);
    const W = 540, H = 430, L = 44, R = 14, T = 14, B = 40;
    const all = series.flatMap((s) => s.pts);
    const span = Math.max(3, ...all.map(([a, b]) => Math.max(Math.abs(a - 100), Math.abs(b - 100)))) * 1.15;
    const x = (v) => L + ((v - (100 - span)) / (2 * span)) * (W - L - R);
    const y = (v) => T + (((100 + span) - v) / (2 * span)) * (H - T - B);
    const s = svg(W, H, "範例相對輪動圖");
    const q = [["q-imp", 100 - span, 100 + span, "轉強"], ["q-lead", 100, 100 + span, "領先"], ["q-weak", 100, 100, "轉弱"], ["q-lag", 100 - span, 100, "落後"]];
    q.forEach(([cls, x0, y0, name]) => {
      add(s, "rect", { x: x(x0), y: y(y0), width: x(x0 + span) - x(x0), height: y(y0 - span) - y(y0), class: cls });
      const tx = x0 < 100 ? x(x0) + 8 : x(x0 + span) - 8;
      const ty = y0 > 100 ? y(y0) + 18 : y(y0 - span) - 8;
      add(s, "text", { x: tx, y: ty, class: `q-name ${cls}-t`, "text-anchor": x0 < 100 ? "start" : "end" }, name);
    });
    add(s, "line", { x1: x(100), x2: x(100), y1: T, y2: H - B, class: "r-axis" });
    add(s, "line", { x1: L, x2: W - R, y1: y(100), y2: y(100), class: "r-axis" });
    [-2, -1, 1, 2].forEach((k) => {
      const v = 100 + (k * span) / 2.3;
      add(s, "text", { x: x(v), y: H - B + 14, class: "k-ax", "text-anchor": "middle" }, v.toFixed(1));
      add(s, "text", { x: L - 6, y: y(v) + 4, class: "k-ax", "text-anchor": "end" }, v.toFixed(1));
    });
    add(s, "text", { x: (L + W - R) / 2, y: H - 6, class: "r-lbl", "text-anchor": "middle" }, "相對強度（÷ 基準，平滑後標準化）→");
    add(s, "text", { x: 12, y: (T + H - B) / 2, class: "r-lbl", "text-anchor": "middle", transform: `rotate(-90 12 ${(T + H - B) / 2})` }, "相對動能 →");
    series.forEach((ser, k) => {
      const g = add(s, "g", { class: `s${ser.c != null ? ser.c : k % 6}${ser.bf ? " bf" : ""}${ser.dim ? " dim" : ""}` });
      add(g, "polyline", { points: ser.pts.map(([a, b]) => `${x(a)},${y(b)}`).join(" "), class: "r-trail" });
      ser.pts.forEach(([a, b], i) => {
        const lastPt = i === ser.pts.length - 1;
        tip(add(g, "circle", { cx: x(a), cy: y(b), r: lastPt ? 5.5 : 2.6, class: lastPt ? "r-head" : "r-dot" }), `${ser.n} · ${ser.pts.length - 1 - i === 0 ? "本週" : `${ser.pts.length - 1 - i} 週前`}`);
      });
      const [la, lb] = ser.pts[ser.pts.length - 1];
      add(g, "text", { x: x(la) + 8, y: y(lb) - 7, class: "r-name" }, ser.n + (ser.bf ? "（回推）" : ""));
    });
    el.replaceChildren(s);
  }

  /* ---------- 折線（ECharts line 外觀） ---------- */
  function line(el) {
    const series = json(el.dataset.series, []);
    const labels = json(el.dataset.labels, []);
    const W = 640, H = 230, L = 44, R = 14, T = 30, B = 26;
    const vals = series.flatMap((s) => s.v.filter((v) => v != null));
    let mn = el.dataset.min != null ? +el.dataset.min : Math.min(...vals);
    let mx = el.dataset.max != null ? +el.dataset.max : Math.max(...vals);
    if (mn === mx) { mn -= 1; mx += 1; }
    const n = Math.max(...series.map((s) => s.v.length));
    const x = (i) => L + (n === 1 ? 0.5 : i / (n - 1)) * (W - L - R);
    const y = (v) => T + ((mx - v) / (mx - mn)) * (H - T - B);
    const s = svg(W, H, el.getAttribute("aria-label") || "範例折線圖");
    for (let g = 0; g <= 4; g++) {
      const v = mn + ((mx - mn) * g) / 4;
      add(s, "line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "k-grid" });
      add(s, "text", { x: L - 6, y: y(v) + 4, class: "k-ax", "text-anchor": "end" }, el.dataset.pct ? `${(v * 100).toFixed(0)}%` : v.toFixed(Math.abs(mx - mn) < 1 ? 2 : 1));
    }
    labels.forEach((t, i) => add(s, "text", { x: x(i), y: H - 6, class: "k-ax", "text-anchor": "middle" }, t));
    if (el.dataset.ref != null) {
      const rv = +el.dataset.ref;
      add(s, "line", { x1: L, x2: W - R, y1: y(rv), y2: y(rv), class: "l-ref" });
      add(s, "text", { x: W - R, y: y(rv) - 4, class: "k-note sm", "text-anchor": "end" }, el.dataset.refLabel || "");
    }
    if (el.dataset.band) {  // 標出某一段（例如變差的那一季）
      const [a, b2] = el.dataset.band.split("-").map(Number);
      add(s, "rect", { x: x(a) - 14, y: T, width: x(b2) - x(a) + 28, height: H - T - B, class: "l-band" });
    }
    let lx = L;
    series.forEach((ser) => {
      const g = add(s, "g", { class: `c-${ser.c || "ai"}${ser.dash ? " dash" : ""}` });
      const segs = []; let cur = [];
      ser.v.forEach((v, i) => { if (v == null) { if (cur.length) segs.push(cur); cur = []; } else cur.push(`${x(i)},${y(v)}`); });
      if (cur.length) segs.push(cur);
      segs.forEach((pts) => add(g, "polyline", { points: pts.join(" "), class: "l-line" }));
      ser.v.forEach((v, i) => {
        if (v == null) return;
        const thin = (ser.thin || []).includes(i);
        tip(add(g, "circle", { cx: x(i), cy: y(v), r: 3.6, class: thin ? "l-dot thin" : "l-dot" }), `${ser.n} · ${labels[i] || `第 ${i + 1} 點`} · ${v}${thin ? " · 樣本不足" : ""}`);
      });
      const lg = add(s, "g", { class: `c-${ser.c || "ai"}${ser.dash ? " dash" : ""}` });
      add(lg, "line", { x1: lx, x2: lx + 18, y1: 12, y2: 12, class: "l-line" });
      add(lg, "text", { x: lx + 23, y: 16, class: "l-leg" }, ser.n);
      lx += 34 + ser.n.length * 12.5;
    });
    el.replaceChildren(s);
  }

  const KINDS = { kline, rrg, line };
  /* 一張圖的資料寫錯只讓那張圖顯示錯誤，不影響其他圖和切換鈕 */
  function draw() {
    document.querySelectorAll("[data-chart]").forEach((el) => {
      const f = KINDS[el.dataset.chart];
      if (!f) return;
      try { f(el); } catch (err) { el.textContent = "（範例圖的資料有誤）"; console.error("mockup chart", err); }
    });
  }

  /* 價格的漲跌色依市場：台股紅漲綠跌、美股綠漲紅跌（2026-11-11 使用者決定）。mockup 用控制列切換市場看兩種 */
  function syncKc() {
    const kc = document.body.dataset.kc || "us";
    document.querySelectorAll(".mock-bar [data-set-kc]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.setKc === kc)));
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-set-kc]");
    if (!b) return;
    document.body.dataset.kc = b.dataset.setKc;
    syncKc();
  });
  syncKc();
  draw();
})();
