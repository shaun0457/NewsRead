/* 一键停止翻译：表头的“停止翻译”按钮（有论文在用模型时才出现），批量操作里的“停止翻译”也走这里。
   只停用模型的部分（翻译、整理原文、等确认页数的），已译的保留；原页还没渲染的照常渲染。 */
(function (PR) {
  "use strict";
  const L = PR.lib;
  const btn = PR.$("#stopAllBtn");

  // 正在或等着用模型的论文；只渲染原页的（type 为 prepare）不算
  L.modelBusy = (i) => !!(i.job && ["queued", "running", "confirm"].includes(i.job.state) && i.job.type !== "prepare");

  PR.stopJobs = async function (items, at) {
    const its = items.filter(L.modelBusy);
    if (!its.length) return PR.toast(PR.t("选中的论文没有在翻译"));
    if (!(await PR.confirm({ title: PR.t("停止 {n} 篇的翻译？", { n: its.length }), body: PR.t("已译的部分保留，之后可以接着译；还没渲染的原页照常渲染。"), ok: PR.t("停止"), danger: true, at }))) return;
    try {
      const r = await PR.api("/api/jobs/stop", { method: "POST", body: { ids: its.map((i) => i.id) } });
      PR.toast(PR.t("已停止 {n} 篇", { n: r.stopped }));
    } catch (e) { PR.toast(PR.t("停止失败：{msg}", { msg: PR.esc(e.message) })); }
    L.load();
  };

  PR.renderStopAll = function () {
    const n = L.items.filter(L.modelBusy).length;
    btn.hidden = !n || L.picking;
    btn.innerHTML = PR.icon("stop", "sm") + PR.t("停止翻译（{n}）", { n });
  };
  btn.title = PR.t("停止所有论文的翻译和原文整理，已译的部分保留");
  btn.onclick = () => PR.stopJobs(L.items, btn);
})(window.PR);
