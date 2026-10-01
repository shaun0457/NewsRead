/* 页面开着就连着一条 WebSocket，让服务知道还有人在用。
   用 start.cmd / start.sh 启动时，页面都关了、后台任务也做完了，服务会自己退出（见 easyread/presence.py）。 */
(function () {
  "use strict";
  if (location.protocol !== "http:" || typeof WebSocket === "undefined") return;
  let retries = 0;
  function connect() {
    let ws;
    try { ws = new WebSocket("ws://" + location.host + "/api/presence"); } catch (e) { return; }
    ws.onopen = () => { retries = 0; };
    ws.onclose = () => { retries += 1; setTimeout(connect, Math.min(30000, 1000 * retries)); };  // 断了就重连（服务重启过）
  }
  connect();
})();
