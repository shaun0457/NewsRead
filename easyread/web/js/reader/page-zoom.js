/* Original-page zoom keeps the same page detail in view and leaves text size alone. */
(function (PR) {
  "use strict";
  PR.initPageZoom = function ({ scroller, beforeZoom, afterZoom }) {
    let value = 1;
    const panel = PR.$("#pageview");
    const label = PR.$(".pv-zoom-value");
    function set(next) {
      next = Math.max(0.5, Math.min(3, Math.round(next * 4) / 4));
      if (next === value) return;
      const view = scroller.getBoundingClientRect();
      const x = view.left + scroller.clientWidth / 2;
      const y = view.top + scroller.clientHeight / 2;
      const pages = Array.from(scroller.children);
      const anchor = pages.find(p => p.getBoundingClientRect().bottom > y) || pages[pages.length - 1];
      const old = anchor?.getBoundingClientRect();
      const fx = old?.width ? (x - old.left) / old.width : 0.5;
      const fy = old?.height ? (y - old.top) / old.height : 0;
      beforeZoom();
      value = next;
      scroller.style.setProperty("--pv-zoom", String(value));
      label.textContent = Math.round(value * 100) + "%";
      PR.$('[data-pv-zoom="out"]').disabled = value <= 0.5;
      PR.$('[data-pv-zoom="in"]').disabled = value >= 3;
      if (anchor) {
        const rect = anchor.getBoundingClientRect();
        scroller.scrollLeft += rect.left + fx * rect.width - x;
        scroller.scrollTop += rect.top + fy * rect.height - y;
      }
      afterZoom();
    }
    panel.addEventListener("click", e => {
      const button = e.target.closest("[data-pv-zoom]");
      if (!button) return;
      const action = button.dataset.pvZoom;
      set(action === "fit" ? 1 : value + (action === "in" ? 0.25 : -0.25));
    });
    scroller.addEventListener("wheel", e => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      set(value + (e.deltaY < 0 ? 0.25 : -0.25));
    }, { passive: false });
    return { get value() { return value; }, set };
  };
})(window.PR);
