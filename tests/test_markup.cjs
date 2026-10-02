const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function markup(realKatex = false) {
  const PR = { esc: text => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;") };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../easyread/web/js/common/markup.js"), "utf8"), {
    window: { PR }, katex: realKatex ? require("../easyread/web/vendor/katex/katex.min.js") : { renderToString: tex => '<math>' + PR.esc(tex) + '</math>' },
  });
  return PR;
}

test("bilingual headings render without requiring blank lines before the answer", () => {
  const html = markup().mdBlocks("## English (ASD-STE100)\nThe device calculates $y=Wx$.\n## 中文解释\n器件计算 $y=Wx$。");
  assert.equal((html.match(/class="md-h"/g) || []).length, 2);
  assert.ok(!html.includes("##"));
  assert.ok(html.indexOf("English") < html.indexOf("中文解释"));
  assert.equal((html.match(/<math>y=Wx<\/math>/g) || []).length, 2);
});

test("both inline math delimiter styles render inside Chinese text and bold text", () => {
  const html = markup().md(String.raw`衰减常数 **\(\alpha\)**，相位常数 $\beta$，因子 \(\left|\frac{\sinh q}{q}\right|\)。`);
  assert.ok(html.includes(String.raw`<strong><math>\alpha</math></strong>`));
  assert.ok(html.includes(String.raw`<math>\beta</math>`));
  assert.ok(html.includes(String.raw`<math>\left|\frac{\sinh q}{q}\right|</math>`));
  assert.ok(!html.includes(String.raw`\(`));
});

test("display math is extracted before paragraph splitting, including blank lines within TeX", () => {
  const tex = String.raw`\frac{1}{L}\int_0^L e^{-(a+j\beta)z}\,dz`;
  for (const [left, right] of [["$$", "$$"], ["\\[", "\\]"]]) {
    const html = markup().mdBlocks("积分：\n" + left + "\n" + tex + "\n\n= I\n" + right + "\n\n取模后。\n" + left + String.raw`\left|\frac{\sinh q}{q}\right|` + right);
    assert.equal((html.match(/class="eq"/g) || []).length, 2);
    assert.ok(html.includes('<div class="eq"><math>' + tex + '\n\n= I</math></div>'));
    assert.ok(html.includes("<p>取模后。</p>"));
    assert.ok(!html.includes(left));
  }
});

test("table pipes inside parenthesized math or code do not create extra cells", () => {
  const html = markup().mdBlocks(String.raw`| 变量 | 定义 |
| --- | --- |
| \(q\) | \(\left|\frac{\sinh q}{q}\right|\) |
| 代码 | \`a|b\` |
| 文字 | a\|b |`.replace(/\\`/g, "`"));
  assert.equal((html.match(/<td/g) || []).length, 6);
  assert.ok(html.includes(String.raw`<math>\left|\frac{\sinh q}{q}\right|</math>`));
  assert.ok(html.includes("<code>a|b</code>"));
  assert.ok(html.includes("<td>a|b</td>"));
});

test("math delimiter examples inside code remain literal and HTML stays escaped", () => {
  const html = markup().mdBlocks("格式 `\\(x\\)` 或 `$x$`。\n\n```tex\n\\[x\\]\n\n$$<script>$$\n```\n\n正文 \\(y\\)。");
  assert.ok(html.includes("<code>\\(x\\)</code>"));
  assert.ok(html.includes("<code>$x$</code>"));
  assert.ok(html.includes("<pre><code>\\[x\\]\n\n$$&lt;script&gt;$$\n</code></pre>"));
  assert.equal((html.match(/<math>/g) || []).length, 1);
  assert.ok(!html.includes("<script>"));
});

test("unfinished streamed delimiters stay readable until the matching close arrives", () => {
  const PR = markup();
  const answer = "积分：\n\\[\n\\frac{1}{L}\\int_0^L e^{-(a+j\\beta)z}\\,dz\n\\]";
  for (let i = 0; i < answer.length; i++) {
    const html = PR.mdBlocks(answer.slice(0, i));
    assert.ok(!html.includes("<math>"));
  }
  assert.equal((PR.mdBlocks(answer).match(/<math>/g) || []).length, 1);
  assert.ok(!PR.md(String.raw`价格 \$5；未闭合 \(x；转义 \\(y\\)`).includes("<math>"));
});

test("the integral, logarithm and hyperbolic expressions use the bundled KaTeX renderer", () => {
  const html = markup(true).mdBlocks(String.raw`\(\alpha\) 与 $\beta$。
\[
20\lg\left\{e^{-\alpha L/4}R^{1/2}\right\}.
\]
\[
\frac{1}{L}\int_0^L e^{-(a+j\beta)z}\,dz
\]
$$\left|\frac{\sinh q}{q}\right|$$`);
  assert.equal((html.match(/class="katex"/g) || []).length, 5);
  assert.equal((html.match(/class="katex-display"/g) || []).length, 3);
  assert.ok(!html.includes("katex-error"));
});

test("headings can precede tables and lists; their text still escapes HTML", () => {
  const html = markup().mdBlocks("## <script>unsafe</script>\n| Metric | Value |\n| --- | --- |\n| Error | 2% |\n## 中文解释\n- 误差为 **2%**。\n- 保留原值。");
  assert.ok(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes('<table class="tbl">'));
  assert.ok(html.includes("<ul>"));
  assert.ok(html.includes("<strong>2%</strong>"));
  assert.equal((html.match(/class="md-h"/g) || []).length, 2);
});

test("blank lines between numbered steps do not reset each displayed number to one", () => {
  const html = markup().mdBlocks("1. 准备器件。\n\n2. 输入 $x$。\n\n3. 读取结果。");
  assert.ok(html.includes('<ol><li>准备器件。</li></ol>'));
  assert.ok(html.includes('<ol start="2"><li>输入 <math>x</math>。</li></ol>'));
  assert.ok(html.includes('<ol start="3"><li>读取结果。</li></ol>'));
});
