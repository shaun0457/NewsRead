const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const script = (name) => fs.readFileSync(path.join(__dirname, "../easyread/web/js/", name), "utf8");
const translate = (s, values) => values ? s.replace(/\{(\w+)\}/g, (match, key) => values[key]) : s;
function formatter(t = translate) {
  const PR = { t };
  vm.runInNewContext(script("common/cite.js"), { window: { PR } });
  return PR;
}
const preprint = { id: "pre", authors: "Evan Miller", title_en: "Adding Error Bars", year: "2024", arxiv: "arXiv:2411.00640 [stat.AP]", url: "https://arxiv.org/abs/2411.00640" };
const conference = { id: "conf", authors: "Ashish Vaswani, Noam Shazeer", title_en: "Attention Is All You Need", year: 2017, venue: "NeurIPS", doi: "10.1234/attention" };
const journal = { id: "journal", authors: "Ada Lovelace", title_en: "Notes on Computing", year: "1843", venue: "Scientific Memoirs" };

const exact = [
  [preprint, "gb", "MILLER E. Adding Error Bars[EB/OL]. arXiv:2411.00640, 2024. https://arxiv.org/abs/2411.00640."],
  [conference, "gb", "VASWANI A, SHAZEER N. Attention Is All You Need[C]. NeurIPS, 2017."],
  [journal, "gb", "LOVELACE A. Notes on Computing[J]. Scientific Memoirs, 1843."],
  [preprint, "apa", "Miller, E. (2024). Adding Error Bars. arXiv:2411.00640. https://arxiv.org/abs/2411.00640"],
  [conference, "apa", "Vaswani, A., & Shazeer, N. (2017). Attention Is All You Need. NeurIPS"],
  [journal, "apa", "Lovelace, A. (1843). Notes on Computing. Scientific Memoirs"],
  [preprint, "bibtex", "@misc{miller2024adding,\n  title = {{Adding Error Bars}},\n  author = {Evan Miller},\n  year = {2024},\n  eprint = {2411.00640},\n  archivePrefix = {arXiv},\n  url = {https://arxiv.org/abs/2411.00640}\n}"],
  [conference, "bibtex", "@inproceedings{vaswani2017attention,\n  title = {{Attention Is All You Need}},\n  author = {Ashish Vaswani and Noam Shazeer},\n  year = {2017},\n  booktitle = {NeurIPS},\n  doi = {10.1234/attention}\n}"],
  [journal, "bibtex", "@article{lovelace1843notes,\n  title = {{Notes on Computing}},\n  author = {Ada Lovelace},\n  year = {1843},\n  journal = {Scientific Memoirs}\n}"],
];
for (const [paper, style, expected] of exact) test(`${paper.id} has exact ${style} output`, () => {
  assert.equal(formatter().cite(paper, style), expected);
});

test("conference identification uses venue words and whole abbreviations", () => {
  const PR = formatter();
  for (const venue of ["Conference on Learning", "Proceedings of XYZ", "Workshop on XYZ", "Symposium on XYZ", "ICML", "ICLR", "ACL", "EMNLP", "NAACL", "CVPR", "ICCV", "ECCV", "AAAI", "IJCAI", "KDD", "SIGIR", "WWW", "CHI"]) {
    assert.equal(PR.citeType({ venue, arxiv: "1706.03762" }), "conference", venue);
  }
  assert.equal(PR.citeType(preprint), "preprint");
  assert.equal(PR.citeType({ venue: "Machine Learning", arxiv: "1706.03762" }), "journal");
  assert.equal(PR.citeType({}), "journal");
});

