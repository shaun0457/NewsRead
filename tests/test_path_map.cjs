const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function mapApi() {
  const source = fs.readFileSync(path.join(__dirname, "../easyread/web/js/research/path-map.js"), "utf8");
  const context = { window: {}, Number, String, Math };
  vm.runInNewContext(source, context);
  return context.window.PRPathMap;
}

test("reading path map renders stable paper nodes and directional citation edges", () => {
  const api = mapApi();
  const html = api.render({
    steps: [
      { paper_key: "openalex:W1", role: "基礎", paper: { title: "Foundation Paper", year: 2021, is_start_paper: true } },
      { paper_key: "openalex:W2", role: "方法", paper: { title: "Method Paper", year: 2024 } },
    ],
    selectedKey: "openalex:W1", showSequence: true, showRelations: true,
    relations: [{ source: "openalex:W2", target: "openalex:W1" }],
    view: { scale: 1, panX: 0, panY: 0 }, esc: value => String(value), labels: { start: "起點論文" },
  });
  assert.match(html, /data-path-key="openalex:W1"/);
  assert.match(html, /data-path-key="openalex:W2"/);
  assert.match(html, /rw-path-edge-sequence/);
  assert.match(html, /rw-path-edge-citation/);
  assert.match(html, /marker-end="url\(#rw-path-arrow-citation\)"/);
  assert.match(html, /起點論文/);
  assert.match(html, /marker id="rw-path-arrow-sequence" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="12" viewBox="0 0 12 12" refX="10" refY="6" orient="auto"/);
  assert.match(html, /marker id="rw-path-arrow-citation" markerUnits="userSpaceOnUse" markerWidth="12" markerHeight="12" viewBox="0 0 12 12" refX="10" refY="6" orient="auto"/);
  assert.equal((html.match(/M 2 2 L 10 6 L 2 10 z/g) || []).length, 2);
  assert.match(html, /rw-path-edge-sequence[^>]*data-from="0" data-to="1"/);
  assert.match(html, /rw-path-edge-citation[^>]*data-from="1" data-to="0"/);
});

test("rendered node sizes determine edge endpoints and the dashed line reaches its arrow", () => {
  const api = mapApi();
  const nodes = [
    { offsetLeft: 42, offsetTop: 62, offsetWidth: 218, offsetHeight: 132 },
    { offsetLeft: 334, offsetTop: 270, offsetWidth: 218, offsetHeight: 150 },
  ];
  const edge = {
    dataset: { from: "0", to: "1" }, style: {},
    classList: { contains: name => name === "rw-path-edge-sequence" },
    setAttribute(name, value) { this[name] = value; }, getTotalLength() { return 101; },
  };
  const canvas = { querySelectorAll: selector => selector === ".rw-path-node" ? nodes : [edge] };
  const stage = { addEventListener() {} };
  api.bind({ querySelector: selector => selector === ".rw-path-map-stage" ? stage : canvas }, {}, () => {});
  assert.equal(edge.d, api.edgePath(
    { x: 42, y: 62, width: 218, height: 132 },
    { x: 334, y: 270, width: 218, height: 150 },
  ));
  assert.equal(edge.style.strokeDashoffset, String(5 - 101 % 14));
});

test("all edge directions finish with a straight 10px segment into the arrow", () => {
  const api = mapApi();
  const box = (x, y) => ({ x, y, width: 218, height: 132 });
  for (const [source, target, axis, direction] of [
    [box(0, 0), box(292, 300), "y", 1],
    [box(292, 300), box(0, 0), "y", -1],
    [box(0, 0), box(292, 30), "x", 1],
    [box(292, 30), box(0, 0), "x", -1],
  ]) {
    const path = api.edgePath(source, target);
    assert.match(path, /^M .+ C .+, .+, .+ L .+$/);
    const [startX, startY, c1X, c1Y, c2X, c2Y, approachX, approachY, endX, endY] = [...path.matchAll(/-?\d+(?:\.\d+)?/g)].map(match => Number(match[0]));
    const [control, approach, end, otherControl, otherApproach, otherEnd] = axis === "x"
      ? [c2X, approachX, endX, c2Y, approachY, endY]
      : [c2Y, approachY, endY, c2X, approachX, endX];
    assert.equal(otherControl, otherApproach);
    assert.equal(otherApproach, otherEnd);
    assert.equal(end - approach, direction * 10);
    assert.ok((approach - control) * direction > 0);
    assert.ok(Number.isFinite(startX + startY + c1X + c1Y));
  }
});
