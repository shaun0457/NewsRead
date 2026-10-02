const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function reader(block, edits = {}) {
  let html = '';
  const node = { classList: { contains: () => false }, querySelector: () => null, replaceWith() {} };
  const PR = {
    state: { reader: { edits }, paper: { blocks: [block] } },
    on() {}, emit() {}, esc: String, md: String, t: s => s, imageUrl: s => '/p/test/' + s, hashText: s => s,
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../easyread/web/js/reader/render.js'), 'utf8'), {
    window: { PR }, document: {
      getElementById: () => node,
      createElement: () => ({ set innerHTML(value) { html = value; }, firstChild: {} }),
    },
  });
  PR.blockById[block.id] = block;
  PR.renderBlock(block.id);
  return { PR, html };
}

test('read-first figure displays source labels without requiring a translation', () => {
  const { PR, html } = reader({ id: 'fig1', type: 'figure', src: 'figures/a.webp', image_en: 'Accuracy', caption_en: 'Figure 1' });
  assert.match(html, /src="\/p\/test\/figures\/a.webp"/);
  assert.match(html, /class="zh en-main" lang="en" data-key="fig1#image">Accuracy/);
  assert.equal((html.match(/Accuracy/g) || []).length, 1);
  assert.equal(PR.hasZh(PR.blockById.fig1), false);
});

test('translated figure preserves original labels and reader edits', () => {
  const { PR, html } = reader({ id: 'fig1', type: 'figure', image_en: 'Accuracy', image_zh: 'translated', caption_en: 'Figure 1' }, {
    'fig1#image': { zh: 'my wording', base: 'old translation' },
  });
  assert.match(html, /data-key="fig1#image">my wording/);
  assert.match(html, /class="en" lang="en">Accuracy/);
  assert.match(html, /stale-tag/);
  assert.deepEqual(Array.from(PR.blockKeys(PR.blockById.fig1)), ['fig1#caption', 'fig1#image']);
});

test('legacy figure without image text retains its page fallback', () => {
  const { html } = reader({ id: 'fig1', type: 'figure', page: 2, caption_zh: 'caption' });
  assert.match(html, /fig-missing/);
  assert.doesNotMatch(html, /figure-translation/);
});