test("preprint repositories from metadata enrichment are not journals", () => {
  const PR = formatter();
  for (const venue of ["arXiv", "arXiv.org", "arXiv preprint arXiv:2301.00001", "CoRR", "OpenReview", "OpenReview.net"]) {
    const paper = { ...preprint, venue, arxiv: "2301.00001" };
    assert.equal(PR.citeType(paper), "preprint", venue);
    assert.match(PR.cite(paper, "gb"), /\[EB\/OL\]/);
    const bib = PR.cite(paper, "bibtex");
    assert.match(bib, /^@misc\{/);
    assert.doesNotMatch(bib, /journal =|booktitle =/);
  }
  assert.equal(PR.citeType({ ...preprint, venue: "ICLR 2026 (OpenReview)" }), "conference");
  const openReview = PR.cite({ ...journal, venue: "OpenReview", arxiv: "" }, "bibtex");
  assert.match(openReview, /^@misc\{/);
  assert.doesNotMatch(openReview, /archivePrefix|eprint/);
  assert.match(openReview, /howpublished = \{OpenReview\}/);
});

test("GB author truncation follows author language without changing Chinese names", () => {
  const PR = formatter();
  assert.equal(PR.cite({ ...conference, authors: "Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit" }, "gb"),
    "VASWANI A, SHAZEER N, PARMAR N, et al. Attention Is All You Need[C]. NeurIPS, 2017.");
  assert.equal(PR.cite({ authors: "张三, 李四, 王五, 赵六", title_zh: "论文阅读", year: "2024", venue: "科学期刊" }, "gb"),
    "张三, 李四, 王五, 等. 论文阅读[J]. 科学期刊, 2024.");
});

test("APA keeps twenty authors and uses nineteen plus final author above twenty", () => {
  const PR = formatter(), authors = Array.from({ length: 21 }, (_, n) => "Alice Person" + (n + 1));
  const twenty = PR.cite({ ...journal, authors: authors.slice(0, 20).join(", ") }, "apa");
  assert.match(twenty, /Person19, A\., & Person20, A\./);
  const twentyOne = PR.cite({ ...journal, authors: authors.join(", ") }, "apa");
  assert.equal(twentyOne, authors.slice(0, 19).map((n) => n.split(" ")[1] + ", A.").join(", ") + ", … Person21, A. (1843). Notes on Computing. Scientific Memoirs");
  assert.doesNotMatch(twentyOne, /Person20|&/);
});

test("BibTeX protects title case and escapes special characters in metadata", () => {
  const out = formatter().cite({ ...journal, title_en: "A&B 50% $ # x_y {Z}", venue: "R&D" }, "bibtex");
  assert.ok(out.includes("title = {{A\\&B 50\\% \\$ \\# x\\_y \\{Z\\}}}"));
  assert.ok(out.includes("journal = {R\\&D}"));
});

test("BibTeX preserves DOI and URL identifiers without TeX escapes", () => {
  const doi = "10.1000/a_b", url = "https://example.org/a_b?query=50%25#section_1";
  const out = formatter().cite({ ...journal, doi, url, venue: "R&D" }, "bibtex");
  assert.ok(out.includes("doi = {" + doi + "}"));
  assert.ok(out.includes("url = {" + url + "}"));
  assert.ok(out.includes("journal = {R\\&D}"));
  assert.doesNotMatch(out, /doi = \{[^\n]*\\|url = \{[^\n]*\\/);
});

test("batch BibTeX keys are unique, including generated suffix collisions and over 26 duplicates", () => {
  const PR = formatter();
  const two = PR.citeBatch([journal, journal], "bibtex");
  assert.deepEqual([...two.matchAll(/@\w+\{([^,]+)/g)].map((m) => m[1]), ["lovelace1843notesa", "lovelace1843notesb"]);
  const papers = Array.from({ length: 28 }, () => ({ ...journal }));
  papers.push({ ...journal, title_en: "Notesa" });
  const keys = [...PR.citeBatch(papers, "bibtex").matchAll(/@\w+\{([^,]+)/g)].map((m) => m[1]);
  assert.equal(new Set(keys).size, 29);
  assert.equal(keys[0], "lovelace1843notesb");
  assert.ok(keys.includes("lovelace1843notesaa"));
  assert.equal(keys[28], "lovelace1843notesa");
});

test("missing fields are reported by style and never become null or undefined text", () => {
  const PR = formatter(), paper = { ...journal, year: null };
  for (const style of ["gb", "apa", "bibtex"]) {
    assert.deepEqual(Array.from(PR.citeMissing(paper, style)), ["年份"]);
    assert.doesNotMatch(PR.cite(paper, style), /undefined|null/);
    assert.doesNotMatch(PR.cite({}, style), /undefined|null/);
  }
  assert.deepEqual(Array.from(PR.citeMissing({}, "gb")), ["作者", "年份", "题名", "出处"]);
  assert.deepEqual(Array.from(PR.citeMissing({}, "bibtex")), ["作者", "年份", "题名"]);
  assert.deepEqual(Array.from(PR.citeMissing({ ...preprint, venue: " " }, "gb")), []);
});

test("batch GB sorts Latin surnames before Chinese pinyin; APA sorts without numbering", () => {
  const PR = formatter(), papers = [
    { ...journal, authors: "张三" }, { ...journal, authors: "Bob Zebra" },
    { ...journal, authors: "李四" }, { ...journal, authors: "Alice Adams" },
  ];
  const gb = PR.citeBatch(papers, "gb").split("\n\n");
  assert.match(gb[0], /^\[1\] ADAMS A/);
  assert.match(gb[1], /^\[2\] ZEBRA B/);
  assert.match(gb[2], /^\[3\] 李四/);
  assert.match(gb[3], /^\[4\] 张三/);
  assert.match(PR.citeBatch([preprint, journal], "apa"), /^Lovelace,/);
  assert.doesNotMatch(PR.citeBatch([preprint, journal], "apa"), /\[\d+\]/);
  assert.equal(papers[0].authors, "张三");
});

test("GB entries without authors follow every named entry", () => {
  const papers = [{ ...journal, authors: "", title_en: "Anonymous work" }, { ...journal, authors: "张三" }, { ...journal, authors: "Alice Zebra" }];
  const gb = formatter().citeBatch(papers, "gb").split("\n\n");
  assert.match(gb[0], /^\[1\] ZEBRA A/);
  assert.match(gb[1], /^\[2\] 张三/);
  assert.match(gb[2], /^\[3\] Anonymous work/);
});

test("author names separated by and export as separate authors", () => {
  const PR = formatter(), paper = { ...journal, authors: "A Smith and B Doe, C Jones" };
  assert.match(PR.cite(paper, "gb"), /^SMITH A, DOE B, JONES C\./);
  assert.match(PR.cite(paper, "apa"), /^Smith, A\., Doe, B\., & Jones, C\./);
  assert.match(PR.cite(paper, "bibtex"), /author = \{A Smith and B Doe and C Jones\}/);
  assert.match(PR.cite({ ...paper, authors: "Brandon Smith" }, "gb"), /^SMITH B\./);
});

// 对话框只需要节点与事件的轻量桩；测试选中、格式记忆、补信息跳转和空选择。
function dialog() {
  const PR = formatter(), nodes = new Map(), memory = new Map(), copied = [];
  const node = (key) => {
    if (!nodes.has(key)) nodes.set(key, {
      listeners: {}, dataset: {}, value: "", innerHTML: "", isConnected: true,
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener(name, fn) { this.listeners[name] = fn; },
      focus() {}, select() {}, setAttribute() {},
    });
    return nodes.get(key);
  };
  Object.assign(PR, {
    lib: { select(id) { this.selected = id; }, filtered: () => [journal], items: [journal], cats: () => [] },
    $: node, $$: () => [], esc: (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;"),
    icon: () => "", toast: (s) => copied.push(s), ls: { get: (k, d) => memory.get(k) || d, set: (k, v) => memory.set(k, v) },
  });
  vm.runInNewContext(script("library/cite-export.js"), {
    window: { PR }, document: { activeElement: null }, navigator: { clipboard: { writeText: async (s) => copied.push(s) } },
  });
  const click = (selector, data = {}) => node("#citeExportDlg").listeners.click({ target: { closest: (s) => s === selector ? { dataset: data } : null } });
  return { PR, node, memory, copied, click };
}

test("export selection controls preview and copy, format persists, and missing metadata links to details", async () => {
  const r = dialog(), incomplete = { ...journal, year: "" };
  r.PR.openCiteExport([incomplete, preprint], "Thesis");
  assert.match(r.node(".cite-items").innerHTML, /缺年份/);
  r.node("#citeExportDlg").listeners.change({ target: { dataset: { item: "0" }, checked: false } });
  assert.equal(r.node("textarea").value, r.PR.citeBatch([preprint], "gb"));
  await r.click("[data-style]", { style: "bibtex" });
  assert.equal(r.node("textarea").value, r.PR.citeBatch([preprint], "bibtex"));
  await r.click("[data-copy]");
  assert.equal(r.copied[0], r.node("textarea").value);
  r.PR.openCiteExport([incomplete], "Thesis");
  assert.match(r.node("textarea").value, /^@article/);
  await r.click("[data-edit]", { edit: "0" });
  assert.equal(r.PR.lib.selected, journal.id);
  r.node("#citeExportDlg").listeners.change({ target: { dataset: { item: "0" }, checked: false } });
  assert.equal(r.node("textarea").value, "");
  assert.equal(r.node("[data-copy]").disabled, true);
  assert.equal(r.node("[data-save]").disabled, true);
});

test("citation warnings use the selected UI language without altering citation metadata", () => {
  const en = JSON.parse(fs.readFileSync(path.join(__dirname, "../easyread/web/i18n/en.json"), "utf8"));
  const PR = formatter((key) => en[key] || key);
  assert.deepEqual(Array.from(PR.citeMissing({ ...journal, year: "" }, "gb")), ["Year"]);
  assert.equal(PR.cite(journal, "gb"), formatter().cite(journal, "gb"));
});

test("the export dialog switches between the opened list, all papers and a category", () => {
  const r = dialog();
  const tagged = { ...preprint, id: "tagged", tags: ["毕业论文"] };
  Object.assign(r.PR.lib, { items: [journal, tagged], cats: () => ["毕业论文"] });
  r.PR.openCiteExport([journal], "在读");
  assert.match(r.node(".dialog").innerHTML, /value="c:毕业论文"/);
  const change = (value) => r.node("#citeExportDlg").listeners.change({ target: { dataset: { scope: "" }, value } });
  change("c:毕业论文");
  assert.equal(r.node("textarea").value.split("\n").filter((l) => l.startsWith("[")).length, 1);
  assert.match(r.node("textarea").value, new RegExp(tagged.title_en.slice(0, 20)));
  change("all");
  assert.equal(r.node("textarea").value.split("\n").filter((l) => l.startsWith("[")).length, 2);
});

test("export order: by author, by year, or dragged by hand (numbering follows the list)", () => {
  const r = dialog();
  const older = { ...preprint, id: "older", authors: "Zed Young", year: "1990" };
  r.PR.openCiteExport([preprint, journal, older], "Thesis");
  const firsts = () => r.node("textarea").value.split("\n\n").map((x) => x.slice(4, 12));
  const order = (value) => r.node("#citeExportDlg").listeners.change({ target: { dataset: { order: "" }, value } });
  order("author");
  assert.deepEqual(firsts(), ["LOVELACE", "MILLER E", "YOUNG Z."]);
  order("year");
  assert.deepEqual(firsts(), ["LOVELACE", "YOUNG Z.", "MILLER E"]);
  r.PR.citeMove(2, 0);  // 把最后一篇拖到最前
  assert.deepEqual(firsts(), ["MILLER E", "LOVELACE", "YOUNG Z."]);
  assert.equal(r.memory.get("easyread-cite-order"), "custom");
  assert.match(r.node("textarea").value, /^\[1\] MILLER/);
});
