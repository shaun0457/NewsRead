/* PaperRead Interactive Mindmap View (powered by mind-elixir-core) */
(function (PR) {
  "use strict";

  const getME = () => window.MindElixir?.default || window.MindElixir;

  const LIGHT_PALETTE = ["#2b5b84", "#2e7d5b", "#9c5221", "#784384", "#227093", "#b33939", "#474787", "#8b572a"];
  const DARK_PALETTE = ["#5c93c4", "#52b788", "#e07a5f", "#b5838d", "#48cae4", "#ff6b6b", "#9d8df1", "#e9c46a"];

  const ICON_EXPAND_ALL =
    '<svg class="i sm" viewBox="0 0 20 20" aria-hidden="true">' +
    '<circle cx="4" cy="10" r="2" fill="currentColor"/>' +
    '<circle cx="16" cy="4" r="1.5" fill="currentColor"/>' +
    '<circle cx="16" cy="10" r="1.5" fill="currentColor"/>' +
    '<circle cx="16" cy="16" r="1.5" fill="currentColor"/>' +
    '<path d="M6 10h4m0 0V4h4.5m-4.5 6v6h4.5m-4.5-6h4.5"/>' +
    '</svg>';

  const ICON_COLLAPSE_MAIN =
    '<svg class="i sm" viewBox="0 0 20 20" aria-hidden="true">' +
    '<circle cx="4" cy="10" r="2" fill="currentColor"/>' +
    '<circle cx="12" cy="5" r="1.5" fill="currentColor"/>' +
    '<circle cx="12" cy="15" r="1.5" fill="currentColor"/>' +
    '<path d="M6 10h3a1 1 0 0 0 1-1V5h1m-1 5a1 1 0 0 1 1 1v4h1"/>' +
    '<path d="M17 5h-3m3 10h-3"/>' +
    '</svg>';

  function isDarkTheme() {
    const ds = document.documentElement.dataset.theme;
    if (ds === "dark") return true;
    if (ds === "light") return false;
    const pref = PR?.prefs?.theme;
    if (pref === "dark") return true;
    if (pref === "light") return false;
    return Boolean(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function getTheme(isDark = isDarkTheme()) {
    return {
      name: isDark ? "PaperReadDark" : "PaperReadLight",
      type: isDark ? "dark" : "light",
      palette: isDark ? DARK_PALETTE : LIGHT_PALETTE,
      cssVar: {
        "--bgcolor": isDark ? "#1a1917" : "#f6f3ec",
        "--color": isDark ? "#ddd7cb" : "#23211d",
        "--main-bgcolor": isDark ? "#22211e" : "#fbfaf6",
        "--main-color": isDark ? "#ede9e0" : "#22201d",
        "--main-border": isDark ? "1px solid #3e3b35" : "1px solid #d8d0c2",
        "--root-bgcolor": isDark ? "#2c4866" : "#244d73",
        "--root-color": "#ffffff",
        "--root-border-color": isDark ? "#3f678f" : "#1b3c5a",
        "--root-radius": "8px",
        "--main-radius": "6px",
        "--selected": isDark ? "#86b8c9" : "#2d6173",
        "--accent-color": isDark ? "#86b8c9" : "#2d6173",
        "--topic-padding": "6px 10px",
        "--node-gap-x": "26px",
        "--node-gap-y": "12px",
        "--main-gap-x": "32px",
        "--main-gap-y": "16px",
      },
    };
  }

  /* 將 Mermaid mindmap 文字解析為 MindElixirData 樹狀結構 */
  function parseToData(source, fallbackTitle = PR.t("論文心智圖")) {
    let rawRoot = null;
    const lines = String(source || "").split(/\r?\n/);
    const parsedLines = [];

    for (const rawLine of lines) {
      if (!rawLine.trim() || /^\s*mindmap\s*$/i.test(rawLine)) continue;
      const spaces = (rawLine.match(/^\s*/) || [""])[0].replace(/\t/g, "  ").length;
      let label = rawLine.trim();

      // 去除 Mermaid 節點形狀語法及自訂 ID: root((...)), ((...)), [...], {...}, (...)
      label = label.replace(/^[\w-]+(?=\(\(|\[|\{|\()/, "");
      label = label
        .replace(/^root\(\((.*)\)\)$/i, "$1")
        .replace(/^\(\((.*)\)\)$/, "$1")
        .replace(/^\((.*)\)$/, "$1")
        .replace(/^\[(.*)\]$/, "$1")
        .replace(/^\{(.*)\}$/, "$1")
        .trim();

      // 去除兩側包裹之單雙引號
      label = label.replace(/^["'](.*)["']$/, "$1").trim();

      if (!label) continue;
      parsedLines.push({ depth: spaces, label });
    }

    if (!parsedLines.length) {
      return {
        nodeData: {
          id: "me-root",
          topic: fallbackTitle,
          expanded: true,
          children: [],
        },
        direction: 1,
      };
    }

    let nodeSeq = 1;
    const makeNode = (label) => ({
      id: "me-node-" + nodeSeq++,
      topic: label,
      expanded: true,
      children: [],
    });

    const stack = [{ depth: -1, node: null }];

    for (const item of parsedLines) {
      const node = makeNode(item.label);
      while (stack.length > 1 && stack.at(-1).depth >= item.depth) {
        stack.pop();
      }
      const parent = stack.at(-1).node;
      if (parent) {
        parent.children.push(node);
      } else if (!rawRoot) {
        rawRoot = node;
      } else {
        // 多個頂層分支，將它們收攏到一個共同根節點下
        if (rawRoot.id !== "me-root") {
          const virtualRoot = {
            id: "me-root",
            topic: fallbackTitle,
            expanded: true,
            children: [rawRoot],
          };
          rawRoot = virtualRoot;
        }
        rawRoot.children.push(node);
      }
      stack.push({ depth: item.depth, node });
    }

    const finalRoot = rawRoot || makeNode(fallbackTitle);
    finalRoot.id = "me-root";
    finalRoot.expanded = true;

    // 預設將第一層主分支以外的下層節點收攏（即第一層子節點 expanded 設為 false）
    if (Array.isArray(finalRoot.children)) {
      for (const child of finalRoot.children) {
        child.expanded = false;
      }
    }

    return {
      nodeData: finalRoot,
      direction: 1, // 預設 1: 向右展開；亦可切換為 2: 雙側分佈
    };
  }

  /* 封裝單一心智圖畫布控制與工具列行為 */
  function mount(container, options = {}) {
    const ME = getME();
    if (!ME) return null;

    const {
      data,
      direction = 1,
      compact = false,
      onOpenModal = null,
      showModalBtn = true,
      showDirBtn = true,
      zoomControls = true,
      expandControls = true,
    } = options;

    container.innerHTML = "";
    container.classList.add("mm-stage-wrap");

    // 畫布容器
    const canvasWrap = document.createElement("div");
    canvasWrap.className = "mm-canvas-host";
    container.appendChild(canvasWrap);

    // 建立工具列
    const toolbar = document.createElement("div");
    toolbar.className = "mm-toolbar";
    let tbHtml = "";

    if (expandControls) {
      tbHtml += '<button type="button" class="btn icon sm" data-mm-act="expand-all" title="' + PR.t("全部展開") + '" aria-label="' + PR.t("全部展開") + '">' + ICON_EXPAND_ALL + '</button>';
      tbHtml += '<button type="button" class="btn icon sm" data-mm-act="collapse-main" title="' + PR.t("收合至主分支") + '" aria-label="' + PR.t("收合至主分支") + '">' + ICON_COLLAPSE_MAIN + '</button>';
      tbHtml += '<span class="mm-tb-sep"></span>';
    }

    if (showDirBtn) {
      tbHtml += '<button type="button" class="btn sm mm-btn-dir" data-mm-act="toggle-dir" title="' + PR.t("切換佈局方向（向右／雙側）") + '">' + (direction === 2 ? PR.t("雙側") : PR.t("向右")) + '</button>';
      tbHtml += '<span class="mm-tb-sep"></span>';
    }

    if (zoomControls) {
      tbHtml += '<button type="button" class="btn icon sm" data-mm-act="zoom-out" title="' + PR.t("縮小") + '">−</button>';
      tbHtml += '<span class="mm-zoom-label" data-mm-zoom>100%</span>';
      tbHtml += '<button type="button" class="btn icon sm" data-mm-act="zoom-in" title="' + PR.t("放大") + '">+</button>';
      tbHtml += '<button type="button" class="btn sm" data-mm-act="fit-center" title="' + PR.t("適應視窗並置中") + '">' + PR.t("適應") + '</button>';
    }

    if (showModalBtn && onOpenModal) {
      tbHtml += '<span class="mm-tb-sep"></span>';
      tbHtml += '<button type="button" class="btn sm accent mm-btn-modal" data-mm-act="open-modal" title="' + PR.t("詳細檢視心智圖") + '">' + PR.t("詳細檢視") + '</button>';
    }

    toolbar.innerHTML = tbHtml;
    container.appendChild(toolbar);

    // 實例化 MindElixir
    let curDirection = direction;
    const isDark = isDarkTheme();
    const meOptions = {
      el: canvasWrap,
      direction: curDirection,
      draggable: false,
      editable: false,
      contextMenu: false,
      toolBar: false,
      keypress: false,
      mouseSelectionButton: 2, // 2: 右鍵選取，讓左鍵自然為拖曳平移
      compact,
      theme: getTheme(isDark),
      markdown: (text) => (PR.md ? PR.md(String(text || ""), { cite: false, xref: false }) : (PR.titleHtml ? PR.titleHtml(String(text || "")) : PR.esc(String(text || "")))),
    };

    let instance = null;
    try {
      instance = new ME(meOptions);
      const mindData = data ? JSON.parse(JSON.stringify(data)) : ME.new(PR.t("論文心智圖"));
      mindData.direction = curDirection;
      mindData.theme = getTheme(isDark);
      instance.init(mindData);
    } catch (err) {
      console.error("[MindElixir] 初始化失敗:", err); // i18n-ok
      container.innerHTML = '<div class="rp-map-error"><span>' + PR.esc(err.message) + '</span></div>';
      return null;
    }

    // 點擊節點切換展開／收合（排除拖曳移動畫布）
    let mdX = 0, mdY = 0, isDrag = false;
    if (typeof canvasWrap.addEventListener === "function") {
      canvasWrap.addEventListener("mousedown", (e) => {
        mdX = e.clientX;
        mdY = e.clientY;
        isDrag = false;
      });
      canvasWrap.addEventListener("mousemove", (e) => {
        if (Math.hypot(e.clientX - mdX, e.clientY - mdY) > 5) {
          isDrag = true;
        }
      });
      canvasWrap.addEventListener("click", (e) => {
        if (isDrag) return;
        if (e.target.closest("a, button, input, select, textarea")) return;
        const tpc = e.target.closest("me-tpc");
        if (!tpc || !instance) return;
        if (tpc.parentElement?.tagName === "ME-ROOT") return;
        const nodeObj = tpc.nodeObj;
        if (nodeObj && Array.isArray(nodeObj.children) && nodeObj.children.length > 0) {
          instance.expandNode(tpc);
        }
      });
    }

    const zoomLabel = toolbar.querySelector("[data-mm-zoom]");
    const updateZoomDisplay = () => {
      if (zoomLabel && instance) {
        zoomLabel.textContent = Math.round((instance.scaleVal || 1) * 100) + "%";
      }
    };

    const fitAndCenter = () => {
      if (!instance) return;
      try {
        instance.scaleFit();
        instance.toCenter();
        updateZoomDisplay();
      } catch (e) { /* ignore */ }
    };

    // 延遲初次適應與置中以確保容器已完成 layout
    setTimeout(fitAndCenter, 60);

    // 工具列事件
    toolbar.onclick = (e) => {
      const btn = e.target.closest("[data-mm-act]");
      if (!btn || !instance) return;
      const act = btn.dataset.mmAct;

      if (act === "zoom-in") {
        instance.scale(Math.min(2.5, (instance.scaleVal || 1) + 0.15));
        updateZoomDisplay();
      } else if (act === "zoom-out") {
        instance.scale(Math.max(0.2, (instance.scaleVal || 1) - 0.15));
        updateZoomDisplay();
      } else if (act === "fit-center") {
        fitAndCenter();
      } else if (act === "toggle-dir") {
        curDirection = curDirection === 2 ? 1 : 2;
        btn.textContent = curDirection === 2 ? PR.t("雙側") : PR.t("向右");
        if (curDirection === 2) instance.initSide();
        else instance.initRight();
        fitAndCenter();
      } else if (act === "expand-all") {
        try {
          const rootEl = instance.findEle("me-root");
          if (rootEl) instance.expandNodeAll(rootEl, true);
          fitAndCenter();
        } catch (err) { /* ignore */ }
      } else if (act === "collapse-main") {
        try {
          const rootEl = instance.findEle("me-root");
          if (rootEl) {
            instance.expandNodeAll(rootEl, true);
            const children = instance.nodeData?.children || [];
            for (const c of children) {
              const el = instance.findEle(c.id);
              if (el) instance.expandNodeAll(el, false);
            }
          }
          fitAndCenter();
        } catch (err) { /* ignore */ }
      } else if (act === "open-modal" && onOpenModal) {
        onOpenModal();
      }
    };

    // 監聽深色模式切換
    const ObserverClass = window.MutationObserver || globalThis.MutationObserver;
    let observer = null;
    if (ObserverClass) {
      observer = new ObserverClass(() => {
        if (instance) {
          instance.changeTheme(getTheme(isDarkTheme()), true);
        }
      });
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }

    return {
      instance,
      fitAndCenter,
      destroy() {
        observer?.disconnect?.();
        try { instance?.destroy?.(); } catch (e) { /* ignore */ }
      },
    };
  }

  /* 側邊欄內嵌入心智圖（預設單側收合狀態） */
  function renderPanel(container, generated, options = {}) {
    const rawMermaid = generated?.mermaid || "";
    const title = options.title || PR.t("論文心智圖");
    const mindData = parseToData(rawMermaid, title);

    const onOpenModal = () => {
      openModal(mindData, { title, onRegenerate: options.onRegenerate });
    };

    const ctrl = mount(container, {
      data: mindData,
      direction: 1, // 側邊欄空間較窄，預設向右單向展開（單側收合狀態）
      compact: true,
      onOpenModal,
      showModalBtn: true,
      showDirBtn: false,
      zoomControls: true,
      expandControls: true,
    });

    return ctrl;
  }

  /* 滿版大視窗 Modal 檢視（預設雙側收合狀態） */
  function openModal(mindData, options = {}) {
    const backdrop = PR.$("#mindmapDlg");
    if (!backdrop) return;
    const dialog = backdrop.querySelector(".dialog");
    if (!dialog) return;

    const title = options.title || PR.t("論文心智圖");
    const titleDisp = PR.titleHtml ? PR.titleHtml(title) : PR.esc(title);

    const isDark = isDarkTheme();
    dialog.innerHTML =
      '<div class="mm-modal-head">' +
        '<div class="mm-modal-title"><b>' + PR.t("論文心智圖") + '</b><span class="mm-modal-sub">' + titleDisp + '</span></div>' +
        '<div class="mm-modal-actions">' +
          (options.onRegenerate ? '<button type="button" class="btn sm line" data-mm-modal="regen">' + PR.icon("sparkle", "sm") + PR.t("重新產生") + '</button>' : '') +
          '<button type="button" class="btn icon sm theme-btn" data-mm-modal="theme" title="' + (isDark ? PR.t("换成浅色") : PR.t("换成深色")) + '">' +
            (PR.icon ? PR.icon(isDark ? "sun" : "moon", "sm") : '') +
          '</button>' +
          '<button type="button" class="btn icon sm" data-mm-modal="close" title="' + PR.t("關閉") + '" aria-label="' + PR.t("關閉") + '">×</button>' +
        '</div>' +
      '</div>' +
      '<div class="mm-modal-body" id="mmModalStage"></div>';

    backdrop.classList.add("open");

    // 複製資料以維持雙欄收合預設，並套用最新深淺色主題
    const modalData = mindData ? JSON.parse(JSON.stringify(mindData)) : null;
    if (modalData) {
      modalData.theme = getTheme(isDark);
      if (modalData.nodeData?.children) {
        for (const child of modalData.nodeData.children) {
          child.expanded = false;
        }
      }
    }

    const stage = dialog.querySelector("#mmModalStage");
    const ctrl = mount(stage, {
      data: modalData,
      direction: 2, // 大視窗預設使用視野開闊的雙側放射佈局（雙欄收合狀態）
      compact: false,
      showModalBtn: false,
      showDirBtn: true,
      zoomControls: true,
      expandControls: true,
    });

    const close = () => {
      backdrop.classList.remove("open");
      ctrl?.destroy();
      dialog.innerHTML = "";
      document.removeEventListener("keydown", onKeyDown);
    };

    const onKeyDown = (e) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKeyDown);

    backdrop.onclick = (e) => {
      if (e.target === backdrop || e.target.closest('[data-mm-modal="close"]')) {
        close();
      } else if (e.target.closest('[data-mm-modal="regen"]')) {
        close();
        if (options.onRegenerate) options.onRegenerate();
      } else if (e.target.closest('[data-mm-modal="theme"]')) {
        if (typeof PR.toggleTheme === "function") {
          PR.toggleTheme();
        } else {
          const next = isDarkTheme() ? "light" : "dark";
          document.documentElement.dataset.theme = next;
        }
        const currentDark = isDarkTheme();
        const themeBtn = dialog.querySelector('[data-mm-modal="theme"]');
        if (themeBtn && PR.icon) {
          themeBtn.innerHTML = PR.icon(currentDark ? "sun" : "moon", "sm");
          themeBtn.title = currentDark ? PR.t("换成浅色") : PR.t("换成深色");
        }
        if (ctrl?.instance) {
          ctrl.instance.changeTheme(getTheme(currentDark), true);
        }
      }
    };
  }

  /* 匯出為 PNG 格式 Blob 物件（完整展開節點） */
  async function exportPngBlob(sourceOrData, options = {}) {
    const ME = getME();
    if (!ME) throw new Error("MindElixir not loaded");

    let data = null;
    if (typeof sourceOrData === "string") {
      data = parseToData(sourceOrData, options.title);
    } else if (sourceOrData && sourceOrData.nodeData) {
      data = JSON.parse(JSON.stringify(sourceOrData));
    } else {
      throw new Error("Invalid mindmap data");
    }

    // 完整展開所有分支以產出完整圖像
    function expandAll(node) {
      if (!node) return;
      node.expanded = true;
      if (Array.isArray(node.children)) {
        node.children.forEach(expandAll);
      }
    }
    expandAll(data.nodeData);
    data.direction = options.direction || 2;

    const host = document.createElement("div");
    host.style.cssText = "position:fixed;left:-99999px;top:-99999px;width:2400px;height:1800px;visibility:hidden;pointer-events:none;z-index:-1000;";
    document.body.appendChild(host);

    let tempInst = null;
    try {
      tempInst = new ME({
        el: host,
        direction: data.direction,
        draggable: false,
        editable: false,
        contextMenu: false,
        toolBar: false,
        keypress: false,
        mouseSelectionButton: 2,
        compact: false,
        theme: getTheme(false),
        markdown: (text) => (PR.md ? PR.md(String(text || ""), { cite: false, xref: false }) : (PR.titleHtml ? PR.titleHtml(String(text || "")) : PR.esc(String(text || "")))),
      });
      tempInst.init(data);
      const rootEl = tempInst.findEle("me-root");
      if (rootEl) {
        try { tempInst.expandNodeAll(rootEl, true); } catch (e) { /* ignore */ }
      }

      // 擷取並內嵌 KaTeX 樣式，確保 SVG/PNG 中數學符號排版與字體正確呈現，且隱藏重複之 MathML 輔助標籤
      let katexStyles =
        ".katex { font: normal 1.1em KaTeX_Main, Times New Roman, serif; line-height: 1.2; text-indent: 0; text-rendering: auto; border-color: currentColor; display: inline-block; }\n" +
        ".katex .katex-mathml { clip: rect(1px, 1px, 1px, 1px); border: 0; height: 1px; overflow: hidden; padding: 0; position: absolute; width: 1px; display: none !important; }\n" +
        ".katex .katex-html { display: inline-block; }\n" +
        ".katex .base { position: relative; display: inline-block; white-space: nowrap; width: min-content; }\n" +
        ".katex .strut { display: inline-block; }\n" +
        ".katex .msupsub { text-align: left; }\n" +
        ".katex .vlist-t { display: inline-table; table-layout: fixed; }\n" +
        ".katex .vlist-r { display: table-row; }\n" +
        ".katex .vlist { display: table-cell; vertical-align: bottom; position: relative; }\n" +
        ".katex .mord { display: inline-block; }\n" +
        ".katex .mathnormal { font-style: italic; }\n" +
        ".katex .mtight { font-size: 0.7em; }\n" +
        "me-tpc, div { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }\n";

      try {
        if (typeof document !== "undefined" && document.styleSheets) {
          for (const sheet of document.styleSheets) {
            if (sheet.href && sheet.href.includes("katex")) {
              try {
                for (const rule of sheet.cssRules) {
                  katexStyles += rule.cssText + "\n";
                }
              } catch (_) {}
            }
          }
        }
      } catch (_) {}

      await new Promise((resolve) => setTimeout(resolve, 80));
      return await tempInst.exportPng(false, katexStyles);
    } finally {
      try { tempInst?.destroy?.(); } catch (e) { /* ignore */ }
      host.remove();
    }
  }

  /* 匯出為 PNG Base64 字串（用於後端 API 或下載傳輸） */
  async function exportPngBase64(sourceOrData, options = {}) {
    const blob = await exportPngBlob(sourceOrData, options);
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const res = String(reader.result || "");
        const base64 = res.includes(",") ? res.split(",")[1] : res;
        resolve(base64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  PR.mindmap = {
    parseToData,
    getTheme,
    mount,
    renderPanel,
    openModal,
    exportPngBlob,
    exportPngBase64,
  };
})(window.PR);
